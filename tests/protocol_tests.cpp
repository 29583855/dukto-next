#include "core/error.h"
#include "core/protocol.h"

#include <QJsonArray>
#include <QRandomGenerator>
#include <QtTest>
#include <limits>

using dukto::Error;
namespace wire = dukto::next;

class ProtocolTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-04；按书面偏移独立给出线格式，防止编码器与解码器出现相同字节序错误。
    void goldenControlFrame() {
        const auto expected =
            QByteArray::fromHex("444b544e45585431000100000001000001020304050607080000000200000000");
        const wire::Header header{wire::Type::Hello, Q_UINT64_C(0x0102030405060708), 2};
        QCOMPARE(wire::encodeHeader(header), expected);
        const auto observed = wire::decodeHeader(expected);
        QCOMPARE(observed.type, wire::Type::Hello);
        QCOMPARE(observed.correlation, header.correlation);
        QCOMPARE(observed.payloadBytes, quint32(2));
        QCOMPARE(wire::encodeFrame({header, "{}"}), expected + "{}");
        wire::Decoder decoder;
        const auto bytes = expected + "{}";
        for (const auto character : bytes)
            decoder.append(QByteArray(1, character));
        QCOMPARE(decoder.requiredBytes(), 0);
        QCOMPARE(decoder.take().payload, QByteArray("{}"));
        QCOMPARE(decoder.requiredBytes(), wire::HeaderBytes);
        decoder.finish();
    }
    // 日期：2026-11-04；数据样本独立固定 UUID/64 位序号/8 MiB 块边界与正文长度字段。
    void goldenDataFrame() {
        const auto expected = QByteArray::fromHex(
            "00112233445566778899aabbccddeeff0102030405060708ffffffffffffffff007ffffd00000003"
            "00ff7f");
        const wire::Fragment fragment{QUuid("00112233-4455-6677-8899-aabbccddeeff"),
                                      Q_UINT64_C(0x0102030405060708),
                                      std::numeric_limits<quint64>::max(), wire::BlockLimit - 3,
                                      QByteArray::fromHex("00ff7f")};
        QCOMPARE(wire::encodeFragment(fragment), expected);
        const auto observed = wire::decodeFragment(expected);
        QCOMPARE(observed.task, fragment.task);
        QCOMPARE(observed.file, fragment.file);
        QCOMPARE(observed.block, fragment.block);
        QCOMPARE(observed.offset, fragment.offset);
        QCOMPARE(observed.bytes, fragment.bytes);
        const auto encoded = wire::encodeFrame(
            {{wire::Type::Data, 9, static_cast<quint32>(expected.size())}, expected});
        wire::Decoder decoder;
        decoder.append(encoded.left(wire::HeaderBytes));
        decoder.append(encoded.mid(wire::HeaderBytes));
        QCOMPARE(decoder.take().payload, expected);
        decoder.finish();
        auto invalid = fragment;
        ++invalid.offset;
        QVERIFY_EXCEPTION_THROWN(wire::encodeFragment(invalid), Error);
        invalid = fragment;
        invalid.task = QUuid();
        QVERIFY_EXCEPTION_THROWN(wire::encodeFragment(invalid), Error);
        invalid = fragment;
        invalid.file = 0;
        QVERIFY_EXCEPTION_THROWN(wire::encodeFragment(invalid), Error);
        invalid = fragment;
        invalid.bytes.clear();
        QVERIFY_EXCEPTION_THROWN(wire::encodeFragment(invalid), Error);
        auto wrongLength = expected;
        wrongLength[39] = 4;
        QVERIFY_EXCEPTION_THROWN(wire::decodeFragment(wrongLength), Error);
        QVERIFY_EXCEPTION_THROWN(wire::decodeFragment(expected.left(39)), Error);
    }
    // 日期：2026-11-04；未知版本/类型/保留位/零序号/超限长度在 32 字节头处拒绝，不申请正文。
    void malformedHeadersRejected() {
        const auto valid =
            QByteArray::fromHex("444b544e45585431000100000001000001020304050607080000000200000000");
        for (const int offset : {0, 8, 10, 12, 14, 28}) {
            auto bytes = valid;
            bytes[offset] = 0x7f;
            QVERIFY_EXCEPTION_THROWN(wire::decodeHeader(bytes), Error);
            wire::Decoder decoder;
            QVERIFY_EXCEPTION_THROWN(decoder.append(bytes), Error);
            QVERIFY_EXCEPTION_THROWN(decoder.requiredBytes(), Error);
            QVERIFY_EXCEPTION_THROWN(decoder.finish(), Error);
        }
        for (const auto length : {0U, 1U, 65537U, 0xffffffffU}) {
            auto bytes = valid;
            bytes.replace(
                24, 4, QByteArray::fromHex(QByteArray::number(length, 16).rightJustified(8, '0')));
            QVERIFY_EXCEPTION_THROWN(wire::decodeHeader(bytes), Error);
        }
        auto bytes = valid;
        bytes.replace(16, 8, QByteArray(8, '\0'));
        QVERIFY_EXCEPTION_THROWN(wire::decodeHeader(bytes), Error);
        QVERIFY_EXCEPTION_THROWN(wire::decodeHeader(valid.left(31)), Error);
        QVERIFY_EXCEPTION_THROWN(wire::encodeFrame({{wire::Type::Hello, 1, 3}, "{}"}), Error);
    }
    // 日期：2026-11-04；重复键、转义别名键及嵌套重复键都必须拒绝，不能依赖 Qt 最后值覆盖。
    void hostileJsonRejected() {
        const QList<QByteArray> rejected{"",
                                         "[]",
                                         "null",
                                         "{}{}",
                                         "{} garbage",
                                         "{\"a\":1,\"a\":2}",
                                         "{\"a\":1,\"\\u0061\":2}",
                                         "{\"nested\":{\"a\":1,\"a\":2}}",
                                         "{\"a\":1,}",
                                         "{\"a\":[1,]}",
                                         "{\"a\":01}",
                                         "{\"a\":1e999}",
                                         "{\"a\":\"\\uD800\"}",
                                         "{\"a\":\"\\u0000\"}",
                                         "{\"a\":\"\\q\"}",
                                         "{\"a\":\"unfinished}",
                                         QByteArray("{\"a\":\"") + QByteArray::fromHex("ff") +
                                             "\"}",
                                         QByteArray::fromHex("efbbbf") + "{}",
                                         "{\"\":1}"};
        for (const auto &bytes : rejected) {
            bool denied = false;
            try {
                wire::parseControl(bytes);
            } catch (const Error &error) {
                denied = true;
                QCOMPARE(error.stage, QString("protocol"));
                QVERIFY(!error.message.contains("unfinished"));
            }
            QVERIFY2(denied, bytes.constData());
        }
        const auto accepted =
            QStringLiteral("{\"名字\":\"中文🚀\",\"a\":true,\"b\":null,\"c\":-1}").toUtf8();
        QCOMPARE(wire::parseControl(accepted)[QStringLiteral("名字")].toString(),
                 QStringLiteral("中文🚀"));
        QCOMPARE(wire::parseControl("{\"a\":\"\\uD83D\\uDE80\"}")["a"].toString(),
                 QStringLiteral("🚀"));
    }
    // 日期：2026-11-04；精确验证字节、字符串、字段数、数组与递归深度的可接受和拒绝边界。
    void controlResourceBoundaries() {
        const auto maximum = '{' + QByteArray(wire::ControlLimit - 2, ' ') + '}';
        QVERIFY(wire::parseControl(maximum).isEmpty());
        QVERIFY_EXCEPTION_THROWN(wire::parseControl(maximum + ' '), Error);
        wire::encodeControl({{"value", QString(4096, 'a')}});
        QVERIFY_EXCEPTION_THROWN(wire::encodeControl({{"value", QString(4097, 'a')}}), Error);
        QJsonArray array;
        for (int index = 0; index < 100; ++index)
            array.append(index);
        wire::encodeControl({{"items", array}});
        array.append(100);
        QVERIFY_EXCEPTION_THROWN(wire::encodeControl({{"items", array}}), Error);
        QJsonObject object;
        for (int index = 0; index < 32; ++index)
            object.insert(QString::number(index), index);
        wire::encodeControl(object);
        object.insert("extra", 33);
        QVERIFY_EXCEPTION_THROWN(wire::encodeControl(object), Error);
        QByteArray nested("0");
        for (int index = 0; index < 15; ++index)
            nested = '[' + nested + ']';
        wire::parseControl("{\"a\":" + nested + '}');
        nested = '[' + nested + ']';
        QVERIFY_EXCEPTION_THROWN(wire::parseControl("{\"a\":" + nested + '}'), Error);
    }
    // 日期：2026-11-04；超 2^53 与完整 u64 均精确保留；数字值、符号、溢出及非 ASCII 数字拒绝。
    void decimalBoundaries() {
        const auto maximum = std::numeric_limits<quint64>::max();
        QCOMPARE(wire::decimal("18446744073709551615", maximum), maximum);
        QCOMPARE(wire::decimal("9007199254740993", maximum), Q_UINT64_C(9007199254740993));
        QCOMPARE(wire::decimal("0", 0), quint64(0));
        for (const auto &text : QStringList{"", "00", "01", "-1", "+1", "1.0", "1e3", " 1",
                                            "18446744073709551616", "/", QStringLiteral("１")})
            QVERIFY_EXCEPTION_THROWN(wire::decimal(text, maximum), Error);
        QVERIFY_EXCEPTION_THROWN(wire::decimal(123, maximum), Error);
        QVERIFY_EXCEPTION_THROWN(wire::decimal("1", 0), Error);
        QVERIFY_EXCEPTION_THROWN(wire::decimal("101", 100), Error);
    }
    // 日期：2026-11-04；截断头/正文、未取走的完整帧及越界追加不能被当作成功输入继续使用。
    void truncationAndDecoderState() {
        const auto header = wire::encodeHeader({wire::Type::Hello, 1, 2});
        for (int length = 1; length <= wire::HeaderBytes; ++length) {
            wire::Decoder decoder;
            decoder.append(header.left(length));
            QVERIFY_EXCEPTION_THROWN(decoder.finish(), Error);
        }
        wire::Decoder decoder;
        QVERIFY_EXCEPTION_THROWN(decoder.append(header + "{}"), Error);
        QVERIFY_EXCEPTION_THROWN(decoder.append(header), Error);
        wire::Decoder multiple;
        for (int round = 0; round < 100; ++round) {
            multiple.append(header);
            multiple.append("{");
            multiple.append("}");
            QCOMPARE(multiple.take().payload, QByteArray("{}"));
        }
        multiple.finish();
        wire::Decoder badBody;
        badBody.append(header);
        badBody.append("[]");
        QVERIFY_EXCEPTION_THROWN(badBody.take(), Error);
        QVERIFY_EXCEPTION_THROWN(badBody.requiredBytes(), Error);
        wire::Decoder early;
        QVERIFY_EXCEPTION_THROWN(early.take(), Error);
        QVERIFY_EXCEPTION_THROWN(early.append(header), Error);
    }
    // 日期：2026-11-04；有确定种子的畸形线样本持续撞击头部和正文边界，异常仅用统一 Error 返回。
    void boundedMalformedCorpus() {
        QRandomGenerator random(20261104);
        for (int round = 0; round < 2000; ++round) {
            QByteArray bytes(static_cast<int>(random.bounded(512U)), '\0');
            for (auto &character : bytes)
                character = static_cast<char>(random.generate());
            try {
                wire::parseControl(bytes);
            } catch (const Error &) {
            }
            if (bytes.size() >= wire::HeaderBytes) {
                try {
                    wire::decodeHeader(bytes.left(wire::HeaderBytes));
                } catch (const Error &) {
                }
            }
        }
    }
};
QTEST_GUILESS_MAIN(ProtocolTests)
#include "protocol_tests.moc"

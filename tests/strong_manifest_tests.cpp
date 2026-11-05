#include "core/error.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/strongmanifest.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>

namespace {
// 日期：2026-11-04；独立测试摘要只对样本原字节使用标准 SHA-256，不复用强清单编码器。
QByteArray sha(const QByteArray &bytes) {
    return QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
}

// 日期：2026-11-04；测试导入只使用真实公开字段，源路径故意与原数据库不同以核对身份边界。
dukto::StrongEntry imported(const QJsonObject &value) {
    return {dukto::next::decimal(value["id"], 10000000),
            value["path"].toString(),
            "",
            value["type"] == "directory",
            static_cast<qint64>(dukto::next::decimal(value["bytes"], 100000000)),
            QByteArray::fromHex(value["sha256"].toString().toLatin1())};
}
} // namespace

class StrongManifestTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-04；固定身份由独立 Python hashlib/struct 样本计算，包含 Unicode、目录和空文件。
    void independentCanonicalVector() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto expected =
            QByteArray::fromHex("6336657ba5ca0e8364a9ecd122e38b6cd9cddd5ff56b7e7885d45bb757099c8c");
        {
            dukto::StrongManifest manifest(store, "vector.sqlite", true);
            manifest.append({1, QStringLiteral("资料"), "", true, 0, {}});
            manifest.append(
                {2, QStringLiteral("资料/a.bin"), "not-transmitted", false, 3, sha("abc")});
            manifest.appendBlock(2, 0, 3, sha("abc"));
            manifest.append({3, QStringLiteral("资料/empty"), "", false, 0, sha("")});
            QCOMPARE(manifest.seal(expected), expected);
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(2, 1, 3, sha("abc")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.seal(), dukto::Error);
            QVERIFY(!dukto::next::encodeControl({{"entries", manifest.entries()}})
                         .contains("not-transmitted"));
        }
        dukto::StrongManifest restored(store, "vector.sqlite", false);
        QCOMPARE(restored.summary()["sha256"].toString().toLatin1(), expected.toHex());
        QCOMPARE(restored.summary()["entries"].toString(), QString("3"));
        QCOMPARE(restored.summary()["blocks"].toString(), QString("1"));
        QCOMPARE(restored.summary()["bytes"].toString(), QString("3"));
        QCOMPARE(restored.blocks(2).size(), 1);
        QVERIFY(restored.blocks(2, 1).isEmpty());
        QVERIFY_EXCEPTION_THROWN(restored.entry(4), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(restored.blocks(2, 2), dukto::Error);
    }

    // 日期：2026-11-04；真实扫描两整块加尾块，公开分页导入另一数据库后获得相同强内容身份。
    void scanBlocksAndRoundtrip() {
        QTemporaryDir temporary;
        const auto source = temporary.filePath("bundle");
        QVERIFY(QDir().mkpath(source + "/empty-directory"));
        QFile input(source + "/data.bin");
        QVERIFY(input.open(QIODevice::WriteOnly));
        const QByteArray fragment(256 * 1024, 'x');
        for (int index = 0; index < 32; ++index)
            QCOMPARE(input.write(fragment), qint64(fragment.size()));
        QCOMPARE(input.write("tail-of-final-block-37-bytes-0123456789", 37), qint64(37));
        input.close();
        QFile empty(source + "/empty-file");
        QVERIFY(empty.open(QIODevice::WriteOnly));
        empty.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.scan({source});
        QCOMPARE(manifest.summary()["entries"].toString(), QString("4"));
        QCOMPARE(manifest.summary()["blocks"].toString(), QString("3"));
        QCOMPARE(manifest.summary()["bytes"].toString(), QString::number(8 * 1024 * 1024 + 37));
        QCOMPARE(manifest.entry(2).sha256, dukto::hashFile(source + "/data.bin"));
        const auto list = manifest.blocks(2);
        QCOMPARE(list[0].toObject()["sha256"].toString().toLatin1(),
                 sha(QByteArray(4 * 1024 * 1024, 'x')).toHex());
        QCOMPARE(list[2].toObject()["bytes"].toString(), QString("37"));
        dukto::StrongManifest receiver(store, "received.sqlite", true);
        for (const auto &value : manifest.entries()) {
            const auto entry = imported(value.toObject());
            receiver.append(entry);
            for (const auto &block : manifest.blocks(entry.id)) {
                const auto object = block.toObject();
                receiver.appendBlock(entry.id, dukto::next::decimal(object["block"], 100),
                                     static_cast<qint64>(dukto::next::decimal(
                                         object["bytes"], dukto::StrongBlockBytes)),
                                     QByteArray::fromHex(object["sha256"].toString().toLatin1()));
            }
        }
        QCOMPARE(receiver.seal(),
                 QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1()));
        QCOMPARE(receiver.summary(), manifest.summary());
        QCOMPARE(receiver.entry(2).source, QString(""));
        QVERIFY(store.validateFile("source.sqlite") <= dukto::MaxMetadataBytes);
    }

    // 日期：2026-11-04；缺块、坏身份、重复块、穿越和跨平台重名不能被当作有效强清单。
    void invalidAndIncompleteRecords() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        {
            dukto::StrongManifest manifest(store, "incomplete.sqlite", true);
            QVERIFY_EXCEPTION_THROWN(manifest.append({1, "../escape", "", false, 1, sha("x")}),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.append({1, "parent/child", "", false, 1, sha("x")}),
                                     dukto::Error);
            manifest.append({1, "A", "", false, 1, sha("x")});
            QVERIFY_EXCEPTION_THROWN(manifest.append({2, "a", "", false, 0, sha("")}),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(1, 1, 1, sha("x")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(1, 0, 2, sha("xx")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.seal(), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.summary(), dukto::Error);
            manifest.appendBlock(1, 0, 1, sha("x"));
            QVERIFY_EXCEPTION_THROWN(manifest.appendBlock(1, 0, 1, sha("x")), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(manifest.seal(QByteArray(32, 'z')), dukto::Error);
        }
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "incomplete.sqlite", false),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "incomplete.sqlite", true),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "../escape.sqlite", true),
                                 dukto::Error);
        QVERIFY(!QFile::exists(temporary.filePath("escape.sqlite.lock")));
    }

    // 日期：2026-11-04；目录条目多时分页保持上限；取消后的数据库不能重载为完整清单。
    void pagingAndCancellation() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "pages.sqlite", true);
        for (int index = 0; index < 301; ++index)
            manifest.append({static_cast<quint64>(index + 1),
                             QString("item-%1").arg(index, 4, 10, QChar('0')), "", false, 0,
                             sha("")});
        manifest.seal();
        quint64 after = 0;
        int pages = 0;
        for (;;) {
            const auto page = manifest.entries(after);
            if (page.isEmpty())
                break;
            QVERIFY(page.size() <= 100);
            QVERIFY(QJsonDocument(page).toJson(QJsonDocument::Compact).size() <=
                    dukto::next::ControlLimit - 1024);
            after = dukto::next::decimal(page.last().toObject()["id"], 10000000);
            ++pages;
        }
        QCOMPARE(after, quint64(301));
        QCOMPARE(pages, 4);
        {
            dukto::StrongManifest cancelled(store, "cancelled.sqlite", true);
            std::atomic_bool cancel{true};
            QVERIFY_EXCEPTION_THROWN(cancelled.scan({temporary.path()}, &cancel), dukto::Error);
        }
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "cancelled.sqlite", false),
                                 dukto::Error);
        const auto source = temporary.filePath("scan-source");
        QVERIFY(QDir().mkdir(source));
        for (int index = 0; index < 20; ++index) {
            QFile file(source + QString("/sample-%1").arg(index));
            QVERIFY(file.open(QIODevice::WriteOnly));
        }
        int callbacks = 0;
        dukto::StrongManifest revoked(store, "revoked.sqlite", true);
        QVERIFY_EXCEPTION_THROWN(revoked.scan({source}, nullptr,
                                              [&]() {
                                                  // 日期：2026-11-04；真实目录枚举尚未完成时撤销，须停止扫描且不生成可发布强身份。
                                                  if (++callbacks >= 5)
                                                      throw dukto::Error(
                                                          dukto::ExitCode::Permission,
                                                          "authorization revoked", "auth");
                                              }),
                                 dukto::Error);
        QCOMPARE(callbacks, 5);
        QVERIFY_EXCEPTION_THROWN(revoked.summary(), dukto::Error);
    }

    // 日期：2026-11-04；已冻结数据库中块或全摘要被改变时，重载重算必须拒绝，不能只信任元数据摘要。
    void persistentTamperingRejected() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        {
            dukto::StrongManifest manifest(store, "changed.sqlite", true);
            manifest.append({1, "sample", "", false, 3, sha("abc")});
            manifest.appendBlock(1, 0, 3, sha("abc"));
            manifest.seal();
        }
        const auto name = QUuid::createUuid().toString();
        {
            auto database = QSqlDatabase::addDatabase("QSQLITE", name);
            database.setDatabaseName(QDir(store.directory()).filePath("changed.sqlite"));
            QVERIFY(database.open());
            {
                QSqlQuery change(database);
                QVERIFY(change.exec("UPDATE blocks SET sha=zeroblob(32) WHERE file=1 AND block=0"));
            }
            database.close();
        }
        QSqlDatabase::removeDatabase(name);
        QVERIFY_EXCEPTION_THROWN(dukto::StrongManifest(store, "changed.sqlite", false),
                                 dukto::Error);
    }
};
QTEST_GUILESS_MAIN(StrongManifestTests)
#include "strong_manifest_tests.moc"

#include "core/error.h"
#include "core/transferaccounting.h"
#include <QtTest>
#include <limits>

namespace {
// 日期：2026-11-06；独立常量构造合法远端快照，不用被测编码器生成恶意输入的基准。
QJsonObject baseline() {
    return {{"bytes", "16"},       {"confirmed", "8"},
            {"restored", "0"},     {"copiedBytes", "4"},
            {"skippedBytes", "4"}, {"discardedBytes", "2"},
            {"copiedFiles", "1"},  {"copiedDirectories", "0"},
            {"skippedFiles", "1"}, {"skippedDirectories", "0"}};
}
} // namespace

class TransferAccountingTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-06；混合恢复、复制、准备跳过、晚期冲突、空文件及目录须满足独立期望。
    void mixedDispositions() {
        dukto::TransferAccounting meter(100, 6);
        meter.restored(10);
        meter.written(15, 0);
        QCOMPARE(meter.handled(), qint64(10));
        meter.written(15, 30);
        meter.settled({1, "copy", "", false, 40, {}}, false, true);
        meter.settled({2, "skip", "", false, 50, {}}, true, false);
        QCOMPARE(meter.received(), qint64(40));
        QCOMPARE(meter.handled(), qint64(90));
        QCOMPARE(meter.remaining(), qint64(10));
        meter.written(10, 10);
        meter.settled({3, "late", "", false, 10, {}}, true, true);
        meter.settled({4, "empty", "", false, 0, {}}, false, true);
        meter.settled({5, "directory", "", true, 0, {}}, false, false);
        meter.settled({6, "skip-directory", "", true, 0, {}}, true, false);
        QCOMPARE(meter.snapshot(), (QJsonObject{{"bytes", "50"},
                                                {"confirmed", "50"},
                                                {"restored", "10"},
                                                {"copiedBytes", "40"},
                                                {"skippedBytes", "60"},
                                                {"discardedBytes", "10"},
                                                {"copiedFiles", "2"},
                                                {"copiedDirectories", "1"},
                                                {"skippedFiles", "2"},
                                                {"skippedDirectories", "1"}}));
        QCOMPARE(meter.confirmed(), qint64(50));
        QCOMPARE(meter.restoredBytes(), qint64(10));
        QCOMPARE(meter.handled(), qint64(100));
        QCOMPARE(meter.remaining(), qint64(0));
    }

    // 日期：2026-11-06；全部跳过时逻辑完成但网络/复制为零；空文件仍占一个处置条目。
    void allSkipped() {
        dukto::TransferAccounting meter(9, 3);
        meter.settled({1, "tree", "", true, 0, {}}, true, false);
        meter.settled({2, "tree/body", "", false, 9, {}}, true, false);
        meter.settled({3, "tree/empty", "", false, 0, {}}, true, false);
        QCOMPARE(meter.received(), qint64(0));
        QCOMPARE(meter.confirmed(), qint64(0));
        QCOMPARE(meter.handled(), qint64(9));
        QCOMPARE(meter.snapshot()["copiedBytes"].toString(), QString("0"));
        QCOMPARE(meter.snapshot()["skippedFiles"].toString(), QString("2"));
        QCOMPARE(meter.snapshot()["skippedDirectories"].toString(), QString("1"));
    }

    // 日期：2026-11-06；恢复正文在晚期冲突时同样属于丢弃，不重复加入网络或逻辑总量。
    void restoredLateConflict() {
        dukto::TransferAccounting meter(12, 1);
        meter.restored(12);
        meter.settled({1, "late", "", false, 12, {}}, true, true);
        QCOMPARE(meter.handled(), qint64(12));
        QCOMPARE(meter.received() - meter.restoredBytes(), qint64(0));
        QCOMPARE(meter.snapshot()["copiedBytes"].toString(), QString("0"));
        QCOMPARE(meter.snapshot()["discardedBytes"].toString(), QString("12"));
    }

    // 日期：2026-11-06；所有拒绝路径必须保持原状态，未收正文、重复ID及伪造目录不能完成任务。
    void rejectedLocalUpdates() {
        dukto::TransferAccounting meter(12, 2);
        auto previous = meter.snapshot();
        QVERIFY_EXCEPTION_THROWN(meter.written(-1, 0), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.written(1, 2), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.restored(13), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.settled({1, "a", "", false, 1, {}}, false, true),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.settled({1, "a", "", false, 1, {}}, false, false),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.settled({1, "a", "", true, 1, {}}, true, false),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.settled({1, "a", "", true, 0, {}}, false, true),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.settled({2, "a", "", false, 1, {}}, true, false),
                                 dukto::Error);
        QCOMPARE(meter.snapshot(), previous);
        meter.settled({1, "a", "", false, 4, {}}, true, false);
        previous = meter.snapshot();
        QVERIFY_EXCEPTION_THROWN(meter.settled({1, "a", "", false, 4, {}}, true, false),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.written(9, 9), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.restored(9), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.settled({2, "b", "", true, 0, {}}, true, false),
                                 dukto::Error);
        QCOMPARE(meter.snapshot(), previous);
    }

    // 日期：2026-11-06；覆盖格式、上限、字节守恒、条目守恒、进度回退及事后改类。
    void rejectedSnapshots_data() {
        QTest::addColumn<int>("attack");
        const char *names[] = {"missing",
                               "extra",
                               "numeric",
                               "noncanonical",
                               "negative",
                               "received-over-total",
                               "confirmed-over-received",
                               "restore-old-body",
                               "copied-over-confirmed",
                               "discarded-over-skip",
                               "discarded-over-confirmed",
                               "skip-over-total",
                               "over-count",
                               "bytes-without-files",
                               "skip-without-files",
                               "unfinished-final-count",
                               "regressed-count",
                               "regressed-bytes",
                               "regressed-skips",
                               "discard-reclassification",
                               "copied-reclassification",
                               "skipped-reclassification",
                               "received-skip-overlap"};
        for (int index = 0; index < int(sizeof(names) / sizeof(names[0])); ++index)
            QTest::newRow(names[index]) << index;
    }

    // 日期：2026-11-06；先接受合法快照再注入单处破坏，拒绝时原快照逐字段保持不变。
    void rejectedSnapshots() {
        QFETCH(int, attack);
        dukto::TransferAccounting meter(32, 8);
        meter.accept(baseline());
        auto invalid = baseline();
        switch (attack) {
        case 0:
            invalid.remove("copiedBytes");
            break;
        case 1:
            invalid["unknown"] = "0";
            break;
        case 2:
            invalid["skippedBytes"] = 4;
            break;
        case 3:
            invalid["skippedBytes"] = "04";
            break;
        case 4:
            invalid["discardedBytes"] = "-1";
            break;
        case 5:
            invalid["bytes"] = "33";
            break;
        case 6:
            invalid["confirmed"] = "17";
            break;
        case 7:
            invalid["restored"] = "1";
            break;
        case 8:
            invalid["copiedBytes"] = "7";
            break;
        case 9:
            invalid["discardedBytes"] = "5";
            break;
        case 10:
            invalid["discardedBytes"] = "9";
            break;
        case 11:
            invalid["skippedBytes"] = "33";
            break;
        case 12:
            invalid["skippedDirectories"] = "8";
            break;
        case 13:
            invalid["copiedFiles"] = "0";
            break;
        case 14:
            invalid["skippedFiles"] = "0";
            break;
        case 15:
            invalid["copiedDirectories"] = "6";
            break;
        case 16:
            invalid["skippedDirectories"] = "1";
            invalid["skippedFiles"] = "0";
            break;
        case 17:
            invalid["bytes"] = "15";
            break;
        case 18:
            invalid["skippedBytes"] = "3";
            break;
        case 19:
            invalid["discardedBytes"] = "3";
            break;
        case 20:
            invalid["copiedBytes"] = "5";
            break;
        case 21:
            invalid["skippedBytes"] = "5";
            break;
        case 22:
            invalid["bytes"] = "32";
            break;
        }
        bool rejected = false;
        try {
            meter.accept(invalid);
        } catch (const dukto::Error &error) {
            rejected = error.stage == "progress" || error.stage == "protocol";
        }
        QVERIFY(rejected);
        QCOMPARE(meter.snapshot(), baseline());
    }

    // 日期：2026-11-06；非零拷贝或跳过增量必须同时归结新文件，合法聚合快照可以跨过多项。
    void acceptedSnapshots() {
        dukto::TransferAccounting meter(32, 8);
        meter.accept(baseline());
        meter.accept(baseline());
        auto complete = baseline();
        complete["bytes"] = "30";
        complete["confirmed"] = "30";
        complete["copiedBytes"] = "28";
        complete["copiedFiles"] = "4";
        complete["copiedDirectories"] = "2";
        complete["skippedDirectories"] = "1";
        meter.accept(complete);
        QCOMPARE(meter.handled(), qint64(32));
        QCOMPARE(meter.remaining(), qint64(0));
    }

    // 日期：2026-11-06；有符号64位上边界仍精确，最后一字节跳过不能因加法溢出回退。
    void maximumBytes() {
        const auto maximum = std::numeric_limits<qint64>::max();
        dukto::TransferAccounting meter(maximum, 2);
        meter.restored(maximum - 1);
        meter.settled({1, "a", "", false, maximum - 1, {}}, false, true);
        meter.settled({2, "b", "", false, 1, {}}, true, false);
        QCOMPARE(meter.handled(), maximum);
        QCOMPARE(meter.remaining(), qint64(0));
        const auto before = meter.snapshot();
        QVERIFY_EXCEPTION_THROWN(meter.written(maximum, maximum), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(meter.restored(maximum), dukto::Error);
        QCOMPARE(meter.snapshot(), before);
        dukto::TransferAccounting remote(maximum, 2);
        remote.accept(before);
        QCOMPARE(remote.snapshot(), before);
    }

    // 日期：2026-11-06；百万零字节项仍只保留固定计数，空条目不能绕过数量或重复ID约束。
    void boundedMillionEntries() {
        static_assert(sizeof(dukto::TransferAccounting) <= 128,
                      "Accounting must remain fixed size");
        dukto::TransferAccounting meter(0, 1000000);
        for (quint64 id = 1; id <= 1000000; ++id)
            meter.settled({id, {}, {}, id % 2 == 0, 0, {}}, id % 3 == 0, id % 2 != 0);
        const auto value = meter.snapshot();
        QCOMPARE(value["copiedFiles"].toString(), QString("333333"));
        QCOMPARE(value["copiedDirectories"].toString(), QString("333334"));
        QCOMPARE(value["skippedFiles"].toString(), QString("166667"));
        QCOMPARE(value["skippedDirectories"].toString(), QString("166666"));
        QVERIFY_EXCEPTION_THROWN(meter.settled({1000001, {}, {}, false, 0, {}}, true, false),
                                 dukto::Error);
        QCOMPARE(meter.snapshot(), value);
    }
};

QTEST_GUILESS_MAIN(TransferAccountingTests)
#include "transfer_accounting_tests.moc"

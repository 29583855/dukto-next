#include "core/buffercredit.h"
#include "core/error.h"
#include "core/files.h"
#include "core/privatestore.h"
#include "core/statebudget.h"
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QSqlDatabase>
#include <QTemporaryDir>
#include <QTextStream>
#include <QtEndian>
#include <QtTest>
#include <cstdlib>
#include <limits>
#include <thread>
#include <vector>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace {
using Budget = dukto::StateBudget;
using Category = Budget::Category;
const QUuid Domain("7c28222c-8aab-43d0-806d-c9e2737c988d");

// 日期：2026-11-08；独立测试键不取路径名，实际接入由业务层结合原生对象生命周期生成。
QByteArray key(int index) {
    return QCryptographicHash::hash(QByteArray::number(index), QCryptographicHash::Sha256);
}

// 日期：2026-11-08；小额度只允许最后1024字节增长，账本固定字节与类别额度分别保留。
Budget::Limits limits(qint64 extra = 1024) {
    return {Budget::FileBytes + extra, {{extra, Budget::FileBytes + extra, extra, extra}}};
}

// 日期：2026-11-08；只在测试自有普通账本上读取完整原件，产品接口仍逐项有界访问。
QByteArray bytes(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        throw dukto::Error(dukto::ExitCode::Disk, "fixture read", "test");
    return file.readAll();
}

// 日期：2026-11-08；测试夹具原地改写已有独立文件而不换代权限，用于注入真实中断布局和校验损坏。
void replace(const QString &path, const QByteArray &value) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate) ||
        file.write(value) != value.size() || !file.flush())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture write", "test");
}

// 日期：2026-11-08；独立按公开格式编码整数和校验，不调用产品序列化器生成恢复夹具。
void number(QByteArray &value, int offset, quint64 integer) {
    qToLittleEndian(integer, reinterpret_cast<uchar *>(value.data() + offset));
}

// 日期：2026-11-08；夹具校验只用于实际文件故障布局，业务结果仍通过公开账本接口核验。
QByteArray sealed(QByteArray value) {
    value.replace(
        value.size() - 32, 32,
        QCryptographicHash::hash(value.left(value.size() - 32), QCryptographicHash::Sha256));
    return value;
}

// 日期：2026-11-08；把真实两次提交原件转为独立写前意图，覆盖头/槽单边落盘和撕裂数据页。
QByteArray journal(const QByteArray &before, const QByteArray &after, int slot) {
    QByteArray value(4096, '\0');
    value.replace(0, 8, QByteArray("DKBUDTX1", 8));
    number(value, 8, quint64(slot));
    number(value, 16,
           qFromLittleEndian<quint64>(reinterpret_cast<const uchar *>(before.constData() + 72)));
    number(value, 24,
           qFromLittleEndian<quint64>(reinterpret_cast<const uchar *>(after.constData() + 72)));
    value.replace(40, 512, before.left(512));
    value.replace(552, 512, after.left(512));
    value.replace(1064, 256, before.mid(8192 + slot * 256, 256));
    value.replace(1320, 256, after.mid(8192 + slot * 256, 256));
    return sealed(value);
}

class ChildProcess final : public QProcess {
  public:
    // 日期：2026-11-08；夹具断言或启动异常提前返回时，也必须终止并收取自有测试子进程。
    ~ChildProcess() override {
        if (state() != QProcess::NotRunning) {
            kill();
            waitForFinished(10000);
        }
    }
};

// 日期：2026-11-08；启动真实独立进程，等其完成全部打开/观察后才同时放行预算竞争。
void start(QProcess &process, const QStringList &arguments) {
    process.start(QCoreApplication::applicationFilePath(), arguments);
    QElapsedTimer timer;
    timer.start();
    const bool started = process.waitForStarted(10000);
    while (started && !process.canReadLine() && timer.elapsed() < 30000 &&
           process.state() != QProcess::NotRunning)
        process.waitForReadyRead(int(qMax<qint64>(1, 30000 - timer.elapsed())));
    const auto line = process.readLine();
    if (started && (line == "ready\n" || line == "ready\r\n")) {
        qInfo().noquote() << "Child readiness bytes:" << line.toHex();
        return;
    }
    const auto error = process.readAllStandardError().left(4096);
    if (process.state() != QProcess::NotRunning) {
        process.kill();
        process.waitForFinished(10000);
    }
    const auto message = QStringLiteral("child startup: ready=%1 exit=%2 stderr=%3")
                             .arg(QString::fromLatin1(line.toHex()))
                             .arg(process.exitCode())
                             .arg(QString::fromUtf8(error));
    qWarning().noquote() << message;
    throw dukto::Error(dukto::ExitCode::Runtime, message, "test");
}

// 日期：2026-11-08；子进程退出绕过析构，证明持久预留不依赖正常关闭；独立主体只参与原生锁。
int child(const QStringList &arguments) {
    try {
        dukto::PrivateStore store(arguments[2]);
        if (arguments[1] == "--hold-lock") {
            dukto::BudgetFile file(store, false);
            dukto::BudgetFile::Lock lock(file, {}, 1000);
            QTextStream(stdout) << "ready" << Qt::endl;
            std::getchar();
            return 0;
        }
        Budget budget(store, Domain);
        const auto record = budget.lookup(QByteArray::fromHex(arguments[3].toLatin1()));
        QTextStream(stdout) << "ready" << Qt::endl;
        std::getchar();
        budget.reserve(record, 1024);
        std::_Exit(10);
    } catch (const dukto::Error &error) {
        QTextStream(stderr) << error.stage << ": " << error.message << Qt::endl;
        if (error.stage == "budget-full")
            return 11;
        if (error.stage == "budget-stale" || error.stage == "budget-pending")
            return 12;
        return 90;
    }
}
} // namespace

class StateBudgetTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；固定实际文件长度、私有键保留、初始化幂等拒绝及账本自身计量均核对原文件。
    void fixedFileAndPrivateBoundary() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        QCOMPARE(QFileInfo(path).size(), Budget::FileBytes);
        const auto original = dukto::hashFile(path);
        QVERIFY_EXCEPTION_THROWN(Budget::initialize(store, Domain, limits()), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(store.write("state-budget.bin", {}), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(store.remove("STATE-BUDGET.BIN"), dukto::Error);
        Budget budget(store, Domain);
        const auto usage = budget.usage();
        QCOMPARE(usage.totalCommitted, Budget::FileBytes);
        QCOMPARE(usage.totalReserved, qint64(0));
        QVERIFY(!usage.overdrawn);
        QCOMPARE(dukto::hashFile(path), original);
    }

    // 日期：2026-11-08；超32位数值不分配对应内存或磁盘，四类别与合计的最后额度独立生效。
    void categoriesAndLargeAmounts() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        auto quota = limits(1LL << 34);
        quota.categories[0] = 256;
        Budget::initialize(store, Domain, quota);
        Budget budget(store, Domain);
        const auto history = budget.enroll(key(1), Category::History, 128);
        const auto same = budget.enroll(key(1), Category::History, 128);
        QCOMPARE(same.registration, history.registration);
        QVERIFY_EXCEPTION_THROWN(budget.reserve(history, 257), dukto::Error);
        auto body = budget.enroll(key(2), Category::Body, 0);
        const auto pending = budget.reserve(body, (1LL << 32) + 17);
        QCOMPARE(budget.usage().reserved[2], (1LL << 32) + 17);
        body = budget.settle(pending, (1LL << 32) + 9);
        QCOMPARE(budget.usage().totalCommitted, Budget::FileBytes + 128 + (1LL << 32) + 9);
        QCOMPARE(QFileInfo(store.directory() + "/state-budget.bin").size(), Budget::FileBytes);
        QCOMPARE(body.reserved, qint64(0));
    }

    // 日期：2026-11-08；两个真实进程在同一持久预算争夺最后1024字节，只有一个获得增长资格。
    void processesCompeteForLastCredit() {
        compete(false);
    }

    // 日期：2026-11-08；同一对象的两个实际执行者使用同一旧修订，第二个不能重复发放预留。
    void processesCompeteForSameObject() {
        compete(true);
    }

    // 日期：2026-11-08；直接退出留下的预留跨重开保留；共享使用者不能冒充原执行者完成或退款。
    void exitRetainsCreditAndMaintenanceReconciles() {
        QTemporaryDir root;
        const auto state = root.filePath("state");
        {
            dukto::PrivateStore store(state, true, dukto::PrivateStore::Use::Maintenance);
            Budget::initialize(store, Domain, limits());
            Budget(store, Domain).enroll(key(1), Category::Body, 0);
        }
        ChildProcess process;
        start(process, {"--reserve", state, QString::fromLatin1(key(1).toHex())});
        process.write("x");
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 10);
        {
            dukto::PrivateStore store(state);
            Budget budget(store, Domain);
            const auto record = budget.lookup(key(1));
            QVERIFY(record.pending);
            QCOMPARE(budget.usage().totalReserved, qint64(1024));
            QVERIFY_EXCEPTION_THROWN(budget.settle(record, 0), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(budget.reconcile(record, 0), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(budget.retire(record), dukto::Error);
        }
        dukto::PrivateStore store(state, false, dukto::PrivateStore::Use::Maintenance);
        Budget budget(store, Domain);
        const auto finished = budget.reconcile(budget.lookup(key(1)), 512);
        QCOMPARE(budget.usage().totalCommitted, Budget::FileBytes + 512);
        budget.retire(finished);
        budget.retire(finished);
        QCOMPARE(budget.usage().totalCommitted, Budget::FileBytes);
        QCOMPARE(budget.usage().totalReserved, qint64(0));
    }

    // 日期：2026-11-08；最近完成通知可幂等，旧观察不能覆盖下次操作；超预期实物占用记为透支。
    void revisionsIdempotenceAndOverdraw() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        Budget budget(store, Domain);
        const auto initial = budget.enroll(key(1), Category::Body, 0);
        const auto first = budget.reserve(initial, 512);
        const auto done = budget.settle(first, 256);
        QCOMPARE(budget.settle(first, 256).revision, done.revision);
        QVERIFY_EXCEPTION_THROWN(budget.reserve(initial, 512), dukto::Error);
        const auto second = budget.reserve(done, 1024);
        QVERIFY_EXCEPTION_THROWN(budget.settle(first, 256), dukto::Error);
        const auto over = budget.settle(second, 2048);
        QVERIFY(budget.usage().overdrawn);
        QVERIFY_EXCEPTION_THROWN(budget.reserve(over, 2049), dukto::Error);
        const auto shrinking = budget.reserve(over, 1024);
        budget.settle(shrinking, 512);
        QVERIFY(!budget.usage().overdrawn);
        QCOMPARE(budget.usage().committed[2], qint64(512));
    }

    // 日期：2026-11-08；真实独立进程持有原生锁，取消/期限有界；原进程退出后同一账本可以继续使用。
    void nativeLockTimeoutAndCancellation() {
        QTemporaryDir root;
        const auto state = root.filePath("state");
        {
            dukto::PrivateStore store(state, true, dukto::PrivateStore::Use::Maintenance);
            Budget::initialize(store, Domain, limits());
        }
        dukto::PrivateStore store(state);
        Budget budget(store, Domain, {}, 30);
        ChildProcess process;
        start(process, {"--hold-lock", state});
        QElapsedTimer timer;
        timer.start();
        QVERIFY_EXCEPTION_THROWN(budget.usage(), dukto::Error);
        QVERIFY(timer.elapsed() < 2000);
        int checks = 0;
        QVERIFY_EXCEPTION_THROWN((Budget(store, Domain,
                                         [&]() {
                                             // 日期：2026-11-08；仅在等待锁时注入取消，不能在持锁回调内执行任意业务。
                                             if (++checks == 3)
                                                 throw dukto::Error(dukto::ExitCode::Cancelled,
                                                                    "cancel", "test");
                                         })),
                                 dukto::Error);
        QCOMPARE(checks, 3);
        process.kill();
        QVERIFY(process.waitForFinished(10000));
        QCOMPARE(budget.usage().totalCommitted, Budget::FileBytes);
    }

    // 日期：2026-11-08；同一实例被多线程调用时仍需互斥，真实文件头/槽合计不会丢更新。
    void threadsShareOneInstance() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        Budget budget(store, Domain, {}, 5000);
        std::array<Budget::Record, 4> records;
        for (int index = 0; index < 4; ++index)
            records[index] = budget.enroll(key(index), Category::Body, 0);
        std::array<bool, 4> passed{};
        std::vector<std::thread> workers;
        for (int index = 0; index < 4; ++index)
            workers.emplace_back([&, index]() {
                // 日期：2026-11-08；每线程只改自有记录，聚合值必须通过同一共享账本串行提交。
                try {
                    const auto pending = budget.reserve(records[index], 256);
                    budget.settle(pending, 128);
                    passed[index] = true;
                } catch (...) {
                }
            });
        for (auto &worker : workers)
            worker.join();
        for (const auto result : passed)
            QVERIFY(result);
        QCOMPARE(budget.usage().totalCommitted, Budget::FileBytes + 512);
        QCOMPARE(budget.usage().totalReserved, qint64(0));
    }

    // 日期：2026-11-08；每种布局都使用同一真实原件的旧/新记录，分别验证可恢复和拒绝范围。
    void writeAheadRecovery_data() {
        QTest::addColumn<int>("layout");
        for (int index = 0; index < 5; ++index)
            QTest::newRow(qPrintable(QString::number(index))) << index;
    }

    // 日期：2026-11-08；模拟意图已同步而头/槽任一尚未完整落盘，重开后预留只向前恢复且合计唯一。
    void writeAheadRecovery() {
        QFETCH(int, layout);
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        QByteArray before, after;
        Budget::Record pending;
        {
            Budget budget(store, Domain);
            const auto record = budget.enroll(key(1), Category::Body, 0);
            before = bytes(path);
            pending = budget.reserve(record, 1024);
            after = bytes(path);
        }
        auto interrupted = before;
        const int offset = 8192 + pending.slot * 256;
        if (layout == 1 || layout == 4)
            interrupted.replace(offset, 256, after.mid(offset, 256));
        if (layout == 2 || layout == 4)
            interrupted.replace(0, 512, after.left(512));
        if (layout == 3) {
            interrupted.replace(offset, 128, after.mid(offset, 128));
            interrupted.replace(0, 256, after.left(256));
        }
        interrupted.replace(4096, 4096, journal(before, after, pending.slot));
        replace(path, interrupted);
        Budget recovered(store, Domain);
        QCOMPARE(recovered.lookup(key(1)).operation, pending.operation);
        QCOMPARE(recovered.usage().totalReserved, qint64(1024));
        QCOMPARE(bytes(path), after);
    }

    // 日期：2026-11-08；正常日志清零前退出的完成操作可重放，重复完成/退役不重复退款。
    void completedTransactionReplay() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        QByteArray before, after;
        Budget::Record pending, done;
        {
            Budget budget(store, Domain);
            pending = budget.reserve(budget.enroll(key(1), Category::Body, 0), 1024);
            before = bytes(path);
            done = budget.settle(pending, 512);
            after = bytes(path);
        }
        auto interrupted = after;
        interrupted.replace(4096, 4096, journal(before, after, pending.slot));
        replace(path, interrupted);
        Budget recovered(store, Domain);
        QCOMPARE(recovered.usage().totalCommitted, Budget::FileBytes + 512);
        QCOMPARE(recovered.settle(pending, 512).revision, done.revision);
        recovered.retire(done);
        recovered.retire(done);
        QCOMPARE(recovered.usage().totalCommitted, Budget::FileBytes);
    }

    // 日期：2026-11-08；尺寸、头、日志、槽、域和根绑定的损坏均保留原件并拒绝；不回退到旧零占用。
    void corruptionAndDomainBinding() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        {
            Budget(store, Domain).enroll(key(1), Category::Body, 256);
        }
        const auto original = bytes(path);
        for (const int offset : {8, 512, 4096, 8192 + 104}) {
            auto bad = original;
            bad[offset] = char(bad[offset] ^ 0x01);
            replace(path, bad);
            QVERIFY_EXCEPTION_THROWN((Budget(store, Domain)), dukto::Error);
            QCOMPARE(bytes(path), bad);
        }
        replace(path, original.left(original.size() - 1));
        QVERIFY_EXCEPTION_THROWN((Budget(store, Domain)), dukto::Error);
        replace(path, original);
        QVERIFY_EXCEPTION_THROWN((Budget(store, QUuid::createUuid())), dukto::Error);
        dukto::PrivateStore other(root.filePath("other"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(other, Domain, limits());
        const auto copied = other.directory() + "/state-budget.bin";
        replace(copied, original);
        QVERIFY_EXCEPTION_THROWN((Budget(other, Domain)), dukto::Error);
        QCOMPARE(bytes(copied), original);
    }

    // 日期：2026-11-08；旧事务即使校验正确，也不能覆盖更新后的有效头/槽，拒绝时保留全部原字节。
    void staleJournalIsRejected() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        QByteArray oldIntent, latest;
        {
            Budget budget(store, Domain);
            const auto first = budget.enroll(key(1), Category::Body, 0);
            const auto before = bytes(path);
            const auto pending = budget.reserve(first, 512);
            oldIntent = journal(before, bytes(path), first.slot);
            budget.settle(pending, 256);
            latest = bytes(path);
        }
        latest.replace(4096, 4096, oldIntent);
        replace(path, latest);
        QVERIFY_EXCEPTION_THROWN((Budget(store, Domain)), dukto::Error);
        QCOMPARE(bytes(path), latest);
    }

    // 日期：2026-11-08；意图写入或清零撕裂不能视为无日志并退款，未知现场拒绝且可恢复原件保持。
    void tornIntentIsRejected() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        QByteArray before, after;
        int slot = -1;
        {
            Budget budget(store, Domain);
            const auto first = budget.enroll(key(1), Category::Body, 0);
            slot = first.slot;
            before = bytes(path);
            budget.reserve(first, 1024);
            after = bytes(path);
        }
        const auto intent = journal(before, after, slot);
        for (const int split : {1, 2048, 4064}) {
            for (const bool clearing : {false, true}) {
                auto damaged = clearing ? after : before;
                auto torn = intent;
                if (clearing)
                    torn.replace(0, split, QByteArray(split, '\0'));
                else
                    torn.replace(split, 4096 - split, QByteArray(4096 - split, '\0'));
                damaged.replace(4096, 4096, torn);
                replace(path, damaged);
                QVERIFY_EXCEPTION_THROWN((Budget(store, Domain)), dukto::Error);
                QCOMPARE(bytes(path), damaged);
            }
        }
    }

    // 日期：2026-11-08；空键、负金额和64位合计溢出不能改写账本，失败后原对象仍可继续授信。
    void invalidAdmissionLeavesLedgerUnchanged() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        Budget budget(store, Domain);
        const auto first = budget.enroll(key(1), Category::Body, 0);
        const auto path = store.directory() + "/state-budget.bin";
        const auto original = bytes(path);
        QVERIFY_EXCEPTION_THROWN(budget.enroll({}, Category::Body, 0), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(budget.enroll(QByteArray(32, '\0'), Category::Body, 0),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(budget.enroll(key(2), Category(4), 0), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(budget.enroll(key(2), Category::Body, -1), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(budget.reserve(first, -1), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(budget.reserve(first, std::numeric_limits<qint64>::max()),
                                 dukto::Error);
        QCOMPARE(bytes(path), original);
        const auto pending = budget.reserve(first, 1024);
        QVERIFY_EXCEPTION_THROWN(budget.settle(pending, -1), dukto::Error);
        QCOMPARE(budget.settle(pending, 512).committed, qint64(512));
    }

    // 日期：2026-11-08；固定槽全部有效但耗尽时受控拒绝，失败不扩张文件或制造新的空账本。
    void fixedSlotExhaustion() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        auto original = bytes(path);
        for (int index = 0; index < Budget::SlotCount; ++index) {
            QByteArray slot(256, '\0');
            number(slot, 0, 1);
            slot.replace(8, 32, key(index));
            slot.replace(40, 16, QUuid::createUuid().toRfc4122());
            number(slot, 88, 1);
            number(slot, 96, 3);
            original.replace(8192 + index * 256, 256, sealed(slot));
        }
        replace(path, original);
        Budget budget(store, Domain);
        QVERIFY_EXCEPTION_THROWN(budget.enroll(key(10000), Category::Body, 0), dukto::Error);
        QCOMPARE(bytes(path), original);
        const auto old = budget.lookup(key(0));
        budget.retire(old);
        const auto replacement = budget.enroll(key(10000), Category::Body, 1);
        QCOMPARE(replacement.slot, old.slot);
        QVERIFY(replacement.registration != old.registration);
        QVERIFY_EXCEPTION_THROWN(budget.retire(old), dukto::Error);
        QCOMPARE(budget.usage().totalCommitted, Budget::FileBytes + 1);
    }

    // 日期：2026-11-08；真实硬链接使账本不再独立，所有平台必须拒绝共享同一对象的另一名称。
    void hardLinkIsRejected() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto path = store.directory() + "/state-budget.bin";
        const auto alias = store.directory() + "/alias.bin";
#ifdef Q_OS_WIN
        QVERIFY(CreateHardLinkW(reinterpret_cast<LPCWSTR>(QDir::toNativeSeparators(alias).utf16()),
                                reinterpret_cast<LPCWSTR>(QDir::toNativeSeparators(path).utf16()),
                                nullptr));
#else
        QVERIFY(::link(QFile::encodeName(path).constData(), QFile::encodeName(alias).constData()) ==
                0);
#endif
        QVERIFY_EXCEPTION_THROWN((Budget(store, Domain)), dukto::Error);
    }

    // 日期：2026-11-08；重复有界写入/对账及重开不增加文件长度，不借用SQLite连接，也归还应用缓冲授信。
    void repeatedUseReturnsResources() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        Budget::initialize(store, Domain, limits());
        const auto credit = dukto::BufferCredit::usage().value("used");
        const auto connections = QSqlDatabase::connectionNames();
        {
            Budget budget(store, Domain);
            auto record = budget.enroll(key(1), Category::Body, 0);
            for (int round = 0; round < 64; ++round)
                record = budget.settle(budget.reserve(record, 1024), round % 2 ? 0 : 512);
            budget.retire(record);
        }
        QCOMPARE(Budget(store, Domain).usage().totalCommitted, Budget::FileBytes);
        QCOMPARE(QFileInfo(store.directory() + "/state-budget.bin").size(), Budget::FileBytes);
        QCOMPARE(dukto::BufferCredit::usage().value("used"), credit);
        QCOMPARE(QSqlDatabase::connectionNames(), connections);
    }

  private:
    // 日期：2026-11-08；真实竞争公共夹具保留不同对象与同对象的独立结果，退出码不得被忽略。
    void compete(bool same) {
        QTemporaryDir root;
        const auto state = root.filePath("state");
        {
            dukto::PrivateStore store(state, true, dukto::PrivateStore::Use::Maintenance);
            Budget::initialize(store, Domain, limits());
            Budget budget(store, Domain);
            budget.enroll(key(1), Category::Body, 0);
            if (!same)
                budget.enroll(key(2), Category::Body, 0);
        }
        ChildProcess first, second;
        start(first, {"--reserve", state, QString::fromLatin1(key(1).toHex())});
        start(second, {"--reserve", state, QString::fromLatin1(key(same ? 1 : 2).toHex())});
        first.write("x");
        second.write("x");
        QVERIFY(first.waitForFinished(30000));
        QVERIFY(second.waitForFinished(30000));
        const int loser = same ? 12 : 11;
        QVERIFY((first.exitCode() == 10 && second.exitCode() == loser) ||
                (second.exitCode() == 10 && first.exitCode() == loser));
        dukto::PrivateStore store(state);
        Budget budget(store, Domain);
        QCOMPARE(budget.usage().totalReserved, qint64(1024));
        QCOMPARE(budget.usage().totalCommitted, Budget::FileBytes);
        QVERIFY(!budget.usage().overdrawn);
    }
};

// 日期：2026-11-08；Qt测试与真实子进程使用同一程序，特殊模式不能误入普通方法计数。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto arguments = app.arguments();
    if (arguments.size() >= 3 && (arguments[1] == "--reserve" || arguments[1] == "--hold-lock"))
        return child(arguments);
    StateBudgetTests tests;
    return QTest::qExec(&tests, argc, argv);
}
#include "state_budget_tests.moc"

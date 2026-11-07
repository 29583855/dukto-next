#include "core/clientdownloadcleanup.h"
#include "core/durablereceive.h"
#include "core/error.h"
#include "core/expiredtaskcleanup.h"
#include "core/files.h"
#include "core/strongmanifest.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QProcess>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>
#include <cstdlib>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace {
// 日期：2026-11-07；只打开测试自有SQLite库，查询和异常处理结束后立即归还连接。
void database(const QString &path, const std::function<void(QSqlDatabase)> &callback) {
    const auto name = QUuid::createUuid().toString();
    auto db = QSqlDatabase::addDatabase("QSQLITE", name);
    db.setDatabaseName(path);
    if (!db.open())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture open", "test");
    try {
        callback(db);
    } catch (...) {
        db.close();
        db = QSqlDatabase();
        QSqlDatabase::removeDatabase(name);
        throw;
    }
    db.close();
    db = QSqlDatabase();
    QSqlDatabase::removeDatabase(name);
}

// 日期：2026-11-07；直接读原接收日志，独立于被测清理模块判断持久状态、原生身份和临时名。
QJsonObject directoryRow(const QString &journal) {
    QJsonObject result;
    database(journal, [&](QSqlDatabase db) {
        QSqlQuery query(db);
        if (!query.exec(
                "SELECT state,temporary,target,length(native) FROM directories WHERE id=3") ||
            !query.next())
            throw dukto::Error(dukto::ExitCode::Disk, "fixture directory row", "test");
        result = {{"state", query.value(0).toString()},
                  {"temporary", query.value(1).toString()},
                  {"target", query.value(2).toString()},
                  {"nativeBytes", query.value(3).toInt()}};
    });
    return result;
}

// 日期：2026-11-07；独立读库确认删除意图已经提交，测试不依赖产品内部回调次数。
bool hasDirectoryIntent(const QString &journal) {
    bool found = false;
    database(journal, [&](QSqlDatabase db) {
        QSqlQuery query(db);
        if (!query.exec(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='directory_cleanup'"))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture intent table", "test");
        if (!query.next())
            return;
        query.finish();
        if (!query.exec("SELECT 1 FROM directory_cleanup WHERE id=3 AND cleaned=0"))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture intent row", "test");
        found = query.next();
    });
    return found;
}

// 日期：2026-11-07；只读取测试拥有的最终跳过证据，分辨缺记录、待清理和已确认状态。
qint64 finalSkipCleaned(const QString &journal) {
    qint64 cleaned = -1;
    database(journal, [&](QSqlDatabase db) {
        QSqlQuery query(db);
        if (!query.exec("SELECT cleaned FROM skip_final WHERE id=3"))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture final skip", "test");
        if (query.next())
            cleaned = query.value(0).toLongLong();
    });
    return cleaned;
}

// 日期：2026-11-07；独立读取维护确认位，区分已确认与记录缺失，不能只判断待办行消失。
qint64 directoryIntentCleaned(const QString &journal) {
    qint64 cleaned = -1;
    database(journal, [&](QSqlDatabase db) {
        QSqlQuery query(db);
        if (!query.exec("SELECT cleaned FROM directory_cleanup WHERE id=3") || !query.next())
            throw dukto::Error(dukto::ExitCode::Disk, "fixture cleanup confirmation", "test");
        cleaned = query.value(0).toLongLong();
    });
    return cleaned;
}

struct Fixture {
    QTemporaryDir root;
    bool server;
    QUuid task = QUuid::createUuid();
    const QUuid owner = QUuid::createUuid();
    const QString stateParent = root.filePath("state");
    QString state;
    QString manifestName;
    QString journal;
    const QString output = root.filePath("output");
    QString mapped;
    QDateTime expiry;
    const QByteArray body = QByteArray(1024, 'd');
    dukto::ConflictPolicy policy;

    // 日期：2026-11-07；生产接收器在目录发布前/后实际中断，保留已完成文件和其他真实目录。
    explicit Fixture(bool isServer = false, const QString &phase = "before", int extra = 0,
                     dukto::ConflictPolicy conflict = dukto::ConflictPolicy::Rename)
        : server(isServer), policy(conflict) {
        const auto sources = root.filePath("sources/package");
        if (!root.isValid() || !QDir().mkpath(sources + "/b-pending") || !QDir().mkpath(output) ||
            !QDir().mkpath(stateParent))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture mkdir", "test");
        for (int i = 0; i < extra; ++i)
            if (!QDir().mkpath(sources + QString("/c%1").arg(i, 3, 10, QChar('0'))))
                throw dukto::Error(dukto::ExitCode::Disk, "fixture extra mkdir", "test");
        QFile file(sources + "/a.bin");
        if (!file.open(QIODevice::WriteOnly) || file.write(body) != body.size())
            throw dukto::Error(dukto::ExitCode::Disk, "fixture source", "test");
        file.close();
        state = QDir(stateParent).filePath(server ? "service" : "transfers");
        dukto::PrivateStore store(state, true);
        QJsonObject summary;
        {
            dukto::StrongManifest seed(store, "seed.sqlite", true);
            seed.scan({sources});
            summary = seed.summary();
            if (seed.entry(3).relative != "package/b-pending")
                throw dukto::Error(dukto::ExitCode::Runtime, "fixture ordering", "test");
        }
        quint64 revision = 0;
        if (server) {
            dukto::TaskStore tasks(store);
            const auto identity = QByteArray::fromHex(summary["sha256"].toString().toLatin1());
            auto value = tasks.create(owner, QUuid::createUuid(), "upload", "docs", "", output,
                                      identity, policy, policy == dukto::ConflictPolicy::Skip);
            task = value.id;
            auto lease = tasks.acquire(owner, task);
            value = tasks.bindManifest(*lease, summary);
            value = tasks.advance(*lease, value.revision, "transferring", 0);
            revision = value.revision;
        }
        const auto key = task.toString(QUuid::WithoutBraces);
        manifestName = (server ? "manifest-" : "download-") + key + ".sqlite";
        store.write(manifestName, store.read("seed.sqlite", 1024 * 1024));
        journal = QDir(state).filePath("receive-" + key + ".sqlite");
        {
            dukto::StrongManifest manifest(store, manifestName, false);
            dukto::DurableReceive receiver(store, QFileInfo(journal).fileName(), task, manifest,
                                           output, policy);
            mapped = receiver.prepareDisposition(1).path;
            const auto prepared = receiver.prepareDisposition(2);
            receiver.openDisposition(2, prepared.path);
            receiver.write(0, 0, body);
            receiver.finishDisposition();
            for (int i = 0; i < extra; ++i)
                receiver.prepareDisposition(static_cast<quint64>(4 + i));
            bool interrupted = false;
            bool injectedSkipTarget = false;
            try {
                receiver.prepareDisposition(3, [&]() {
                    // 日期：2026-11-07；按真实随机临时目录或真实发布名触发，不能依赖内部回调次数。
                    const auto parent = QDir(output).filePath(mapped);
                    const bool temporaryExists =
                        !QDir(parent)
                             .entryList({".dukto-*.dir"},
                                        QDir::Dirs | QDir::Hidden | QDir::NoDotAndDotDot)
                             .isEmpty();
                    const bool published = QFileInfo::exists(parent + "/b-pending");
                    if ((phase == "skip" || phase == "skip-after-delete") && temporaryExists &&
                        !injectedSkipTarget) {
                        const auto conflict = parent + "/b-pending";
                        if (!QDir().mkdir(conflict))
                            throw dukto::Error(dukto::ExitCode::Disk, "fixture skip mkdir", "test");
                        QFile keep(conflict + "/keep.bin");
                        if (!keep.open(QIODevice::WriteOnly) || keep.write("outside") != 7)
                            throw dukto::Error(dukto::ExitCode::Disk, "fixture skip target",
                                               "test");
                        injectedSkipTarget = true;
                    }
                    if (phase == "skip" && finalSkipCleaned(journal) == 0)
                        throw dukto::Error(dukto::ExitCode::Cancelled, "fixture skip interruption",
                                           "test");
                    if (phase == "skip-after-delete" && !temporaryExists &&
                        finalSkipCleaned(journal) == 0)
                        throw dukto::Error(dukto::ExitCode::Cancelled,
                                           "fixture skip confirmation interruption", "test");
                    if ((phase == "before" && temporaryExists) || (phase == "after" && published))
                        throw dukto::Error(dukto::ExitCode::Cancelled, "fixture interruption",
                                           "test");
                });
            } catch (const dukto::Error &error) {
                if (error.code != dukto::ExitCode::Cancelled)
                    throw;
                interrupted = true;
            }
            if (!interrupted)
                throw dukto::Error(dukto::ExitCode::Runtime, "fixture did not interrupt", "test");
        }
        if (server) {
            dukto::TaskStore tasks(store);
            auto lease = tasks.acquire(owner, task);
            tasks.advance(*lease, revision, "interrupted", 0);
            database(QDir(state).filePath("tasks.sqlite"), [&](QSqlDatabase db) {
                QSqlQuery query(db);
                query.prepare("SELECT updated FROM tasks WHERE id=?");
                query.addBindValue(key);
                if (!query.exec() || !query.next())
                    throw dukto::Error(dukto::ExitCode::Disk, "fixture task time", "test");
                expiry = QDateTime::fromString(query.value(0).toString(), Qt::ISODate).addDays(8);
            });
        }
    }

    // 日期：2026-11-07；统一经真实公开核心入口调用，客户端与服务器各自取得独占维护锁。
    QJsonObject cleanup(bool apply, quint64 after = 0, const std::function<void()> &check = {}) {
        dukto::PrivateStore store(state, false, dukto::PrivateStore::Use::Maintenance);
        return server ? dukto::cleanupExpiredUpload(store, owner, task, expiry, apply, after, check)
                      : dukto::cleanupClientDownload(store, task, apply, after, check);
    }

    // 日期：2026-11-07；真实维护子进程在FULL意图提交后或删除后退出，不执行析构或补确认。
    void crashCleanup(bool afterRemoval) {
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {afterRemoval ? "--crash-cleanup" : "--crash-before-cleanup",
                       server ? "server" : "client", state, owner.toString(QUuid::WithoutBraces),
                       task.toString(QUuid::WithoutBraces), expiry.toString(Qt::ISODate),
                       temporary()});
        if (!process.waitForFinished(30000) || process.exitCode() != 47)
            throw dukto::Error(dukto::ExitCode::Runtime, "fixture cleanup did not crash", "test");
    }

    // 日期：2026-11-07；维护退出后新建原接收器，使用真实持久决定完成跳过，不修改任务授权或终态。
    void resumeSkippedDirectory() {
        dukto::PrivateStore store(state);
        dukto::StrongManifest manifest(store, manifestName, false);
        dukto::DurableReceive receiver(store, QFileInfo(journal).fileName(), task, manifest, output,
                                       policy);
        const auto result = receiver.prepareDisposition(3);
        if (!result.skipped || result.skippedRoot != 3 || result.path != mapped + "/b-pending")
            throw dukto::Error(dukto::ExitCode::Runtime, "fixture skip recovery", "test");
    }

    // 日期：2026-11-07；返回原日志中的随机临时路径，不依赖清理函数输出定位删除对象。
    QString temporary() const {
        return QDir(output).filePath(directoryRow(journal)["temporary"].toString());
    }

    // 日期：2026-11-07；执行仅针对测试自有接收日志的固定损坏语句，构造失败不能被忽略。
    void change(const QString &statement) {
        database(journal, [&](QSqlDatabase db) {
            QSqlQuery query(db);
            if (!query.exec(statement))
                throw dukto::Error(dukto::ExitCode::Disk, "fixture change", "test");
        });
    }

    // 日期：2026-11-07；独立读取已发布正文和输入源，确认清理未误删完成项目。
    bool completedDataPreserved() const {
        QFile completed(QDir(output).filePath(mapped + "/a.bin"));
        QFile source(root.filePath("sources/package/a.bin"));
        return completed.open(QIODevice::ReadOnly) && completed.readAll() == body &&
               source.open(QIODevice::ReadOnly) && source.readAll() == body;
    }
};

// 日期：2026-11-07；筛选ID=3的真实分页结果，独立确认目录条目与普通文件使用相同游标。
QJsonObject pendingEntry(const QJsonObject &result) {
    for (const auto &item : result["entries"].toArray())
        if (item.toObject()["id"] == "3")
            return item.toObject();
    throw dukto::Error(dukto::ExitCode::Runtime, "fixture pending entry absent", "test");
}
} // namespace

class DirectoryCleanupTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-07；两个角色各覆盖删除前后真实进程退出，再由原接收器完成确认的交错顺序。
    void finalSkipReceiverMaintenanceConvergence_data() {
        QTest::addColumn<bool>("server");
        QTest::addColumn<bool>("afterRemoval");
        for (const bool server : {false, true})
            for (const bool afterRemoval : {false, true})
                QTest::newRow(((server ? "server-" : "client-") +
                               QString(afterRemoval ? "after-delete" : "before-delete"))
                                  .toUtf8())
                    << server << afterRemoval;
    }

    // 日期：2026-11-07；接收器已确认时维护仅补日志；预览、事务回滚和重入均保留同名新目录内容。
    void finalSkipReceiverMaintenanceConvergence() {
        QFETCH(bool, server);
        QFETCH(bool, afterRemoval);
        Fixture fixture(server, "skip", 0, dukto::ConflictPolicy::Skip);
        const auto temporary = fixture.temporary();
        fixture.crashCleanup(afterRemoval);
        QCOMPARE(QFileInfo::exists(temporary), !afterRemoval);
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(0));
        QCOMPARE(directoryIntentCleaned(fixture.journal), qint64(0));
        fixture.resumeSkippedDirectory();
        QVERIFY(!QFileInfo::exists(temporary));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(1));
        QCOMPARE(directoryIntentCleaned(fixture.journal), qint64(0));
        QVERIFY(QDir().mkdir(temporary));
        QFile keep(temporary + "/keep.bin");
        QVERIFY(keep.open(QIODevice::WriteOnly));
        QCOMPARE(keep.write("external replacement"), qint64(20));
        keep.close();
        QJsonObject preview;
        try {
            preview = fixture.cleanup(false);
        } catch (const dukto::Error &error) {
            QFAIL(qPrintable(error.message));
        }
        QCOMPARE(pendingEntry(preview)["action"].toString(), QString("pending-confirmation"));
        QCOMPARE(directoryIntentCleaned(fixture.journal), qint64(0));
        fixture.change(
            "CREATE TRIGGER reject_adoption BEFORE UPDATE OF cleaned ON directory_cleanup "
            "WHEN NEW.cleaned=1 BEGIN SELECT RAISE(ABORT,'fixture adoption failure'); END");
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QCOMPARE(directoryIntentCleaned(fixture.journal), qint64(0));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(1));
        fixture.change("DROP TRIGGER reject_adoption");
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QCOMPARE(directoryIntentCleaned(fixture.journal), qint64(1));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(1));
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        fixture.resumeSkippedDirectory();
        QVERIFY(keep.open(QIODevice::ReadOnly));
        QCOMPARE(keep.readAll(), QByteArray("external replacement"));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；接收器完成后的日志协调仍须拒绝损坏证明和不可能的反向完成状态。
    void finalSkipReconciliationRejectsDamage_data() {
        QTest::addColumn<bool>("server");
        QTest::addColumn<QString>("damage");
        for (const bool server : {false, true})
            for (const auto &damage : QStringList{"directory-proof", "skip-proof", "reverse"})
                QTest::newRow(((server ? "server-" : "client-") + damage).toUtf8())
                    << server << damage;
    }

    // 日期：2026-11-07；原生新对象与已完成正文保留，不能仅凭cleaned=1绕过原决定和维护意图。
    void finalSkipReconciliationRejectsDamage() {
        QFETCH(bool, server);
        QFETCH(QString, damage);
        Fixture fixture(server, "skip", 0, dukto::ConflictPolicy::Skip);
        const auto temporary = fixture.temporary();
        fixture.crashCleanup(true);
        fixture.resumeSkippedDirectory();
        QVERIFY(QDir().mkdir(temporary));
        fixture.change(damage == "directory-proof" ? "UPDATE directory_cleanup SET spec=x'7b7d'"
                       : damage == "skip-proof"    ? "UPDATE skip_final SET spec=x'7b7d'"
                                                   : "UPDATE skip_final SET cleaned=0");
        if (damage == "reverse")
            fixture.change("UPDATE directory_cleanup SET cleaned=1");
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(false), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QVERIFY(QFileInfo::exists(temporary));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；最终skip目录清理、删除后取消重入和幂等确认同时覆盖客户端与服务器。
    void finalSkipCleanup_data() {
        QTest::addColumn<bool>("server");
        QTest::newRow("client") << false;
        QTest::newRow("server") << true;
    }

    // 日期：2026-11-07；只有skip_final完整证明原临时身份时才清理，两个完成位在同一事务确认。
    void finalSkipCleanup() {
        QFETCH(bool, server);
        Fixture fixture(server, "skip", 0, dukto::ConflictPolicy::Skip);
        const auto temporary = fixture.temporary();
        const auto keep = QDir(fixture.output).filePath(fixture.mapped + "/b-pending/keep.bin");
        QVERIFY(QFileInfo::exists(temporary));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(0));
        QCOMPARE(pendingEntry(fixture.cleanup(false))["action"].toString(), QString("temporary"));
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true, 0,
                                                 [&]() {
                                                     if (!QFileInfo::exists(temporary) &&
                                                         hasDirectoryIntent(fixture.journal))
                                                         throw dukto::Error(
                                                             dukto::ExitCode::Cancelled,
                                                             "fixture cleanup pause", "test");
                                                 }),
                                 dukto::Error);
        QVERIFY(!QFileInfo::exists(temporary));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(0));
        QVERIFY(hasDirectoryIntent(fixture.journal));
        fixture.change("CREATE TRIGGER reject_directory_confirmation "
                       "BEFORE UPDATE OF cleaned ON directory_cleanup WHEN NEW.cleaned=1 "
                       "BEGIN SELECT RAISE(ABORT,'fixture confirmation failure'); END");
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(0));
        QVERIFY(hasDirectoryIntent(fixture.journal));
        fixture.change("DROP TRIGGER reject_directory_confirmation");
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(1));
        QCOMPARE(directoryRow(fixture.journal)["state"].toString(), QString("committing"));
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QVERIFY(QFileInfo::exists(keep));
        QCOMPARE(fixture.completedDataPreserved(), true);
    }

    // 日期：2026-11-07；接收器删除临时目录后退出时，目标原生身份与skip证明允许维护安全补确认。
    void finalSkipReceiverCrashAfterRemoval_data() {
        QTest::addColumn<bool>("server");
        QTest::newRow("client") << false;
        QTest::newRow("server") << true;
    }

    // 日期：2026-11-07；原skip清理的删除后崩溃窗口可恢复，外部冲突目录及其中数据保持不变。
    void finalSkipReceiverCrashAfterRemoval() {
        QFETCH(bool, server);
        Fixture fixture(server, "skip-after-delete", 0, dukto::ConflictPolicy::Skip);
        QVERIFY(!QFileInfo::exists(fixture.temporary()));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(0));
        QCOMPARE(pendingEntry(fixture.cleanup(false))["action"].toString(),
                 QString("pending-confirmation"));
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QCOMPARE(finalSkipCleaned(fixture.journal), qint64(1));
        QVERIFY(QFileInfo::exists(
            QDir(fixture.output).filePath(fixture.mapped + "/b-pending/keep.bin")));
    }

    // 日期：2026-11-07；客户端下载清理后同一任务重新创建原目录，服务器保留清理确认及幂等历史。
    void cleanupAndResume_data() {
        QTest::addColumn<bool>("server");
        QTest::newRow("client") << false;
        QTest::newRow("server") << true;
    }

    // 日期：2026-11-07；同时检查预览零修改、已完成正文保护、删除、重复执行及原接收器恢复。
    void cleanupAndResume() {
        QFETCH(bool, server);
        Fixture fixture(server);
        const auto temporary = fixture.temporary();
        QCOMPARE(directoryRow(fixture.journal)["state"].toString(), QString("committing"));
        const auto preview = fixture.cleanup(false);
        QCOMPARE(pendingEntry(preview)["kind"].toString(), QString("directory"));
        QCOMPARE(pendingEntry(preview)["action"].toString(), QString("temporary"));
        QVERIFY(QFileInfo::exists(temporary));
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QVERIFY(!QFileInfo::exists(temporary));
        QVERIFY(fixture.completedDataPreserved());
        if (server) {
            QVERIFY(QDir().mkdir(temporary));
            QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
            QVERIFY(QFileInfo::exists(temporary));
        } else {
            QCOMPARE(directoryRow(fixture.journal)["state"].toString(), QString("planned"));
            QCOMPARE(directoryRow(fixture.journal)["nativeBytes"].toInt(), 0);
            QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("0"));
            dukto::PrivateStore store(fixture.state);
            dukto::StrongManifest manifest(store, fixture.manifestName, false);
            dukto::DurableReceive receiver(store, QFileInfo(fixture.journal).fileName(),
                                           fixture.task, manifest, fixture.output);
            QCOMPARE(receiver.prepare(3), fixture.mapped + "/b-pending");
        }
    }

    // 日期：2026-11-07；复用客户端/服务器样本，覆盖重命名已发生而完成确认未持久化的崩溃窗口。
    void publishedCommitIsPreserved_data() {
        cleanupAndResume_data();
    }

    // 日期：2026-11-07；按原生身份确认已发布目录，绝不将committing一概当成垃圾。
    void publishedCommitIsPreserved() {
        QFETCH(bool, server);
        Fixture fixture(server, "after");
        const auto published = QDir(fixture.output).filePath(fixture.mapped + "/b-pending");
        QVERIFY(QFileInfo::exists(published));
        QCOMPARE(pendingEntry(fixture.cleanup(false))["action"].toString(),
                 QString("preserved-published"));
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("0"));
        QVERIFY(QFileInfo::exists(published));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；四种冲突策略及客户端/服务器均运行生产目录接收路径。
    void policies_data() {
        QTest::addColumn<bool>("server");
        QTest::addColumn<QString>("policy");
        for (const bool server : {false, true})
            for (const auto &policy : QStringList{"rename", "fail", "overwrite", "skip"})
                QTest::newRow(((server ? "server-" : "client-") + policy).toUtf8())
                    << server << policy;
    }

    // 日期：2026-11-07；skip保持既有持久处置边界，其余策略清理后不改变已完成正文。
    void policies() {
        QFETCH(bool, server);
        QFETCH(QString, policy);
        Fixture fixture(server, "before", 0, dukto::checkedConflictPolicy(policy));
        const auto temporary = fixture.temporary();
        const auto result = fixture.cleanup(true);
        QCOMPARE(result["cleanedDirectories"].toString(),
                 policy == "skip" ? QString("0") : QString("1"));
        QCOMPARE(QFileInfo::exists(temporary), policy == "skip");
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；删除前替换、缺失且无意图、非空目录各自保持原数据并明确拒绝。
    void unsafeDirectories_data() {
        QTest::addColumn<bool>("server");
        QTest::addColumn<QString>("mode");
        for (const bool server : {false, true})
            for (const auto &mode :
                 QStringList{"replacement", "missing", "nonempty", "file", "damaged-spec"})
                QTest::newRow(((server ? "server-" : "client-") + mode).toUtf8()) << server << mode;
    }

    // 日期：2026-11-07；保留外部新增内容，不能递归删除或仅靠随机目录名推定归属。
    void unsafeDirectories() {
        QFETCH(bool, server);
        QFETCH(QString, mode);
        Fixture fixture(server);
        const auto temporary = fixture.temporary();
        if (mode == "replacement" || mode == "file") {
            QVERIFY(QDir().rename(temporary, temporary + "-held"));
            if (mode == "replacement")
                QVERIFY(QDir().mkdir(temporary));
            else {
                QFile replacement(temporary);
                QVERIFY(replacement.open(QIODevice::WriteOnly));
                QCOMPARE(replacement.write("original"), qint64(8));
            }
        } else if (mode == "missing") {
            QVERIFY(QDir().rmdir(temporary));
        } else if (mode == "nonempty") {
            QFile keep(temporary + "/user.bin");
            QVERIFY(keep.open(QIODevice::WriteOnly));
            QCOMPARE(keep.write("user-data"), qint64(9));
        } else
            fixture.change("UPDATE directories SET spec=x'7b7d' WHERE id=3");
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QCOMPARE(QFileInfo::exists(temporary), mode != "missing");
        QVERIFY(fixture.completedDataPreserved());
        if (mode == "nonempty") {
            QVERIFY(QFile::remove(temporary + "/user.bin"));
            QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        }
    }

    // 日期：2026-11-07；真实子进程在目录删除后跳过析构，两个角色均需恢复锁和原删除意图。
    void processExitAfterRemoval_data() {
        cleanupAndResume_data();
    }

    // 日期：2026-11-07；不是模拟缺文件，子进程确实执行生产清理并在FULL确认之前_Exit。
    void processExitAfterRemoval() {
        QFETCH(bool, server);
        Fixture fixture(server);
        const auto temporary = fixture.temporary();
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(),
                      {"--crash-cleanup", server ? "server" : "client", fixture.state,
                       fixture.owner.toString(QUuid::WithoutBraces),
                       fixture.task.toString(QUuid::WithoutBraces),
                       fixture.expiry.toString(Qt::ISODate), temporary});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 47);
        QVERIFY(!QFileInfo::exists(temporary));
        QCOMPARE(directoryRow(fixture.journal)["state"].toString(), QString("committing"));
        QCOMPARE(pendingEntry(fixture.cleanup(false))["action"].toString(),
                 QString("pending-confirmation"));
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；客户端SQL复位后、事务提交前取消必须回滚，随后仍可由持久删除意图恢复。
    void confirmationRollback() {
        Fixture fixture;
        const auto temporary = fixture.temporary();
        int missing = 0;
        QVERIFY_EXCEPTION_THROWN(
            fixture.cleanup(true, 0,
                            [&]() {
                                if (!QFileInfo::exists(temporary) && ++missing == 2)
                                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel",
                                                       "test");
                            }),
            dukto::Error);
        QCOMPARE(missing, 2);
        QCOMPARE(directoryRow(fixture.journal)["state"].toString(), QString("committing"));
        QVERIFY(directoryRow(fixture.journal)["nativeBytes"].toInt() > 0);
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QCOMPARE(directoryRow(fixture.journal)["state"].toString(), QString("planned"));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；两个角色在删除意图FULL提交后、系统删除前分别取消或真实退出。
    void interruptionBeforeRemoval_data() {
        QTest::addColumn<bool>("server");
        QTest::addColumn<QString>("mode");
        for (const bool server : {false, true})
            for (const auto &mode : QStringList{"cancel", "process"})
                QTest::newRow(((server ? "server-" : "client-") + mode).toUtf8()) << server << mode;
    }

    // 日期：2026-11-07；原目录必须仍在，随后同任务重入可完成，不能把未删除的意图当成成功。
    void interruptionBeforeRemoval() {
        QFETCH(bool, server);
        QFETCH(QString, mode);
        Fixture fixture(server);
        const auto temporary = fixture.temporary();
        if (mode == "process") {
            QProcess process;
            process.start(QCoreApplication::applicationFilePath(),
                          {"--crash-before-cleanup", server ? "server" : "client", fixture.state,
                           fixture.owner.toString(QUuid::WithoutBraces),
                           fixture.task.toString(QUuid::WithoutBraces),
                           fixture.expiry.toString(Qt::ISODate), temporary});
            QVERIFY(process.waitForFinished(30000));
            QCOMPARE(process.exitCode(), 47);
        } else {
            QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true, 0,
                                                     [&]() {
                                                         // 日期：2026-11-07；确认持久意图可由另一连接读取后才取消。
                                                         if (hasDirectoryIntent(fixture.journal))
                                                             throw dukto::Error(
                                                                 dukto::ExitCode::Cancelled,
                                                                 "cancel before delete", "test");
                                                     }),
                                     dukto::Error);
        }
        QVERIFY(QFileInfo::exists(temporary));
        QVERIFY(hasDirectoryIntent(fixture.journal));
        QCOMPARE(directoryRow(fixture.journal)["state"].toString(), QString("committing"));
        QCOMPARE(fixture.cleanup(true)["cleanedDirectories"].toString(), QString("1"));
        QVERIFY(!QFileInfo::exists(temporary));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；损坏持久意图的正文或超32位确认整数均必须拒绝，而不能截断为合法状态。
    void damagedIntent_data() {
        QTest::addColumn<bool>("server");
        QTest::addColumn<QString>("mode");
        for (const bool server : {false, true})
            for (const auto &mode : QStringList{"spec", "wide-zero", "wide-one"})
                QTest::newRow(((server ? "server-" : "client-") + mode).toUtf8()) << server << mode;
    }

    // 日期：2026-11-07；先由非空目录真实拒绝生成意图，再损坏日志，额外内容及原目录始终保留。
    void damagedIntent() {
        QFETCH(bool, server);
        QFETCH(QString, mode);
        Fixture fixture(server);
        const auto temporary = fixture.temporary();
        QFile keep(temporary + "/keep.bin");
        QVERIFY(keep.open(QIODevice::WriteOnly));
        QCOMPARE(keep.write("keep"), qint64(4));
        keep.close();
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QVERIFY(hasDirectoryIntent(fixture.journal));
        QVERIFY(QFile::remove(keep.fileName()));
        database(fixture.journal, [&](QSqlDatabase db) {
            QSqlQuery query(db);
            if (!query.exec("PRAGMA ignore_check_constraints=ON") ||
                !query.exec(mode == "spec"
                                ? "UPDATE directory_cleanup SET spec=x'7b7d'"
                                : "UPDATE directory_cleanup SET cleaned=" +
                                      QString(mode == "wide-zero" ? "4294967296" : "4294967297")))
                throw dukto::Error(dukto::ExitCode::Disk, "fixture damaged intent", "test");
        });
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(false), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QVERIFY(QFileInfo::exists(temporary));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；接收日志即使没有WAL旁路文件，也不能在不支持的模式下运行维护。
    void walModeWithoutSidecars_data() {
        cleanupAndResume_data();
    }

    // 日期：2026-11-07；两个角色均从SQLite元数据拒绝WAL，且原目录不被删除。
    void walModeWithoutSidecars() {
        QFETCH(bool, server);
        Fixture fixture(server);
        const auto temporary = fixture.temporary();
        database(fixture.journal, [](QSqlDatabase db) {
            QSqlQuery query(db);
            if (!query.exec("PRAGMA journal_mode=WAL") || !query.next() || query.value(0) != "wal")
                throw dukto::Error(dukto::ExitCode::Disk, "fixture directory WAL", "test");
        });
        QVERIFY(!QFileInfo::exists(fixture.journal + "-wal"));
        QVERIFY(!QFileInfo::exists(fixture.journal + "-shm"));
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(false), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QVERIFY(QFileInfo::exists(temporary));
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；Windows使用真实junction，POSIX使用真实符号链接，绝不模拟成普通目录。
    void linkedDirectoryIsRejected_data() {
        cleanupAndResume_data();
    }

    // 日期：2026-11-07；链接指向测试自有目录，确认拒绝后只解除链接，防止测试清理误跟随目标。
    void linkedDirectoryIsRejected() {
        QFETCH(bool, server);
        Fixture fixture(server);
        const auto temporary = fixture.temporary();
        const auto held = temporary + "-held";
        QVERIFY(QDir().rename(temporary, held));
#ifdef Q_OS_WIN
        QProcess process;
        process.start("cmd.exe", {"/d", "/c", "mklink", "/J", QDir::toNativeSeparators(temporary),
                                  QDir::toNativeSeparators(held)});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 0);
#else
        QVERIFY(QFile::link(held, temporary));
#endif
        bool rejected = false;
        try {
            fixture.cleanup(true);
        } catch (const dukto::Error &) {
            rejected = true;
        }
#ifdef Q_OS_WIN
        const bool unlinked = RemoveDirectoryW(reinterpret_cast<LPCWSTR>(temporary.utf16()));
#else
        const bool unlinked = QFile::remove(temporary);
#endif
        QVERIFY(unlinked);
        QVERIFY(rejected);
        QVERIFY(QFileInfo(held).isDir());
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；即使原临时目录被移入同名新父目录，也不能只凭子目录身份执行清理。
    void replacedParentIsRejected() {
        Fixture fixture;
        const auto temporary = fixture.temporary();
        const auto parent = QDir(fixture.output).filePath(fixture.mapped);
        const auto name = QFileInfo(temporary).fileName();
        QVERIFY(QDir().rename(parent, parent + "-held"));
        QVERIFY(QDir().mkdir(parent));
        QVERIFY(QDir().rename(parent + "-held/" + name, temporary));
        QVERIFY_EXCEPTION_THROWN(fixture.cleanup(true), dukto::Error);
        QVERIFY(QFileInfo::exists(temporary));
        QFile original(parent + "-held/a.bin");
        QVERIFY(original.open(QIODevice::ReadOnly));
        QCOMPARE(original.readAll(), fixture.body);
    }

    // 日期：2026-11-07；文件和目录混合超过100条，按全局清单序号分页且执行不积累结果数组。
    void mixedPagination() {
        Fixture fixture(false, "before", 100);
        const auto first = fixture.cleanup(false);
        QCOMPARE(first["entries"].toArray().size(), 100);
        QCOMPARE(first["after"].toString(), QString("100"));
        QVERIFY(first["more"].toBool());
        const auto second = fixture.cleanup(false, 100);
        QCOMPARE(second["entries"].toArray().size(), 3);
        QVERIFY(!second["more"].toBool());
        const auto result = fixture.cleanup(true);
        QCOMPARE(result["after"].toString(), QString("103"));
        QCOMPARE(result["cleanedDirectories"].toString(), QString("1"));
        QCOMPARE(result["preservedDirectories"].toString(), QString("101"));
        QCOMPARE(result["preservedFiles"].toString(), QString("1"));
        QVERIFY(result["entries"].toArray().isEmpty());
        QVERIFY(fixture.completedDataPreserved());
    }

    // 日期：2026-11-07；两个真实CLI入口均输出目录种类和计数，不要求用户增加不同分页参数。
    void commandLine_data() {
        cleanupAndResume_data();
    }

    // 日期：2026-11-07；CLI JSON由独立子进程取得，只有实际返回成功且目录消失才通过。
    void commandLine() {
        QFETCH(bool, server);
        Fixture fixture(server);
        if (server) {
            database(QDir(fixture.state).filePath("tasks.sqlite"), [](QSqlDatabase db) {
                // 日期：2026-11-07；只将测试任务时间回退，CLI使用真实当前时间判断保留期限。
                QSqlQuery query(db);
                if (!query.exec("UPDATE tasks SET updated='2026-01-01T00:00:00Z'"))
                    throw dukto::Error(dukto::ExitCode::Disk, "fixture age", "test");
            });
        }
        QString cli = QDir(QCoreApplication::applicationDirPath()).filePath("dukto-cli");
#ifdef Q_OS_WIN
        cli += ".exe";
#endif
        const auto invoke = [&](const QString &action) {
            // 日期：2026-11-07；公开命令只读取隔离状态父目录，并验证真正的子进程终态。
            QStringList args{"--json",
                             "--state-directory",
                             fixture.stateParent,
                             server ? "serve" : "client",
                             "cleanup",
                             action,
                             "--task",
                             fixture.task.toString(QUuid::WithoutBraces)};
            if (server)
                args.append({"--client", fixture.owner.toString(QUuid::WithoutBraces)});
            QProcess process;
            process.start(cli, args);
            if (!process.waitForFinished(30000) || process.exitCode() != 0)
                throw dukto::Error(dukto::ExitCode::Runtime, "fixture CLI exit", "test");
            return QJsonDocument::fromJson(process.readAllStandardOutput()).object();
        };
        QCOMPARE(pendingEntry(invoke("preview"))["kind"].toString(), QString("directory"));
        QCOMPARE(invoke("run")["cleanedDirectories"].toString(), QString("1"));
        QVERIFY(!QFileInfo::exists(fixture.temporary()));
        QVERIFY(fixture.completedDataPreserved());
    }
};

// 日期：2026-11-07；独立进程跳过析构验证目录删除后的真实崩溃恢复，其余参数交给QtTest。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    const auto arguments = application.arguments();
    if (arguments.size() == 8 &&
        (arguments[1] == "--crash-cleanup" || arguments[1] == "--crash-before-cleanup")) {
        dukto::PrivateStore store(arguments[3], false, dukto::PrivateStore::Use::Maintenance);
        const auto check = [&]() {
            // 日期：2026-11-07；以真实删除结果触发进程退出，不以回调顺序冒充崩溃窗口。
            const auto journal = QDir(arguments[3]).filePath("receive-" + arguments[5] + ".sqlite");
            if ((arguments[1] == "--crash-cleanup" && !QFileInfo::exists(arguments[7])) ||
                (arguments[1] == "--crash-before-cleanup" && hasDirectoryIntent(journal)))
                std::_Exit(47);
        };
        if (arguments[2] == "server")
            dukto::cleanupExpiredUpload(store, QUuid(arguments[4]), QUuid(arguments[5]),
                                        QDateTime::fromString(arguments[6], Qt::ISODate), true, 0,
                                        check);
        else
            dukto::cleanupClientDownload(store, QUuid(arguments[5]), true, 0, check);
        return 48;
    }
    DirectoryCleanupTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "directory_cleanup_tests.moc"

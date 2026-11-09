#include "core/durablereceive.h"
#include "core/error.h"
#include "core/expiredtaskcleanup.h"
#include "core/files.h"
#include "core/protocol.h"
#include "core/service.h"
#include "core/statecleanup.h"
#include "core/statesession.h"
#include "core/strongmanifest.h"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QProcess>
#include <QSqlQuery>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QTimer>
#include <QtTest>
#include <cstdio>
#include <cstdlib>

namespace {
// 日期：2026-11-07；测试数据库连接在回调异常后也必须关闭，不污染后续跨进程互斥样本。
void database(dukto::PrivateStore &store, const QString &name,
              const std::function<void(QSqlDatabase)> &callback) {
    const auto connection = QUuid::createUuid().toString();
    auto db = QSqlDatabase::addDatabase("QSQLITE", connection);
    db.setDatabaseName(QDir(store.directory()).filePath(name));
    if (!db.open())
        throw dukto::Error(dukto::ExitCode::Disk, "fixture open", "test");
    try {
        callback(db);
    } catch (...) {
        db.close();
        db = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection);
        throw;
    }
    db.close();
    db = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection);
}

// 日期：2026-11-07；独立读取原接收日志定位实际随机临时名，不依赖清理函数返回值。
QString temporary(dukto::PrivateStore &store, const QUuid &id) {
    QString result;
    database(store, "receive-" + id.toString(QUuid::WithoutBraces) + ".sqlite",
             [&](QSqlDatabase db) {
                 // 日期：2026-11-07；样本第二个文件是未完成正文，第一项已经发布。
                 QSqlQuery query(db);
                 if (!query.exec("SELECT temporary FROM files WHERE id=2") || !query.next())
                     throw dukto::Error(dukto::ExitCode::Disk, "fixture temporary", "test");
                 result = query.value(0).toString();
             });
    return result;
}

struct Fixture {
    QTemporaryDir root;
    const QUuid owner = QUuid::createUuid();
    const QUuid request = QUuid::createUuid();
    QUuid id;
    QByteArray identity;
    QDateTime updated;
    const QByteArray body = QByteArray(65536, 'a');
    QString pending;

    // 日期：2026-11-07；真实强清单、任务及接收日志含一个最终文件和一个未完成临时文件。
    explicit Fixture(int count = 2) {
        if (!QDir().mkpath(root.filePath("output")) || !QDir().mkpath(root.filePath("sources")))
            throw dukto::Error(dukto::ExitCode::Disk, "fixture dirs", "test");
        QStringList paths;
        for (int index = 0; index < count; ++index) {
            const auto path =
                root.filePath(QString("sources/f%1.bin").arg(index, 3, 10, QChar('0')));
            QFile source(path);
            if (!source.open(QIODevice::WriteOnly) || source.write(body) != body.size())
                throw dukto::Error(dukto::ExitCode::Disk, "fixture source", "test");
            source.close();
            paths.append(path);
        }
        dukto::PrivateStore store(root.filePath("private"), true);
        QJsonObject summary;
        {
            dukto::StrongManifest manifest(store, "fixture.sqlite", true);
            manifest.scan(paths);
            summary = manifest.summary();
            identity = QByteArray::fromHex(summary["sha256"].toString().toLatin1());
        }
        dukto::TaskStore tasks(store);
        auto task =
            tasks.create(owner, request, "upload", "docs", "", root.filePath("output"), identity);
        id = task.id;
        auto lease = tasks.acquire(owner, id);
        task = tasks.bindManifest(*lease, summary);
        task = tasks.advance(*lease, task.revision, "transferring", 0);
        const auto key = id.toString(QUuid::WithoutBraces);
        store.write("manifest-" + key + ".sqlite", store.read("fixture.sqlite", 1024 * 1024));
        {
            dukto::StrongManifest manifest(store, "manifest-" + key + ".sqlite", false);
            for (int index = 1; index <= count; ++index) {
                dukto::DurableReceive receiver(store, "receive-" + key + ".sqlite", id, manifest,
                                               root.filePath("output"));
                receiver.open(static_cast<quint64>(index), manifest.entry(index).relative);
                receiver.write(0, 0, index == 1 ? body : body.left(4096));
                if (index == 1)
                    receiver.finish();
            }
        }
        tasks.advance(*lease, task.revision, "interrupted", 0);
        database(store, "tasks.sqlite", [&](QSqlDatabase db) {
            // 日期：2026-11-07；从真实持久时间推导边界，避免测试执行耗时造成秒级误差。
            QSqlQuery query(db);
            query.prepare("SELECT updated FROM tasks WHERE id=?");
            query.addBindValue(key);
            if (!query.exec() || !query.next())
                throw dukto::Error(dukto::ExitCode::Disk, "fixture updated", "test");
            updated = QDateTime::fromString(query.value(0).toString(), Qt::ISODate);
        });
        pending = temporary(store, id);
    }

    // 日期：2026-11-07；只改自有测试库中的固定语句，用于构造损坏、年龄及提交不确定状态。
    void change(const QString &name, const QString &statement) {
        dukto::PrivateStore store(root.filePath("private"));
        database(store, name, [&](QSqlDatabase db) {
            // 日期：2026-11-07；失败必须中止样本，不能把未成功构造的负例算作通过。
            QSqlQuery query(db);
            if (!query.exec(statement))
                throw dukto::Error(dukto::ExitCode::Disk, "fixture change", "test");
        });
    }
};

// 日期：2026-11-07；独立子进程在删除完成而FULL确认之前直接退出，跳过析构模拟真实崩溃。
int crashWorker(const QStringList &args) {
    dukto::PrivateStore store(args[2], false, dukto::PrivateStore::Use::Maintenance);
    int points = 0;
    dukto::cleanupExpiredUpload(store, QUuid(args[3]), QUuid(args[4]),
                                QDateTime::fromString(args[5], Qt::ISODate), true, 0, [&]() {
                                    // 日期：2026-11-07；以真实临时路径消失为崩溃触发条件，不依赖内部回调序号。
                                    ++points;
                                    if (!QFileInfo::exists(args[6]) && points > 1)
                                        std::_Exit(29);
                                });
    return 30;
}
} // namespace

class ExpiredTaskCleanupTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-09；真实定时器在长期开启的监听中回收过期正文，共享使用时让出，已发布和未知项保持。
    void idleServiceTimerAndSharedPriority() {
        Fixture fixture;
        const auto state = fixture.root.filePath("service");
        QVERIFY(QDir().rename(fixture.root.filePath("private"), state));
        {
            dukto::PrivateStore store(state);
            dukto::initializeIdentity(store, {"127.0.0.1"});
            store.write("unknown.part", "keep-unknown");
        }
        const auto pending = fixture.root.filePath("output/" + fixture.pending);
        const auto published = dukto::hashFile(fixture.root.filePath("output/f000.bin"));
        {
            dukto::ServiceListener listener(fixture.root.path(), "service", 2000);
            QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
            auto timer = listener.findChild<QTimer *>("stateMaintenanceTimer");
            QVERIFY(timer);
            QCOMPARE(timer->interval(), 60000);
            QSignalSpy events(&listener, &dukto::ServiceListener::event);
            {
                dukto::PrivateStore active(state);
                database(active, "tasks.sqlite", [](QSqlDatabase db) {
                    // 日期：2026-11-09；仅调整测试任务UTC字段，不使用生产虚拟时钟开关。
                    QSqlQuery query(db);
                    QVERIFY(query.exec("UPDATE tasks SET updated='2000-01-01T00:00:00Z'"));
                });
                timer->setInterval(20);
                QTRY_VERIFY_WITH_TIMEOUT(!events.isEmpty(), 3000);
                QVERIFY(QFileInfo::exists(pending));
                QCOMPARE(active.read("unknown.part"), QByteArray("keep-unknown"));
                QVERIFY_EXCEPTION_THROWN(dukto::PrivateStore(fixture.root.filePath("budget"), false,
                                                             dukto::PrivateStore::Use::Maintenance),
                                         dukto::Error);
            }
            QTRY_VERIFY_WITH_TIMEOUT(!QFileInfo::exists(pending), 10000);
            timer->stop();
            listener.stop();
            QVERIFY(!listener.requestMaintenance());
            QCOMPARE(dukto::hashFile(fixture.root.filePath("output/f000.bin")), published);
            dukto::PrivateStore retained(state);
            QCOMPARE(retained.read("unknown.part"), QByteArray("keep-unknown"));
            dukto::TaskStore tasks(retained);
            QCOMPARE(tasks.task(fixture.owner, fixture.id).request, fixture.request);
        }
        dukto::PrivateStore coordinator(fixture.root.filePath("budget"), false,
                                        dukto::PrivateStore::Use::Maintenance);
        QVERIFY(coordinator.maintenance());
    }

    // 日期：2026-11-09；真实未完成TLS连接占据工作槽时不能启动维护，断开后可恢复维护且停止归还根。
    void activeConnectionDefersServiceMaintenance() {
        QTemporaryDir root;
        {
            dukto::PrivateStore store(root.filePath("service"), true);
            dukto::initializeIdentity(store, {"127.0.0.1"});
        }
        dukto::ServiceListener listener(root.path(), "service", 2000);
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QTcpSocket connection;
        connection.connectToHost(QHostAddress::LocalHost, listener.serverPort());
        QTRY_COMPARE_WITH_TIMEOUT(connection.state(), QAbstractSocket::ConnectedState, 3000);
        QTest::qWait(50);
        QVERIFY(!listener.requestMaintenance());
        connection.abort();
        bool scheduled = false;
        QTRY_VERIFY_WITH_TIMEOUT(scheduled || (scheduled = listener.requestMaintenance()), 5000);
        listener.stop();
        dukto::PrivateStore exclusive(root.filePath("service"), false,
                                      dukto::PrivateStore::Use::Maintenance);
        QVERIFY(exclusive.maintenance());
    }

    // 日期：2026-11-09；空闲共享根释放后同名换代也不授予清理或认证资格，原目录和新目录均保留。
    void serviceMaintenanceRejectsReplacementRoot() {
        QTemporaryDir root;
        const auto state = root.filePath("service");
        {
            dukto::PrivateStore store(state, true);
            dukto::initializeIdentity(store, {"127.0.0.1"});
            store.write("original.json", "original");
        }
        dukto::ServiceListener listener(root.path(), "service", 2000);
        QVERIFY(listener.listen(QHostAddress::LocalHost, 0));
        QVERIFY(QDir().rename(state, root.filePath("original")));
        {
            dukto::PrivateStore replacement(state, true);
            dukto::initializeIdentity(replacement, {"127.0.0.1"});
            replacement.write("unknown.part", "replacement");
        }
        QSignalSpy events(&listener, &dukto::ServiceListener::event);
        QVERIFY(listener.requestMaintenance());
        QTRY_VERIFY_WITH_TIMEOUT(!events.isEmpty(), 3000);
        const auto report = qvariant_cast<QJsonObject>(events.last().at(0));
        QCOMPARE(report["event"].toString(), QString("state-cleanup-error"));
        QCOMPARE(report["code"].toInt(), int(dukto::ExitCode::Integrity));
        QVERIFY_EXCEPTION_THROWN(listener.publicInfo(), dukto::Error);
        listener.stop();
        dukto::PrivateStore original(root.filePath("original"));
        dukto::PrivateStore replacement(state);
        QCOMPARE(original.read("original.json"), QByteArray("original"));
        QCOMPARE(replacement.read("unknown.part"), QByteArray("replacement"));
        QVERIFY(!replacement.exists("gc-cursor.json"));
    }

    // 日期：2026-11-08；自动维护不得凭tasks.sqlite名称初始化未知普通库或隐式迁移旧版库。
    void batchPreservesUnknownDatabaseBytes() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("service"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        store.write("tasks.sqlite", QByteArray());
        const auto name = root.filePath("service/tasks.sqlite");
        database(store, "tasks.sqlite", [](QSqlDatabase db) {
            // 日期：2026-11-08；真实未知库含独立业务数据，不能被自动维护补建任务表或更改版本。
            QSqlQuery query(db);
            if (!query.exec("CREATE TABLE personal_note(value TEXT)") ||
                !query.exec("INSERT INTO personal_note VALUES('preserve')") ||
                !query.exec("PRAGMA user_version=3"))
                throw dukto::Error(dukto::ExitCode::Runtime, "unknown database fixture", "test");
        });
        const auto before = dukto::hashFile(name);
        const auto report = dukto::cleanupState(store, QDateTime::currentDateTimeUtc(), true);
        QVERIFY2(report["errorCount"].toString() == "0",
                 qPrintable(QJsonDocument(report).toJson(QJsonDocument::Compact)));
        QVERIFY(!report["taskDatabaseEligible"].toBool());
        QCOMPARE(dukto::hashFile(name), before);
        QVERIFY(!store.exists("gc-cursor.json"));
        database(store, "tasks.sqlite", [](QSqlDatabase db) {
            // 日期：2026-11-08；版本和表名相同但列属于其他业务的库，也不能被维护器认领。
            QSqlQuery query(db);
            if (!query.exec("DROP TABLE personal_note") ||
                !query.exec("CREATE TABLE tasks(value TEXT)") ||
                !query.exec("CREATE TABLE task_expiry(value TEXT)"))
                throw dukto::Error(dukto::ExitCode::Runtime, "same-name database fixture", "test");
        });
        const auto sameName = dukto::hashFile(name);
        QVERIFY(!dukto::cleanupState(store, QDateTime::currentDateTimeUtc(),
                                     true)["taskDatabaseEligible"]
                     .toBool());
        QCOMPARE(dukto::hashFile(name), sameName);
        QVERIFY(!store.exists("tasks.sqlite-wal"));
        QVERIFY(!store.exists("tasks.sqlite-shm"));

        Fixture fixture;
        fixture.change("tasks.sqlite", "PRAGMA user_version=2");
        dukto::PrivateStore old(fixture.root.filePath("private"), false,
                                dukto::PrivateStore::Use::Maintenance);
        const auto path = fixture.root.filePath("private/tasks.sqlite");
        const auto original = dukto::hashFile(path);
        const auto retained = dukto::cleanupState(old, fixture.updated.addDays(8), true);
        QVERIFY(!retained["taskDatabaseEligible"].toBool());
        QCOMPARE(dukto::hashFile(path), original);
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
    }

    // 日期：2026-11-08；真实CLI验证批量预览/执行、活动共享拒绝及参数误用，不用库内调用代替接线。
    void batchCommandLineAndSharedRefusal() {
        Fixture fixture;
        fixture.change("tasks.sqlite", "UPDATE tasks SET updated='2000-01-01T00:00:00Z'");
        QVERIFY(QDir().rename(fixture.root.filePath("private"), fixture.root.filePath("service")));
        auto cli = QDir(QCoreApplication::applicationDirPath()).filePath("dukto-cli");
#ifdef Q_OS_WIN
        cli += ".exe";
#endif
        QStringList args{
            "state",        "gc",      "preview", "--state-directory", fixture.root.path(),
            "--state-root", "service", "--json"};
        const auto invoke = [&](const QStringList &arguments, int expected) {
            // 日期：2026-11-08；核对进程真实退出码和单条JSON，失败输出保存在测试原件。
            QProcess process;
            process.start(cli, arguments);
            if (!process.waitForFinished(30000) || process.exitCode() != expected)
                throw dukto::Error(dukto::ExitCode::Runtime, "batch CLI exit", "test");
            const auto value = QJsonDocument::fromJson(process.readAllStandardOutput()).object();
            if (value.isEmpty())
                throw dukto::Error(dukto::ExitCode::Runtime, "batch CLI JSON", "test");
            return value;
        };
        QCOMPARE(invoke(args, 0)["eligible"].toString(), QString("1"));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
        {
            dukto::PrivateStore busy(fixture.root.filePath("service"));
            QCOMPARE(invoke(args, int(dukto::ExitCode::Permission))["stage"].toString(),
                     QString("state-use"));
            QVERIFY(!busy.exists("gc-cursor.json"));
        }
        auto bad = args;
        bad << "--budget-total" << "1";
        invoke(bad, int(dukto::ExitCode::Config));
        args[2] = "run";
        QCOMPARE(invoke(args, 0)["uploadTasksProcessed"].toString(), QString("1"));
        QVERIFY(!QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/f000.bin")));
    }

    // 日期：2026-11-08；删除后取消不推进任务游标，已有FULL意图可由下一批安全重入。
    void batchCancellationResumesDeletionIntent() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        dukto::StateCleanupLimits limits;
        limits.milliseconds = 30000;
        const auto path = fixture.root.filePath("output/" + fixture.pending);
        const auto check = [&]() {
            // 日期：2026-11-08；以真实临时正文消失为取消条件，避免依赖内部调用次数。
            if (!QFileInfo::exists(path))
                throw dukto::Error(dukto::ExitCode::Cancelled, "test cancellation", "test");
        };
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupState(store, fixture.updated.addDays(8), true, limits, check),
            dukto::Error);
        QVERIFY(!store.exists("gc-cursor.json"));
        const auto result = dukto::cleanupState(store, fixture.updated.addDays(8), true, limits);
        QCOMPARE(result["errorCount"].toString(), QString("0"));
        QVERIFY(!QFileInfo::exists(path));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/f000.bin")));
    }

    // 日期：2026-11-08；自动维护必须先核对已有域关联，伪造/残片标记不会触发任何临时正文删除。
    void automaticCleanupRejectsBrokenDomain() {
        Fixture fixture;
        fixture.change("tasks.sqlite", "UPDATE tasks SET updated='2000-01-01T00:00:00Z'");
        QVERIFY(QDir().rename(fixture.root.filePath("private"), fixture.root.filePath("service")));
        QFile marker(fixture.root.filePath("service/state-domain.bin"));
        QVERIFY(marker.open(QIODevice::WriteOnly));
        QCOMPARE(marker.write("broken"), qint64(6));
        marker.close();
        dukto::tryAutomaticStateCleanup(fixture.root.path(), "service");
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
        QVERIFY_EXCEPTION_THROWN(dukto::StateSession::root(fixture.root.path(), "service"),
                                 dukto::Error);
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
    }

    // 日期：2026-11-08；批次预览保持正文与任务，执行复用原删除凭据并保留最终文件和请求身份。
    void batchCleanupRetainsOriginalsAndRequests() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        dukto::StateCleanupLimits limits;
        limits.milliseconds = 30000;
        const auto path = fixture.root.filePath("output/" + fixture.pending);
        const auto now = fixture.updated.addDays(7);
        const auto preview = dukto::cleanupState(store, now, false, limits);
        QCOMPARE(preview["eligible"].toString(), QString("1"));
        QCOMPARE(preview["errorCount"].toString(), QString("0"));
        QVERIFY(QFileInfo::exists(path));
        QVERIFY(!store.exists("gc-cursor.json"));
        const auto result = dukto::cleanupState(store, now, true, limits);
        QCOMPARE(result["uploadTasksProcessed"].toString(), QString("1"));
        QCOMPARE(result["errorCount"].toString(), QString("0"));
        QVERIFY(!QFileInfo::exists(path));
        QCOMPARE(dukto::hashFile(fixture.root.filePath("output/f000.bin")),
                 dukto::hashFile(fixture.root.filePath("sources/f000.bin")));
        dukto::TaskStore tasks(store);
        QCOMPARE(tasks
                     .create(fixture.owner, fixture.request, "upload", "docs", "",
                             fixture.root.filePath("output"), fixture.identity)
                     .id,
                 fixture.id);
        const auto repeated = dukto::cleanupState(store, now.addDays(1), true, limits);
        QCOMPARE(repeated["errorCount"].toString(), QString("0"));
        QVERIFY(!QFileInfo::exists(path));
        QVERIFY(store.exists("gc-last.json"));
    }

    // 日期：2026-11-08；共享占用优先，释放后真实业务根打开触发过期清理，不需用户手动指定任务。
    void automaticBusinessOpenHonorsSharedUse() {
        Fixture fixture;
        fixture.change("tasks.sqlite", "UPDATE tasks SET updated='2000-01-01T00:00:00Z'");
        QVERIFY(QDir().rename(fixture.root.filePath("private"), fixture.root.filePath("service")));
        const auto path = fixture.root.filePath("output/" + fixture.pending);
        {
            dukto::PrivateStore busy(fixture.root.filePath("service"));
            dukto::tryAutomaticStateCleanup(fixture.root.path(), "service");
            QVERIFY(QFileInfo::exists(path));
        }
        const auto store = dukto::StateSession::root(fixture.root.path(), "service");
        QVERIFY(!QFileInfo::exists(path));
        QVERIFY(store->exists("gc-last.json"));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/f000.bin")));
    }

    // 日期：2026-11-08；提交结果未知及损坏进度均保留正文；错误不会被批次完成或后续业务掩盖。
    void batchCleanupRejectsUnknownCommitAndCursor() {
        Fixture fixture;
        fixture.change("receive-" + fixture.id.toString(QUuid::WithoutBraces) + ".sqlite",
                       "UPDATE files SET state='committing' WHERE id=2");
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        dukto::StateCleanupLimits limits;
        limits.milliseconds = 30000;
        const auto result = dukto::cleanupState(store, fixture.updated.addDays(8), true, limits);
        QCOMPARE(result["errorCount"].toString(), QString("1"));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
        store.write("gc-cursor.json", "{}");
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupState(store, fixture.updated.addDays(8), true),
                                 dukto::Error);
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
    }

    // 日期：2026-11-08；单项批次持久推进稳定任务游标，后续运行仍能处理同根中的其他过期任务。
    void batchCleanupPersistsTaskCursor() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        dukto::TaskStore tasks(store);
        const auto secondRequest = QUuid::createUuid();
        auto second = tasks.create(fixture.owner, secondRequest, "upload", "docs", "",
                                   fixture.root.filePath("output"), fixture.identity);
        {
            auto lease = tasks.acquire(fixture.owner, second.id);
            dukto::StrongManifest manifest(store, "fixture.sqlite", false);
            second = tasks.bindManifest(*lease, manifest.summary());
            second = tasks.advance(*lease, second.revision, "transferring", 0);
            tasks.advance(*lease, second.revision, "interrupted", 0);
        }
        dukto::StateCleanupLimits limits;
        limits.tasks = 1;
        limits.milliseconds = 30000;
        const auto now = fixture.updated.addDays(8);
        const auto first = dukto::cleanupState(store, now, true, limits);
        QCOMPARE(first["tasksVisited"].toString(), QString("1"));
        QVERIFY(first["more"].toBool());
        const auto next = dukto::cleanupState(store, now, true, limits);
        QCOMPARE(next["tasksVisited"].toString(), QString("1"));
        // 日期：2026-11-08；第二任务故意无接收证据，必须报告失败而非删除或反复只处理第一任务。
        QCOMPARE(next["errorCount"].toString(), QString("1"));
        QCOMPARE(tasks.task(fixture.owner, second.id).state, QString("interrupted"));
    }

    // 日期：2026-11-07；保留期边界、预览零正文变更、最终文件和源文件保护及幂等请求均实测。
    void retentionAndIdempotency() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        const auto path = fixture.root.filePath("output/" + fixture.pending);
        const auto early = dukto::cleanupExpiredUpload(
            store, fixture.owner, fixture.id, fixture.updated.addDays(7).addSecs(-1), false);
        QVERIFY(!early["eligible"].toBool());
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                             fixture.updated.addDays(7).addSecs(-1),
                                                             true),
                                 dukto::Error);
        QVERIFY(QFileInfo::exists(path));
        const auto preview = dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                         fixture.updated.addDays(7), false);
        QVERIFY(preview["eligible"].toBool());
        QCOMPARE(preview["entries"].toArray().size(), 2);
        dukto::TaskStore tasks(store);
        QCOMPARE(tasks.task(fixture.owner, fixture.id).state, QString("interrupted"));
        QVERIFY(QFileInfo::exists(path));
        const auto result = dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                        fixture.updated.addDays(7), true);
        QVERIFY(result["expired"].toBool());
        QCOMPARE(result["cleanedFiles"].toString(), QString("1"));
        QVERIFY(!QFileInfo::exists(path));
        QCOMPARE(tasks.task(fixture.owner, fixture.id).state, QString("failed"));
        QCOMPARE(tasks
                     .create(fixture.owner, fixture.request, "upload", "docs", "",
                             fixture.root.filePath("output"), fixture.identity)
                     .id,
                 fixture.id);
        for (const auto &name :
             QStringList{"output/f000.bin", "sources/f000.bin", "sources/f001.bin"}) {
            QFile file(fixture.root.filePath(name));
            QVERIFY(file.open(QIODevice::ReadOnly));
            QCOMPARE(file.readAll(), fixture.body);
        }
        const auto repeated = dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                          fixture.updated.addDays(8), true);
        QCOMPARE(repeated["cleanedFiles"].toString(), QString("1"));
    }

    // 日期：2026-11-07；删除意图与确认之间崩溃后重启，保留原请求且不会重新传输或删除最终文件。
    void crashAfterRemoval() {
        Fixture fixture;
        const auto path = fixture.root.filePath("output/" + fixture.pending);
        QProcess worker;
        worker.start(QCoreApplication::applicationFilePath(),
                     {"--crash", fixture.root.filePath("private"),
                      fixture.owner.toString(QUuid::WithoutBraces),
                      fixture.id.toString(QUuid::WithoutBraces),
                      fixture.updated.addDays(7).toString(Qt::ISODate), path});
        QVERIFY(worker.waitForFinished(30000));
        QCOMPARE(worker.exitCode(), 29);
        QVERIFY(!QFileInfo::exists(path));
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        const auto result = dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                        fixture.updated.addDays(8), true);
        QCOMPARE(result["cleanedFiles"].toString(), QString("1"));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/f000.bin")));
    }

    // 日期：2026-11-07；同名外部文件替换后原生ID不同，拒绝清理并保留替换内容。
    void replacedTemporary() {
        Fixture fixture;
        const auto path = fixture.root.filePath("output/" + fixture.pending);
        QVERIFY(QFile::rename(path, path + ".saved"));
        QFile other(path);
        QVERIFY(other.open(QIODevice::WriteOnly));
        QCOMPARE(other.write("external"), qint64(8));
        other.close();
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                             fixture.updated.addDays(8), true),
                                 dukto::Error);
        QVERIFY(other.open(QIODevice::ReadOnly));
        QCOMPARE(other.readAll(), QByteArray("external"));
        QVERIFY(QFileInfo::exists(path + ".saved"));
    }

    // 日期：2026-11-07；完成、活动、提交不确定和错误主体不能进入删除，按真实库状态验证。
    void guards_data() {
        QTest::addColumn<QString>("mutation");
        QTest::newRow("task-committing") << "UPDATE tasks SET state='committing'";
        QTest::newRow("task-active") << "UPDATE tasks SET state='transferring'";
        QTest::newRow("task-completed") << "UPDATE tasks SET state='completed',processed=total";
        QTest::newRow("invalid-time") << "UPDATE tasks SET updated='invalid'";
    }

    // 日期：2026-11-07；拒绝项必须实际保留临时正文及任务幂等身份，不能只检查异常类型。
    void guards() {
        QFETCH(QString, mutation);
        Fixture fixture;
        fixture.change("tasks.sqlite", mutation);
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                             fixture.updated.addDays(31), true),
                                 dukto::Error);
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
    }

    // 日期：2026-11-07；文件提交不确定时预览和执行均拒绝，任务仍保持可恢复的原状态。
    void unresolvedCommit() {
        Fixture fixture;
        fixture.change("receive-" + fixture.id.toString(QUuid::WithoutBraces) + ".sqlite",
                       "UPDATE files SET state='committing' WHERE id=2");
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        for (const bool apply : {false, true})
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                                 fixture.updated.addDays(8), apply),
                                     dukto::Error);
        dukto::TaskStore tasks(store);
        QCOMPARE(tasks.task(fixture.owner, fixture.id).state, QString("interrupted"));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
    }

    // 日期：2026-11-07；预览100项分页，执行全部项时不积累结果数组，103项真实临时文件逐项回收。
    void boundedPages() {
        Fixture fixture(104);
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        const auto first = dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                       fixture.updated.addDays(8), false);
        QCOMPARE(first["entries"].toArray().size(), 100);
        QVERIFY(first["more"].toBool());
        const auto second = dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                        fixture.updated.addDays(8), false, 100);
        QCOMPARE(second["entries"].toArray().size(), 4);
        QVERIFY(!second["more"].toBool());
        const auto result = dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                        fixture.updated.addDays(8), true);
        QCOMPARE(result["cleanedFiles"].toString(), QString("103"));
        QVERIFY(result["entries"].toArray().isEmpty());
        QCOMPARE(QDir(fixture.root.filePath("output"))
                     .entryList({"*.part"}, QDir::Files | QDir::Hidden)
                     .size(),
                 0);
    }

    // 日期：2026-11-07；普通共享实例、错误主体及活跃任务租约不能取得清理权限。
    void ownership() {
        Fixture fixture;
        {
            dukto::PrivateStore shared(fixture.root.filePath("private"));
            QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(shared, fixture.owner, fixture.id,
                                                                 fixture.updated.addDays(8), true),
                                     dukto::Error);
        }
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, QUuid::createUuid(), fixture.id,
                                                             fixture.updated.addDays(8), true),
                                 dukto::Error);
        dukto::TaskStore tasks(store);
        auto lease = tasks.acquire(fixture.owner, fixture.id);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                             fixture.updated.addDays(8), true),
                                 dukto::Error);
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
    }

    // 日期：2026-11-07；失败及取消默认保留30天，已过期凭据不因新更新时间重新延长保留期。
    void terminalRetention_data() {
        QTest::addColumn<QString>("state");
        QTest::newRow("cancelled") << "cancelled";
        QTest::newRow("failed") << "failed";
    }

    // 日期：2026-11-07；保留原终态、修订和幂等键，不能把失败或取消冒充完成。
    void terminalRetention() {
        QFETCH(QString, state);
        Fixture fixture;
        fixture.change("tasks.sqlite", "UPDATE tasks SET state='" + state +
                                           "',error=" + (state == "failed" ? "3" : "0"));
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        dukto::TaskStore tasks(store);
        const auto before = tasks.task(fixture.owner, fixture.id).publicInfo();
        QVERIFY_EXCEPTION_THROWN(
            dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                        fixture.updated.addDays(30).addSecs(-1), true),
            dukto::Error);
        dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id, fixture.updated.addDays(30),
                                    true);
        QCOMPARE(tasks.task(fixture.owner, fixture.id).publicInfo(), before);
    }

    // 日期：2026-11-07；已确认删除后同名新文件属于新对象，重复清理必须保留它。
    void replacementAfterConfirmation() {
        Fixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id, fixture.updated.addDays(8),
                                    true);
        QFile replacement(fixture.root.filePath("output/" + fixture.pending));
        QVERIFY(replacement.open(QIODevice::WriteOnly));
        QCOMPARE(replacement.write("new owner"), qint64(9));
        replacement.close();
        dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id, fixture.updated.addDays(8),
                                    true);
        QVERIFY(replacement.open(QIODevice::ReadOnly));
        QCOMPARE(replacement.readAll(), QByteArray("new owner"));
    }

    // 日期：2026-11-07；损坏日志中的超32位整数不能经截断被接受为普通文件的0/1确认标志。
    void wideConfirmationFlag_data() {
        QTest::addColumn<QString>("flag");
        QTest::newRow("wide-zero") << "4294967296";
        QTest::newRow("wide-one") << "4294967297";
    }

    // 日期：2026-11-07；预览及执行均拒绝损坏意图，并保持清理后新出现的同名对象正文不变。
    void wideConfirmationFlag() {
        QFETCH(QString, flag);
        Fixture fixture;
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id, fixture.updated.addDays(8),
                                    true);
        const auto journal = "receive-" + fixture.id.toString(QUuid::WithoutBraces) + ".sqlite";
        database(store, journal, [&](QSqlDatabase db) {
            QSqlQuery query(db);
            if (!query.exec("PRAGMA ignore_check_constraints=ON") ||
                !query.exec("UPDATE expired_cleanup SET cleaned=" + flag))
                throw dukto::Error(dukto::ExitCode::Disk, "fixture wide confirmation", "test");
        });
        QFile replacement(fixture.root.filePath("output/" + fixture.pending));
        QVERIFY(replacement.open(QIODevice::WriteOnly));
        QCOMPARE(replacement.write("new owner"), qint64(9));
        replacement.close();
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                             fixture.updated.addDays(8), false),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                             fixture.updated.addDays(8), true),
                                 dukto::Error);
        QVERIFY(replacement.open(QIODevice::ReadOnly));
        QCOMPARE(replacement.readAll(), QByteArray("new owner"));
    }

    // 日期：2026-11-07；目录被改名并换成同名目录后，根身份不同，拒绝访问其中的任何正文。
    void replacedRoot() {
        Fixture fixture;
        QVERIFY(QDir().rename(fixture.root.filePath("output"), fixture.root.filePath("saved")));
        QVERIFY(QDir().mkdir(fixture.root.filePath("output")));
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        QVERIFY_EXCEPTION_THROWN(dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id,
                                                             fixture.updated.addDays(8), true),
                                 dukto::Error);
        QVERIFY(QFileInfo::exists(fixture.root.filePath("saved/" + fixture.pending)));
        dukto::TaskStore tasks(store);
        QCOMPARE(tasks.task(fixture.owner, fixture.id).state, QString("interrupted"));
    }

    // 日期：2026-11-07；真实CLI使用本机服务器状态，预览、执行及误用选项分别核对退出码与正文。
    void commandLine() {
        Fixture fixture;
        fixture.change("tasks.sqlite",
                       "UPDATE tasks SET updated='" +
                           QDateTime::currentDateTimeUtc().addDays(-8).toString(Qt::ISODate) + "'");
        QVERIFY(QDir().rename(fixture.root.filePath("private"), fixture.root.filePath("service")));
        const auto cli = QDir(QCoreApplication::applicationDirPath())
                             .filePath(
#ifdef Q_OS_WIN
                                 "dukto-cli.exe"
#else
                                 "dukto-cli"
#endif
                             );
        const QStringList base{"--json",
                               "--state-directory",
                               fixture.root.path(),
                               "serve",
                               "cleanup",
                               "preview",
                               "--client",
                               fixture.owner.toString(QUuid::WithoutBraces),
                               "--task",
                               fixture.id.toString(QUuid::WithoutBraces)};
        const auto invoke = [&](const QStringList &args, int expected) {
            // 日期：2026-11-07；读取真实进程终态和规范JSON，不能以启动成功代替命令成功。
            QProcess process;
            process.start(cli, args);
            if (!process.waitForFinished(30000) || process.exitCode() != expected)
                throw dukto::Error(dukto::ExitCode::Runtime, "CLI fixture exit", "test");
            const auto result = QJsonDocument::fromJson(process.readAllStandardOutput()).object();
            if (result.isEmpty())
                throw dukto::Error(dukto::ExitCode::Runtime, "CLI fixture JSON", "test");
            return result;
        };
        const auto preview = invoke(base, 0);
        QVERIFY(preview["eligible"].toBool());
        QVERIFY(!preview["applied"].toBool());
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
        auto invalid = base;
        invalid.append({"--to", "127.0.0.1"});
        invoke(invalid, 2);
        auto run = base;
        run[5] = "run";
        auto cursor = run;
        cursor.append({"--after", "0"});
        invoke(cursor, 2);
        auto duplicate = run;
        duplicate.append({"--client", fixture.owner.toString(QUuid::WithoutBraces)});
        invoke(duplicate, 2);
        const auto applied = invoke(run, 0);
        QVERIFY(applied["expired"].toBool());
        QCOMPARE(applied["cleanedFiles"].toString(), QString("1"));
        QVERIFY(!QFileInfo::exists(fixture.root.filePath("output/" + fixture.pending)));
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/f000.bin")));
    }

    // 日期：2026-11-07；真实版本二升级增加过期表；原任务公开结果、修订与幂等身份不变。
    void versionTwoMigration() {
        Fixture fixture;
        QJsonObject before;
        {
            dukto::PrivateStore store(fixture.root.filePath("private"));
            dukto::TaskStore tasks(store);
            before = tasks.task(fixture.owner, fixture.id).publicInfo();
        }
        fixture.change("tasks.sqlite", "DROP TABLE task_expiry");
        fixture.change("tasks.sqlite", "PRAGMA user_version=2");
        dukto::PrivateStore store(fixture.root.filePath("private"), false,
                                  dukto::PrivateStore::Use::Maintenance);
        {
            dukto::TaskStore tasks(store);
            QCOMPARE(tasks.task(fixture.owner, fixture.id).publicInfo(), before);
        }
        database(store, "tasks.sqlite", [&](QSqlDatabase db) {
            // 日期：2026-11-07；独立SQL核对实际磁盘版本与空过期表，不能只接受新构造成功。
            QSqlQuery query(db);
            QVERIFY(query.exec("PRAGMA user_version"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), 3);
            query.finish();
            QVERIFY(query.exec("SELECT COUNT(*) FROM task_expiry"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), 0);
        });
        dukto::cleanupExpiredUpload(store, fixture.owner, fixture.id, fixture.updated.addDays(8),
                                    true);
        QVERIFY(QFileInfo::exists(fixture.root.filePath("output/f000.bin")));
    }
};

// 日期：2026-11-07；同一原生测试程序兼任独立崩溃工作者，正常模式仍输出完整QtTest原件。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto args = app.arguments();
    if (args.size() == 7 && args[1] == "--crash")
        return crashWorker(args);
    try {
        ExpiredTaskCleanupTests tests;
        return QTest::qExec(&tests, argc, argv);
    } catch (const dukto::Error &error) {
        std::fprintf(stderr, "cleanup fixture error: %s [%s]\n", error.message.toUtf8().constData(),
                     error.stage.toUtf8().constData());
        return 1;
    }
}
#include "expired_task_cleanup_tests.moc"

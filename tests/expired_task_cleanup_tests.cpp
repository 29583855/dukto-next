#include "core/durablereceive.h"
#include "core/error.h"
#include "core/expiredtaskcleanup.h"
#include "core/files.h"
#include "core/protocol.h"
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

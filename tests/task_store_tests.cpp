#include "core/error.h"
#include "core/protocol.h"
#include "core/strongmanifest.h"
#include "core/taskstore.h"

#include <QSqlQuery>
#include <QTemporaryDir>
#include <QtTest>
#include <mutex>
#include <thread>
#include <vector>

namespace {
// 日期：2026-11-04；清单总计样本不含源路径，用于验证持久绑定与请求强身份的一致性。
QJsonObject summary(const QByteArray &sha) {
    return {{"version", 1},
            {"entries", "2"},
            {"blocks", "1"},
            {"bytes", "3"},
            {"blockBytes", QString::number(dukto::StrongBlockBytes)},
            {"sha256", QString::fromLatin1(sha.toHex())}};
}

// 日期：2026-11-06；测试自有数据库独立连接，成功/异常均先析构查询再关闭移除注册。
void withDatabase(dukto::PrivateStore &store, const std::function<void(QSqlDatabase)> &operation) {
    const auto connection = QUuid::createUuid().toString();
    {
        auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
        database.setDatabaseName(store.directory() + "/tasks.sqlite");
        if (!database.open())
            throw dukto::Error(dukto::ExitCode::Disk, "fixture database", "test");
        try {
            operation(database);
        } catch (...) {
            database.close();
            database = QSqlDatabase();
            QSqlDatabase::removeDatabase(connection);
            throw;
        }
        database.close();
    }
    QSqlDatabase::removeDatabase(connection);
}

// 日期：2026-11-06；独立SQL夹具失败必须终止，不能把缺失样本当作迁移成功。
void executeFixture(QSqlDatabase database, const QString &statement) {
    QSqlQuery query(database);
    if (!query.exec(statement))
        throw dukto::Error(dukto::ExitCode::Disk, "fixture sql", "test");
}

// 日期：2026-11-06；从原始版本一架构及已完成记录独立构造迁移输入，不调用新版初始化器。
QByteArray legacyTask(dukto::PrivateStore &store, const QUuid &owner, const QUuid &request,
                      const QUuid &id, const QString &root) {
    store.write("tasks.sqlite", {});
    const auto spec = dukto::next::encodeControl({{"version", 1},
                                                  {"direction", "download"},
                                                  {"share", "docs"},
                                                  {"path", "file"},
                                                  {"root", root},
                                                  {"uploadManifest", ""},
                                                  {"conflict", "keep-both"}});
    withDatabase(store, [&](QSqlDatabase database) {
        // 日期：2026-11-06；保留旧物理列顺序及原请求摘要，发现迁移误重建或误插列。
        executeFixture(
            database,
            "CREATE TABLE tasks(id TEXT PRIMARY KEY,owner TEXT NOT NULL,request TEXT NOT NULL,"
            "requesthash BLOB NOT NULL,spec BLOB NOT NULL,state TEXT NOT NULL,desired TEXT NOT "
            "NULL,"
            "revision INTEGER NOT NULL,manifest BLOB NOT NULL,total INTEGER NOT NULL,"
            "entries INTEGER NOT NULL,processed INTEGER NOT NULL,error INTEGER NOT NULL,"
            "message TEXT NOT NULL,updated TEXT NOT NULL,UNIQUE(owner,request))");
        executeFixture(database, "PRAGMA user_version=1");
        QSqlQuery query(database);
        query.prepare(
            "INSERT INTO tasks VALUES(?,?,?,?,?,'completed','',6,?,3,2,3,0,'','legacy-time')");
        query.addBindValue(id.toString(QUuid::WithoutBraces));
        query.addBindValue(owner.toString(QUuid::WithoutBraces));
        query.addBindValue(request.toString(QUuid::WithoutBraces));
        query.addBindValue(QCryptographicHash::hash(spec, QCryptographicHash::Sha256));
        query.addBindValue(spec);
        query.addBindValue(QByteArray(32, 'x'));
        if (!query.exec())
            throw dukto::Error(dukto::ExitCode::Disk, "fixture legacy insert", "test");
    });
    return spec;
}

// 日期：2026-11-06；独立快照描述已同步但尚未归结条目的数据，避免用被测编码器形成共同错误。
QJsonObject initialAccounting() {
    return {{"bytes", "2"},        {"confirmed", "2"},
            {"restored", "0"},     {"copiedBytes", "0"},
            {"skippedBytes", "0"}, {"discardedBytes", "0"},
            {"copiedFiles", "0"},  {"copiedDirectories", "0"},
            {"skippedFiles", "0"}, {"skippedDirectories", "0"}};
}

} // namespace

class TaskStoreTests final : public QObject {
    Q_OBJECT
  private slots:

    // 日期：2026-11-06；真实旧架构升级后任务身份、摘要、修订和完成结果逐字段保持，新增任务仍可分页。
    void versionOneMigration() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        const auto id = QUuid::createUuid();
        const auto original = legacyTask(store, owner, request, id, root.path());
        QJsonObject before;
        {
            dukto::TaskStore tasks(store);
            const auto task = tasks.task(owner, id);
            QCOMPARE(task.revision, quint64(6));
            QCOMPARE(task.processed, qint64(3));
            QCOMPARE(task.state, QString("completed"));
            QVERIFY(task.accounting.isEmpty());
            QVERIFY(!task.publicInfo().contains("receivedBytes"));
            before = task.publicInfo();
            QCOMPARE(
                tasks.create(owner, request, "download", "docs", "file", root.path()).publicInfo(),
                before);
            const auto second =
                tasks.create(owner, QUuid::createUuid(), "download", "docs", "other", root.path());
            const auto page = tasks.page(owner);
            QCOMPARE(page["tasks"].toArray().size(), 2);
            QCOMPARE(page["after"].toString(), QString("2"));
            QVERIFY(!page["more"].toBool());
            QCOMPARE(tasks.page(owner, 1)["tasks"].toArray().first().toObject()["taskId"],
                     QJsonValue(second.id.toString(QUuid::WithoutBraces)));
        }
        withDatabase(store, [&](QSqlDatabase database) {
            // 日期：2026-11-06；检查磁盘版本及未改写的旧参数，不能只读取内存对象。
            QSqlQuery query(database);
            QVERIFY(query.exec("PRAGMA user_version"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), 2);
            query.finish();
            query.prepare("SELECT spec,requesthash,accounting,updated FROM tasks WHERE id=?");
            query.addBindValue(id.toString(QUuid::WithoutBraces));
            QVERIFY(query.exec());
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toByteArray(), original);
            QCOMPARE(query.value(1).toByteArray(),
                     QCryptographicHash::hash(original, QCryptographicHash::Sha256));
            QCOMPARE(query.value(2).toByteArray(), QByteArray{});
            QCOMPARE(query.value(3).toString(), QString("legacy-time"));
        });
        dukto::TaskStore reopened(store);
        QCOMPARE(reopened.task(owner, id).publicInfo(), before);
    }

    // 日期：2026-11-06；未来版本及负版本均拒绝，不能重建旧表或悄悄降低持久架构版本。
    void unsupportedSchema_data() {
        QTest::addColumn<int>("version");
        QTest::newRow("future") << 3;
        QTest::newRow("negative") << -1;
    }

    // 日期：2026-11-06；在真实旧库中写入不支持版本，初始化失败后原版本及列数仍保持。
    void unsupportedSchema() {
        QFETCH(int, version);
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        legacyTask(store, QUuid::createUuid(), QUuid::createUuid(), QUuid::createUuid(),
                   root.path());
        withDatabase(store, [&](QSqlDatabase database) {
            // 日期：2026-11-06；变更只限自有样本，拒绝后需要保持同一版本。
            executeFixture(database, "PRAGMA user_version=" + QString::number(version));
        });
        QVERIFY_EXCEPTION_THROWN(dukto::TaskStore tasks(store), dukto::Error);
        withDatabase(store, [&](QSqlDatabase database) {
            // 日期：2026-11-06；核对失败未追加计量列，也未覆盖原数据库。
            QSqlQuery query(database);
            QVERIFY(query.exec("PRAGMA user_version"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), version);
            query.finish();
            QVERIFY(query.exec("PRAGMA table_info(tasks)"));
            int columns = 0;
            while (query.next())
                ++columns;
            QCOMPARE(columns, 15);
        });
    }

    // 日期：2026-11-06；迁移中途发现重复列必须回滚此前新建的索引及版本，不留下半次升级。
    void migrationRollsBack() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        const auto original = legacyTask(store, QUuid::createUuid(), QUuid::createUuid(),
                                         QUuid::createUuid(), root.path());
        withDatabase(store, [&](QSqlDatabase database) {
            // 日期：2026-11-06；人为构造版本一记录与重复新列，强制ALTER在真实事务中失败。
            executeFixture(database,
                           "ALTER TABLE tasks ADD COLUMN accounting BLOB NOT NULL DEFAULT X''");
        });
        QVERIFY_EXCEPTION_THROWN(dukto::TaskStore tasks(store), dukto::Error);
        withDatabase(store, [&](QSqlDatabase database) {
            // 日期：2026-11-06；旧参数、版本和索引集合均需保持，不仅要求初始化报错。
            QSqlQuery query(database);
            QVERIFY(query.exec("PRAGMA user_version"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), 1);
            query.finish();
            QVERIFY(query.exec(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='tasks_owner'"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), 0);
            query.finish();
            QVERIFY(query.exec("SELECT spec FROM tasks"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toByteArray(), original);
            QVERIFY(!query.next());
        });
    }

    // 日期：2026-11-06；计量与逻辑进度同一事务保存，重开查询及分页均返回一致固定计数。
    void persistentAccountingAndReset() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        QUuid id;
        QJsonObject snapshot;
        {
            dukto::TaskStore tasks(store);
            auto task =
                tasks.create(owner, QUuid::createUuid(), "download", "docs", "file", root.path());
            id = task.id;
            auto lease = tasks.acquire(owner, id);
            task = tasks.bindManifest(*lease, summary(QByteArray(32, 'x')));
            QVERIFY_EXCEPTION_THROWN(
                tasks.recordAccounting(*lease, task.revision, initialAccounting()), dukto::Error);
            task = tasks.advance(*lease, task.revision, "transferring", 0);
            const auto revision = task.revision;
            task = tasks.recordAccounting(*lease, revision, initialAccounting());
            QCOMPARE(task.revision, revision + 1);
            QCOMPARE(task.processed, qint64(2));
            QCOMPARE(task.accounting, initialAccounting());
            QCOMPARE(task.publicInfo()["bytes"], QJsonValue("2"));
            QCOMPARE(task.publicInfo()["receivedBytes"], QJsonValue("2"));
            QCOMPARE(task.publicInfo()["copiedBytes"], QJsonValue("0"));
            QVERIFY_EXCEPTION_THROWN(tasks.recordAccounting(*lease, revision, initialAccounting()),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "transferring", 3),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "verifying", 3),
                                     dukto::Error);
            task = tasks.requestStop(owner, id, true);
            QVERIFY_EXCEPTION_THROWN(
                tasks.recordAccounting(*lease, task.revision, initialAccounting()), dukto::Error);
            task = tasks.advance(*lease, task.revision, "pausing", 2);
            task = tasks.advance(*lease, task.revision, "paused", 2);
            snapshot = task.publicInfo();
        }
        dukto::TaskStore reopened(store);
        auto task = reopened.task(owner, id);
        QCOMPARE(task.publicInfo(), snapshot);
        QCOMPARE(reopened.page(owner)["tasks"].toArray().first().toObject(), snapshot);
        auto lease = reopened.acquire(owner, id);
        QVERIFY_EXCEPTION_THROWN(reopened.advance(*lease, task.revision, "checking", 2),
                                 dukto::Error);
        task = reopened.advance(*lease, task.revision, "checking", 0);
        QCOMPARE(task.processed, qint64(0));
        QVERIFY(task.accounting.isEmpty());
        QVERIFY(!task.publicInfo().contains("handledBytes"));
        task = reopened.advance(*lease, task.revision, "transferring", 0);
        auto full = initialAccounting();
        full["bytes"] = "3";
        full["confirmed"] = "3";
        task = reopened.recordAccounting(*lease, task.revision, full);
        QVERIFY_EXCEPTION_THROWN(reopened.advance(*lease, task.revision, "verifying", 3),
                                 dukto::Error);
        full["copiedBytes"] = "3";
        full["copiedFiles"] = "1";
        task = reopened.recordAccounting(*lease, task.revision, full);
        QVERIFY_EXCEPTION_THROWN(reopened.advance(*lease, task.revision, "verifying", 3),
                                 dukto::Error);
        full["copiedDirectories"] = "1";
        task = reopened.recordAccounting(*lease, task.revision, full);
        task = reopened.advance(*lease, task.revision, "verifying", 3);
        task = reopened.advance(*lease, task.revision, "committing", 3);
        task = reopened.advance(*lease, task.revision, "completed", 3);
        QVERIFY_EXCEPTION_THROWN(reopened.recordAccounting(*lease, task.revision, full),
                                 dukto::Error);
        QCOMPARE(reopened.task(owner, id).accounting, full);
        QCOMPARE(task.publicInfo()["copiedDirectories"], QJsonValue("1"));
    }

    // 日期：2026-11-06；受保护任务库发生内容损坏时仍须拒绝；不能仅依赖JSON可解析或总字节相等。
    void damagedAccounting_data() {
        QTest::addColumn<int>("attack");
        const char *names[] = {"malformed",
                               "missing",
                               "unknown",
                               "regressed-total",
                               "wrong-handled",
                               "skip-on-rename",
                               "directory-skip-on-rename",
                               "premature-final-count",
                               "completed-without-items",
                               "null-column"};
        for (int i = 0; i < int(sizeof(names) / sizeof(names[0])); ++i)
            QTest::newRow(names[i]) << i;
    }

    // 日期：2026-11-06；合法快照关闭后再破坏真实SQLite列，读取失败且不将损坏改写成空计量。
    void damagedAccounting() {
        QFETCH(int, attack);
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        QUuid id;
        {
            dukto::TaskStore tasks(store);
            auto task =
                tasks.create(owner, QUuid::createUuid(), "download", "docs", "file", root.path());
            id = task.id;
            auto lease = tasks.acquire(owner, id);
            task = tasks.bindManifest(*lease, summary(QByteArray(32, 'x')));
            task = tasks.advance(*lease, task.revision, "transferring", 0);
            tasks.recordAccounting(*lease, task.revision, initialAccounting());
        }
        auto invalid = initialAccounting();
        if (attack == 1)
            invalid.remove("copiedFiles");
        if (attack == 2)
            invalid["unknown"] = "0";
        if (attack == 3)
            invalid["bytes"] = "4";
        if (attack == 4)
            invalid["confirmed"] = "1";
        if (attack == 5) {
            invalid["skippedBytes"] = "1";
            invalid["skippedFiles"] = "1";
        }
        if (attack == 6)
            invalid["skippedDirectories"] = "1";
        if (attack == 7)
            invalid["copiedDirectories"] = "2";
        if (attack == 8) {
            invalid["bytes"] = "3";
            invalid["confirmed"] = "3";
        }
        withDatabase(store, [&](QSqlDatabase database) {
            // 日期：2026-11-06；只修改指定列，失败后生产读取必须继续拒绝，不能自动修复未知证据。
            QSqlQuery query(database);
            query.prepare("UPDATE tasks SET accounting=?");
            query.addBindValue(attack == 0 ? QByteArray("{") : dukto::next::encodeControl(invalid));
            QVERIFY(query.exec());
            if (attack == 8)
                executeFixture(database, "UPDATE tasks SET state='completed',processed=3");
            if (attack == 9) {
                // 日期：2026-11-06；架构NOT NULL应在写入点直接拒绝，不给损坏值进入生产读取。
                QVERIFY(!query.exec("UPDATE tasks SET accounting=NULL"));
            }
        });
        dukto::TaskStore reopened(store);
        if (attack == 9)
            QCOMPARE(reopened.task(owner, id).accounting, initialAccounting());
        else {
            QVERIFY_EXCEPTION_THROWN(reopened.task(owner, id), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(reopened.page(owner), dukto::Error);
        }
    }

    // 日期：2026-11-06；不合法快照更新必须整体回滚，修订、处理量和前一快照不改变。
    void rejectedAccountingTransaction() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::TaskStore tasks(store);
        const auto owner = QUuid::createUuid();
        auto task =
            tasks.create(owner, QUuid::createUuid(), "download", "docs", "file", root.path());
        auto lease = tasks.acquire(owner, task.id);
        task = tasks.bindManifest(*lease, summary(QByteArray(32, 'x')));
        task = tasks.advance(*lease, task.revision, "transferring", 0);
        task = tasks.recordAccounting(*lease, task.revision, initialAccounting());
        const auto before = task.publicInfo();
        const auto revision = task.revision;
        auto invalid = initialAccounting();
        invalid["bytes"] = "1";
        QVERIFY_EXCEPTION_THROWN(tasks.recordAccounting(*lease, task.revision, invalid),
                                 dukto::Error);
        QCOMPARE(tasks.task(owner, task.id).publicInfo(), before);
        invalid = initialAccounting();
        invalid["skippedDirectories"] = "1";
        QVERIFY_EXCEPTION_THROWN(tasks.recordAccounting(*lease, task.revision, invalid),
                                 dukto::Error);
        QCOMPARE(tasks.task(owner, task.id).publicInfo(), before);
        auto next = initialAccounting();
        next["bytes"] = "3";
        next["confirmed"] = "3";
        task = tasks.recordAccounting(*lease, task.revision, next);
        QCOMPARE(task.processed, qint64(3));
        QCOMPARE(task.revision, revision + 1);
    }
    // 日期：2026-11-05；内部跳过准备尚未接入公开协议，拒绝创建且不能占用请求ID或留下不可读任务。
    void internalSkipNotPublished() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::TaskStore tasks(store);
        const auto owner = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        QVERIFY_EXCEPTION_THROWN(tasks.create(owner, request, "download", "docs", "file",
                                              root.path(), {}, dukto::ConflictPolicy::Skip),
                                 dukto::Error);
        const auto accepted = tasks.create(owner, request, "download", "docs", "file", root.path());
        QCOMPARE(tasks.task(owner, accepted.id).id, accepted.id);
        QVERIFY(!accepted.publicInfo().contains("conflict"));
    }
    // 日期：2026-11-05；两种非默认策略均绑定请求摘要，覆盖不能借 fail 能力或旧摘要绕过。
    void conflictRequestBinding_data() {
        QTest::addColumn<QString>("policy");
        QTest::newRow("fail") << QString("fail");
        QTest::newRow("overwrite") << QString("overwrite");
    }
    // 日期：2026-11-05；冲突策略绑定幂等键、公开查询和重开，默认旧规范格式仍不增加字段。
    void conflictRequestBinding() {
        QFETCH(QString, policy);
        const auto conflict = dukto::checkedConflictPolicy(policy);
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        QUuid id;
        {
            dukto::TaskStore tasks(store);
            const auto task =
                tasks.create(owner, request, "download", "docs", "file", root.path(), {}, conflict);
            id = task.id;
            QCOMPARE(task.publicInfo()["conflict"].toString(), policy);
            QCOMPARE(
                tasks.create(owner, request, "download", "docs", "file", root.path(), {}, conflict)
                    .id,
                id);
            QVERIFY_EXCEPTION_THROWN(
                tasks.create(owner, request, "download", "docs", "file", root.path()),
                dukto::Error);
            const auto original =
                tasks.create(owner, QUuid::createUuid(), "download", "docs", "other", root.path());
            QVERIFY(!original.publicInfo().contains("conflict"));
        }
        dukto::TaskStore tasks(store);
        const auto task = tasks.task(owner, id);
        QVERIFY(task.conflict == conflict);
        QCOMPARE(task.publicInfo()["conflict"].toString(), policy);
    }
    // 日期：2026-11-05；尚未扫描的等待任务可暂停/恢复，正文扫描只能在获得调度许可后重新进入。
    void unboundQueuePauseAndResume() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        dukto::TaskStore tasks(store);
        const auto owner = QUuid::createUuid();
        auto task =
            tasks.create(owner, QUuid::createUuid(), "download", "docs", "file", root.path());
        auto lease = tasks.acquire(owner, task.id);
        task = tasks.advance(*lease, task.revision, "queued", 0);
        task = tasks.requestStop(owner, task.id, true);
        QCOMPARE(task.desired, QString("pause"));
        task = tasks.advance(*lease, task.revision, "pausing", 0);
        task = tasks.advance(*lease, task.revision, "paused", 0);
        task = tasks.advance(*lease, task.revision, "checking", 0);
        QVERIFY(task.desired.isEmpty());
        task = tasks.advance(*lease, task.revision, "queued", 0);
        task = tasks.advance(*lease, task.revision, "interrupted", 0);
        task = tasks.advance(*lease, task.revision, "checking", 0);
        task = tasks.advance(*lease, task.revision, "queued", 0);
        task = tasks.advance(*lease, task.revision, "scanning", 0);
        task = tasks.bindManifest(*lease, summary(QByteArray(32, 'x')));
        QCOMPARE(task.state, QString("queued"));
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "scanning", 0), dukto::Error);
    }
    // 日期：2026-11-04；受保护数据库中的创建根意外变化但摘要未同步时，不能继续使用错误根执行任务。
    void changedCreationRejected() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        QUuid id;
        {
            dukto::TaskStore tasks(store);
            id = tasks
                     .create(owner, QUuid::createUuid(), "download", "docs", "file",
                             temporary.path())
                     .id;
        }
        const auto connection = QUuid::createUuid().toString();
        {
            auto database = QSqlDatabase::addDatabase("QSQLITE", connection);
            database.setDatabaseName(store.directory() + "/tasks.sqlite");
            QVERIFY(database.open());
            {
                QSqlQuery query(database);
                QVERIFY(query.exec("SELECT spec FROM tasks"));
                QVERIFY(query.next());
                auto spec = dukto::next::parseControl(query.value(0).toByteArray());
                query.finish();
                spec["root"] = temporary.filePath("different-root");
                query.prepare("UPDATE tasks SET spec=?");
                query.addBindValue(dukto::next::encodeControl(spec));
                QVERIFY(query.exec());
            }
            database.close();
        }
        QSqlDatabase::removeDatabase(connection);
        dukto::TaskStore changed(store);
        QVERIFY_EXCEPTION_THROWN(changed.task(owner, id), dukto::Error);
    }
    // 日期：2026-11-04；重复请求及重开库返回同一任务，其他主体与参数冲突不能取得或重用任务。
    void persistentIdempotencyAndOwnership() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        const auto other = QUuid::createUuid();
        QUuid id;
        {
            dukto::TaskStore tasks(store);
            const auto first =
                tasks.create(owner, request, "download", "docs", "folder", temporary.path());
            id = first.id;
            QCOMPARE(first.state, QString("scanning"));
            QCOMPARE(
                tasks.create(owner, request, "download", "docs", "folder", temporary.path()).id,
                id);
            QVERIFY_EXCEPTION_THROWN(
                tasks.create(owner, request, "download", "docs", "changed", temporary.path()),
                dukto::Error);
            QVERIFY_EXCEPTION_THROWN(tasks.task(other, id), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(tasks.acquire(other, id), dukto::Error);
            QVERIFY_EXCEPTION_THROWN(tasks.requestStop(other, id, false), dukto::Error);
            QVERIFY(
                tasks.create(other, request, "download", "docs", "folder", temporary.path()).id !=
                id);
            QVERIFY(!dukto::next::encodeControl(first.publicInfo())
                         .contains(temporary.path().toUtf8()));
            QVERIFY_EXCEPTION_THROWN(tasks.create(owner, QUuid::createUuid(), "download", "docs",
                                                  "../escape", temporary.path()),
                                     dukto::Error);
            QVERIFY_EXCEPTION_THROWN(
                tasks.create(owner, QUuid::createUuid(), "upload", "docs", "", temporary.path()),
                dukto::Error);
        }
        dukto::TaskStore reopened(store);
        QCOMPARE(reopened.create(owner, request, "download", "docs", "folder", temporary.path()).id,
                 id);
        auto lease = reopened.acquire(owner, id);
        dukto::TaskStore second(store);
        QVERIFY_EXCEPTION_THROWN(second.acquire(owner, id), dukto::Error);
        lease.reset();
        QVERIFY(second.acquire(owner, id) != nullptr);
    }

    // 日期：2026-11-04；八个真实线程使用独立 SQLite 连接争用同一稳定请求，只能持久产生一个任务。
    void simultaneousCreation() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        const auto state = store.directory();
        const auto root = temporary.path();
        std::mutex mutex;
        std::vector<QUuid> ids;
        std::vector<QString> errors;
        std::vector<std::thread> threads;
        for (int index = 0; index < 8; ++index)
            threads.emplace_back([&]() {
                // 日期：2026-11-04；线程不共享 Qt 数据库对象，仅保存返回 ID 和规范异常。
                try {
                    dukto::PrivateStore privateStore(state);
                    dukto::TaskStore tasks(privateStore);
                    const auto task = tasks.create(owner, request, "download", "docs", "", root);
                    std::lock_guard<std::mutex> guard(mutex);
                    ids.push_back(task.id);
                } catch (const std::exception &error) {
                    std::lock_guard<std::mutex> guard(mutex);
                    errors.push_back(QString::fromUtf8(error.what()));
                }
            });
        for (auto &thread : threads)
            thread.join();
        QVERIFY2(errors.empty(), errors.empty() ? "" : qPrintable(errors.front()));
        QCOMPARE(ids.size(), size_t(8));
        for (const auto &id : ids)
            QCOMPARE(id, ids.front());
    }

    // 日期：2026-11-04；完成确认必须经过完整字节、校验和提交阶段；修订冲突不能覆盖新状态。
    void completionAndCompareExchange() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::TaskStore tasks(store);
        const auto owner = QUuid::createUuid();
        const QByteArray sha(32, 'a');
        auto task =
            tasks.create(owner, QUuid::createUuid(), "upload", "docs", "", temporary.path(), sha);
        const auto lease = tasks.acquire(owner, task.id);
        QVERIFY_EXCEPTION_THROWN(tasks.bindManifest(*lease, summary(QByteArray(32, 'b'))),
                                 dukto::Error);
        task = tasks.bindManifest(*lease, summary(sha));
        QCOMPARE(task.state, QString("queued"));
        QCOMPARE(tasks.bindManifest(*lease, summary(sha)).revision, task.revision);
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "completed", 3),
                                 dukto::Error);
        task = tasks.advance(*lease, task.revision, "transferring", 0);
        const auto before = task.revision;
        task = tasks.advance(*lease, task.revision, "transferring", 1);
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, before, "transferring", 2), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "verifying", 1),
                                 dukto::Error);
        task = tasks.advance(*lease, task.revision, "verifying", 3);
        task = tasks.advance(*lease, task.revision, "committing", 3);
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "failed", 3, 5),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(tasks.requestStop(owner, task.id, false), dukto::Error);
        task = tasks.advance(*lease, task.revision, "completed", 3);
        const auto completed = task.publicInfo();
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "transferring", 3),
                                 dukto::Error);
        QCOMPARE(tasks.requestStop(owner, task.id, false).publicInfo(), completed);
        QCOMPARE(tasks.create(owner, task.request, "upload", "docs", "", temporary.path(), sha)
                     .publicInfo(),
                 completed);
        dukto::TaskStore restarted(store);
        QCOMPARE(restarted.task(owner, task.id).publicInfo(), completed);
    }

    // 日期：2026-11-04；长路径让字节预算先于条数生效，完整分页不重复/遗漏或泄露其他主体。
    void boundedTaskPages() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::TaskStore tasks(store);
        const auto owner = QUuid::createUuid();
        QStringList parts;
        for (int index = 0; index < 19; ++index)
            parts.append(QString(200, 'x'));
        const auto path = parts.join('/');
        QSet<QString> expected;
        for (int index = 0; index < 110; ++index)
            expected.insert(
                tasks.create(owner, QUuid::createUuid(), "download", "docs", path, temporary.path())
                    .id.toString(QUuid::WithoutBraces));
        const auto other = tasks.create(QUuid::createUuid(), QUuid::createUuid(), "download",
                                        "docs", "", temporary.path());
        QSet<QString> seen;
        quint64 after = 0;
        int pages = 0;
        for (;;) {
            const auto page = tasks.page(owner, after);
            QVERIFY(dukto::next::encodeControl(page).size() <= dukto::next::ControlLimit);
            const auto entries = page["tasks"].toArray();
            QVERIFY(!entries.isEmpty() && entries.size() <= 100);
            if (!pages)
                QVERIFY(entries.size() < 100);
            for (const auto &value : entries) {
                const auto task = value.toObject();
                const auto id = task["taskId"].toString();
                QVERIFY(!seen.contains(id));
                QVERIFY(id != other.id.toString(QUuid::WithoutBraces));
                QVERIFY(!task.contains("root"));
                seen.insert(id);
            }
            const auto next = page["after"].toString().toULongLong();
            QVERIFY(next > after);
            after = next;
            ++pages;
            if (!page["more"].toBool())
                break;
        }
        QVERIFY(pages > 1);
        QCOMPARE(seen, expected);
        QVERIFY(tasks.page(QUuid::createUuid())["tasks"].toArray().isEmpty());
    }

    // 日期：2026-11-04；停止请求先持久化，工作者确认前不显示已停止；恢复先检查，取消优先于暂停。
    void pauseCancellationAndRecoveryStates() {
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::TaskStore tasks(store);
        const auto owner = QUuid::createUuid();
        auto task =
            tasks.create(owner, QUuid::createUuid(), "download", "docs", "", temporary.path());
        const auto lease = tasks.acquire(owner, task.id);
        QVERIFY_EXCEPTION_THROWN(tasks.requestStop(owner, task.id, true), dukto::Error);
        task = tasks.bindManifest(*lease, summary(QByteArray(32, 'a')));
        task = tasks.advance(*lease, task.revision, "transferring", 2);
        const auto oldRevision = task.revision;
        task = tasks.requestStop(owner, task.id, true);
        QCOMPARE(task.state, QString("transferring"));
        QCOMPARE(task.desired, QString("pause"));
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, oldRevision, "transferring", 3),
                                 dukto::Error);
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "verifying", 3),
                                 dukto::Error);
        task = tasks.advance(*lease, task.revision, "pausing", 2);
        task = tasks.advance(*lease, task.revision, "paused", 2);
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "transferring", 2),
                                 dukto::Error);
        task = tasks.advance(*lease, task.revision, "checking", 0);
        QCOMPARE(task.desired, QString(""));
        task = tasks.advance(*lease, task.revision, "transferring", 2);
        task = tasks.advance(*lease, task.revision, "interrupted", 2);
        task = tasks.advance(*lease, task.revision, "checking", 1);
        task = tasks.advance(*lease, task.revision, "transferring", 1);
        task = tasks.requestStop(owner, task.id, false);
        QCOMPARE(task.desired, QString("cancel"));
        QCOMPARE(tasks.requestStop(owner, task.id, true).desired, QString("cancel"));
        task = tasks.advance(*lease, task.revision, "cancelling", 1);
        task = tasks.advance(*lease, task.revision, "cancelled", 1);
        QCOMPARE(task.desired, QString(""));
        QVERIFY_EXCEPTION_THROWN(tasks.advance(*lease, task.revision, "checking", 1), dukto::Error);
    }
};
QTEST_GUILESS_MAIN(TaskStoreTests)
#include "task_store_tests.moc"

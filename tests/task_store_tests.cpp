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
} // namespace

class TaskStoreTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；冲突策略绑定幂等键、公开查询和重开，默认旧规范格式仍不增加字段。
    void conflictRequestBinding() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("private"), true);
        const auto owner = QUuid::createUuid();
        const auto request = QUuid::createUuid();
        QUuid id;
        {
            dukto::TaskStore tasks(store);
            const auto task = tasks.create(owner, request, "download", "docs", "file", root.path(),
                                           {}, dukto::ConflictPolicy::Fail);
            id = task.id;
            QCOMPARE(task.publicInfo()["conflict"].toString(), QString("fail"));
            QCOMPARE(tasks
                         .create(owner, request, "download", "docs", "file", root.path(), {},
                                 dukto::ConflictPolicy::Fail)
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
        QVERIFY(task.conflict == dukto::ConflictPolicy::Fail);
        QCOMPARE(task.publicInfo()["conflict"].toString(), QString("fail"));
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

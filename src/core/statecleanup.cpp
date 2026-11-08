#include "statecleanup.h"
#include "error.h"
#include "expiredtaskcleanup.h"
#include "protocol.h"
#include "sqlitecache.h"
#include "sqliteruntime.h"
#include "statesession.h"
#include "taskstore.h"
#include "uploadmanifest.h"
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonArray>
#include <QRegularExpression>
#include <QSqlError>
#include <QSqlQuery>
#include <QUrl>
#include <limits>

namespace dukto {
namespace {
constexpr auto CursorName = "gc-cursor.json";
constexpr auto ReportName = "gc-last.json";
struct BatchEnd {};
class TaskDatabaseProbe final {
  public:
    // 日期：2026-11-08；只读不可变探针不恢复热日志、不创建WAL/shm，也不迁移或补建未知库架构。
    explicit TaskDatabaseProbe(const QString &path) : connection_(QUuid::createUuid().toString()) {
        database_ = addSqliteDatabase(connection_);
        QUrl uri = QUrl::fromLocalFile(path);
        uri.setQuery("immutable=1");
        database_.setDatabaseName(QString::fromUtf8(uri.toEncoded()));
        database_.setConnectOptions("QSQLITE_OPEN_READONLY;QSQLITE_OPEN_URI");
    }
    // 日期：2026-11-08；所有局部查询退出后归还连接注册项及固定缓存额度，包括探针打开失败。
    ~TaskDatabaseProbe() {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
    }
    // 日期：2026-11-08；只接受已迁移完成的任务/到期表，旧库留给显式业务恢复，自动维护不认领。
    bool ready() {
        if (!database_.open())
            throw Error(ExitCode::Integrity, QStringLiteral("清理任务库只读核对失败"), "cleanup");
        credit_.configure(database_);
        QSqlQuery query(database_);
        if (!query.exec("PRAGMA user_version") || !query.next())
            throw Error(ExitCode::Integrity, QStringLiteral("清理任务库版本读取失败"), "cleanup");
        if (query.value(0).toInt() != 3)
            return false;
        query.finish();
        if (!query.exec(
                "SELECT name,type FROM sqlite_master WHERE type IN('table','view','trigger') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"))
            throw Error(ExitCode::Integrity, QStringLiteral("清理任务库架构读取失败"), "cleanup");
        QStringList tables;
        while (query.next()) {
            if (tables.size() == 2 || query.value(1).toString() != "table")
                return false;
            tables.append(query.value(0).toString());
        }
        if (query.lastError().isValid())
            throw Error(ExitCode::Integrity, QStringLiteral("清理任务库架构枚举失败"), "cleanup");
        if (tables != QStringList{"task_expiry", "tasks"})
            return false;
        query.finish();
        return columns("PRAGMA table_info(tasks)",
                       {"id", "owner", "request", "requesthash", "spec", "state", "desired",
                        "revision", "manifest", "total", "entries", "processed", "error", "message",
                        "updated", "accounting"},
                       {"TEXT", "TEXT", "TEXT", "BLOB", "BLOB", "TEXT", "TEXT", "INTEGER", "BLOB",
                        "INTEGER", "INTEGER", "INTEGER", "INTEGER", "TEXT", "TEXT", "BLOB"}) &&
               columns("PRAGMA table_info(task_expiry)", {"id", "owner", "revision", "started"},
                       {"TEXT", "TEXT", "INTEGER", "TEXT"});
    }

  private:
    // 日期：2026-11-08；固定列名/类型/主键/非空形状必须匹配，其他同名业务库不进入可写任务路径。
    bool columns(const QString &statement, const QStringList &names, const QStringList &types) {
        QSqlQuery query(database_);
        if (!query.exec(statement))
            throw Error(ExitCode::Integrity, QStringLiteral("清理任务库列读取失败"), "cleanup");
        int index = 0;
        while (query.next()) {
            if (index == names.size() || query.value(0).toInt() != index ||
                query.value(1).toString() != names[index] ||
                query.value(2).toString() != types[index] ||
                query.value(3).toInt() != (index == 0 ? 0 : 1) ||
                query.value(5).toInt() != (index == 0 ? 1 : 0))
                return false;
            ++index;
        }
        if (query.lastError().isValid())
            throw Error(ExitCode::Integrity, QStringLiteral("清理任务库列枚举失败"), "cleanup");
        return index == names.size();
    }
    QString connection_;
    SqliteCacheCredit credit_{1024};
    QSqlDatabase database_;
};

// 日期：2026-11-08；未知库及待恢复旁路保持原字节，只有已完成初始化的业务库进入任务候选枚举。
bool taskDatabaseReady(PrivateStore &store) {
    if (!store.exists("tasks.sqlite"))
        return false;
    store.validateFile("tasks.sqlite");
    for (const auto &suffix : QStringList{"-journal", "-wal", "-shm"})
        if (store.exists("tasks.sqlite" + suffix))
            return false;
    TaskDatabaseProbe probe(QDir(store.directory()).filePath("tasks.sqlite"));
    return probe.ready();
}

struct Cursor {
    quint64 tasks = 0;
    quint64 entries = 0;
};

// 日期：2026-11-08；进度只决定下一次从哪里扫描，不赋予任何文件删除资格；损坏时保留现场。
Cursor readCursor(PrivateStore &store) {
    Cursor result;
    if (!store.exists(CursorName))
        return result;
    const auto raw = store.read(CursorName, 4096);
    const auto value = next::parseControl(raw);
    bool tasks = false, entries = false;
    result.tasks = value["tasks"].toString().toULongLong(&tasks);
    result.entries = value["entries"].toString().toULongLong(&entries);
    if (value.size() != 3 || value["version"] != 1 || raw != next::encodeControl(value) || !tasks ||
        !entries || value["tasks"] != QString::number(result.tasks) ||
        value["entries"] != QString::number(result.entries) ||
        result.tasks > quint64(std::numeric_limits<qint64>::max()) ||
        result.entries > quint64(std::numeric_limits<qint64>::max()))
        throw Error(ExitCode::Integrity, QStringLiteral("自动清理进度无效，保留原数据"), "cleanup");
    return result;
}

// 日期：2026-11-08；只保存固定数量的错误码和阶段，不把正文、凭据和本机路径写入自动维护报告。
void recordFailure(QJsonArray &errors, qint64 &count, const Error &error) {
    ++count;
    if (errors.size() < 8)
        errors.append(QJsonObject{{"code", int(error.code)}, {"stage", error.stage.left(64)}});
}
} // namespace

// 日期：2026-11-08；先分页收集有限候选，再复用逐项身份/删除意图；不在目录枚举期间删除文件。
QJsonObject cleanupState(PrivateStore &store, const QDateTime &now, bool apply,
                         const StateCleanupLimits &limits, const std::function<void()> &check) {
    if (!store.maintenance() || !now.isValid() || now.timeSpec() != Qt::UTC || limits.tasks < 1 ||
        limits.tasks > 100 || limits.directoryEntries < 1 || limits.directoryEntries > 1024 ||
        limits.milliseconds < 1 || limits.milliseconds > 30000)
        throw Error(ExitCode::Config, QStringLiteral("清理需要独占状态根、UTC时钟及有效批量上限"),
                    "cleanup");
    auto cursor = readCursor(store);
    const auto original = cursor;
    QElapsedTimer timer;
    timer.start();
    const auto checkpoint = [&]() {
        // 日期：2026-11-08；取消向上传递；时间批次停止保留已有删除意图，下次继续同一候选。
        if (check)
            check();
        if (timer.elapsed() >= limits.milliseconds)
            throw BatchEnd{};
    };
    qint64 tasksVisited = 0, eligible = 0, uploads = 0, scansVisited = 0, scans = 0;
    qint64 failures = 0;
    QJsonArray errors;
    bool taskMore = false, scanMore = false, timedOut = false;
    bool taskDatabaseEligible = false;
    try {
        taskDatabaseEligible = taskDatabaseReady(store);
        if (taskDatabaseEligible) {
            TaskStore tasks(store);
            for (;;) {
                checkpoint();
                const auto candidate = tasks.nextCleanupTask(cursor.tasks);
                if (candidate.isEmpty()) {
                    cursor.tasks = 0;
                    break;
                }
                if (tasksVisited == limits.tasks) {
                    taskMore = true;
                    break;
                }
                const QUuid owner(candidate["owner"].toString());
                const QUuid id(candidate["task"].toString());
                try {
                    bool allowed = false;
                    {
                        auto lease = tasks.acquire(owner, id);
                        allowed = tasks.task(owner, id).direction == "upload" &&
                                  tasks.expiryInfo(*lease, now)["eligible"].toBool();
                    }
                    if (allowed) {
                        ++eligible;
                        cleanupExpiredUpload(store, owner, id, now, apply, 0, checkpoint);
                        if (apply)
                            ++uploads;
                    }
                } catch (const Error &error) {
                    if (error.code == ExitCode::Cancelled)
                        throw;
                    recordFailure(errors, failures, error);
                }
                ++tasksVisited;
                cursor.tasks = candidate["after"].toString().toULongLong();
            }
        } else
            cursor.tasks = 0;

        QStringList candidates;
        quint64 position = 0;
        int visited = 0;
        bool ended = true;
        static const QRegularExpression marker("\\Aupload-source-([0-9a-f-]{36})\\.scan\\.json\\z");
        try {
            store.visitStorageEntries(
                [&](const NativeDirectoryEntry &entry) {
                    // 日期：2026-11-08；游标是可重复的枚举进度；名称匹配仅产生候选，实际删除仍需完整证据。
                    checkpoint();
                    if (++position <= cursor.entries)
                        return;
                    if (visited == limits.directoryEntries) {
                        ended = false;
                        throw BatchEnd{};
                    }
                    ++visited;
                    const auto match = marker.match(entry.name);
                    const QUuid request(match.captured(1));
                    if (entry.kind == NativeDirectoryEntry::Kind::Regular && match.hasMatch() &&
                        !request.isNull() &&
                        request.toString(QUuid::WithoutBraces) == match.captured(1))
                        candidates.append(match.captured(1));
                },
                check);
        } catch (const BatchEnd &) {
            scanMore = true;
            if (ended)
                throw;
        }
        for (const auto &key : candidates) {
            checkpoint();
            try {
                const auto result = cleanupUploadScan(store, QUuid(key), now, apply, checkpoint);
                ++scansVisited;
                if (result["eligible"].toBool()) {
                    ++eligible;
                    if (apply && result["action"] == "cleaned")
                        ++scans;
                }
            } catch (const Error &error) {
                if (error.code == ExitCode::Cancelled)
                    throw;
                recordFailure(errors, failures, error);
            }
        }
        cursor.entries = ended ? 0 : position - 1;
    } catch (const BatchEnd &) {
        timedOut = true;
    } catch (const Error &error) {
        if (error.code == ExitCode::Cancelled)
            throw;
        recordFailure(errors, failures, error);
    }
    QJsonObject result{{"eventVersion", 1},
                       {"event", "state-cleanup"},
                       {"applied", apply},
                       {"taskDatabaseEligible", taskDatabaseEligible},
                       {"tasksVisited", QString::number(tasksVisited)},
                       {"eligible", QString::number(eligible)},
                       {"uploadTasksProcessed", QString::number(uploads)},
                       {"scansVisited", QString::number(scansVisited)},
                       {"scansCleaned", QString::number(scans)},
                       {"errors", errors},
                       {"errorCount", QString::number(failures)},
                       {"more", taskMore || scanMore || timedOut},
                       {"timeLimitReached", timedOut},
                       {"unknownObjectsPreserved", true},
                       {"taskIdentitiesPreserved", true},
                       {"globalQuotaEnforced", false},
                       {"message", apply ? QStringLiteral("本批过期临时项维护完成")
                                         : QStringLiteral("过期临时项预览完成，正文保留")}};
    if (apply && (tasksVisited || scansVisited || failures || cursor.entries != original.entries ||
                  cursor.tasks != original.tasks)) {
        store.write(CursorName,
                    next::encodeControl({{"version", 1},
                                         {"tasks", QString::number(cursor.tasks)},
                                         {"entries", QString::number(cursor.entries)}}));
        store.write(ReportName, next::encodeControl(result));
    }
    return result;
}

// 日期：2026-11-08；只尝试已有私有根，不创建目录、不等待独占锁；正常业务随后仍执行原有严格核对。
void tryAutomaticStateCleanup(const QString &parent, const QString &relative,
                              const std::function<void()> &check) {
    if (check)
        check();
    if (!QFileInfo(QDir(parent).filePath(relative)).isDir())
        return;
    try {
        auto store = StateSession::observe(parent, relative, PrivateStore::Use::Maintenance, check);
        cleanupState(*store, QDateTime::currentDateTimeUtc(), true, {}, check);
    } catch (const Error &error) {
        if (error.code == ExitCode::Cancelled)
            throw;
        // 日期：2026-11-08；维护为机会式执行，权限/损坏错误不重置任何状态；显式维护可取得原错误。
    }
}
} // namespace dukto

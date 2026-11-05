#include "taskstore.h"
#include "auth.h"
#include "error.h"
#include "files.h"
#include "protocol.h"
#include "strongmanifest.h"

#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonDocument>
#include <QMutex>
#include <QMutexLocker>
#include <QSqlQuery>
#include <QThread>
#include <limits>

namespace dukto {
namespace {
const QString Columns = "id,owner,request,spec,state,desired,revision,manifest,total,entries,"
                        "processed,error,message,requesthash";

// 日期：2026-11-05；保留5秒初始化预算，以10ms短轮询避免多进程共享指数退避长期错过已释放的锁。
void lockInitialization(QLockFile &lock) {
    QElapsedTimer elapsed;
    elapsed.start();
    for (;;) {
        if (lock.tryLock(0))
            return;
        const auto remaining = 5000 - elapsed.elapsed();
        if (remaining <= 0)
            throw Error(ExitCode::Permission, QStringLiteral("任务库正在初始化，请重试"), "task");
        QThread::msleep(static_cast<unsigned long>(qMin<qint64>(10, remaining)));
    }
}

// 日期：2026-11-04；任何失败都只报告规范错误，不回显 SQL 和任务中的本地绝对路径。
void checked(QSqlQuery &query) {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("持久任务数据库操作失败"), "task");
}

// 日期：2026-11-04；所有架构和事务语句固定，用户输入只用参数绑定。
void execute(QSqlDatabase database, const QString &sql) {
    QSqlQuery query(database);
    if (!query.exec(sql))
        throw Error(ExitCode::Disk, QStringLiteral("持久任务数据库事务失败"), "task");
}

class Transaction final {
  public:
    // 日期：2026-11-04；先取得 SQLite 写锁再读取幂等键，避免两个进程都认为请求不存在。
    explicit Transaction(QSqlDatabase database) : database_(database) {
        execute(database_, "BEGIN IMMEDIATE");
    }
    // 日期：2026-11-04；任何异常回滚本次变更，不能留下半次创建或部分状态更新。
    ~Transaction() {
        if (!done_)
            database_.rollback();
    }
    // 日期：2026-11-04；FULL 同步成功后才允许向网络返回任务创建或完成状态。
    void commit() {
        if (!database_.commit())
            throw Error(ExitCode::Disk, QStringLiteral("持久任务提交失败"), "task");
        done_ = true;
    }

  private:
    QSqlDatabase database_;
    bool done_ = false;
};

// 日期：2026-11-04；UUID 按规范不带括号保存，不接受空身份来绕过所属主体比较。
QString uuid(const QUuid &id) {
    if (id.isNull())
        throw Error(ExitCode::Permission, QStringLiteral("任务或主体身份无效"), "task");
    return id.toString(QUuid::WithoutBraces);
}

// 日期：2026-11-04；终态不能被恢复或取消重新激活，确认丢失只查询原结果。
bool terminal(const QString &state) {
    return state == "completed" || state == "cancelled" || state == "failed";
}

// 日期：2026-11-05；扫描/恢复可先排队，获准后再扫描；等待断开可中断，提交和终态规则保持。
bool permitted(const QString &before, const QString &after) {
    if (terminal(before))
        return false;
    if (before == after)
        return before == "transferring" || before == "checking";
    if (after == "failed")
        return before != "committing";
    if (after == "cancelling")
        return before != "committing";
    if (before == "scanning")
        return after == "queued" || after == "interrupted";
    if (before == "queued")
        return after == "transferring" || after == "checking" || after == "pausing" ||
               after == "scanning" || after == "interrupted";
    if (before == "transferring")
        return after == "pausing" || after == "verifying" || after == "interrupted";
    if (before == "pausing")
        return after == "paused" || after == "interrupted";
    if (before == "interrupted")
        return after == "checking" || after == "pausing";
    if (before == "paused")
        return after == "checking";
    if (before == "checking")
        return after == "transferring" || after == "pausing" || after == "interrupted" ||
               after == "queued";
    if (before == "verifying")
        return after == "committing" || after == "pausing" || after == "interrupted";
    if (before == "committing")
        return after == "completed";
    if (before == "cancelling")
        return after == "cancelled";
    return false;
}

// 日期：2026-11-05；严格区分旧保留双方与版本二失败/覆盖策略，损坏或未知策略一律拒绝。
TransferTask row(const QSqlQuery &query) {
    const auto encoded = query.value(3).toByteArray();
    const auto spec = next::parseControl(encoded);
    const bool keepBoth = spec["version"] == 1 && spec["conflict"] == "keep-both";
    const bool failConflict = spec["version"] == 2 && spec["conflict"] == "fail";
    const bool overwriteConflict = spec["version"] == 2 && spec["conflict"] == "overwrite";
    if ((!keepBoth && !failConflict && !overwriteConflict) ||
        query.value(13).toByteArray() !=
            QCryptographicHash::hash(encoded, QCryptographicHash::Sha256))
        throw Error(ExitCode::Integrity, QStringLiteral("任务创建参数摘要已损坏"), "task");
    TransferTask result{QUuid(query.value(0).toString()), QUuid(query.value(1).toString()),
                        QUuid(query.value(2).toString()), spec["direction"].toString(),
                        spec["share"].toString(),         spec["path"].toString(),
                        spec["root"].toString(),          query.value(4).toString(),
                        query.value(5).toString(),        query.value(6).toULongLong(),
                        query.value(7).toByteArray(),     query.value(8).toLongLong(),
                        query.value(9).toLongLong(),      query.value(10).toLongLong(),
                        query.value(11).toInt(),          query.value(12).toString()};
    result.conflict =
        keepBoth ? ConflictPolicy::Rename : checkedConflictPolicy(spec["conflict"].toString());
    const QStringList states{"scanning",  "queued",    "transferring", "pausing",   "paused",
                             "checking",  "verifying", "committing",   "completed", "cancelling",
                             "cancelled", "failed",    "interrupted"};
    if (result.id.isNull() || result.owner.isNull() || result.request.isNull() ||
        !result.revision || result.total < 0 || result.processed < 0 ||
        result.revision >= static_cast<quint64>(std::numeric_limits<qint64>::max()) ||
        result.processed > result.total || result.entries < 0 || !states.contains(result.state) ||
        !QStringList{"", "pause", "cancel"}.contains(result.desired) ||
        (result.direction != "upload" && result.direction != "download") ||
        !QDir::isAbsolutePath(result.root) ||
        (!result.manifest.isEmpty() && result.manifest.size() != 32) || result.error < 0 ||
        result.error > 7 || (result.state == "failed" && !result.error) ||
        (result.state != "failed" && result.error) ||
        (result.state == "completed" &&
         (result.manifest.isEmpty() || !result.entries || result.processed != result.total)))
        throw Error(ExitCode::Integrity, QStringLiteral("持久任务记录已损坏"), "task");
    validateShareName(result.share);
    if (!result.relative.isEmpty())
        validateRelativePath(result.relative);
    return result;
}
} // namespace

// 日期：2026-11-05；非默认策略显式返回供恢复核对，旧任务公开格式保持兼容且不输出本地根。
QJsonObject TransferTask::publicInfo() const {
    QJsonObject result{{"taskId", id.toString(QUuid::WithoutBraces)},
                       {"requestId", request.toString(QUuid::WithoutBraces)},
                       {"direction", direction},
                       {"share", share},
                       {"path", relative},
                       {"state", state},
                       {"desired", desired},
                       {"revision", QString::number(revision)},
                       {"manifest", QString::fromLatin1(manifest.toHex())},
                       {"bytes", QString::number(processed)},
                       {"total", QString::number(total)},
                       {"entries", QString::number(entries)},
                       {"error", error},
                       {"message", message}};
    if (conflict != ConflictPolicy::Rename)
        result["conflict"] = conflictPolicyName(conflict);
    return result;
}

// 日期：2026-11-04；锁文件名只由已验证的服务生成任务 UUID 组成，禁止路径或用户提供文件名。
TaskLease::TaskLease(QUuid task, QUuid owner, const QString &path)
    : task_(task), owner_(owner), path_(path), lock_(path) {
    lock_.setStaleLockTime(0);
    lock_.tryLock(0);
}

// 日期：2026-11-04；QLockFile 归还所有权；进程崩溃后的锁依原生进程身份判定，不按任务年龄删除。
TaskLease::~TaskLease() = default;

// 日期：2026-11-05；身份状态根先安全创建空数据库，SQLite 日志继承受限文件权限。
TaskStore::TaskStore(PrivateStore &store, bool control)
    : store_(store), connection_(QUuid::createUuid().toString()), cacheCredit_(1024, control) {
    // 日期：2026-11-04；同进程线程先串行初始化，避免 Windows 锁文件探测句柄与解锁删除竞争。
    static QMutex initializationMutex;
    QMutexLocker initializationGuard(&initializationMutex);
    QLockFile initialization(QDir(store.directory()).filePath("tasks-init.lock"));
    initialization.setStaleLockTime(0);
    lockInitialization(initialization);
    if (!store.exists("tasks.sqlite"))
        store.write("tasks.sqlite", {});
    if (store.validateFile("tasks.sqlite") > MaxMetadataBytes)
        throw Error(ExitCode::Disk, QStringLiteral("任务库超过磁盘预算"), "task");
    database_ = QSqlDatabase::addDatabase("QSQLITE", connection_);
    try {
        database_.setDatabaseName(QDir(store.directory()).filePath("tasks.sqlite"));
        if (!database_.open())
            throw Error(ExitCode::Disk, QStringLiteral("无法打开持久任务库"), "task");
        execute(database_, "PRAGMA busy_timeout=2000");
        execute(database_, "PRAGMA page_size=4096");
        execute(database_, "PRAGMA max_page_count=65536");
        cacheCredit_.configure(database_);
        execute(database_, "PRAGMA temp_store=FILE");
        execute(database_, "PRAGMA journal_mode=DELETE");
        execute(database_, "PRAGMA journal_size_limit=8388608");
        execute(database_, "PRAGMA synchronous=FULL");
        QSqlQuery version(database_);
        if (!version.exec("PRAGMA user_version") || !version.next() || version.value(0).toInt() > 1)
            throw Error(ExitCode::Config, QStringLiteral("任务库版本不受支持"), "task");
        version.finish();
        Transaction transaction(database_);
        execute(database_, "CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, owner TEXT NOT "
                           "NULL, request TEXT NOT NULL, "
                           "requesthash BLOB NOT NULL, spec BLOB NOT NULL, state TEXT NOT NULL, "
                           "desired TEXT NOT NULL, revision INTEGER NOT NULL, "
                           "manifest BLOB NOT NULL, total INTEGER NOT NULL, entries INTEGER NOT "
                           "NULL, processed INTEGER NOT NULL, error INTEGER NOT NULL, "
                           "message TEXT NOT NULL, updated TEXT NOT NULL, UNIQUE(owner,request))");
        execute(database_, "CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner)");
        execute(database_, "PRAGMA user_version=1");
        transaction.commit();
    } catch (...) {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
        throw;
    }
}

// 日期：2026-11-04；不隐式恢复或改写提交阶段；重新执行前由调用者持有任务租约并核对磁盘证据。
TaskStore::~TaskStore() {
    database_.close();
    database_ = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection_);
}

// 日期：2026-11-05；仅已开放策略可创建任务；非默认使用版本二，默认旧摘要保持，并发数可调整。
TransferTask TaskStore::create(const QUuid &owner, const QUuid &request, const QString &direction,
                               const QString &share, const QString &relative, const QString &root,
                               const QByteArray &uploadManifest, ConflictPolicy conflict) {
    const auto ownerId = uuid(owner);
    const auto requestId = uuid(request);
    validateShareName(share);
    if (!relative.isEmpty())
        validateRelativePath(relative);
    if ((direction != "upload" && direction != "download") || !QDir::isAbsolutePath(root) ||
        (direction == "upload" && uploadManifest.size() != 32) ||
        (direction == "download" && !uploadManifest.isEmpty()))
        throw Error(ExitCode::Config, QStringLiteral("任务创建参数或上传内容身份无效"), "task");
    checkedConflictPolicy(conflictPolicyName(conflict));
    const auto spec = next::encodeControl(
        {{"version", conflict == ConflictPolicy::Rename ? 1 : 2},
         {"direction", direction},
         {"share", share},
         {"path", relative},
         {"root", QDir::cleanPath(root)},
         {"uploadManifest", QString::fromLatin1(uploadManifest.toHex())},
         {"conflict",
          conflict == ConflictPolicy::Rename ? "keep-both" : conflictPolicyName(conflict)}});
    const auto hash = QCryptographicHash::hash(spec, QCryptographicHash::Sha256);
    Transaction transaction(database_);
    QSqlQuery previous(database_);
    previous.prepare("SELECT " + Columns + " FROM tasks WHERE owner=? AND request=?");
    previous.addBindValue(ownerId);
    previous.addBindValue(requestId);
    checked(previous);
    if (previous.next()) {
        if (previous.value(13).toByteArray() != hash)
            throw Error(ExitCode::Integrity, QStringLiteral("同一请求 ID 已绑定不同参数或内容"),
                        "task");
        const auto existing = row(previous);
        previous.finish();
        transaction.commit();
        return existing;
    }
    previous.finish();
    QSqlQuery count(database_);
    count.prepare(
        "SELECT COUNT(*),COALESCE(SUM(CASE WHEN owner=? THEN 1 ELSE 0 END),0) FROM tasks");
    count.addBindValue(ownerId);
    checked(count);
    if (!count.next() || count.value(0).toInt() >= 1024 || count.value(1).toInt() >= 128)
        throw Error(ExitCode::Permission, QStringLiteral("持久任务数量已达上限，需管理已有任务"),
                    "task");
    count.finish();
    const auto id = QUuid::createUuid();
    QSqlQuery insert(database_);
    insert.prepare("INSERT INTO tasks VALUES(?,?,?,?,?,'scanning','',1,?,0,0,0,0,'',?)");
    insert.addBindValue(uuid(id));
    insert.addBindValue(ownerId);
    insert.addBindValue(requestId);
    insert.addBindValue(hash);
    insert.addBindValue(spec);
    insert.addBindValue(QByteArray(""));
    insert.addBindValue(QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
    checked(insert);
    insert.finish();
    transaction.commit();
    return task(owner, id);
}

// 日期：2026-11-04；不存在和不属于当前主体统一拒绝，避免枚举其他主体任务。
TransferTask TaskStore::task(const QUuid &owner, const QUuid &id) const {
    QSqlQuery query(database_);
    query.prepare("SELECT " + Columns + " FROM tasks WHERE owner=? AND id=?");
    query.addBindValue(uuid(owner));
    query.addBindValue(uuid(id));
    checked(query);
    if (!query.next())
        throw Error(ExitCode::Permission, QStringLiteral("任务不存在或无权访问"), "task");
    return row(query);
}

// 日期：2026-11-04；持有租约不会长期持有数据库事务，其他连接仍可查询或提交停止请求。
std::unique_ptr<TaskLease> TaskStore::acquire(const QUuid &owner, const QUuid &id) const {
    auto lease = tryAcquire(owner, id);
    if (!lease)
        throw Error(ExitCode::Permission, QStringLiteral("同一任务已有活动执行者，请查询或重试"),
                    "task");
    return lease;
}

// 日期：2026-11-04；游标仅是当前主体的顺序边界；每条仍由查询所属条件和记录完整性约束。
QJsonObject TaskStore::page(const QUuid &owner, quint64 after) const {
    if (after > static_cast<quint64>(std::numeric_limits<qint64>::max()))
        throw Error(ExitCode::Config, QStringLiteral("任务分页序号无效"), "task");
    QSqlQuery query(database_);
    query.prepare("SELECT " + Columns +
                  ",rowid FROM tasks WHERE owner=? AND rowid>? ORDER BY rowid LIMIT 101");
    query.addBindValue(uuid(owner));
    query.addBindValue(static_cast<qlonglong>(after));
    checked(query);
    QJsonArray entries;
    int bytes = 1024;
    bool more = false;
    quint64 last = after;
    while (query.next()) {
        const auto task = row(query).publicInfo();
        const auto size = QJsonDocument(task).toJson(QJsonDocument::Compact).size() + 1;
        if (entries.size() == 100 || bytes + size > next::ControlLimit) {
            more = true;
            break;
        }
        entries.append(task);
        bytes += size;
        last = query.value(14).toULongLong();
    }
    return {{"tasks", entries}, {"after", QString::number(last)}, {"more", more}};
}

// 日期：2026-11-04；只在原生跨进程锁成功后返回有效租约，不凭数据库状态推断进程是否存活。
std::unique_ptr<TaskLease> TaskStore::tryAcquire(const QUuid &owner, const QUuid &id) const {
    task(owner, id);
    std::unique_ptr<TaskLease> lease(
        new TaskLease(id, owner, QDir(store_.directory()).filePath("task-" + uuid(id) + ".lock")));
    if (!lease->lock_.isLocked())
        return {};
    return lease;
}

// 日期：2026-11-04；锁对象不能由调用方自行构造；每次写状态仍核对其有效锁定状态。
void TaskStore::verifyLease(const TaskLease &lease) const {
    if (!lease.lock_.isLocked() || lease.owner_.isNull() || lease.task_.isNull() ||
        lease.path_ != QDir(store_.directory()).filePath("task-" + uuid(lease.task_) + ".lock"))
        throw Error(ExitCode::Permission, QStringLiteral("任务执行所有权无效"), "task");
}

// 日期：2026-11-04；更新规范计数和修订号，私有根路径始终留在原创建 spec 中。
void TaskStore::save(const TransferTask &task) const {
    if (task.revision >= static_cast<quint64>(std::numeric_limits<qint64>::max()))
        throw Error(ExitCode::Integrity, QStringLiteral("任务修订号已耗尽"), "task");
    QSqlQuery update(database_);
    update.prepare("UPDATE tasks SET "
                   "state=?,desired=?,revision=?,manifest=?,total=?,entries=?,processed=?,error=?,"
                   "message=?,updated=? WHERE id=? AND owner=?");
    update.addBindValue(task.state);
    update.addBindValue(task.desired.isNull() ? QString("") : task.desired);
    update.addBindValue(static_cast<qlonglong>(task.revision));
    update.addBindValue(task.manifest.isNull() ? QByteArray("") : task.manifest);
    update.addBindValue(task.total);
    update.addBindValue(task.entries);
    update.addBindValue(task.processed);
    update.addBindValue(task.error);
    update.addBindValue(task.message.isNull() ? QString("") : task.message);
    update.addBindValue(QDateTime::currentDateTimeUtc().toString(Qt::ISODate));
    update.addBindValue(uuid(task.id));
    update.addBindValue(uuid(task.owner));
    checked(update);
    if (update.numRowsAffected() != 1)
        throw Error(ExitCode::Integrity, QStringLiteral("任务更新未持久应用"), "task");
}

// 日期：2026-11-04；上传还须与创建时强身份一致，下载首次扫描绑定后确认重试不重新扫描。
TransferTask TaskStore::bindManifest(const TaskLease &lease, const QJsonObject &summary) {
    verifyLease(lease);
    const auto sha = QByteArray::fromHex(summary["sha256"].toString().toLatin1());
    const auto total =
        static_cast<qint64>(next::decimal(summary["bytes"], std::numeric_limits<qint64>::max()));
    const auto entries = static_cast<qint64>(next::decimal(summary["entries"], 10000000));
    if (summary["version"] != 1 || summary["blockBytes"] != QString::number(StrongBlockBytes) ||
        !entries || sha.size() != 32 || summary["sha256"] != QString::fromLatin1(sha.toHex()))
        throw Error(ExitCode::Integrity, QStringLiteral("任务强清单总计无效"), "task");
    Transaction transaction(database_);
    auto current = task(lease.owner_, lease.task_);
    if (!current.manifest.isEmpty()) {
        if (current.manifest != sha || current.total != total || current.entries != entries)
            throw Error(ExitCode::Integrity, QStringLiteral("任务已绑定其他强清单"), "task");
    } else {
        if (current.state != "scanning" || !current.desired.isEmpty())
            throw Error(ExitCode::Config, QStringLiteral("任务当前状态不能绑定清单"), "task");
        QSqlQuery spec(database_);
        spec.prepare("SELECT spec FROM tasks WHERE id=?");
        spec.addBindValue(uuid(current.id));
        checked(spec);
        if (!spec.next())
            throw Error(ExitCode::Integrity, QStringLiteral("任务创建记录丢失"), "task");
        const auto creation = next::parseControl(spec.value(0).toByteArray());
        spec.finish();
        if (current.direction == "upload" &&
            creation["uploadManifest"] != QString::fromLatin1(sha.toHex()))
            throw Error(ExitCode::Integrity, QStringLiteral("上传清单与创建内容身份不符"), "task");
        current.manifest = sha;
        current.total = total;
        current.entries = entries;
        current.state = "queued";
        ++current.revision;
        save(current);
    }
    transaction.commit();
    return current;
}

// 日期：2026-11-05；禁止绑定清单后重扫；提交中结果未知必须核对证据，不能归为普通失败。
TransferTask TaskStore::advance(const TaskLease &lease, quint64 revision, const QString &state,
                                qint64 processed, int error, const QString &message) {
    verifyLease(lease);
    Transaction transaction(database_);
    auto current = task(lease.owner_, lease.task_);
    if (current.revision != revision)
        throw Error(ExitCode::Config, QStringLiteral("任务修订已变化，请重新查询"), "task");
    if (!permitted(current.state, state) || (state == "scanning" && !current.manifest.isEmpty()) ||
        processed < 0 || processed > current.total ||
        (state != "checking" && processed < current.processed) || message.toUtf8().size() > 1024 ||
        error < 0 || error > 7 || (state == "failed" && !error) || (state != "failed" && error) ||
        ((state == "verifying" || state == "committing" || state == "completed") &&
         processed != current.total) ||
        ((state == "transferring" || state == "verifying" || state == "committing" ||
          state == "completed") &&
         current.manifest.isEmpty()) ||
        (current.desired == "cancel" && state != "cancelling" && state != "cancelled" &&
         state != "failed") ||
        (current.desired == "pause" &&
         (state == "transferring" || state == "verifying" || state == "committing")))
        throw Error(ExitCode::Config, QStringLiteral("任务状态转换、进度或停止请求冲突"), "task");
    current.state = state;
    current.processed = processed;
    current.error = error;
    current.message = message;
    if (state == "checking" || terminal(state))
        current.desired.clear();
    ++current.revision;
    save(current);
    transaction.commit();
    return current;
}

// 日期：2026-11-05；未扫描的排队任务允许暂停；请求停止仍须执行者确认，提交中不可撤销。
TransferTask TaskStore::requestStop(const QUuid &owner, const QUuid &id, bool pause) {
    Transaction transaction(database_);
    auto current = task(owner, id);
    if (current.state == "committing")
        throw Error(ExitCode::Config, QStringLiteral("任务已进入提交阶段，请查询最终结果"), "task");
    if (pause && current.manifest.isEmpty() && current.state != "queued" &&
        !terminal(current.state))
        throw Error(ExitCode::Config,
                    QStringLiteral("扫描尚未完成，当前可取消或等待清单完成后暂停"), "task");
    if (!terminal(current.state) && current.desired != "cancel" &&
        !(pause && (current.state == "paused" || current.state == "cancelling"))) {
        current.desired = pause ? "pause" : "cancel";
        ++current.revision;
        save(current);
    }
    transaction.commit();
    return current;
}
} // namespace dukto

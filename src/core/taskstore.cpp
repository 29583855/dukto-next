#include "taskstore.h"
#include "auth.h"
#include "error.h"
#include "files.h"
#include "protocol.h"
#include "strongmanifest.h"
#include "transferaccounting.h"

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
                        "processed,error,message,requesthash,accounting";

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

// 日期：2026-11-06；计量必须绑定任务总计及策略；旧复制策略不能出现跳过或丢弃结果。
TransferAccounting checkedAccounting(const TransferTask &task, const QJsonObject &snapshot) {
    if (task.manifest.size() != 32 || task.entries <= 0)
        throw Error(ExitCode::Integrity, QStringLiteral("任务计量尚未绑定强清单"), "task");
    TransferAccounting meter(task.total, static_cast<quint64>(task.entries));
    meter.accept(snapshot);
    if (task.conflict != ConflictPolicy::Skip &&
        (snapshot["skippedBytes"] != "0" || snapshot["discardedBytes"] != "0" ||
         snapshot["skippedFiles"] != "0" || snapshot["skippedDirectories"] != "0"))
        throw Error(ExitCode::Integrity, QStringLiteral("任务策略不允许跳过处置计量"), "task");
    return meter;
}

// 日期：2026-11-06；总字节到达不代表条目已提交；显式计量必须归结全部空文件及目录后才进入终阶段。
bool accountingComplete(const TransferTask &task) {
    if (task.accounting.isEmpty())
        return !task.accountingRequired;
    const auto &value = task.accounting;
    return value["copiedFiles"].toString().toULongLong() +
               value["copiedDirectories"].toString().toULongLong() +
               value["skippedFiles"].toString().toULongLong() +
               value["skippedDirectories"].toString().toULongLong() ==
           static_cast<quint64>(task.entries);
}

// 日期：2026-11-06；旧规范保持；版本三任务必须具备绑定计量，丢失或降级证据一律拒绝。
TransferTask row(const QSqlQuery &query) {
    const auto encoded = query.value(3).toByteArray();
    const auto spec = next::parseControl(encoded);
    const bool keepBoth = spec["version"] == 1 && spec["conflict"] == "keep-both";
    const bool failConflict = spec["version"] == 2 && spec["conflict"] == "fail";
    const bool overwriteConflict = spec["version"] == 2 && spec["conflict"] == "overwrite";
    const bool explicitAccounting =
        spec["version"] == 3 && spec.size() == 8 && spec["progress"] == "disposition-v1" &&
        QStringList{"rename", "fail", "overwrite", "skip"}.contains(spec["conflict"].toString());
    if ((!keepBoth && !failConflict && !overwriteConflict && !explicitAccounting) ||
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
    result.accountingRequired = explicitAccounting;
    result.conflict = explicitAccounting && spec["conflict"] == "skip" ? ConflictPolicy::Skip
                      : keepBoth ? ConflictPolicy::Rename
                                 : checkedConflictPolicy(spec["conflict"].toString());
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
    const auto accounting = query.value(14).toByteArray();
    if (result.accountingRequired && ((result.manifest.isEmpty() && !accounting.isEmpty()) ||
                                      (!result.manifest.isEmpty() && accounting.isEmpty())))
        throw Error(ExitCode::Integrity, QStringLiteral("任务必需计量证据缺失或未绑定"), "task");
    if (!accounting.isEmpty()) {
        result.accounting = next::parseControl(accounting);
        const auto meter = checkedAccounting(result, result.accounting);
        if (meter.handled() != result.processed ||
            ((result.state == "verifying" || result.state == "committing" ||
              result.state == "completed") &&
             !accountingComplete(result)))
            throw Error(ExitCode::Integrity, QStringLiteral("持久任务计量与状态不同"), "task");
    }
    validateShareName(result.share);
    if (!result.relative.isEmpty())
        validateRelativePath(result.relative);
    return result;
}
} // namespace

// 日期：2026-11-06；旧格式保持；版本三另列计量版本及实际复制/跳过/接收，不输出本地根。
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
    if (accountingRequired)
        result["accountingVersion"] = 1;
    if (!accounting.isEmpty()) {
        for (const auto &key :
             QStringList{"copiedBytes", "skippedBytes", "discardedBytes", "copiedFiles",
                         "copiedDirectories", "skippedFiles", "skippedDirectories"})
            result[key] = accounting[key];
        result["receivedBytes"] = accounting["bytes"];
        result["confirmedBytes"] = accounting["confirmed"];
        result["restoredBytes"] = accounting["restored"];
        result["handledBytes"] = QString::number(processed);
    }
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

// 日期：2026-11-07；事务迁移计量与过期凭据表；已有版本不重写文件头，旧记录及修订保持。
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
        if (!version.exec("PRAGMA user_version") || !version.next() ||
            version.value(0).toInt() < 0 || version.value(0).toInt() > 3)
            throw Error(ExitCode::Config, QStringLiteral("任务库版本不受支持"), "task");
        const auto schema = version.value(0).toInt();
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
        if (schema < 2) {
            execute(database_, "ALTER TABLE tasks ADD COLUMN accounting BLOB NOT NULL DEFAULT X''");
            // 日期：2026-11-06；只在实际迁移时设置版本，已有版本查询不能改写SQLite文件头。
        }
        if (schema < 3) {
            execute(database_, "CREATE TABLE task_expiry(id TEXT PRIMARY KEY,owner TEXT NOT NULL,"
                               "revision INTEGER NOT NULL,started TEXT NOT NULL)");
            execute(database_, "PRAGMA user_version=3");
        }
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

// 日期：2026-11-06；内部显式处置任务绑定版本三与计量契约，默认仍拒绝skip且保持旧幂等规范。
TransferTask TaskStore::create(const QUuid &owner, const QUuid &request, const QString &direction,
                               const QString &share, const QString &relative, const QString &root,
                               const QByteArray &uploadManifest, ConflictPolicy conflict,
                               bool dispositionAccounting) {
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
    // 日期：2026-11-06；公开skip仍禁止创建无必需计量的旧任务，重试也不得降级。
    if (conflict == ConflictPolicy::Skip && !dispositionAccounting)
        throw Error(ExitCode::Config, QStringLiteral("跳过任务必须使用完整处置计量"), "conflict");
    QJsonObject creation{{"version", dispositionAccounting                ? 3
                                     : conflict == ConflictPolicy::Rename ? 1
                                                                          : 2},
                         {"direction", direction},
                         {"share", share},
                         {"path", relative},
                         {"root", QDir::cleanPath(root)},
                         {"uploadManifest", QString::fromLatin1(uploadManifest.toHex())},
                         {"conflict", !dispositionAccounting && conflict == ConflictPolicy::Rename
                                          ? "keep-both"
                                          : conflictPolicyName(conflict)}};
    if (dispositionAccounting)
        creation["progress"] = "disposition-v1";
    const auto spec = next::encodeControl(creation);
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
    insert.prepare("INSERT INTO tasks(id,owner,request,requesthash,spec,state,desired,revision,"
                   "manifest,total,entries,processed,error,message,updated) "
                   "VALUES(?,?,?,?,?,'scanning','',1,?,0,0,0,0,'',?)");
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

// 日期：2026-11-06；分页游标使用固定rowid列，增加计量列后仍按所属主体及控制帧预算返回。
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
        last = query.value(15).toULongLong();
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

// 日期：2026-11-06；状态、修订及固定计量一起更新，私有根始终留在原创建spec中。
void TaskStore::save(const TransferTask &task) const {
    if (task.revision >= static_cast<quint64>(std::numeric_limits<qint64>::max()))
        throw Error(ExitCode::Integrity, QStringLiteral("任务修订号已耗尽"), "task");
    QSqlQuery update(database_);
    update.prepare("UPDATE tasks SET "
                   "state=?,desired=?,revision=?,manifest=?,total=?,entries=?,processed=?,error=?,"
                   "message=?,updated=?,accounting=? WHERE id=? AND owner=?");
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
    update.addBindValue(task.accounting.isEmpty() ? QByteArray("")
                                                  : next::encodeControl(task.accounting));
    update.addBindValue(uuid(task.id));
    update.addBindValue(uuid(task.owner));
    checked(update);
    if (update.numRowsAffected() != 1)
        throw Error(ExitCode::Integrity, QStringLiteral("任务更新未持久应用"), "task");
}

// 日期：2026-11-06；首次绑定强清单时为版本三初始化必需零计量，上传仍校验创建时身份。
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
        if (current.accountingRequired)
            current.accounting =
                TransferAccounting(total, static_cast<quint64>(entries)).snapshot();
        current.state = "queued";
        ++current.revision;
        save(current);
    }
    transaction.commit();
    return current;
}

// 日期：2026-11-06；显式任务禁止数字进度绕过计量；checking将必需快照归零，全部条目归结才可提交。
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
    if (!current.accounting.isEmpty()) {
        if (state == "checking") {
            if (processed != 0)
                throw Error(ExitCode::Config, QStringLiteral("重新核验必须清零本轮计量"), "task");
            current.accounting = current.accountingRequired
                                     ? TransferAccounting(current.total, current.entries).snapshot()
                                     : QJsonObject{};
        } else if (processed != current.processed ||
                   ((state == "verifying" || state == "committing" || state == "completed") &&
                    !accountingComplete(current))) {
            throw Error(ExitCode::Config, QStringLiteral("任务进度须与已持久处置计量一致"), "task");
        }
    }
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

// 日期：2026-11-06；固定快照与逻辑处理量在同一FULL同步事务更新，失败保留旧修订和进度。
TransferTask TaskStore::recordAccounting(const TaskLease &lease, quint64 revision,
                                         const QJsonObject &snapshot) {
    verifyLease(lease);
    Transaction transaction(database_);
    auto current = task(lease.owner_, lease.task_);
    if (current.revision != revision || current.state != "transferring" ||
        !current.desired.isEmpty())
        throw Error(ExitCode::Config, QStringLiteral("当前任务修订、状态或停止请求不允许更新计量"),
                    "task");
    auto meter = checkedAccounting(
        current, current.accounting.isEmpty()
                     ? TransferAccounting(current.total, current.entries).snapshot()
                     : current.accounting);
    meter.accept(snapshot);
    checkedAccounting(current, snapshot);
    if (meter.handled() < current.processed)
        throw Error(ExitCode::Integrity, QStringLiteral("任务逻辑处理进度不能回退"), "task");
    current.accounting = snapshot;
    current.processed = meter.handled();
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

// 日期：2026-11-07；暂停/中断保留7天，失败/取消保留30天，完成或提交不确定任务不参与。
QJsonObject TaskStore::expiryInfo(const TaskLease &lease, const QDateTime &now) const {
    if (!store_.maintenance() || !now.isValid() || now.timeSpec() != Qt::UTC)
        throw Error(ExitCode::Config, QStringLiteral("过期维护需要独占状态根及UTC时钟"), "cleanup");
    verifyLease(lease);
    const auto current = task(lease.owner_, lease.task_);
    if (current.direction != "upload" || current.manifest.size() != 32)
        throw Error(ExitCode::Config, QStringLiteral("当前入口只清理已绑定清单的服务器上传任务"),
                    "cleanup");
    QSqlQuery expiry(database_);
    expiry.prepare("SELECT owner,revision,started FROM task_expiry WHERE id=?");
    expiry.addBindValue(uuid(current.id));
    checked(expiry);
    if (expiry.next()) {
        const auto started = QDateTime::fromString(expiry.value(2).toString(), Qt::ISODate);
        if (expiry.value(0).toString() != uuid(current.owner) ||
            expiry.value(1).toULongLong() != current.revision || !started.isValid() ||
            started.timeSpec() != Qt::UTC ||
            (current.state != "failed" && current.state != "cancelled"))
            throw Error(ExitCode::Integrity, QStringLiteral("过期凭据与原任务不同"), "cleanup");
        return {{"eligible", true}, {"expired", true}, {"startedUtc", expiry.value(2).toString()}};
    }
    QSqlQuery updated(database_);
    updated.prepare("SELECT updated FROM tasks WHERE id=? AND owner=?");
    updated.addBindValue(uuid(current.id));
    updated.addBindValue(uuid(current.owner));
    checked(updated);
    if (!updated.next())
        throw Error(ExitCode::Integrity, QStringLiteral("过期维护任务记录丢失"), "cleanup");
    const auto text = updated.value(0).toString();
    const auto date = QDateTime::fromString(text, Qt::ISODate);
    if (!date.isValid() || date.timeSpec() != Qt::UTC || date.toString(Qt::ISODate) != text)
        throw Error(ExitCode::Integrity, QStringLiteral("任务更新时间无效"), "cleanup");
    const int days = current.state == "paused" || current.state == "interrupted" ? 7
                     : current.state == "failed" || current.state == "cancelled" ? 30
                                                                                 : 0;
    return {{"eligible", days > 0 && date <= now.addDays(-days)},
            {"expired", false},
            {"updatedUtc", text},
            {"retentionDays", days}};
}

// 日期：2026-11-07；修订绑定的永久凭据保留原请求幂等性；重启续清理不会重新激活任务。
void TaskStore::expire(const TaskLease &lease, const QDateTime &now) {
    Transaction transaction(database_);
    const auto info = expiryInfo(lease, now);
    if (!info["eligible"].toBool())
        throw Error(ExitCode::Config, QStringLiteral("任务尚未过保留期或状态不允许清理"),
                    "cleanup");
    if (info["expired"].toBool()) {
        transaction.commit();
        return;
    }
    auto current = task(lease.owner_, lease.task_);
    if (current.state == "paused" || current.state == "interrupted") {
        current.state = "failed";
        current.desired.clear();
        current.error = static_cast<int>(ExitCode::Cancelled);
        current.message = QStringLiteral("恢复保留期已过，临时正文进入过期清理");
        ++current.revision;
        save(current);
    }
    QSqlQuery insert(database_);
    insert.prepare("INSERT INTO task_expiry VALUES(?,?,?,?)");
    insert.addBindValue(uuid(current.id));
    insert.addBindValue(uuid(current.owner));
    insert.addBindValue(static_cast<qlonglong>(current.revision));
    insert.addBindValue(now.toString(Qt::ISODate));
    checked(insert);
    transaction.commit();
}
} // namespace dukto

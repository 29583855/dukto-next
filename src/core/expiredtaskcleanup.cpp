#include "expiredtaskcleanup.h"
#include "error.h"
#include "protocol.h"
#include "sourcefile.h"
#include "strongmanifest.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QRegularExpression>
#include <QSqlError>
#include <QSqlQuery>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-07；清理错误不回显SQL、凭据或目标绝对路径。
void execute(QSqlQuery &query) {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("过期清理数据库操作失败"), "cleanup");
}

// 日期：2026-11-07；固定语句仅用于FULL同步清理日志，不拼接任何文件名或远端值。
void sql(QSqlDatabase database, const QString &statement) {
    QSqlQuery query(database);
    if (!query.exec(statement))
        throw Error(ExitCode::Disk, QStringLiteral("过期清理事务失败"), "cleanup");
}

class Journal final {
  public:
    // 日期：2026-11-07；先验证普通私有库与旁路文件，再打开；预览只读且不补建缺失日志。
    Journal(PrivateStore &store, const QString &name, bool writable)
        : connection_(QUuid::createUuid().toString()) {
        qint64 bytes = store.validateFile(name);
        for (const auto &suffix : QStringList{"-journal", "-wal", "-shm"}) {
            if (store.exists(name + suffix)) {
                const auto size = store.validateFile(name + suffix);
                if (size > MaxMetadataBytes - bytes)
                    throw Error(ExitCode::Disk, QStringLiteral("接收日志及旁路超出预算"),
                                "cleanup");
                bytes += size;
                if (suffix != "-journal")
                    throw Error(ExitCode::Config, QStringLiteral("清理不接受WAL模式接收库"),
                                "cleanup");
            }
        }
        if (bytes > MaxMetadataBytes)
            throw Error(ExitCode::Disk, QStringLiteral("接收日志超出预算"), "cleanup");
        database_ = QSqlDatabase::addDatabase("QSQLITE", connection_);
        try {
            if (!writable)
                database_.setConnectOptions("QSQLITE_OPEN_READONLY");
            database_.setDatabaseName(QDir(store.directory()).filePath(name));
            if (!database_.open())
                throw Error(ExitCode::Disk, QStringLiteral("无法打开原接收日志"), "cleanup");
            credit_.configure(database_);
            sql(database_, "PRAGMA busy_timeout=1000");
            sql(database_, "PRAGMA temp_store=FILE");
            if (writable) {
                sql(database_, "PRAGMA synchronous=FULL");
                sql(database_, "PRAGMA max_page_count=65536");
            } else
                sql(database_, "PRAGMA query_only=ON");
        } catch (...) {
            close();
            throw;
        }
    }
    // 日期：2026-11-07；所有局部查询销毁后关闭连接，不手动删除SQLite旁路文件。
    ~Journal() {
        close();
    }
    // 日期：2026-11-07；连接只供当前维护线程使用，不跨线程共享。
    QSqlDatabase database() const {
        return database_;
    }

  private:
    // 日期：2026-11-07；构造失败同样归还注册连接和全局缓存授信。
    void close() {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
    }
    QString connection_;
    SqliteCacheCredit credit_{1024};
    QSqlDatabase database_;
};

// 日期：2026-11-07；按原生根身份及完整策略绑定原日志，不能凭同名目录推测所有权。
void verifyBinding(QSqlDatabase database, const TransferTask &task, const QString &root,
                   const QByteArray &identity) {
    QJsonObject expected{{"version", 1},
                         {"task", task.id.toString(QUuid::WithoutBraces)},
                         {"manifest", QString::fromLatin1(task.manifest.toHex())},
                         {"root", root},
                         {"rootIdentity", QString::fromLatin1(identity)}};
    if (task.conflict != ConflictPolicy::Rename) {
        expected["version"] = task.conflict == ConflictPolicy::Skip ? 4 : 2;
        expected["conflict"] = conflictPolicyName(task.conflict);
    }
    QSqlQuery query(database);
    query.prepare("SELECT CASE WHEN length(spec)<=65536 THEN spec ELSE NULL END FROM binding");
    execute(query);
    if (!query.next() || query.value(0).toByteArray() != next::encodeControl(expected) ||
        query.next() || query.lastError().isValid())
        throw Error(ExitCode::Integrity, QStringLiteral("过期接收根、任务或清单身份不同"),
                    "cleanup");
    query.finish();
    query.prepare("SELECT 1 FROM files WHERE id<=0 LIMIT 1");
    execute(query);
    if (query.next() || query.lastError().isValid())
        throw Error(ExitCode::Integrity, QStringLiteral("接收日志存在无效条目序号"), "cleanup");
    query.finish();
    query.prepare("SELECT 1 FROM files WHERE state='committing' LIMIT 1");
    execute(query);
    if (query.next())
        throw Error(ExitCode::Config,
                    QStringLiteral("接收存在未确定提交结果，必须保留并先恢复核验"), "cleanup");
    if (query.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("无法核对接收提交状态"), "cleanup");
    query.finish();
    query.prepare("SELECT 1 FROM directories WHERE state='committing' LIMIT 1");
    execute(query);
    if (query.next())
        throw Error(ExitCode::Config,
                    QStringLiteral("目录存在未确定提交结果，必须保留并先恢复核验"), "cleanup");
    if (query.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("无法核对目录提交状态"), "cleanup");
}

struct Candidate {
    quint64 id = 0;
    QString temporary;
    QByteArray native;
    QByteArray proof;
    QString state;
};

// 日期：2026-11-07；每次只读取一行，清单规范、随机临时名、目标父目录及原生身份全部核对。
Candidate candidate(const QSqlQuery &query, StrongManifest &manifest) {
    Candidate value;
    value.id = query.value(0).toULongLong();
    if (query.value(0).toLongLong() <= 0)
        throw Error(ExitCode::Integrity, QStringLiteral("过期接收条目序号无效"), "cleanup");
    const auto entry = manifest.entry(value.id);
    const auto bytes = query.value(1).toByteArray();
    const auto spec = next::parseControl(bytes);
    const auto original = validateRelativePath(spec["path"].toString());
    const auto target = validateRelativePath(query.value(3).toString());
    value.temporary = validateRelativePath(query.value(2).toString());
    value.native = query.value(4).toByteArray();
    value.state = query.value(5).toString();
    const auto confirmed = query.value(6).toLongLong();
    static const QRegularExpression temporary("\\A\\.dukto-([0-9a-f-]{36})\\.part\\z");
    const auto match = temporary.match(QFileInfo(value.temporary).fileName());
    const QUuid random(match.captured(1));
    if (entry.directory || spec.size() != 2 || spec["entry"] != entry.publicInfo() ||
        bytes != next::encodeControl(spec) || !match.hasMatch() || random.isNull() ||
        random.toString(QUuid::WithoutBraces) != match.captured(1) ||
        QFileInfo(value.temporary).path() != QFileInfo(original).path() ||
        QFileInfo(target).path() != QFileInfo(original).path() || confirmed < 0 ||
        confirmed > entry.bytes || value.native.size() > 128 ||
        !QStringList{"planned", "receiving", "completed"}.contains(value.state) ||
        (value.state == "planned" ? !value.native.isEmpty() : value.native.isEmpty()))
        throw Error(ExitCode::Integrity, QStringLiteral("过期临时项证据无效，保留原文件"),
                    "cleanup");
    value.proof = next::encodeControl(
        {{"id", QString::number(value.id)},
         {"temporary", value.temporary},
         {"native", QString::fromLatin1(value.native.toHex())},
         {"sourceSpecSha256",
          QString::fromLatin1(
              QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex())}});
    return value;
}

// 日期：2026-11-07；先FULL提交不可变删除意图；清理后确认丢失可依据同一身份安全重入。
bool intention(QSqlDatabase database, const Candidate &value, bool create) {
    if (create) {
        sql(database, "BEGIN IMMEDIATE");
        try {
            QSqlQuery insert(database);
            insert.prepare("INSERT OR IGNORE INTO expired_cleanup VALUES(?,?,0)");
            insert.addBindValue(static_cast<qlonglong>(value.id));
            insert.addBindValue(value.proof);
            execute(insert);
            sql(database, "COMMIT");
        } catch (...) {
            database.rollback();
            throw;
        }
    }
    QSqlQuery query(database);
    query.prepare("SELECT CASE WHEN length(spec)<=65536 THEN spec ELSE NULL END,cleaned,"
                  "typeof(cleaned) FROM expired_cleanup WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(value.id));
    execute(query);
    if (!query.next())
        return false;
    if (query.value(0).toByteArray() != value.proof || query.value(2) != "integer" ||
        (query.value(1).toInt() != 0 && query.value(1).toInt() != 1))
        throw Error(ExitCode::Integrity, QStringLiteral("临时清理意图与原条目不符"), "cleanup");
    return query.value(1).toInt() == 1;
}
} // namespace

// 日期：2026-11-07；固定内存逐项维护；预览最多100条，执行不缓存全部条目且随时可安全取消。
QJsonObject cleanupExpiredUpload(PrivateStore &store, const QUuid &owner, const QUuid &id,
                                 const QDateTime &now, bool apply, quint64 after,
                                 const std::function<void()> &check) {
    if (!store.maintenance() || (apply && after) ||
        after > static_cast<quint64>(std::numeric_limits<qint64>::max()))
        throw Error(ExitCode::Config, QStringLiteral("清理需要独占维护且执行不接受分页游标"),
                    "cleanup");
    TaskStore tasks(store);
    auto lease = tasks.acquire(owner, id);
    auto info = tasks.expiryInfo(*lease, now);
    const auto task = tasks.task(owner, id);
    const auto key = id.toString(QUuid::WithoutBraces);
    const auto name = "receive-" + key + ".sqlite";
    QLockFile receiveLock(QDir(store.directory()).filePath(name + ".lock"));
    receiveLock.setStaleLockTime(0);
    if (!receiveLock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("接收日志仍有活动执行者"), "cleanup");
    const auto root = task.relative.isEmpty() ? task.root : resolveInside(task.root, task.relative);
#ifdef Q_OS_WIN
    NativeDirectoryLock heldRoot(root, false);
#else
    PosixDirectory heldRoot(root, false);
#endif
    StrongManifest manifest(store, "manifest-" + key + ".sqlite", false, check);
    const auto summary = manifest.summary();
    if (summary["sha256"] != QString::fromLatin1(task.manifest.toHex()) ||
        summary["entries"] != QString::number(task.entries) ||
        summary["bytes"] != QString::number(task.total))
        throw Error(ExitCode::Integrity, QStringLiteral("过期任务清单与原任务不同"), "cleanup");
    Journal journal(store, name, apply);
    auto database = journal.database();
    verifyBinding(database, task, root, heldRoot.identity());
    QSqlQuery table(database);
    table.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='expired_cleanup'");
    execute(table);
    bool hasIntents = table.next();
    table.finish();
    if (apply) {
        if (check)
            check();
        tasks.expire(*lease, now);
        sql(database, "CREATE TABLE IF NOT EXISTS expired_cleanup(id INTEGER PRIMARY KEY,"
                      "spec BLOB NOT NULL,cleaned INTEGER NOT NULL CHECK(cleaned IN(0,1)))");
        hasIntents = true;
    }
    QJsonArray entries;
    quint64 cursor = after;
    quint64 cleaned = 0;
    quint64 preserved = 0;
    bool more = false;
    for (;;) {
        if (check)
            check();
#ifndef Q_OS_WIN
        heldRoot.verify();
#endif
        QSqlQuery query(database);
        query.prepare(
            "SELECT id,CASE WHEN length(spec)<=65536 THEN spec ELSE NULL END,"
            "CASE WHEN length(CAST(temporary AS BLOB))<=4096 THEN temporary ELSE NULL END,"
            "CASE WHEN length(CAST(target AS BLOB))<=4096 THEN target ELSE NULL END,"
            "CASE WHEN length(native)<=128 THEN native ELSE NULL END,"
            "CASE WHEN length(state)<=16 THEN state ELSE NULL END,confirmed "
            "FROM files WHERE id>? ORDER BY id LIMIT 1");
        query.addBindValue(static_cast<qlonglong>(cursor));
        execute(query);
        if (!query.next()) {
            if (query.lastError().isValid())
                throw Error(ExitCode::Disk, QStringLiteral("过期条目读取失败"), "cleanup");
            break;
        }
        if (!apply && entries.size() == 100) {
            more = true;
            break;
        }
        const auto value = candidate(query, manifest);
        query.finish();
        cursor = value.id;
        QString action = value.state == "receiving" ? "temporary" : "preserved-" + value.state;
        if (value.state == "receiving") {
            const bool done = hasIntents && intention(database, value, apply);
            if (done)
                action = "already-cleaned";
            else if (apply) {
                if (check)
                    check();
#ifndef Q_OS_WIN
                heldRoot.verify();
#endif
                removeReceivedTemporary(resolveInside(root, value.temporary), value.native, false);
                if (check)
                    check();
                sql(database, "BEGIN IMMEDIATE");
                try {
                    QSqlQuery update(database);
                    update.prepare(
                        "UPDATE expired_cleanup SET cleaned=1 WHERE id=? AND spec=? AND cleaned=0");
                    update.addBindValue(static_cast<qlonglong>(value.id));
                    update.addBindValue(value.proof);
                    execute(update);
                    if (update.numRowsAffected() != 1)
                        throw Error(ExitCode::Integrity, QStringLiteral("临时清理确认记录丢失"),
                                    "cleanup");
                    sql(database, "COMMIT");
                } catch (...) {
                    database.rollback();
                    throw;
                }
                action = "cleaned";
            }
            if (action == "already-cleaned" || action == "cleaned")
                ++cleaned;
        } else
            ++preserved;
        if (!apply)
            entries.append(QJsonObject{{"id", QString::number(value.id)},
                                       {"action", action},
                                       {"temporary", value.temporary}});
    }
    if (apply)
        info = tasks.expiryInfo(*lease, now);
    info["eventVersion"] = 1;
    info["event"] = "expired-cleanup";
    info["taskId"] = key;
    info["applied"] = apply;
    info["after"] = QString::number(cursor);
    info["more"] = more;
    info["entries"] = entries;
    info["cleanedFiles"] = QString::number(cleaned);
    info["preservedFiles"] = QString::number(preserved);
    info["message"] = apply ? QStringLiteral("过期临时文件维护结束，任务及幂等记录保留")
                            : QStringLiteral("过期临时文件预览，未终止任务或删除正文");
    return info;
}
} // namespace dukto

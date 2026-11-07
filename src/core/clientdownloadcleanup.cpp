#include "clientdownloadcleanup.h"
#include "directorycleanup.h"
#include "error.h"
#include "files.h"
#include "protocol.h"
#include "sourcefile.h"
#include "sqlitecache.h"
#include "sqliteruntime.h"
#include "strongmanifest.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QLockFile>
#include <QRegularExpression>
#include <QSqlError>
#include <QSqlQuery>
#include <QStringList>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-07；清理错误不回显数据库诊断、服务器凭据或本地绝对路径。
void execute(QSqlQuery &query) {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("客户端清理数据库操作失败"), "cleanup");
}

// 日期：2026-11-07；SQL均为固定本地语句，不将任务 ID、路径或日志内容拼入命令。
void sql(QSqlDatabase database, const QString &statement) {
    QSqlQuery query(database);
    if (!query.exec(statement))
        throw Error(ExitCode::Disk, QStringLiteral("客户端清理事务失败"), "cleanup");
}

class Journal final {
  public:
    // 日期：2026-11-07；先检查私有库及旁路大小，再以有界缓存打开只读预览或FULL同步执行。
    Journal(PrivateStore &store, const QString &name, bool writable)
        : connection_(QUuid::createUuid().toString()) {
        qint64 bytes = store.validateFile(name);
        for (const auto &suffix : QStringList{"-journal", "-wal", "-shm"}) {
            if (!store.exists(name + suffix))
                continue;
            const auto size = store.validateFile(name + suffix);
            if (size > MaxMetadataBytes - bytes)
                throw Error(ExitCode::Disk, QStringLiteral("接收日志及旁路超出预算"), "cleanup");
            bytes += size;
            if (suffix != "-journal")
                throw Error(ExitCode::Config, QStringLiteral("清理不接受WAL模式接收库"), "cleanup");
        }
        if (bytes > MaxMetadataBytes)
            throw Error(ExitCode::Disk, QStringLiteral("接收日志超出预算"), "cleanup");
        database_ = addSqliteDatabase(connection_);
        try {
            if (!writable)
                database_.setConnectOptions("QSQLITE_OPEN_READONLY");
            database_.setDatabaseName(QDir(store.directory()).filePath(name));
            if (!database_.open())
                throw Error(ExitCode::Disk, QStringLiteral("无法打开原接收日志"), "cleanup");
            credit_.configure(database_);
            sql(database_, "PRAGMA busy_timeout=1000");
            QSqlQuery journalMode(database_);
            if (!journalMode.exec("PRAGMA journal_mode") || !journalMode.next() ||
                journalMode.value(0).toString().compare(QStringLiteral("delete"),
                                                        Qt::CaseInsensitive) != 0 ||
                journalMode.next() || journalMode.lastError().isValid())
                throw Error(ExitCode::Config, QStringLiteral("清理不接受WAL模式接收库"), "cleanup");
            journalMode.finish();
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

    // 日期：2026-11-07；关闭连接并释放SQLite授信，不删除或更名用户任务日志。
    ~Journal() {
        close();
    }

    // 日期：2026-11-07；数据库连接仅供当前维护线程短期查询，不跨线程共享。
    QSqlDatabase database() const {
        return database_;
    }

  private:
    // 日期：2026-11-07；销毁查询后归还连接注册项，构造失败也走同一清理路径。
    void close() {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
    }

    QString connection_;
    SqliteCacheCredit credit_{1024};
    QSqlDatabase database_;
};

struct Binding {
    QString root;
    QByteArray rootIdentity;
    ConflictPolicy conflict = ConflictPolicy::Rename;
};

// 日期：2026-11-07；精确核对版本化任务绑定与原生目标根，不能由调用者替换清理目的地。
Binding verifyBinding(QSqlDatabase database, const QUuid &task, const QJsonObject &summary) {
    QSqlQuery query(database);
    if (!query.exec("SELECT CASE WHEN length(spec)<=65536 THEN spec ELSE NULL END FROM binding"))
        throw Error(ExitCode::Integrity, QStringLiteral("接收日志绑定架构无效"), "cleanup");
    if (!query.next())
        throw Error(ExitCode::Integrity, QStringLiteral("接收日志缺少任务绑定"), "cleanup");
    const auto bytes = query.value(0).toByteArray();
    const auto value = next::parseControl(bytes);
    Binding result;
    result.root = value["root"].toString();
    result.rootIdentity = value["rootIdentity"].toString().toLatin1();
    const auto key = task.toString(QUuid::WithoutBraces);
    const auto manifest = summary["sha256"].toString();
    const auto version = value["version"].toInt(-1);
    QJsonObject expected{{"version", version},
                         {"task", key},
                         {"manifest", manifest},
                         {"root", result.root},
                         {"rootIdentity", QString::fromLatin1(result.rootIdentity)}};
    if (version == 1) {
        result.conflict = ConflictPolicy::Rename;
    } else if (version == 2) {
        const auto policy = value["conflict"].toString();
        if (policy != "fail" && policy != "overwrite")
            throw Error(ExitCode::Integrity, QStringLiteral("下载任务冲突策略绑定无效"), "cleanup");
        result.conflict = checkedConflictPolicy(policy);
        expected["conflict"] = policy;
    } else if (version == 3 || version == 4) {
        result.conflict = ConflictPolicy::Skip;
        expected["version"] = version;
        expected["conflict"] = "skip";
    } else
        throw Error(ExitCode::Integrity, QStringLiteral("下载任务绑定版本无效"), "cleanup");
    if (value != expected || bytes != next::encodeControl(expected) || query.next() ||
        query.lastError().isValid() || !QDir::isAbsolutePath(result.root) ||
        QDir::cleanPath(result.root) != result.root || result.rootIdentity.isEmpty() ||
        value["manifest"] != manifest)
        throw Error(ExitCode::Integrity, QStringLiteral("接收日志任务、清单或目标根身份不同"),
                    "cleanup");
    query.finish();
    return result;
}

struct Candidate {
    quint64 id = 0;
    QString temporary;
    QByteArray native;
    QByteArray spec;
    QString state;
    qint64 confirmed = 0;
};

// 日期：2026-11-07；逐行核对强清单映射、同目录随机临时名、原生身份和有限状态。
Candidate candidate(const QSqlQuery &query, StrongManifest &manifest) {
    Candidate result;
    result.id = query.value(0).toULongLong();
    if (!result.id || query.value(0).toLongLong() <= 0)
        throw Error(ExitCode::Integrity, QStringLiteral("下载文件序号无效"), "cleanup");
    const auto entry = manifest.entry(result.id);
    result.spec = query.value(1).toByteArray();
    const auto spec = next::parseControl(result.spec);
    const auto original = validateRelativePath(spec["path"].toString());
    result.temporary = validateRelativePath(query.value(2).toString());
    const auto target = validateRelativePath(query.value(3).toString());
    result.native = query.value(4).toByteArray();
    result.state = query.value(5).toString();
    result.confirmed = query.value(6).toLongLong();
    static const QRegularExpression pattern("\\A\\.dukto-([0-9a-f-]{36})\\.part\\z");
    const auto match = pattern.match(QFileInfo(result.temporary).fileName());
    const QUuid random(match.captured(1));
    const QStringList states{"planned", "receiving", "committing", "completed", "skipped"};
    const bool nativeRequired =
        result.state == "receiving" || result.state == "committing" || result.state == "completed";
    if (query.value(7) != "integer" || query.value(8) != "blob" || query.value(9) != "text" ||
        query.value(10) != "text" || query.value(11) != "blob" || query.value(12) != "text" ||
        query.value(13) != "integer" || entry.directory || spec.size() != 2 ||
        spec["entry"] != entry.publicInfo() || result.spec != next::encodeControl(spec) ||
        !match.hasMatch() || random.isNull() ||
        random.toString(QUuid::WithoutBraces) != match.captured(1) ||
        QFileInfo(result.temporary).path() != QFileInfo(original).path() ||
        QFileInfo(target).path() != QFileInfo(original).path() || result.native.size() > 128 ||
        !states.contains(result.state) || (nativeRequired && result.native.isEmpty()) ||
        (result.state == "planned" && !result.native.isEmpty()) || result.confirmed < 0 ||
        result.confirmed > entry.bytes || (result.state == "planned" && result.confirmed != 0) ||
        ((result.state == "committing" || result.state == "completed") &&
         result.confirmed != entry.bytes) ||
        (result.state == "skipped" && result.confirmed != 0))
        throw Error(ExitCode::Integrity, QStringLiteral("下载临时项证据无效，保留原文件"),
                    "cleanup");
    return result;
}

// 日期：2026-11-07；身份验证、文件删除、检查点清除和状态回退可在任意崩溃点重复执行。
void clean(QSqlDatabase database, const Candidate &value, const QString &root,
           const std::function<void()> &check) {
    if (check)
        check();
    removeReceivedTemporary(resolveInside(root, value.temporary), value.native, false);
    if (check)
        check();
    sql(database, "BEGIN IMMEDIATE");
    try {
        QSqlQuery blocks(database);
        blocks.prepare("DELETE FROM blocks WHERE file=?");
        blocks.addBindValue(static_cast<qlonglong>(value.id));
        execute(blocks);
        QSqlQuery update(database);
        update.prepare("UPDATE files SET native=?,state='planned',confirmed=0 "
                       "WHERE id=? AND spec=? AND native=? AND state='receiving'");
        update.addBindValue(QByteArray(""));
        update.addBindValue(static_cast<qlonglong>(value.id));
        update.addBindValue(value.spec);
        update.addBindValue(value.native);
        execute(update);
        if (update.numRowsAffected() != 1)
            throw Error(ExitCode::Integrity, QStringLiteral("下载清理状态在维护中发生变化"),
                        "cleanup");
        if (check)
            check();
        sql(database, "COMMIT");
    } catch (...) {
        database.rollback();
        throw;
    }
}
} // namespace

// 日期：2026-11-07；独占维护一个下载任务，分页预览或逐项回收中断正文并保留其余历史。
QJsonObject cleanupClientDownload(PrivateStore &store, const QUuid &task, bool apply, quint64 after,
                                  const std::function<void()> &check) {
    if (!store.maintenance() || task.isNull() || (apply && after) ||
        after > static_cast<quint64>(std::numeric_limits<qint64>::max()))
        throw Error(ExitCode::Config, QStringLiteral("客户端清理需要有效任务和独占维护"),
                    "cleanup");
    const auto key = task.toString(QUuid::WithoutBraces);
    const auto manifestName = "download-" + key + ".sqlite";
    const auto receiveName = "receive-" + key + ".sqlite";
    if (!store.exists(manifestName) || !store.exists(receiveName))
        throw Error(ExitCode::Config, QStringLiteral("本机没有该下载任务的可清理接收记录"),
                    "cleanup");
    QLockFile receiveLock(QDir(store.directory()).filePath(receiveName + ".lock"));
    receiveLock.setStaleLockTime(0);
    if (!receiveLock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("接收日志仍有活动执行者"), "cleanup");
    StrongManifest manifest(store, manifestName, false, check);
    manifest.verify(check);
    const auto summary = manifest.summary();
    Journal journal(store, receiveName, apply);
    auto database = journal.database();
    const auto binding = verifyBinding(database, task, summary);
#ifdef Q_OS_WIN
    NativeDirectoryLock root(binding.root, false);
#else
    PosixDirectory root(binding.root, false);
#endif
    if (root.identity() != binding.rootIdentity)
        throw Error(ExitCode::Integrity, QStringLiteral("下载目标目录已被替换，保留原数据"),
                    "cleanup");
    QSqlQuery schema(database);
    schema.prepare(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN('files','blocks') "
        "ORDER BY name");
    execute(schema);
    QStringList tables;
    while (schema.next())
        tables.append(schema.value(0).toString());
    if (schema.lastError().isValid() || tables != QStringList{"blocks", "files"})
        throw Error(ExitCode::Integrity, QStringLiteral("下载接收日志架构不完整"), "cleanup");
    schema.finish();
    QJsonArray entries;
    quint64 cursor = after;
    quint64 cleaned = 0;
    quint64 preserved = 0;
    quint64 cleanedDirectories = 0;
    quint64 preservedDirectories = 0;
    bool more = false;
    for (;;) {
        if (check)
            check();
#ifndef Q_OS_WIN
        root.verify();
#endif
        QSqlQuery query(database);
        query.prepare(receiveCleanupEntryQuery());
        query.addBindValue(static_cast<qlonglong>(cursor));
        query.addBindValue(static_cast<qlonglong>(cursor));
        execute(query);
        if (!query.next()) {
            if (query.lastError().isValid())
                throw Error(ExitCode::Disk, QStringLiteral("下载文件记录读取失败"), "cleanup");
            break;
        }
        if (!apply && entries.size() == 100) {
            more = true;
            break;
        }
        if (query.value(14).toBool()) {
            const auto value = readCleanupDirectory(query, manifest);
            query.finish();
            cursor = value.id;
            const auto directoryCheck = [&]() {
                // 日期：2026-11-07；目录意图、删除及确认期间持续核对取消和固定接收根。
                if (check)
                    check();
#ifndef Q_OS_WIN
                root.verify();
#endif
            };
            const auto action = cleanupReceiveDirectory(
                database, value, binding.root, binding.rootIdentity, apply, true,
                binding.conflict == ConflictPolicy::Skip, manifest, directoryCheck);
            if (action == "cleaned" || action == "already-cleaned")
                ++cleanedDirectories;
            else
                ++preservedDirectories;
            if (!apply)
                entries.append(QJsonObject{{"id", QString::number(value.id)},
                                           {"kind", "directory"},
                                           {"action", action},
                                           {"temporary", value.temporary}});
            continue;
        }
        const auto value = candidate(query, manifest);
        query.finish();
        cursor = value.id;
        QString action;
        if (value.state == "receiving" && binding.conflict != ConflictPolicy::Skip) {
            if (apply) {
#ifndef Q_OS_WIN
                root.verify();
#endif
                clean(database, value, binding.root, check);
                ++cleaned;
                action = "cleaned";
            } else
                action = "temporary";
        } else {
            ++preserved;
            action =
                value.state == "receiving" ? "preserved-skip-policy" : "preserved-" + value.state;
        }
        if (!apply)
            entries.append(QJsonObject{{"id", QString::number(value.id)},
                                       {"kind", "file"},
                                       {"action", action},
                                       {"temporary", value.temporary}});
    }
    QJsonObject result{
        {"eventVersion", 1},
        {"event", "client-download-cleanup"},
        {"taskId", key},
        {"applied", apply},
        {"after", QString::number(cursor)},
        {"more", more},
        {"entries", entries},
        {"cleanedFiles", QString::number(cleaned)},
        {"preservedFiles", QString::number(preserved)},
        {"cleanedDirectories", QString::number(cleanedDirectories)},
        {"preservedDirectories", QString::number(preservedDirectories)},
        {"message", apply ? QStringLiteral("客户端下载临时项清理结束；任务与已发布项目保留")
                          : QStringLiteral("客户端下载清理预览；未删除文件或修改任务日志")}};
    return result;
}
} // namespace dukto

#include "directorycleanup.h"
#include "error.h"
#include "files.h"
#include "nativecommit.h"
#include "protocol.h"
#include "strongmanifest.h"

#include <QCryptographicHash>
#include <QFileInfo>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSqlError>
#include <QStringList>
#include <QUuid>

namespace dukto {
namespace {
// 日期：2026-11-07；固定维护SQL失败立即中止，不能把失败查询当成没有删除意图。
void execute(QSqlQuery &query) {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("目录清理日志操作失败"), "cleanup");
}

// 日期：2026-11-07；仅执行本文件固定事务语句，不拼接任务标识、路径或用户数据。
void sql(QSqlDatabase database, const QString &statement) {
    QSqlQuery query(database);
    if (!query.exec(statement))
        throw Error(ExitCode::Disk, QStringLiteral("目录清理事务失败"), "cleanup");
}

struct Intention {
    bool exists = false;
    bool cleaned = false;
};

// 日期：2026-11-07；嵌套临时目录只能位于原接收器已完成预约的父目录，父目录替换后停止维护。
QByteArray verifyParent(QSqlDatabase database, const DirectoryCleanupEntry &entry,
                        const QString &root, const QByteArray &rootIdentity) {
    const auto separator = entry.source.lastIndexOf('/');
    if (separator < 0)
        return rootIdentity;
    QSqlQuery query(database);
    query.prepare("SELECT CASE WHEN length(CAST(target AS BLOB))<=4096 THEN target ELSE NULL END,"
                  "CASE WHEN length(native)<=128 THEN native ELSE NULL END,"
                  "CASE WHEN length(state)<=16 THEN state ELSE NULL END,"
                  "typeof(target),typeof(native) FROM directories WHERE source=?");
    query.addBindValue(entry.source.left(separator));
    execute(query);
    if (!query.next() || query.value(2) != "completed" || query.value(3) != "text" ||
        query.value(4) != "blob" || query.value(1).toByteArray().isEmpty())
        throw Error(ExitCode::Integrity, QStringLiteral("目录清理父目录预约无效"), "cleanup");
    const auto parent = validateRelativePath(query.value(0).toString());
    const auto native = query.value(1).toByteArray();
    if (query.next() || query.lastError().isValid() ||
        QFileInfo(entry.temporary).path() != parent ||
        receivedDirectoryIdentity(resolveInside(root, parent)) != native)
        throw Error(ExitCode::Integrity, QStringLiteral("目录清理父目录已被替换"), "cleanup");
    return native;
}

// 日期：2026-11-07；只读预览不创建表；已有意图必须完整绑定本次原目录与维护方式。
Intention intention(QSqlDatabase database, quint64 id, const QByteArray &proof) {
    QSqlQuery query(database);
    query.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='directory_cleanup'");
    execute(query);
    if (!query.next()) {
        if (query.lastError().isValid())
            throw Error(ExitCode::Disk, QStringLiteral("无法核对目录清理架构"), "cleanup");
        return {};
    }
    query.finish();
    query.prepare("SELECT CASE WHEN length(spec)<=65536 THEN spec ELSE NULL END,"
                  "CASE WHEN typeof(cleaned)='integer' THEN cleaned ELSE NULL END,"
                  "typeof(spec),typeof(cleaned) FROM directory_cleanup WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(id));
    execute(query);
    if (!query.next()) {
        if (query.lastError().isValid())
            throw Error(ExitCode::Disk, QStringLiteral("无法核对目录清理意图"), "cleanup");
        return {};
    }
    if (query.value(0).toByteArray() != proof || query.value(2) != "blob" ||
        query.value(3) != "integer" ||
        (query.value(1).toLongLong() != 0 && query.value(1).toLongLong() != 1))
        throw Error(ExitCode::Integrity, QStringLiteral("目录清理意图与原记录不符"), "cleanup");
    const bool cleaned = query.value(1).toLongLong() == 1;
    if (query.next() || query.lastError().isValid())
        throw Error(ExitCode::Integrity, QStringLiteral("目录清理意图重复或读取失败"), "cleanup");
    Intention result;
    result.exists = true;
    result.cleaned = cleaned;
    return result;
}

// 日期：2026-11-07；删除前单独FULL持久保存身份及目标，不能在目录消失后猜测其是否已发布。
void saveIntention(QSqlDatabase database, quint64 id, const QByteArray &proof) {
    sql(database, "CREATE TABLE IF NOT EXISTS directory_cleanup(id INTEGER PRIMARY KEY,"
                  "spec BLOB NOT NULL,cleaned INTEGER NOT NULL CHECK(cleaned IN(0,1)))");
    sql(database, "BEGIN IMMEDIATE");
    try {
        QSqlQuery query(database);
        query.prepare("INSERT OR IGNORE INTO directory_cleanup VALUES(?,?,0)");
        query.addBindValue(static_cast<qlonglong>(id));
        query.addBindValue(proof);
        execute(query);
        const auto saved = intention(database, id, proof);
        if (!saved.exists || saved.cleaned)
            throw Error(ExitCode::Integrity, QStringLiteral("目录删除意图状态不同"), "cleanup");
        sql(database, "COMMIT");
    } catch (...) {
        database.rollback();
        throw;
    }
}

// 日期：2026-11-07；目录删除后原子复位客户端下载预约，或保留服务器幂等清理确认。
void confirm(QSqlDatabase database, const DirectoryCleanupEntry &entry, const QByteArray &proof,
             bool resetForResume, const std::function<void()> &check) {
    sql(database, "BEGIN IMMEDIATE");
    try {
        QSqlQuery query(database);
        if (resetForResume) {
            query.prepare("UPDATE directories SET native=?,state='planned' "
                          "WHERE id=? AND spec=? AND temporary=? AND target=? "
                          "AND native=? AND state='committing'");
            query.addBindValue(QByteArray(""));
            query.addBindValue(static_cast<qlonglong>(entry.id));
            query.addBindValue(entry.spec);
            query.addBindValue(entry.temporary);
            query.addBindValue(entry.target);
            query.addBindValue(entry.native);
            execute(query);
            if (query.numRowsAffected() != 1)
                throw Error(ExitCode::Integrity, QStringLiteral("目录预约在维护中已变化"),
                            "cleanup");
            query.prepare("DELETE FROM directory_cleanup WHERE id=? AND spec=? AND cleaned=0");
        } else {
            query.prepare("UPDATE directory_cleanup SET cleaned=1 WHERE id=? AND spec=? "
                          "AND cleaned=0");
        }
        query.addBindValue(static_cast<qlonglong>(entry.id));
        query.addBindValue(proof);
        execute(query);
        if (query.numRowsAffected() != 1)
            throw Error(ExitCode::Integrity, QStringLiteral("目录清理确认丢失"), "cleanup");
        if (check)
            check();
        sql(database, "COMMIT");
    } catch (...) {
        database.rollback();
        throw;
    }
}
} // namespace

// 日期：2026-11-07；两个主键索引按序合并，每个字段有字节界限，文件/目录共用after参数。
QString receiveCleanupEntryQuery() {
    return "SELECT id,CASE WHEN length(spec)<=65536 THEN spec ELSE NULL END,"
           "CASE WHEN length(CAST(temporary AS BLOB))<=4096 THEN temporary ELSE NULL END,"
           "CASE WHEN length(CAST(target AS BLOB))<=4096 THEN target ELSE NULL END,"
           "CASE WHEN length(native)<=128 THEN native ELSE NULL END,"
           "CASE WHEN length(state)<=16 THEN state ELSE NULL END,confirmed,"
           "typeof(id),typeof(spec),typeof(temporary),typeof(target),typeof(native),"
           "typeof(state),typeof(confirmed),0 AS directory,NULL AS source,NULL AS sourceType "
           "FROM files WHERE id>? UNION ALL "
           "SELECT id,CASE WHEN length(spec)<=65536 THEN spec ELSE NULL END,"
           "CASE WHEN length(CAST(temporary AS BLOB))<=4096 THEN temporary ELSE NULL END,"
           "CASE WHEN length(CAST(target AS BLOB))<=4096 THEN target ELSE NULL END,"
           "CASE WHEN length(native)<=128 THEN native ELSE NULL END,"
           "CASE WHEN length(state)<=16 THEN state ELSE NULL END,0,"
           "typeof(id),typeof(spec),typeof(temporary),typeof(target),typeof(native),"
           "typeof(state),'integer',1,"
           "CASE WHEN length(CAST(source AS BLOB))<=4096 THEN source ELSE NULL END,typeof(source) "
           "FROM directories WHERE id>? ORDER BY id LIMIT 1";
}

// 日期：2026-11-07；随机目录名和目标父路径必须与冻结清单映射一致，损坏记录不参与删除。
DirectoryCleanupEntry readCleanupDirectory(const QSqlQuery &query, StrongManifest &manifest) {
    DirectoryCleanupEntry result;
    result.id = query.value(0).toULongLong();
    if (!result.id || query.value(0).toLongLong() <= 0)
        throw Error(ExitCode::Integrity, QStringLiteral("目录清理序号无效"), "cleanup");
    const auto entry = manifest.entry(result.id);
    result.source = entry.relative;
    result.spec = query.value(1).toByteArray();
    const auto spec = next::parseControl(result.spec);
    const auto original = validateRelativePath(spec["path"].toString());
    result.temporary = validateRelativePath(query.value(2).toString());
    result.target = validateRelativePath(query.value(3).toString());
    result.native = query.value(4).toByteArray();
    result.state = query.value(5).toString();
    static const QRegularExpression pattern("\\A\\.dukto-([0-9a-f-]{36})\\.dir\\z");
    const auto match = pattern.match(QFileInfo(result.temporary).fileName());
    const QUuid random(match.captured(1));
    if (query.value(7) != "integer" || query.value(8) != "blob" || query.value(9) != "text" ||
        query.value(10) != "text" || query.value(11) != "blob" || query.value(12) != "text" ||
        query.value(16) != "text" || !entry.directory || query.value(15) != entry.relative ||
        spec.size() != 2 || spec["entry"] != entry.publicInfo() ||
        result.spec != next::encodeControl(spec) || !match.hasMatch() || random.isNull() ||
        random.toString(QUuid::WithoutBraces) != match.captured(1) ||
        QFileInfo(result.temporary).path() != QFileInfo(original).path() ||
        QFileInfo(result.target).path() != QFileInfo(original).path() ||
        result.native.size() > 128 ||
        !QStringList{"planned", "committing", "completed"}.contains(result.state) ||
        (result.state == "planned" ? !result.native.isEmpty() : result.native.isEmpty()))
        throw Error(ExitCode::Integrity, QStringLiteral("临时目录证据无效，保留原数据"), "cleanup");
    return result;
}

// 日期：2026-11-07；不递归、不按名字推断归属；已发布与复用目录保留，未知提交结果拒绝。
QString cleanupReceiveDirectory(QSqlDatabase database, const DirectoryCleanupEntry &entry,
                                const QString &root, const QByteArray &rootIdentity, bool apply,
                                bool resetForResume, bool skipPolicy,
                                const std::function<void()> &check) {
    if (entry.state != "committing")
        return "preserved-" + entry.state;
    if (skipPolicy)
        return "preserved-skip-policy";
    const auto checkpoint = [&]() {
        // 日期：2026-11-07；每个持久化与删除边界都重新检查取消、接收根及原父目录映射。
        if (check)
            check();
        return verifyParent(database, entry, root, rootIdentity);
    };
    checkpoint();
    const auto proof = next::encodeControl(
        {{"version", 1},
         {"id", QString::number(entry.id)},
         {"temporary", entry.temporary},
         {"target", entry.target},
         {"native", QString::fromLatin1(entry.native.toHex())},
         {"sourceSpecSha256",
          QString::fromLatin1(
              QCryptographicHash::hash(entry.spec, QCryptographicHash::Sha256).toHex())},
         {"mode", resetForResume ? "reset" : "expired"}});
    const auto saved = intention(database, entry.id, proof);
    if (saved.cleaned) {
        if (resetForResume)
            throw Error(ExitCode::Integrity, QStringLiteral("下载目录清理状态未原子复位"),
                        "cleanup");
        return "already-cleaned";
    }
    const auto temporary = resolveInside(root, entry.temporary);
    const auto observed = receivedDirectoryIdentity(temporary, checkpoint());
    if (!observed.isEmpty() && observed != entry.native)
        throw Error(ExitCode::Integrity, QStringLiteral("待清理目录已被替换"), "cleanup");
    if (observed.isEmpty()) {
        const auto destination = resolveInside(root, entry.target);
        if (QFileInfo(destination).isDir() &&
            receivedDirectoryIdentity(destination, checkpoint()) == entry.native)
            return "preserved-published";
        if (!saved.exists)
            throw Error(ExitCode::Config, QStringLiteral("目录提交结果未知，必须保留并先恢复核验"),
                        "cleanup");
    }
    if (!apply)
        return observed.isEmpty() ? "pending-confirmation" : "temporary";
    if (!saved.exists)
        saveIntention(database, entry.id, proof);
    // 日期：2026-11-07；操作系统只允许删除空目录，未知子文件、链接和外部新增内容均不会递归移除。
    removeReceivedTemporary(temporary, entry.native, true, checkpoint());
    checkpoint();
    confirm(database, entry, proof, resetForResume, checkpoint);
    return "cleaned";
}
} // namespace dukto

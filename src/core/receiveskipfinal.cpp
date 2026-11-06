#include "durablereceive.h"
#include "error.h"
#include "protocol.h"
#include "receiveskipproof.h"
#include "sourcefile.h"

#include <QFileInfo>
#include <QRegularExpression>
#include <QSqlError>
#include <QSqlQuery>

namespace dukto {
namespace {
// 日期：2026-11-05；原生身份采用有界小写十六进制，空身份只允许没有创建临时项的分支。
bool validNative(const QString &value, bool empty) {
    return (empty || !value.isEmpty()) && value.size() <= 1024 &&
           value == QString::fromLatin1(QByteArray::fromHex(value.toLatin1()).toHex());
}
} // namespace

// 日期：2026-11-06；共用有界记录核对原准备及接收意图，完成核验不得凭此执行清理。
QJsonObject ReceiveSkipProof::finalDecision(quint64 file) const {
    if (!finalSkipsEnabled_)
        return {};
    QSqlQuery query(database_);
    query.prepare("SELECT substr(spec,1,65537),cleaned FROM skip_final WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    if (!query.next()) {
        if (query.lastError().isValid())
            throw Error(ExitCode::Integrity, QStringLiteral("最终跳过证据读取失败"), "receive");
        return {};
    }
    const auto bytes = query.value(0).toByteArray();
    const auto cleaned = query.value(1).toString();
    const auto entry = manifest_.entry(file);
    const auto value = next::parseControl(bytes);
    const auto temporary = value["temporary"].toString();
    const auto native = value["temporaryNative"].toString();
    const auto targetNative = value["native"].toString();
    const QJsonObject expected{{"version", 1},
                               {"entry", entry.publicInfo()},
                               {"path", entry.relative},
                               {"action", "skip"},
                               {"skippedRoot", QString::number(file)},
                               {"native", targetNative},
                               {"temporary", temporary},
                               {"temporaryNative", native}};
    if (value != expected || bytes != next::encodeControl(expected) ||
        (cleaned != "0" && cleaned != "1") || !validNative(targetNative, false) ||
        !validNative(native, temporary.isEmpty()) || temporary.isEmpty() != native.isEmpty())
        throw Error(ExitCode::Integrity, QStringLiteral("最终跳过记录字段损坏"), "receive");
    query.finish();
    query.prepare("SELECT substr(spec,1,65537) FROM skip_decisions WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    const QJsonObject original{{"version", 1},           {"entry", entry.publicInfo()},
                               {"path", entry.relative}, {"action", "receive"},
                               {"skippedRoot", "0"},     {"native", ""}};
    if (!query.next() || query.value(0).toByteArray() != next::encodeControl(original))
        throw Error(ExitCode::Integrity, QStringLiteral("最终跳过缺少原接收准备决定"), "receive");
    query.finish();
    query.prepare(entry.directory ? "SELECT substr(spec,1,65537),substr(temporary,1,4097),"
                                    "substr(target,1,4097),substr(native,1,513),substr(state,1,33) "
                                    "FROM directories WHERE id=?"
                                  : "SELECT substr(spec,1,65537),substr(temporary,1,4097),"
                                    "substr(target,1,4097),substr(native,1,513),substr(state,1,33) "
                                    "FROM files WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    const bool found = query.next();
    if (temporary.isEmpty()) {
        if (found)
            throw Error(ExitCode::Integrity, QStringLiteral("最终跳过遗漏已有临时接收意图"),
                        "receive");
    } else {
        const auto spec =
            next::encodeControl({{"entry", entry.publicInfo()}, {"path", entry.relative}});
        if (!found || query.value(0).toByteArray() != spec ||
            query.value(1).toString() != temporary || query.value(2).toString() != entry.relative ||
            query.value(3).toByteArray().toHex() != native.toLatin1() ||
            !(entry.directory ? QStringList{"committing"} : QStringList{"receiving", "committing"})
                 .contains(query.value(4).toString()) ||
            validateRelativePath(temporary) != temporary ||
            QFileInfo(temporary).path() != QFileInfo(entry.relative).path() ||
            !QRegularExpression(entry.directory ? "\\A\\.dukto-[0-9a-f-]{36}\\.dir\\z"
                                                : "\\A\\.dukto-[0-9a-f-]{36}\\.part\\z")
                 .match(QFileInfo(temporary).fileName())
                 .hasMatch())
            throw Error(ExitCode::Integrity, QStringLiteral("最终跳过的临时项证据不匹配"),
                        "receive");
    }
    return value;
}

// 日期：2026-11-06；原接收执行者与只读核验使用同样的最终决定证明。
QJsonObject DurableReceive::finalSkipDecision(quint64 file) const {
    return ReceiveSkipProof(database_, manifest_, finalSkipsEnabled_).finalDecision(file);
}

// 日期：2026-11-06；历史准备不可变，共用最终证据仅把合法receive改为自身根skip。
QJsonObject ReceiveSkipProof::applyFinal(const StrongEntry &entry,
                                         const QJsonObject &decision) const {
    const auto final = finalDecision(entry.id);
    if (final.isEmpty())
        return decision;
    if (decision["action"] != "receive")
        throw Error(ExitCode::Integrity, QStringLiteral("最终跳过不能覆盖原跳过准备"), "receive");
    auto result = decision;
    result["action"] = "skip";
    result["skippedRoot"] = QString::number(entry.id);
    result["native"] = final["native"];
    return result;
}

// 日期：2026-11-05；最终决定先持久化；临时清理与恢复从不检查旧目标现在是否还存在。
DurableReceive::Preparation DurableReceive::commitLateSkip(quint64 file, const QString &temporary,
                                                           const QByteArray &native,
                                                           const std::function<void()> &check) {
    if (conflict_ != ConflictPolicy::Skip || !finalSkipsEnabled_ ||
        skipDecision(file)["action"] != "receive")
        throw Error(ExitCode::Integrity, QStringLiteral("项目不允许产生晚期跳过"), "receive");
    const auto entry = manifest_.entry(file);
    if (entry.directory && file + 1 != nextDecision_)
        throw Error(ExitCode::Integrity, QStringLiteral("目录后代准备之后不能改变父目录处置"),
                    "receive");
    verifyRoot();
    if (check)
        check();
    const auto path = resolveInside(root_, entry.relative, false);
    QString identity;
    std::unique_ptr<SourceFile> heldFile;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> heldDirectory;
#else
    std::unique_ptr<PosixDirectory> heldDirectory;
#endif
    const QFileInfo existing(path);
    if (entry.directory) {
        if (!existing.isDir() || !existing.isReadable())
            throw Error(ExitCode::Permission, QStringLiteral("晚期跳过目标不是可访问普通目录"),
                        "conflict");
#ifdef Q_OS_WIN
        heldDirectory.reset(new NativeDirectoryLock(path, false));
#else
        heldDirectory.reset(new PosixDirectory(path, false));
#endif
        identity = QString::fromLatin1(heldDirectory->identity().toHex());
    } else {
        if (!existing.isFile())
            throw Error(ExitCode::Permission, QStringLiteral("晚期跳过目标不是普通文件"),
                        "conflict");
        heldFile.reset(new SourceFile(path));
        identity = QString::fromLatin1(heldFile->objectIdentity().toHex());
    }
    // 日期：2026-11-05；文件源身份比接收身份多末尾冒号；自己的发布必须走copied恢复。
    const auto normalized = heldFile ? native + ':' : native;
    if (!native.isEmpty() && QByteArray::fromHex(identity.toLatin1()) == normalized)
        throw Error(ExitCode::Integrity, QStringLiteral("本任务已发布对象不得改判跳过"), "commit");
    const QJsonObject decision{{"version", 1},
                               {"entry", entry.publicInfo()},
                               {"path", entry.relative},
                               {"action", "skip"},
                               {"skippedRoot", QString::number(file)},
                               {"native", identity},
                               {"temporary", temporary},
                               {"temporaryNative", QString::fromLatin1(native.toHex())}};
    sql("BEGIN IMMEDIATE");
    try {
        QSqlQuery query(database_);
        query.prepare("INSERT INTO skip_final VALUES(?,?,?)");
        query.addBindValue(static_cast<qlonglong>(file));
        query.addBindValue(next::encodeControl(decision));
        query.addBindValue(temporary.isEmpty() ? 1 : 0);
        execute(query);
        finalSkipDecision(file);
        resolveFailure(file);
        if (check)
            check();
        verifyRoot();
        if (heldFile)
            heldFile->verifyObject();
#ifndef Q_OS_WIN
        if (heldDirectory)
            heldDirectory->verify();
#endif
        sql("COMMIT");
    } catch (...) {
        database_.rollback();
        throw;
    }
    if (check)
        check();
    cleanupFinalSkip(file, check);
    return {entry.relative, true, file};
}

// 日期：2026-11-05；提交后中断保留待清理记录；删除完成但确认丢失时可安全重试。
void DurableReceive::cleanupFinalSkip(quint64 file, const std::function<void()> &check) {
    const auto decision = finalSkipDecision(file);
    if (decision.isEmpty())
        return;
    QSqlQuery query(database_);
    query.prepare("SELECT cleaned FROM skip_final WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    if (!query.next())
        throw Error(ExitCode::Integrity, QStringLiteral("最终跳过清理记录丢失"), "receive");
    if (query.value(0).toInt() == 1)
        return;
    query.finish();
    if (check)
        check();
    verifyRoot();
    removeReceivedTemporary(resolveInside(root_, decision["temporary"].toString()),
                            QByteArray::fromHex(decision["temporaryNative"].toString().toLatin1()),
                            manifest_.entry(file).directory);
    if (check)
        check();
    verifyRoot();
    sql("BEGIN IMMEDIATE");
    try {
        query.prepare("UPDATE skip_final SET cleaned=1 WHERE id=? AND cleaned=0");
        query.addBindValue(static_cast<qlonglong>(file));
        execute(query);
        if (query.numRowsAffected() != 1)
            throw Error(ExitCode::Integrity, QStringLiteral("最终跳过清理状态损坏"), "receive");
        resolveFailure(file);
        sql("COMMIT");
    } catch (...) {
        database_.rollback();
        throw;
    }
}

// 日期：2026-11-05；逐页逐项核对包括非法首ID和孤立记录，不让无界字段或清单外项进入恢复。
void DurableReceive::verifyFinalSkips(const std::function<void()> &check) {
    QSqlQuery invalid(database_);
    invalid.prepare("SELECT id FROM skip_final WHERE id<=0 LIMIT 1");
    execute(invalid);
    if (invalid.next() || invalid.lastError().isValid())
        throw Error(ExitCode::Integrity, QStringLiteral("最终跳过存在非法序号"), "receive");
    quint64 cursor = 0;
    for (;;) {
        if (check)
            check();
        verifyRoot();
        QSqlQuery query(database_);
        query.setForwardOnly(true);
        query.prepare("SELECT id FROM skip_final WHERE id>? ORDER BY id LIMIT 100");
        query.addBindValue(static_cast<qlonglong>(cursor));
        execute(query);
        int rows = 0;
        while (query.next()) {
            if (query.value(0).toLongLong() <= 0 || query.value(0).toULongLong() >= nextDecision_)
                throw Error(ExitCode::Integrity, QStringLiteral("最终跳过不属于已有准备项"),
                            "receive");
            cursor = query.value(0).toULongLong();
            if (check)
                check();
            verifyRoot();
            finalSkipDecision(cursor);
            ++rows;
        }
        if (query.lastError().isValid())
            throw Error(ExitCode::Disk, QStringLiteral("最终跳过分页读取失败"), "receive");
        if (rows < 100)
            break;
    }
}
} // namespace dukto

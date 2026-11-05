#include "durablereceive.h"
#include "error.h"
#include "protocol.h"
#include "sourcefile.h"

#include <QFileInfo>
#include <QSqlError>
#include <QSqlQuery>

namespace dukto {
namespace {
// 日期：2026-11-05；当前项与磁盘父项共用有界规范验证，不能用损坏父字段传播子树跳过。
QJsonObject checkedDecision(const StrongEntry &entry, const QByteArray &source,
                            const QByteArray &bytes) {
    const auto value = next::parseControl(bytes);
    const auto action = value["action"].toString();
    const auto root = next::decimal(value["skippedRoot"], entry.id);
    const auto native = value["native"].toString();
    const bool skipped = action == "skip";
    const QJsonObject expected{
        {"version", 1},     {"entry", entry.publicInfo()},          {"path", entry.relative},
        {"action", action}, {"skippedRoot", QString::number(root)}, {"native", native}};
    if (source != entry.relative.toUtf8() || value != expected ||
        bytes != next::encodeControl(expected) || (!skipped && action != "receive") ||
        (!skipped && (root || !native.isEmpty())) ||
        (skipped && (!root || (root == entry.id) != !native.isEmpty())) || native.size() > 512 ||
        native != QString::fromLatin1(QByteArray::fromHex(native.toLatin1()).toHex()))
        throw Error(ExitCode::Integrity, QStringLiteral("持久接收决定字段损坏"), "receive");
    return value;
}
} // namespace

// 日期：2026-11-05；按唯一源索引核对父项及连续前置关系，不递归驻留整棵目录树。
QJsonObject DurableReceive::skipDecision(quint64 file) const {
    const auto entry = manifest_.entry(file);
    QSqlQuery query(database_);
    query.prepare("SELECT substr(CAST(source AS BLOB),1,4097),substr(spec,1,65537) "
                  "FROM skip_decisions WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    if (!query.next())
        throw Error(ExitCode::Integrity, QStringLiteral("清单项目缺少持久接收决定"), "receive");
    const auto value =
        checkedDecision(entry, query.value(0).toByteArray(), query.value(1).toByteArray());
    const bool skipped = value["action"] == "skip";
    const auto root = next::decimal(value["skippedRoot"], file);
    const int slash = entry.relative.lastIndexOf('/');
    if (slash < 0) {
        if (skipped && root != file)
            throw Error(ExitCode::Integrity, QStringLiteral("顶层跳过必须绑定自身"), "receive");
        return value;
    }
    query.finish();
    query.prepare("SELECT id,substr(CAST(source AS BLOB),1,4097),substr(spec,1,65537) "
                  "FROM skip_decisions WHERE source=?");
    query.addBindValue(entry.relative.left(slash));
    execute(query);
    if (!query.next() || query.value(0).toLongLong() <= 0 || query.value(0).toULongLong() >= file)
        throw Error(ExitCode::Integrity, QStringLiteral("接收决定缺少前置父目录"), "receive");
    const auto parentId = query.value(0).toULongLong();
    const auto parentEntry = manifest_.entry(parentId);
    const auto parent =
        checkedDecision(parentEntry, query.value(1).toByteArray(), query.value(2).toByteArray());
    const bool parentSkipped = parent["action"] == "skip";
    const auto parentRoot = next::decimal(parent["skippedRoot"], parentId);
    if (!parentEntry.directory || parentEntry.relative != entry.relative.left(slash) ||
        (parentSkipped &&
         (!skipped || root != parentRoot || !value["native"].toString().isEmpty())) ||
        (!parentSkipped && skipped && root != file))
        throw Error(ExitCode::Integrity, QStringLiteral("接收决定的子树跳过关系损坏"), "receive");
    return value;
}

// 日期：2026-11-05；已有决定逐页重验且不访问目标树，删除或替换旧目标不能改写历史跳过决定。
void DurableReceive::verifySkipDecisions(const std::function<void()> &check) {
    QSqlQuery invalid(database_);
    invalid.prepare("SELECT id FROM skip_decisions WHERE id<=0 LIMIT 1");
    execute(invalid);
    if (invalid.next() || invalid.lastError().isValid())
        throw Error(ExitCode::Integrity, QStringLiteral("接收决定存在非法序号"), "receive");
    const auto count = next::decimal(manifest_.summary()["entries"], 10000000);
    quint64 cursor = 0;
    for (;;) {
        if (check)
            check();
        verifyRoot();
        QSqlQuery query(database_);
        query.setForwardOnly(true);
        query.prepare("SELECT id FROM skip_decisions WHERE id>? ORDER BY id LIMIT 100");
        query.addBindValue(static_cast<qlonglong>(cursor));
        execute(query);
        int rows = 0;
        while (query.next()) {
            if (cursor >= count ||
                query.value(0).toLongLong() != static_cast<qlonglong>(cursor + 1))
                throw Error(ExitCode::Integrity, QStringLiteral("接收决定序号不连续"), "receive");
            if (check)
                check();
            verifyRoot();
            skipDecision(++cursor);
            ++rows;
        }
        if (query.lastError().isValid())
            throw Error(ExitCode::Disk, QStringLiteral("接收决定分页读取失败"), "receive");
        if (rows < 100)
            break;
    }
    nextDecision_ = cursor + 1;
}

// 日期：2026-11-05；先持久裁决再创建正文；整目录跳过只延续磁盘父索引，不枚举既有目标或驻留后代列表。
DurableReceive::Preparation
DurableReceive::prepareDisposition(quint64 file, const std::function<void()> &check) try {
    if (conflict_ != ConflictPolicy::Skip)
        return {prepareCopy(file, check), false, 0};
    verifyRoot();
    if (check)
        check();
    verifyRoot();
    const auto entry = manifest_.entry(file);
    QJsonObject decision;
    if (file < nextDecision_) {
        decision = skipDecision(file);
    } else {
        if (file != nextDecision_)
            throw Error(ExitCode::Integrity, QStringLiteral("接收准备必须按冻结清单顺序进行"),
                        "receive");
        quint64 skippedRoot = 0;
        QString native;
        const int slash = entry.relative.lastIndexOf('/');
        if (slash >= 0) {
            QSqlQuery parent(database_);
            parent.prepare("SELECT id FROM skip_decisions WHERE source=?");
            parent.addBindValue(entry.relative.left(slash));
            execute(parent);
            if (!parent.next() || parent.value(0).toLongLong() <= 0 ||
                parent.value(0).toULongLong() >= file)
                throw Error(ExitCode::Integrity, QStringLiteral("接收准备缺少父目录决定"),
                            "receive");
            const auto original = skipDecision(parent.value(0).toULongLong());
            if (original["action"] == "skip")
                skippedRoot = next::decimal(original["skippedRoot"], file);
        }
        std::unique_ptr<TargetReservation> reservation;
        std::unique_ptr<SourceFile> heldFile;
#ifdef Q_OS_WIN
        std::unique_ptr<NativeDirectoryLock> heldDirectory;
#else
        std::unique_ptr<PosixDirectory> heldDirectory;
#endif
        if (!skippedRoot) {
            const auto path = resolveInside(root_, entry.relative);
            reservation.reset(new TargetReservation(path));
            if (!reservation->acquired())
                throw Error(ExitCode::Permission, QStringLiteral("接收准备目标已有活动预约"),
                            "conflict");
            const QFileInfo existing(path);
            if (existing.exists()) {
                if (entry.directory) {
                    if (!existing.isDir() || !existing.isReadable())
                        throw Error(ExitCode::Permission,
                                    QStringLiteral("跳过目录目标类型或访问权限不符"), "conflict");
#ifdef Q_OS_WIN
                    heldDirectory.reset(new NativeDirectoryLock(path, false));
#else
                    heldDirectory.reset(new PosixDirectory(path, false));
#endif
                    native = QString::fromLatin1(heldDirectory->identity().toHex());
                    if (check)
                        check();
#ifndef Q_OS_WIN
                    heldDirectory->verify();
#endif
                } else {
                    if (!existing.isFile())
                        throw Error(ExitCode::Permission,
                                    QStringLiteral("跳过文件目标不是普通文件"), "conflict");
                    heldFile.reset(new SourceFile(path));
                    if (check)
                        check();
                    native = QString::fromLatin1(heldFile->objectIdentity().toHex());
                }
                skippedRoot = file;
            }
        }
        if (check)
            check();
        verifyRoot();
        decision = {{"version", 1},
                    {"entry", entry.publicInfo()},
                    {"path", entry.relative},
                    {"action", skippedRoot ? "skip" : "receive"},
                    {"skippedRoot", QString::number(skippedRoot)},
                    {"native", native}};
        sql("BEGIN IMMEDIATE");
        try {
            QSqlQuery query(database_);
            query.prepare("INSERT INTO skip_decisions VALUES(?,?,?)");
            query.addBindValue(static_cast<qlonglong>(file));
            query.addBindValue(entry.relative);
            query.addBindValue(next::encodeControl(decision));
            execute(query);
            resolveFailure(file);
            if (check)
                check();
            verifyRoot();
            if (heldFile)
                heldFile->verifyObject();
            if (heldDirectory) {
#ifndef Q_OS_WIN
                heldDirectory->verify();
#endif
                if (QString::fromLatin1(heldDirectory->identity().toHex()) != native)
                    throw Error(ExitCode::Integrity, QStringLiteral("跳过目录身份已变化"),
                                "receive");
            }
            sql("COMMIT");
        } catch (...) {
            database_.rollback();
            throw;
        }
        ++nextDecision_;
        if (check)
            check();
    }
    const bool skipped = decision["action"] == "skip";
    if (!skipped)
        prepareCopy(file, check);
    return {entry.relative, skipped, next::decimal(decision["skippedRoot"], file)};
} catch (const Error &error) {
    recordFailure(file, "prepare", error);
    throw;
}
} // namespace dukto

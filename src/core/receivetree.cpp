#include "durablereceive.h"
#include "error.h"
#include "files.h"
#include "protocol.h"
#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>
#include <QSqlQuery>

namespace dukto {
namespace {
// 日期：2026-11-04；目录预约核对稳定原生身份，不以名称或修改时间推断本任务拥有目录。
QByteArray directoryIdentity(const QString &path) {
#ifdef Q_OS_WIN
    NativeDirectoryLock directory(path, false);
#else
    PosixDirectory directory(path, false);
#endif
    return directory.identity();
}
} // namespace

// 日期：2026-11-05；目录同样执行冲突策略与原子不覆盖提交；恢复只认可原日志的目录身份。
QString DurableReceive::prepare(quint64 file, const std::function<void()> &check) {
    verifyRoot();
    if (check)
        check();
    verifyRoot();
    const auto entry = manifest_.entry(file);
    const auto separator = entry.relative.lastIndexOf('/');
    QString parent;
    QSqlQuery query(database_);
    if (separator >= 0) {
        query.prepare("SELECT target,native,state FROM directories WHERE source=?");
        query.addBindValue(entry.relative.left(separator));
        execute(query);
        if (!query.next() || query.value(2).toString() != "completed")
            throw Error(ExitCode::Integrity, QStringLiteral("接收父目录尚未预约完成"), "receive");
        parent = validateRelativePath(query.value(0).toString());
        if (directoryIdentity(resolveInside(root_, parent, false)) != query.value(1).toByteArray())
            throw Error(ExitCode::Integrity, QStringLiteral("接收父目录被替换"), "receive");
        query.finish();
    }
    const auto destination =
        (parent.isEmpty() ? QString() : parent + '/') + QFileInfo(entry.relative).fileName();
    if (!entry.directory)
        return validateRelativePath(destination);
    const auto spec = next::encodeControl({{"entry", entry.publicInfo()}, {"path", destination}});
    query.prepare("SELECT source,spec,temporary,target,native,state FROM directories WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    QString temporary, target, state;
    QByteArray native;
    const bool newlyCreated = !query.next();
    if (newlyCreated) {
        if (conflict_ == ConflictPolicy::Fail &&
            QFileInfo::exists(resolveInside(root_, destination)))
            throw Error(ExitCode::Permission, QStringLiteral("接收目录已存在，冲突策略要求停止"),
                        "conflict");
        temporary = (parent.isEmpty() ? QString() : parent + '/') + ".dukto-" +
                    QUuid::createUuid().toString(QUuid::WithoutBraces) + ".dir";
        target = destination;
        state = "planned";
        query.finish();
        query.prepare("INSERT INTO directories VALUES(?,?,?,?,?,?,'planned')");
        query.addBindValue(static_cast<qlonglong>(file));
        query.addBindValue(entry.relative);
        query.addBindValue(spec);
        query.addBindValue(temporary);
        query.addBindValue(target);
        query.addBindValue(QByteArray(""));
        execute(query);
    } else {
        if (query.value(0).toString() != entry.relative || query.value(1).toByteArray() != spec)
            throw Error(ExitCode::Integrity, QStringLiteral("目录预约与强清单映射不同"), "receive");
        temporary = validateRelativePath(query.value(2).toString());
        target = validateRelativePath(query.value(3).toString());
        native = query.value(4).toByteArray();
        state = query.value(5).toString();
        if (!QStringList{"planned", "committing", "completed"}.contains(state) ||
            QFileInfo(temporary).path() != QFileInfo(destination).path() ||
            QFileInfo(target).path() != QFileInfo(destination).path() ||
            !QRegularExpression("\\A\\.dukto-[0-9a-f-]{36}\\.dir\\z")
                 .match(QFileInfo(temporary).fileName())
                 .hasMatch() ||
            (state != "planned" && native.isEmpty()))
            throw Error(ExitCode::Integrity, QStringLiteral("目录预约状态损坏"), "receive");
        query.finish();
    }
    const auto saveDirectory = [&](const QString &next, const QString &candidate) {
        // 日期：2026-11-04；同一目录意图在每次命名前持久保存，恢复不重新分配已发布目录。
        QSqlQuery update(database_);
        update.prepare("UPDATE directories SET target=?,native=?,state=? WHERE id=?");
        update.addBindValue(candidate);
        update.addBindValue(native);
        update.addBindValue(next);
        update.addBindValue(static_cast<qlonglong>(file));
        execute(update);
        if (update.numRowsAffected() != 1)
            throw Error(ExitCode::Integrity, QStringLiteral("目录预约记录丢失"), "receive");
    };
    const auto path = resolveInside(root_, target);
    if (state != "planned" && QFileInfo(path).isDir() && directoryIdentity(path) == native) {
#ifndef Q_OS_WIN
        PosixDirectory held(QFileInfo(path).absolutePath(), false);
        held.synchronize();
#endif
        saveDirectory("completed", target);
        return target;
    }
    if (state == "completed")
        throw Error(ExitCode::Integrity, QStringLiteral("已预约目录缺失或被替换"), "receive");
    const auto temporaryPath = resolveInside(root_, temporary);
    const auto parentPath = QFileInfo(temporaryPath).absolutePath();
    if (state == "planned") {
        if (!newlyCreated && QFileInfo::exists(temporaryPath))
            throw Error(ExitCode::Integrity,
                        QStringLiteral("目录创建时中断且身份未知，保留并拒绝推断"), "receive");
#ifdef Q_OS_WIN
        NativeDirectoryLock held(parentPath, false);
        if (!QDir(parentPath).mkdir(QFileInfo(temporaryPath).fileName()))
#else
        PosixDirectory held(parentPath, false);
        if (!held.createChild(QFileInfo(temporaryPath).fileName()))
#endif
            throw Error(ExitCode::Disk, QStringLiteral("无法独占创建接收目录"), "receive");
        native = directoryIdentity(temporaryPath);
#ifndef Q_OS_WIN
        PosixDirectory created(temporaryPath, false);
        created.synchronize();
        held.synchronize();
#endif
        saveDirectory("committing", target);
    } else if (directoryIdentity(temporaryPath) != native) {
        throw Error(ExitCode::Integrity, QStringLiteral("目录临时项被替换"), "receive");
    }
    for (int suffix = 0; suffix < 10000; ++suffix) {
        verifyRoot();
        const auto candidate =
            QDir::cleanPath(suffix == 0 ? destination : renamedPath(destination, suffix));
        saveDirectory("committing", candidate);
        if (check)
            check();
        verifyRoot();
        bool published;
#ifdef Q_OS_WIN
        NativeDirectoryLock held(parentPath, false);
        published = renameNoReplace(temporaryPath, resolveInside(root_, candidate), true);
#else
        PosixDirectory held(parentPath, false);
        published =
            held.commitTemporary(QFileInfo(temporary).fileName(), QFileInfo(candidate).fileName());
        if (published)
            held.synchronize();
#endif
        if (!published) {
            if (conflict_ == ConflictPolicy::Fail)
                throw Error(ExitCode::Permission, QStringLiteral("目录提交时出现同名目标"),
                            "conflict");
            continue;
        }
        if (check)
            check();
        if (directoryIdentity(resolveInside(root_, candidate, false)) != native)
            throw Error(ExitCode::Integrity, QStringLiteral("发布目录原生身份不匹配"), "receive");
        saveDirectory("completed", candidate);
        return candidate;
    }
    throw Error(ExitCode::Disk, QStringLiteral("同名目录过多，无法预约目标"), "receive");
}
} // namespace dukto

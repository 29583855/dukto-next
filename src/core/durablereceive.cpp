#include "durablereceive.h"
#include "error.h"
#include "files.h"
#include "protocol.h"
#include "sourcefile.h"

#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>
#include <QSqlQuery>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace dukto {
namespace {
// 日期：2026-11-04；恢复身份只取不会因写入/重命名变化的原生文件 ID，内容另以全摘要核对。
QByteArray nativeIdentity(int descriptor) {
#ifdef Q_OS_WIN
    const auto handle = reinterpret_cast<HANDLE>(_get_osfhandle(descriptor));
    BY_HANDLE_FILE_INFORMATION info;
    if (GetFileType(handle) != FILE_TYPE_DISK || !GetFileInformationByHandle(handle, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)))
        throw Error(ExitCode::Permission, QStringLiteral("持久接收文件身份无效"), "receive");
    return QByteArray::number(static_cast<qulonglong>(info.dwVolumeSerialNumber)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexHigh)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexLow));
#else
    struct stat info;
    if (::fstat(descriptor, &info) != 0 || !S_ISREG(info.st_mode))
        throw Error(ExitCode::Permission, QStringLiteral("持久接收文件身份无效"), "receive");
    return QByteArray::number(static_cast<qulonglong>(info.st_dev)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.st_ino));
#endif
}
} // namespace

class ReceiveFile final {
  public:
    // 日期：2026-11-04；固定父目录并安全打开普通文件；创建必须独占，重开不能截断已有数据。
    ReceiveFile(const QString &path, bool create) : path_(path) {
        const QFileInfo info(path);
        int descriptor = -1;
#ifdef Q_OS_WIN
        parent_.reset(new NativeDirectoryLock(info.absolutePath(), true));
        auto native = QDir::toNativeSeparators(info.absoluteFilePath());
        if (!native.startsWith("\\\\?\\"))
            native =
                native.startsWith("\\\\") ? "\\\\?\\UNC\\" + native.mid(2) : "\\\\?\\" + native;
        const auto handle =
            CreateFileW(reinterpret_cast<LPCWSTR>(native.utf16()), GENERIC_READ | GENERIC_WRITE,
                        FILE_SHARE_READ, nullptr, create ? CREATE_NEW : OPEN_EXISTING,
                        FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (handle == INVALID_HANDLE_VALUE)
            throw Error(ExitCode::Disk, QStringLiteral("无法打开持久接收文件"), "receive");
        descriptor = _open_osfhandle(reinterpret_cast<intptr_t>(handle), _O_RDWR | _O_BINARY);
        if (descriptor < 0) {
            CloseHandle(handle);
            throw Error(ExitCode::Disk, QStringLiteral("无法接管持久接收句柄"), "receive");
        }
#else
        parent_.reset(new PosixDirectory(info.absolutePath(), true));
        descriptor = parent_->openUpdate(info.fileName(), create);
#endif
        if (!device_.open(descriptor, QIODevice::ReadWrite, QFileDevice::AutoCloseHandle)) {
#ifdef Q_OS_WIN
            _close(descriptor);
#else
            ::close(descriptor);
#endif
            throw Error(ExitCode::Disk, QStringLiteral("无法接管持久接收文件"), "receive");
        }
        identity_ = nativeIdentity(device_.handle());
        if (create)
            sync();
    }

    // 日期：2026-11-04；正常销毁不删除临时项；下一执行者必须重新验证检查点。
    ~ReceiveFile() = default;

    // 日期：2026-11-04；返回当前固定普通文件，不允许调用方把此引用交给其他线程。
    QFile &device() {
        return device_;
    }

    // 日期：2026-11-04；原生 ID 用于跨重启确认临时/最终名称指向同一个文件。
    QByteArray identity() const {
        return nativeIdentity(device_.handle());
    }

    // 日期：2026-11-04；检查父目录与当前文件名仍绑定持有的原生对象，拒绝路径替换。
    void verify() const {
        if (identity() != identity_)
            throw Error(ExitCode::Integrity, QStringLiteral("持久接收文件身份已变化"), "receive");
#ifndef Q_OS_WIN
        const auto descriptor = parent_->openRead(QFileInfo(path_).fileName());
        QByteArray observed;
        try {
            observed = nativeIdentity(descriptor);
        } catch (...) {
            ::close(descriptor);
            throw;
        }
        ::close(descriptor);
        if (observed != identity_)
            throw Error(ExitCode::Integrity, QStringLiteral("持久接收文件路径已被替换"), "receive");
#endif
    }

    // 日期：2026-11-04；同步文件数据后才能发布块检查点，Qt flush 本身不构成持久化。
    void sync() {
        verify();
        if (!device_.flush())
            throw Error(ExitCode::Disk, QStringLiteral("持久接收缓冲写入失败"), "receive");
#ifdef Q_OS_WIN
        if (!FlushFileBuffers(reinterpret_cast<HANDLE>(_get_osfhandle(device_.handle()))))
#else
        if (::fsync(device_.handle()) != 0)
#endif
            throw Error(ExitCode::Disk, QStringLiteral("持久接收数据同步失败"), "receive");
#ifndef Q_OS_WIN
        parent_->synchronize();
#endif
    }

  private:
    QString path_;
#ifdef Q_OS_WIN
    std::unique_ptr<NativeDirectoryLock> parent_;
#else
    std::unique_ptr<PosixDirectory> parent_;
#endif
    QFile device_;
    QByteArray identity_;
};

// 日期：2026-11-04；文件上下文只保留固定句柄、增量摘要与标量，16 文件共用一份受保护日志。
struct DurableReceive::Cursor {
    std::unique_ptr<ReceiveFile> file;
    StrongEntry entry;
    QString original;
    QString temporary;
    QString target;
    QByteArray native;
    QString state;
    qint64 confirmed = 0;
    quint64 nextBlock = 0;
    bool sparse = false;
    std::map<quint64, std::unique_ptr<Partial>> partials;
};

// 日期：2026-11-05；非默认冲突策略使用版本化绑定；默认日志保持旧格式，恢复不能更改策略。
DurableReceive::DurableReceive(PrivateStore &store, const QString &name, const QUuid &task,
                               StrongManifest &manifest, const QString &root,
                               ConflictPolicy conflict)
    : store_(store), manifest_(manifest), root_(QDir::cleanPath(root)), conflict_(conflict),
      connection_(QUuid::createUuid().toString()), current_(new Cursor) {
    if (task.isNull() || !QDir::isAbsolutePath(root) || !QFileInfo(root).isDir())
        throw Error(ExitCode::Config, QStringLiteral("持久接收任务或根无效"), "receive");
#ifdef Q_OS_WIN
    rootLock_.reset(new NativeDirectoryLock(root_, false));
#else
    rootLock_.reset(new PosixDirectory(root_, false));
#endif
    conflictPolicyName(conflict_);
    QJsonObject bindingInfo{{"version", 1},
                            {"task", task.toString(QUuid::WithoutBraces)},
                            {"manifest", manifest.summary()["sha256"]},
                            {"root", root_},
                            {"rootIdentity", QString::fromLatin1(rootLock_->identity())}};
    if (conflict_ != ConflictPolicy::Rename) {
        bindingInfo["version"] = 2;
        bindingInfo["conflict"] = conflictPolicyName(conflict_);
    }
    const auto binding = next::encodeControl(bindingInfo);
    // 日期：2026-11-04；先验证单文件状态键，再构造锁路径，防止锁名发生路径穿越。
    const bool exists = store.exists(name);
    ownership_.reset(new QLockFile(QDir(store.directory()).filePath(name + ".lock")));
    ownership_->setStaleLockTime(0);
    if (!ownership_->tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("持久接收已有活动执行者"), "receive");
    if (!exists)
        store.write(name, {});
    store.validateFile(name);
    database_ = QSqlDatabase::addDatabase("QSQLITE", connection_);
    try {
        database_.setDatabaseName(QDir(store.directory()).filePath(name));
        if (!database_.open())
            throw Error(ExitCode::Disk, QStringLiteral("无法打开接收日志"), "receive");
        sql("PRAGMA busy_timeout=2000");
        sql("PRAGMA page_size=4096");
        sql("PRAGMA max_page_count=65536");
        cacheCredit_.configure(database_);
        sql("PRAGMA temp_store=FILE");
        sql("PRAGMA journal_mode=DELETE");
        sql("PRAGMA synchronous=FULL");
        sql("CREATE TABLE IF NOT EXISTS binding(spec BLOB NOT NULL)");
        sql("CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, spec BLOB NOT NULL, "
            "temporary TEXT NOT NULL,target TEXT NOT NULL,native BLOB NOT NULL,"
            "state TEXT NOT NULL,confirmed INTEGER NOT NULL)");
        sql("CREATE TABLE IF NOT EXISTS blocks(file INTEGER NOT NULL,block INTEGER NOT NULL,"
            "sha BLOB NOT NULL,PRIMARY KEY(file,block))");
        sql("CREATE TABLE IF NOT EXISTS directories(id INTEGER PRIMARY KEY,source TEXT UNIQUE NOT "
            "NULL,"
            "spec BLOB NOT NULL,temporary TEXT NOT NULL,target TEXT NOT NULL,native BLOB NOT "
            "NULL,state TEXT NOT NULL)");
        QSqlQuery query(database_);
        query.prepare("SELECT spec FROM binding");
        execute(query);
        if (query.next()) {
            if (query.value(0).toByteArray() != binding || query.next())
                throw Error(ExitCode::Integrity, QStringLiteral("接收日志任务绑定不匹配"),
                            "receive");
        } else {
            if (exists)
                throw Error(ExitCode::Integrity, QStringLiteral("接收日志缺少持久绑定"), "receive");
            query.finish();
            query.prepare("INSERT INTO binding VALUES(?)");
            query.addBindValue(binding);
            execute(query);
        }
    } catch (...) {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
        throw;
    }
}

// 日期：2026-11-04；析构先关原生文件再关日志；所有未提交文件保留供同任务恢复。
DurableReceive::~DurableReceive() {
    current_.reset();
    parked_.clear();
    database_.close();
    database_ = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection_);
}

// 日期：2026-11-04；根被改名或替换后停止访问，不能跟随替换后的根访问文件。
void DurableReceive::verifyRoot() const {
#ifndef Q_OS_WIN
    rootLock_->verify();
#endif
}

// 日期：2026-11-04；SQL 错误明确抛出，不把失败查询解释为没有文件或已完成。
void DurableReceive::execute(QSqlQuery &query) const {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("接收日志操作失败"), "receive");
}

// 日期：2026-11-04；固定 SQL 在失败时抛出统一错误，不打印包含用户路径的数据库诊断。
void DurableReceive::sql(const QString &statement) const {
    QSqlQuery query(database_);
    if (!query.exec(statement))
        throw Error(ExitCode::Disk, QStringLiteral("接收日志事务失败"), "receive");
}

// 日期：2026-11-04；状态写入成功后更新内存副本；持久提交意图先于最终文件名发布。
void DurableReceive::save(const QString &state, const QString &target, qint64 confirmed) {
    QSqlQuery query(database_);
    query.prepare("UPDATE files SET native=?,state=?,target=?,confirmed=? WHERE id=?");
    query.addBindValue(current_->native.isNull() ? QByteArray("") : current_->native);
    query.addBindValue(state);
    query.addBindValue(target);
    query.addBindValue(confirmed);
    query.addBindValue(static_cast<qlonglong>(current_->entry.id));
    execute(query);
    if (query.numRowsAffected() != 1)
        throw Error(ExitCode::Integrity, QStringLiteral("接收日志文件记录丢失"), "receive");
    current_->state = state;
    current_->target = target;
    current_->confirmed = confirmed;
}

// 日期：2026-11-04；清单是唯一块长度和摘要来源，分页只保留有界的最多 100 条记录。
QJsonObject DurableReceive::expectedBlock(quint64 block) const {
    const auto count = static_cast<quint64>(current_->entry.bytes / StrongBlockBytes +
                                            (current_->entry.bytes % StrongBlockBytes != 0));
    if (block >= count)
        throw Error(ExitCode::Integrity, QStringLiteral("接收块序号超出强清单"), "receive");
    const auto page = manifest_.blocks(current_->entry.id, block);
    if (page.isEmpty() || page[0].toObject()["block"] != QString::number(block))
        throw Error(ExitCode::Integrity, QStringLiteral("接收强清单缺少期望块"), "receive");
    return page[0].toObject();
}

// 日期：2026-11-04；按 256 KiB 重读摘要，不随大文件大小增加常驻缓冲。
QByteArray DurableReceive::digest(qint64 offset, qint64 bytes, const std::function<void()> &check) {
    verifyRoot();
    current_->file->verify();
    if (!current_->file->device().seek(offset))
        throw Error(ExitCode::Disk, QStringLiteral("接收校验定位失败"), "receive");
    QCryptographicHash hash(QCryptographicHash::Sha256);
    while (bytes > 0) {
        if (check)
            check();
        verifyRoot();
        const auto part = current_->file->device().read(qMin<qint64>(BufferSize, bytes));
        if (part.isEmpty())
            throw Error(ExitCode::Integrity, QStringLiteral("接收检查点数据不完整"), "receive");
        hash.addData(part);
        bytes -= part.size();
    }
    current_->file->verify();
    return hash.result();
}

// 日期：2026-11-04；兼容单通道顺序模式，只保留重读通过的连续前缀检查点。
quint64 DurableReceive::open(quint64 file, const QString &destination,
                             const std::function<void()> &check) {
    return openFile(file, destination, check, false);
}

// 日期：2026-11-04；稀疏模式保留后到先存的块，恢复不因前面缺块丢弃后面的有效数据。
quint64 DurableReceive::openSparse(quint64 file, const QString &destination,
                                   const std::function<void()> &check) {
    return openFile(file, destination, check, true);
}

// 日期：2026-11-04；并行文件保持独立上下文；达到窗口上限时拒绝，不把文件数转成无界句柄。
void DurableReceive::openConcurrent(quint64 file, const QString &destination,
                                    const std::function<void()> &check) {
    if (parked_.count(file) || current_->entry.id == file)
        throw Error(ExitCode::Config, QStringLiteral("文件已在接收窗口中"), "receive");
    const auto active = parked_.size() + (current_->file ? 1 : 0);
    if (active >= 16)
        throw Error(ExitCode::Permission, QStringLiteral("并行接收文件窗口已满"), "receive");
    if (current_->file)
        parked_.emplace(current_->entry.id, std::move(current_));
    try {
        openFile(file, destination, check, true);
    } catch (...) {
        if (!current_)
            current_.reset(new Cursor);
        throw;
    }
}

// 日期：2026-11-04；切换只移动当前线程的上下文所有权；已有检查点不重复重读或改写。
void DurableReceive::activate(quint64 file) {
    if (current_->entry.id == file && current_->file)
        return;
    const auto found = parked_.find(file);
    if (found == parked_.end())
        throw Error(ExitCode::Config, QStringLiteral("文件不在当前接收窗口"), "receive");
    auto next = std::move(found->second);
    parked_.erase(found);
    if (current_->file)
        parked_.emplace(current_->entry.id, std::move(current_));
    current_ = std::move(next);
}

// 日期：2026-11-04；未完成文件必须保留到窗口收尾或析构，不能通过关闭游标冒充完成。
void DurableReceive::closeCurrent() {
    if (current_->state != "completed" || !current_->partials.empty())
        throw Error(ExitCode::Config, QStringLiteral("接收文件尚未完成提交"), "receive");
    current_.reset(new Cursor);
}

// 日期：2026-11-05；新文件先拒绝明确冲突；既有本任务日志按原生身份恢复，每页最多 100 条。
quint64 DurableReceive::openFile(quint64 file, const QString &destination,
                                 const std::function<void()> &check, bool sparse) {
    verifyRoot();
    current_.reset(new Cursor);
    current_->sparse = sparse;
    current_->entry = manifest_.entry(file);
    if (current_->entry.directory)
        throw Error(ExitCode::Config, QStringLiteral("持久接收只接受清单普通文件"), "receive");
    current_->original = validateRelativePath(destination);
    resolveInside(root_, current_->original);
    const auto spec = next::encodeControl(
        {{"entry", current_->entry.publicInfo()}, {"path", current_->original}});
    QSqlQuery query(database_);
    query.prepare("SELECT spec,temporary,target,native,state,confirmed FROM files WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    bool newlyCreated = !query.next();
    if (newlyCreated) {
        if (conflict_ == ConflictPolicy::Fail &&
            QFileInfo::exists(resolveInside(root_, current_->original)))
            throw Error(ExitCode::Permission, QStringLiteral("接收目标已存在，冲突策略要求停止"),
                        "conflict");
        current_->temporary = QFileInfo(current_->original).path() + "/.dukto-" +
                              QUuid::createUuid().toString(QUuid::WithoutBraces) + ".part";
        current_->temporary = QDir::cleanPath(current_->temporary);
        current_->target = current_->original;
        current_->native.clear();
        current_->state = "planned";
        current_->confirmed = 0;
        query.finish();
        query.prepare("INSERT INTO files VALUES(?,?,?,?,?,'planned',0)");
        query.addBindValue(static_cast<qlonglong>(file));
        query.addBindValue(spec);
        query.addBindValue(current_->temporary);
        query.addBindValue(current_->target);
        query.addBindValue(QByteArray(""));
        execute(query);
    } else {
        if (query.value(0).toByteArray() != spec)
            throw Error(ExitCode::Integrity, QStringLiteral("接收文件映射与原任务不符"), "receive");
        current_->temporary = validateRelativePath(query.value(1).toString());
        current_->target = validateRelativePath(query.value(2).toString());
        current_->native = query.value(3).toByteArray();
        current_->state = query.value(4).toString();
        current_->confirmed = query.value(5).toLongLong();
        if (!QStringList{"planned", "receiving", "committing", "completed"}.contains(
                current_->state) ||
            current_->confirmed < 0 || current_->confirmed > current_->entry.bytes ||
            QFileInfo(current_->temporary).path() != QFileInfo(current_->original).path() ||
            QFileInfo(current_->target).path() != QFileInfo(current_->original).path() ||
            !QRegularExpression("\\A\\.dukto-[0-9a-f-]{36}\\.part\\z")
                 .match(QFileInfo(current_->temporary).fileName())
                 .hasMatch() ||
            (current_->state != "planned" && current_->native.isEmpty()))
            throw Error(ExitCode::Integrity, QStringLiteral("接收日志文件状态损坏"), "receive");
        query.finish();
    }
    if (current_->state == "committing" || current_->state == "completed") {
        recoverCommit(check);
        current_->nextBlock = static_cast<quint64>(current_->entry.bytes / StrongBlockBytes +
                                                   (current_->entry.bytes % StrongBlockBytes != 0));
        return current_->nextBlock;
    }
    const auto temporaryPath = resolveInside(root_, current_->temporary);
    if (current_->state == "planned") {
        if (!newlyCreated && QFileInfo::exists(temporaryPath))
            throw Error(ExitCode::Integrity,
                        QStringLiteral("临时文件创建时中断且身份未记录，保留数据并拒绝推断成功"),
                        "receive");
        checkStorageSpace(root_, current_->entry.bytes, true);
        current_->file.reset(new ReceiveFile(temporaryPath, true));
        current_->native = current_->file->identity();
        save("receiving", current_->target, 0);
    } else {
        current_->file.reset(new ReceiveFile(temporaryPath, false));
        if (current_->file->identity() != current_->native)
            throw Error(ExitCode::Integrity, QStringLiteral("接收临时文件已被替换"), "receive");
    }
    qint64 valid = 0;
    current_->nextBlock = 0;
    quint64 first = 0;
    bool prefix = true;
    for (;;) {
        query.prepare("SELECT block,sha FROM blocks WHERE file=? AND block>=? ORDER BY block "
                      "LIMIT 100");
        query.addBindValue(static_cast<qlonglong>(file));
        query.addBindValue(static_cast<qlonglong>(first));
        execute(query);
        QList<quint64> invalid;
        int rows = 0;
        while (query.next()) {
            ++rows;
            if (check)
                check();
            const auto index = query.value(0).toULongLong();
            const auto block = expectedBlock(index);
            const auto length = block["bytes"].toString().toLongLong();
            const auto sha = QByteArray::fromHex(block["sha256"].toString().toLatin1());
            const auto offset = static_cast<qint64>(index) * StrongBlockBytes;
            const bool eligible = sparse || (prefix && index == current_->nextBlock &&
                                             length <= current_->confirmed - valid);
            const bool accepted = eligible && query.value(1).toByteArray() == sha &&
                                  current_->file->device().size() >= offset + length &&
                                  digest(offset, length, check) == sha;
            if (accepted) {
                valid += length;
                if (index == current_->nextBlock)
                    ++current_->nextBlock;
            } else {
                invalid.append(index);
                prefix = false;
            }
            first = index + 1;
        }
        query.finish();
        if (!invalid.isEmpty()) {
            sql("BEGIN IMMEDIATE");
            try {
                for (const auto index : invalid) {
                    query.prepare("DELETE FROM blocks WHERE file=? AND block=?");
                    query.addBindValue(static_cast<qlonglong>(file));
                    query.addBindValue(static_cast<qlonglong>(index));
                    execute(query);
                }
                sql("COMMIT");
            } catch (...) {
                database_.rollback();
                throw;
            }
        }
        if (rows < 100)
            break;
    }
    sql("BEGIN IMMEDIATE");
    try {
        save("receiving", current_->target, valid);
        sql("COMMIT");
    } catch (...) {
        database_.rollback();
        throw;
    }
    const auto retained =
        sparse ? qMin(current_->file->device().size(), current_->entry.bytes) : valid;
    if (!current_->file->device().resize(retained) || !current_->file->device().seek(0))
        throw Error(ExitCode::Disk, QStringLiteral("无法丢弃未确认接收片段"), "receive");
    return current_->nextBlock;
}

// 日期：2026-11-04；持久块表是稀疏索引；查询不建立随文件大小增长的内存位图。
bool DurableReceive::hasBlock(quint64 block) const {
    if (!current_->file)
        throw Error(ExitCode::Config, QStringLiteral("尚未打开接收文件"), "receive");
    const auto count = static_cast<quint64>(current_->entry.bytes / StrongBlockBytes +
                                            (current_->entry.bytes % StrongBlockBytes != 0));
    if (block >= count)
        throw Error(ExitCode::Integrity, QStringLiteral("接收块查询超出清单"), "receive");
    if (current_->state == "completed")
        return true;
    QSqlQuery query(database_);
    query.prepare("SELECT 1 FROM blocks WHERE file=? AND block=?");
    query.addBindValue(static_cast<qlonglong>(current_->entry.id));
    query.addBindValue(static_cast<qlonglong>(block));
    execute(query);
    return query.next();
}

// 日期：2026-11-04；每块数据先核对强摘要并同步，再以一个小事务记录进度与块检查点。
void DurableReceive::write(quint64 block, quint32 offset, const QByteArray &bytes,
                           const std::function<void()> &check) {
    verifyRoot();
    if (!current_->file || current_->state != "receiving" ||
        (!current_->sparse && block != current_->nextBlock) || bytes.isEmpty() ||
        bytes.size() > BufferSize)
        throw Error(ExitCode::Integrity, QStringLiteral("接收片段状态、顺序或大小无效"), "receive");
    if (check)
        check();
    verifyRoot();
    const auto expected = expectedBlock(block);
    const auto length = expected["bytes"].toString().toLongLong();
    if (static_cast<qint64>(offset) + bytes.size() > length)
        throw Error(ExitCode::Integrity, QStringLiteral("接收片段超过期望块长度"), "receive");
    auto found = current_->partials.find(block);
    if (found == current_->partials.end()) {
        if (offset || hasBlock(block) || current_->partials.size() >= 16)
            throw Error(ExitCode::Integrity, QStringLiteral("接收块重复、片段乱序或活动块额度已满"),
                        "receive");
        found = current_->partials.emplace(block, std::unique_ptr<Partial>(new Partial)).first;
    }
    auto &partial = *found->second;
    if (offset != partial.offset)
        throw Error(ExitCode::Integrity, QStringLiteral("接收块内片段顺序无效"), "receive");
    current_->file->verify();
    if (!current_->file->device().seek(static_cast<qint64>(block) * StrongBlockBytes + offset))
        throw Error(ExitCode::Disk, QStringLiteral("接收片段定位失败"), "receive");
    writeAll(current_->file->device(), bytes);
    partial.hash.addData(bytes);
    partial.offset += static_cast<quint32>(bytes.size());
    if (partial.offset != length)
        return;
    const auto expectedSha = QByteArray::fromHex(expected["sha256"].toString().toLatin1());
    if (partial.hash.result() != expectedSha) {
        current_->partials.erase(found);
        throw Error(ExitCode::Integrity, QStringLiteral("接收块摘要不匹配，不能确认此块"),
                    "receive");
    }
    current_->file->sync();
    sql("BEGIN IMMEDIATE");
    try {
        QSqlQuery query(database_);
        query.prepare("INSERT INTO blocks VALUES(?,?,?)");
        query.addBindValue(static_cast<qlonglong>(current_->entry.id));
        query.addBindValue(static_cast<qlonglong>(block));
        query.addBindValue(expectedSha);
        execute(query);
        save("receiving", current_->target, current_->confirmed + length);
        sql("COMMIT");
    } catch (...) {
        database_.rollback();
        throw;
    }
    current_->partials.erase(found);
    const auto count = static_cast<quint64>(current_->entry.bytes / StrongBlockBytes +
                                            (current_->entry.bytes % StrongBlockBytes != 0));
    while (current_->nextBlock < count && hasBlock(current_->nextBlock))
        ++current_->nextBlock;
}

// 日期：2026-11-04；提交意图保留了唯一目标名与原生 ID；重命名后崩溃只确认同一文件，不分配副本。
void DurableReceive::recoverCommit(const std::function<void()> &check) {
    const auto destination = resolveInside(root_, current_->target);
    if (QFileInfo(destination).isFile()) {
        bool same = false;
        {
            SourceFile candidate(destination);
            same = nativeIdentity(candidate.device().handle()) == current_->native;
            candidate.verify();
        }
        if (same) {
            current_->file.reset(new ReceiveFile(destination, false));
            if (current_->file->device().size() != current_->entry.bytes ||
                digest(0, current_->entry.bytes, check) != current_->entry.sha256)
                throw Error(ExitCode::Integrity, QStringLiteral("已提交文件内容已变化"), "commit");
            current_->file->sync();
            // 日期：2026-11-04；POSIX linkat 回退可能保留同一原生文件的临时硬链接，核验后清理。
#ifndef Q_OS_WIN
            const auto temporary = resolveInside(root_, current_->temporary);
            if (QFileInfo::exists(temporary)) {
                ReceiveFile held(temporary, false);
                if (held.identity() != current_->native)
                    throw Error(ExitCode::Integrity, QStringLiteral("提交临时项身份变化"),
                                "commit");
                PosixDirectory parent(QFileInfo(temporary).absolutePath(), false);
                parent.removeTemporary(QFileInfo(temporary).fileName());
                parent.synchronize();
            }
#endif
            save("completed", current_->target, current_->entry.bytes);
            return;
        }
    }
    if (current_->state == "completed")
        throw Error(ExitCode::Integrity, QStringLiteral("已完成文件缺失或被替换"), "commit");
    current_->file.reset(new ReceiveFile(resolveInside(root_, current_->temporary), false));
    if (current_->file->identity() != current_->native ||
        current_->file->device().size() != current_->entry.bytes ||
        digest(0, current_->entry.bytes, check) != current_->entry.sha256)
        throw Error(ExitCode::Integrity, QStringLiteral("提交中临时文件证据不匹配"), "commit");
    finish(check);
}

// 日期：2026-11-05；全摘要通过后记录提交意图，失败策略在原子发布竞争时停止且保护已有目标。
QString DurableReceive::finish(const std::function<void()> &check) {
    verifyRoot();
    if (!current_->file || current_->confirmed != current_->entry.bytes ||
        !current_->partials.empty() ||
        (current_->state != "receiving" && current_->state != "committing" &&
         current_->state != "completed"))
        throw Error(ExitCode::Integrity, QStringLiteral("文件尚未完整接收"), "commit");
    if (current_->state == "completed")
        return current_->target;
    if (current_->file->device().size() != current_->entry.bytes ||
        digest(0, current_->entry.bytes, check) != current_->entry.sha256)
        throw Error(ExitCode::Integrity, QStringLiteral("接收全文件摘要不匹配"), "commit");
    current_->file->sync();
    for (int suffix = 0; suffix < 10000; ++suffix) {
        const auto candidate = QDir::cleanPath(
            suffix == 0 ? current_->original : renamedPath(current_->original, suffix));
        const auto target = resolveInside(root_, candidate);
        save("committing", candidate, current_->entry.bytes);
        if (check)
            check();
        current_->file->verify();
        bool published = false;
#ifdef Q_OS_WIN
        // 日期：2026-11-04；Windows 文件句柄不共享删除；关闭文件后父目录仍由原生锁固定。
        current_->file.reset();
        NativeDirectoryLock parent(QFileInfo(target).absolutePath(), false);
        published = renameNoReplace(resolveInside(root_, current_->temporary), target, true);
#else
        PosixDirectory parent(QFileInfo(target).absolutePath(), false);
        published = parent.commitTemporary(QFileInfo(current_->temporary).fileName(),
                                           QFileInfo(target).fileName());
        if (published)
            parent.synchronize();
        current_->file.reset();
#endif
        if (!published) {
            current_->file.reset(new ReceiveFile(resolveInside(root_, current_->temporary), false));
            if (current_->file->identity() != current_->native)
                throw Error(ExitCode::Integrity, QStringLiteral("提交竞争中临时文件被替换"),
                            "commit");
            if (conflict_ == ConflictPolicy::Fail)
                throw Error(ExitCode::Permission,
                            QStringLiteral("提交时目标已存在，原文件保持不变"), "conflict");
            continue;
        }
        // 日期：2026-11-04；此检查点可在测试中注入进程退出，日志仍处于 committing 并保留目标名。
        if (check)
            check();
        current_->file.reset(new ReceiveFile(target, false));
        if (current_->file->identity() != current_->native)
            throw Error(ExitCode::Integrity, QStringLiteral("最终文件原生身份不匹配"), "commit");
        save("completed", candidate, current_->entry.bytes);
        return candidate;
    }
    throw Error(ExitCode::Disk, QStringLiteral("同名文件过多，无法独占提交"), "commit");
}

// 日期：2026-11-04；只统计重读通过或已经同步发布的块，未确认片段不参与可恢复字节数。
qint64 DurableReceive::confirmed() const {
    return current_->confirmed;
}

// 日期：2026-11-04；调用者不能把 committing 当作失败后重新创建同名任务。
QString DurableReceive::state() const {
    return current_->state;
}
} // namespace dukto

#include "nativecommit.h"
#include "error.h"
#include "filecredit.h"

#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QThread>
#include <QUuid>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#ifdef Q_OS_LINUX
#include <sys/syscall.h>
#endif
#ifdef Q_OS_MACOS
#include <stdio.h>
#endif
#endif

namespace dukto {
#ifdef Q_OS_WIN
namespace {
// 日期：2026-11-04；原生宽字符接口显式使用长路径前缀，同时支持 UNC 共享目录。
QString nativeLongPath(const QString &path) {
    const auto native = QDir::toNativeSeparators(QFileInfo(path).absoluteFilePath());
    if (native.startsWith("\\\\?\\"))
        return native;
    return native.startsWith("\\\\") ? "\\\\?\\UNC\\" + native.mid(2) : "\\\\?\\" + native;
}
// 日期：2026-11-06；从固定的普通文件句柄提取与持久接收日志同格式的卷/文件ID。
QByteArray replacementIdentity(HANDLE handle) {
    BY_HANDLE_FILE_INFORMATION info;
    if (GetFileType(handle) != FILE_TYPE_DISK || !GetFileInformationByHandle(handle, &info) ||
        (info.dwFileAttributes &
         (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE)))
        throw Error(ExitCode::Integrity, QStringLiteral("覆盖源不再是已验证的普通文件"), "commit");
    return QByteArray::number(static_cast<qulonglong>(info.dwVolumeSerialNumber)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexHigh)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexLow));
}
} // namespace

// 日期：2026-11-04；父目录先固定再访问下一层，关闭检查路径与打开文件之间的替换窗口。
NativeDirectoryLock::NativeDirectoryLock(const QString &directory, bool createMissing) {
    const auto path =
        QDir::cleanPath(QDir::fromNativeSeparators(QFileInfo(directory).absoluteFilePath()));
    QString root;
    QStringList parts;
    if (path.startsWith("//")) {
        parts = path.mid(2).split('/', Qt::SkipEmptyParts);
        if (parts.size() < 2)
            throw Error(ExitCode::Permission, QStringLiteral("无效的 UNC 目录"), "path");
        root = "//" + parts[0] + '/' + parts[1] + '/';
        parts.removeFirst();
        parts.removeFirst();
    } else if (path.size() >= 3 && path[1] == ':' && path[2] == '/') {
        root = path.left(3);
        parts = path.mid(3).split('/', Qt::SkipEmptyParts);
    } else {
        throw Error(ExitCode::Permission, QStringLiteral("Windows 目录必须为绝对路径"), "path");
    }
    handles_.reserve(static_cast<size_t>(parts.size() + 1));
    try {
        QString cursor = root;
        for (int index = -1; index < parts.size(); ++index) {
            if (index >= 0)
                cursor = QDir(cursor).filePath(parts[index]);
            const auto native = nativeLongPath(cursor);
            const auto nativePath = reinterpret_cast<LPCWSTR>(native.utf16());
            auto handle =
                CreateFileW(nativePath, FILE_READ_ATTRIBUTES | FILE_LIST_DIRECTORY,
                            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            if (handle == INVALID_HANDLE_VALUE && index >= 0 && createMissing &&
                (GetLastError() == ERROR_FILE_NOT_FOUND ||
                 GetLastError() == ERROR_PATH_NOT_FOUND)) {
                if (!CreateDirectoryW(nativePath, nullptr) &&
                    GetLastError() != ERROR_ALREADY_EXISTS)
                    throw Error(ExitCode::Disk, QStringLiteral("无法创建接收子目录"), "path");
                handle =
                    CreateFileW(nativePath, FILE_READ_ATTRIBUTES | FILE_LIST_DIRECTORY,
                                FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                                FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            }
            if (handle == INVALID_HANDLE_VALUE)
                throw Error(ExitCode::Disk,
                            QStringLiteral("无法固定接收目录，系统错误码 %1").arg(GetLastError()),
                            "path");
            handles_.push_back(handle);
            BY_HANDLE_FILE_INFORMATION information;
            if (!GetFileInformationByHandle(handle, &information))
                throw Error(ExitCode::Disk, QStringLiteral("无法核对接收目录属性"), "path");
            if (!(information.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ||
                (information.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
                throw Error(ExitCode::Permission,
                            QStringLiteral("接收路径经过重解析点或非目录对象"), "path");
        }
    } catch (...) {
        release();
        throw;
    }
}

// 日期：2026-11-04；句柄只属于当前工作线程，释放后才允许外部重命名目录。
NativeDirectoryLock::~NativeDirectoryLock() {
    release();
}

// 日期：2026-11-04；固定目录句柄的卷/文件索引/写时间构成快照标记，不依赖路径大小写。
QByteArray NativeDirectoryLock::stamp() const {
    BY_HANDLE_FILE_INFORMATION info;
    if (handles_.empty() || !GetFileInformationByHandle(handles_.back(), &info))
        throw Error(ExitCode::Disk, QStringLiteral("无法读取目录快照身份"), "browse");
    QByteArray result;
    for (const auto value :
         {info.dwVolumeSerialNumber, info.nFileIndexHigh, info.nFileIndexLow,
          info.ftLastWriteTime.dwHighDateTime, info.ftLastWriteTime.dwLowDateTime})
        result += QByteArray::number(static_cast<qulonglong>(value)) + ':';
    return result;
}

// 日期：2026-11-04；目录修改时间不参与持久身份，传输自身创建子项不会导致身份误变。
QByteArray NativeDirectoryLock::identity() const {
    BY_HANDLE_FILE_INFORMATION info;
    if (handles_.empty() || !GetFileInformationByHandle(handles_.back(), &info))
        throw Error(ExitCode::Disk, QStringLiteral("无法读取目录原生身份"), "receive");
    return QByteArray::number(static_cast<qulonglong>(info.dwVolumeSerialNumber)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexHigh)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.nFileIndexLow));
}

// 日期：2026-11-04；逆序关闭目录句柄；CloseHandle 不抛异常，适用于异常清理路径。
void NativeDirectoryLock::release() {
    for (auto iterator = handles_.rbegin(); iterator != handles_.rend(); ++iterator)
        CloseHandle(*iterator);
    handles_.clear();
}
#else
namespace {
#ifdef Q_OS_MACOS
// 日期：2026-11-04；macOS 的系统根别名由 root 管理，仅接受指向 /private 同名目录的标准链接。
QString expandSystemDirectoryAlias(const QString &path) {
    for (const auto &alias : {QString("/var"), QString("/tmp"), QString("/etc")}) {
        if (path != alias && !path.startsWith(alias + '/'))
            continue;
        const auto encoded = QFile::encodeName(alias);
        struct stat information;
        if (::lstat(encoded.constData(), &information) != 0 || !S_ISLNK(information.st_mode) ||
            information.st_uid != 0)
            return path;
        const auto canonical = QFileInfo(alias).canonicalFilePath();
        if (canonical == "/private" + alias)
            return canonical + path.mid(alias.size());
    }
    return path;
}
#endif
// 日期：2026-11-04；路径每次只保留前后两个描述符，目录深度不会增加常驻句柄数量。
int openDirectoryPath(const QString &path, bool createMissing) {
    int descriptor = ::open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (descriptor < 0)
        throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "path");
    for (const auto &part : path.split('/', Qt::SkipEmptyParts)) {
        const auto name = QFile::encodeName(part);
        int next =
            ::openat(descriptor, name.constData(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (next < 0 && errno == ENOENT && createMissing) {
            if (::mkdirat(descriptor, name.constData(), 0700) == 0 || errno == EEXIST)
                next = ::openat(descriptor, name.constData(),
                                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        }
        const auto code = errno;
        ::close(descriptor);
        if (next < 0)
            throw Error(code == ELOOP || code == ENOTDIR ? ExitCode::Permission : ExitCode::Disk,
                        QStringLiteral("无法安全打开接收目录：") +
                            QString::fromLocal8Bit(std::strerror(code)),
                        "path");
        descriptor = next;
    }
    return descriptor;
}
} // namespace

// 日期：2026-11-04；不预先 canonicalize 用户路径，避免把恶意符号链接解析为合法目录。
PosixDirectory::PosixDirectory(const QString &directory, bool createMissing)
    : path_(
#ifdef Q_OS_MACOS
          expandSystemDirectoryAlias(QDir::cleanPath(QFileInfo(directory).absoluteFilePath()))),
#else
          QDir::cleanPath(QFileInfo(directory).absoluteFilePath())),
#endif
      descriptor_(openDirectoryPath(path_, createMissing)) {
}

// 日期：2026-11-04；描述符只在当前工作线程使用，析构不抛异常。
PosixDirectory::~PosixDirectory() {
    if (descriptor_ >= 0)
        ::close(descriptor_);
}

// 日期：2026-11-04；POSIX 目录句柄不能禁止外部改名，发布前再次核对目录身份并拒绝替换。
void PosixDirectory::verify() const {
    const int current = openDirectoryPath(path_, false);
    struct stat held;
    struct stat observed;
    const bool same = ::fstat(descriptor_, &held) == 0 && ::fstat(current, &observed) == 0 &&
                      held.st_dev == observed.st_dev && held.st_ino == observed.st_ino;
    ::close(current);
    if (!same)
        throw Error(ExitCode::Permission, QStringLiteral("接收目录在传输期间已被替换"), "path");
}

// 日期：2026-11-04；读取已固定目录本身的身份，目录内增删/替换会改变纳秒时间标记。
QByteArray PosixDirectory::stamp() const {
    verify();
    struct stat info;
    if (::fstat(descriptor_, &info) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("无法读取目录快照身份"), "browse");
    auto result = QByteArray::number(static_cast<qulonglong>(info.st_dev)) + ':' +
                  QByteArray::number(static_cast<qulonglong>(info.st_ino)) + ':';
#ifdef Q_OS_MACOS
    for (const auto &time : {info.st_mtimespec, info.st_ctimespec})
#else
    for (const auto &time : {info.st_mtim, info.st_ctim})
#endif
        result += QByteArray::number(static_cast<qlonglong>(time.tv_sec)) + ':' +
                  QByteArray::number(static_cast<qlonglong>(time.tv_nsec)) + ':';
    return result;
}

// 日期：2026-11-04；固定目录描述符返回稳定设备/inode，仍先拒绝原路径替换。
QByteArray PosixDirectory::identity() const {
    verify();
    struct stat info;
    if (::fstat(descriptor_, &info) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("无法读取目录原生身份"), "receive");
    return QByteArray::number(static_cast<qulonglong>(info.st_dev)) + ':' +
           QByteArray::number(static_cast<qulonglong>(info.st_ino));
}

// 日期：2026-11-04；先固定打开对象再检查类型，避免检查后被替换成链接或特殊设备。
int PosixDirectory::openRead(const QString &name) const {
    if (name.isEmpty() || name == "." || name == ".." || name.contains('/') ||
        name.contains(QChar::Null))
        throw Error(ExitCode::Permission, QStringLiteral("无效的源文件分量"), "read");
    verify();
    const auto encoded = QFile::encodeName(name);
    const int file =
        ::openat(descriptor_, encoded.constData(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    if (file < 0)
        throw Error(errno == ELOOP ? ExitCode::Permission : ExitCode::Disk,
                    QStringLiteral("无法安全打开源文件：") +
                        QString::fromLocal8Bit(std::strerror(errno)),
                    "read");
    struct stat information;
    if (::fstat(file, &information) != 0 || !S_ISREG(information.st_mode)) {
        ::close(file);
        throw Error(ExitCode::Permission, QStringLiteral("源文件不是普通文件"), "read");
    }
    return file;
}

// 日期：2026-11-06；先验证父目录及单层名字，再用不跟随链接的fstatat核验；目录遍历描述符仍独立有界。
struct stat PosixDirectory::fileInformation(const QString &name) const {
    if (name.isEmpty() || name == "." || name == ".." || name.contains('/') ||
        name.contains(QChar::Null))
        throw Error(ExitCode::Permission, QStringLiteral("无效的源文件分量"), "read");
    verify();
    const auto encoded = QFile::encodeName(name);
    struct stat info;
    if (::fstatat(descriptor_, encoded.constData(), &info, AT_SYMLINK_NOFOLLOW) != 0)
        throw Error(ExitCode::Disk,
                    QStringLiteral("无法核对文件路径属性：") +
                        QString::fromLocal8Bit(std::strerror(errno)),
                    "read");
    if (!S_ISREG(info.st_mode))
        throw Error(ExitCode::Permission, QStringLiteral("源文件不是普通文件"), "read");
    return info;
}

// 日期：2026-11-04；接收检查点只能写普通文件，O_EXCL 防覆盖，恢复时不使用 O_TRUNC。
int PosixDirectory::openUpdate(const QString &name, bool create) const {
    if (name.isEmpty() || name == "." || name == ".." || name.contains('/') ||
        name.contains(QChar::Null))
        throw Error(ExitCode::Permission, QStringLiteral("持久接收文件名无效"), "receive");
    verify();
    const auto encoded = QFile::encodeName(name);
    const int flags =
        O_RDWR | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK | (create ? O_CREAT | O_EXCL : 0);
    const int file = ::openat(descriptor_, encoded.constData(), flags, 0600);
    if (file < 0)
        throw Error(errno == ELOOP ? ExitCode::Permission : ExitCode::Disk,
                    QStringLiteral("无法安全打开持久接收文件"), "receive");
    struct stat info;
    if (::fstat(file, &info) != 0 || !S_ISREG(info.st_mode)) {
        ::close(file);
        throw Error(ExitCode::Permission, QStringLiteral("持久接收目标不是普通文件"), "receive");
    }
    return file;
}

// 日期：2026-11-04；文件同步不替代目录项同步，重命名后必须显式执行并检查错误。
void PosixDirectory::synchronize() const {
    verify();
    if (::fsync(descriptor_) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("提交名称已发布但目录同步失败"), "commit");
}

// 日期：2026-11-04；拒绝权限过宽的旧目录，不静默修改用户已有目录的权限。
void PosixDirectory::verifyPrivate() const {
    verify();
    struct stat info;
    if (::fstat(descriptor_, &info) != 0 || info.st_uid != ::geteuid() ||
        (info.st_mode & 0077) != 0)
        throw Error(ExitCode::Permission, QStringLiteral("私有状态目录的所有者或权限不安全"),
                    "identity");
}

// 日期：2026-11-04；renameat 原子发布已同步临时文件，fsync 目录失败必须报告持久化未知。
void PosixDirectory::replaceTemporary(const QString &name, const QString &destination) const {
    verifyPrivate();
    for (const auto &component : {name, destination})
        if (component.isEmpty() || component == "." || component == ".." ||
            component.contains('/') || component.contains(QChar::Null))
            throw Error(ExitCode::Permission, QStringLiteral("私有状态文件名无效"), "identity");
    const auto from = QFile::encodeName(name);
    const auto to = QFile::encodeName(destination);
    if (::renameat(descriptor_, from.constData(), descriptor_, to.constData()) != 0)
        throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "identity");
    if (::fsync(descriptor_) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("状态已替换但目录同步失败，持久化结果未知"),
                    "identity");
}

// 日期：2026-11-04；使用 openat 保证目录替换无法将临时数据重定向到符号链接的外部目标。
int PosixDirectory::createTemporary(QString &name) const {
    verify();
    for (int attempt = 0; attempt < 16; ++attempt) {
        const auto candidate =
            ".dukto-" + QUuid::createUuid().toString(QUuid::WithoutBraces) + ".part";
        const auto encoded = QFile::encodeName(candidate);
        const int file = ::openat(descriptor_, encoded.constData(),
                                  O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (file >= 0) {
            name = candidate;
            return file;
        }
        if (errno != EEXIST)
            throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "write");
    }
    throw Error(ExitCode::Disk, QStringLiteral("无法分配唯一的接收临时名称"), "write");
}

// 日期：2026-11-04；同目录描述符的原子不覆盖命名，不再经绝对路径重新打开被替换的父目录。
bool PosixDirectory::commitTemporary(const QString &name, const QString &destination) const {
    verify();
    const auto from = QFile::encodeName(name);
    const auto to = QFile::encodeName(destination);
#if defined(Q_OS_LINUX) && defined(SYS_renameat2)
    if (syscall(SYS_renameat2, descriptor_, from.constData(), descriptor_, to.constData(), 1U) == 0)
        return true;
    if (errno == EEXIST || errno == ENOTEMPTY)
        return false;
    if (errno != ENOSYS && errno != EINVAL && errno != EOPNOTSUPP)
        throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "commit");
#elif defined(Q_OS_MACOS)
    if (renameatx_np(descriptor_, from.constData(), descriptor_, to.constData(), RENAME_EXCL) == 0)
        return true;
    if (errno == EEXIST || errno == ENOTEMPTY)
        return false;
    if (errno != ENOTSUP && errno != EINVAL)
        throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "commit");
#endif
    if (::linkat(descriptor_, from.constData(), descriptor_, to.constData(), 0) != 0) {
        if (errno == EEXIST)
            return false;
        throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "commit");
    }
    if (::unlinkat(descriptor_, from.constData(), 0) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("文件已提交，但临时名称清理失败"), "commit");
    return true;
}

// 日期：2026-11-05；相对固定父描述符发布普通文件，拒绝不安全目标；同用户外部写入不提供 CAS。
void PosixDirectory::replaceReceived(const QString &name, const QString &destination) const {
    verify();
    if (name == destination)
        throw Error(ExitCode::Config, QStringLiteral("覆盖源和目标不能相同"), "commit");
    for (const auto &component : {name, destination})
        if (component.isEmpty() || component == "." || component == ".." ||
            component.contains('/') || component.contains(QChar::Null))
            throw Error(ExitCode::Permission, QStringLiteral("覆盖文件名无效"), "commit");
    const auto from = QFile::encodeName(name);
    const auto to = QFile::encodeName(destination);
    struct stat information;
    if (::fstatat(descriptor_, from.constData(), &information, AT_SYMLINK_NOFOLLOW) != 0 ||
        !S_ISREG(information.st_mode))
        throw Error(ExitCode::Integrity, QStringLiteral("覆盖临时项不是普通文件"), "commit");
    if (::fstatat(descriptor_, to.constData(), &information, AT_SYMLINK_NOFOLLOW) == 0) {
        if (!S_ISREG(information.st_mode))
            throw Error(ExitCode::Permission, QStringLiteral("覆盖目标不是普通文件"), "conflict");
        if (!(information.st_mode & (S_IWUSR | S_IWGRP | S_IWOTH)))
            throw Error(ExitCode::Permission, QStringLiteral("覆盖目标为只读文件"), "conflict");
    } else if (errno != ENOENT) {
        throw Error(ExitCode::Disk, QStringLiteral("无法核对覆盖目标"), "commit");
    }
    if (::renameat(descriptor_, from.constData(), descriptor_, to.constData()) != 0)
        throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "commit");
    synchronize();
}

// 日期：2026-11-04；不使用原绝对路径，父目录改名后仍能正确清理本任务的临时文件。
void PosixDirectory::removeTemporary(const QString &name) const {
    if (!name.isEmpty()) {
        const auto encoded = QFile::encodeName(name);
        ::unlinkat(descriptor_, encoded.constData(), 0);
    }
}

// 日期：2026-11-07；固定父描述符下显式清理临时项，拒绝路径分量并严格报告系统删除失败。
void PosixDirectory::discardTemporary(const QString &name) const {
    if (!name.startsWith(".dukto-") || !name.endsWith(".part") || name.contains('/') ||
        name.contains(QChar::Null))
        throw Error(ExitCode::Permission, QStringLiteral("临时文件清理名称无效"), "doctor");
    const auto encoded = QFile::encodeName(name);
    if (::unlinkat(descriptor_, encoded.constData(), 0) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("临时文件清理失败"), "doctor");
}

// 日期：2026-11-04；只解除单层名字，不递归删除，不跟随链接指向的目标。
void PosixDirectory::removeEntry(const QString &name) const {
    verifyPrivate();
    if (name.isEmpty() || name == "." || name == ".." || name.contains('/') ||
        name.contains(QChar::Null))
        throw Error(ExitCode::Permission, QStringLiteral("私有状态删除键无效"), "identity");
    const auto encoded = QFile::encodeName(name);
    if (::unlinkat(descriptor_, encoded.constData(), 0) != 0 && errno != ENOENT)
        throw Error(ExitCode::Disk, QStringLiteral("私有状态文件清理失败"), "identity");
}

// 日期：2026-11-05；只删除原生身份仍匹配的普通临时项；POSIX不宣称具备外部改名CAS。
void PosixDirectory::removeOwnedTemporary(const QString &name, const QByteArray &identity,
                                          bool directory) const {
    verify();
    if (name.isEmpty() || name == "." || name == ".." || name.contains('/') ||
        name.contains(QChar::Null) || identity.isEmpty())
        throw Error(ExitCode::Permission, QStringLiteral("临时清理键或身份无效"), "receive");
    const auto encoded = QFile::encodeName(name);
    struct stat info;
    if (::fstatat(descriptor_, encoded.constData(), &info, AT_SYMLINK_NOFOLLOW) != 0) {
        if (errno == ENOENT) {
            synchronize();
            return;
        }
        throw Error(ExitCode::Disk, QStringLiteral("无法核对待清理临时项"), "receive");
    }
    const auto observed = QByteArray::number(static_cast<qulonglong>(info.st_dev)) + ':' +
                          QByteArray::number(static_cast<qulonglong>(info.st_ino));
    if ((directory ? !S_ISDIR(info.st_mode) : !S_ISREG(info.st_mode)) || observed != identity)
        throw Error(ExitCode::Integrity, QStringLiteral("待清理临时项已被替换"), "receive");
    verify();
    if (::unlinkat(descriptor_, encoded.constData(), directory ? AT_REMOVEDIR : 0) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("自有临时项清理失败，保留证据"), "receive");
    synchronize();
}

// 日期：2026-11-04；目录树同名分配也使用相对固定句柄的 mkdirat，避免符号链接替换重定向。
bool PosixDirectory::createChild(const QString &name) const {
    verify();
    const auto encoded = QFile::encodeName(name);
    if (::mkdirat(descriptor_, encoded.constData(), 0700) == 0)
        return true;
    if (errno == EEXIST)
        return false;
    throw Error(ExitCode::Disk, QString::fromLocal8Bit(std::strerror(errno)), "path");
}
#endif

#ifdef Q_OS_WIN
// 日期：2026-11-04；只读取对象自身属性，junction、符号链接和其他重解析点使用相同拒绝策略。
bool isNativeReparsePoint(const QString &path) {
    const auto native = nativeLongPath(path);
    const auto attributes = GetFileAttributesW(reinterpret_cast<LPCWSTR>(native.utf16()));
    return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_REPARSE_POINT);
}

// 日期：2026-11-04；Windows 只使用不覆盖的原生命名操作，不允许最终名称出现部分复制内容。
bool renameNoReplace(const QString &source, const QString &destination, bool durable) {
    const auto from = nativeLongPath(source);
    const auto to = nativeLongPath(destination);
    if (MoveFileExW(reinterpret_cast<LPCWSTR>(from.utf16()), reinterpret_cast<LPCWSTR>(to.utf16()),
                    durable ? MOVEFILE_WRITE_THROUGH : 0))
        return true;
    const auto code = GetLastError();
    if (code == ERROR_ALREADY_EXISTS || code == ERROR_FILE_EXISTS ||
        (code == ERROR_ACCESS_DENIED &&
         GetFileAttributesW(reinterpret_cast<LPCWSTR>(to.utf16())) != INVALID_FILE_ATTRIBUTES))
        return false;
    throw Error(ExitCode::Disk, QStringLiteral("原生文件提交失败，系统错误码 %1").arg(code),
                "commit");
}
#endif

#ifdef Q_OS_WIN
// 日期：2026-11-06；共享占用可短暂等待；固定已验源禁止写入，所有尝试仍仅用同目录原子替换。
void replaceReceivedFile(const QString &source, const QString &destination,
                         const QByteArray &expectedIdentity, const std::function<void()> &check) {
    const QFileInfo fromInfo(source), toInfo(destination);
    if (fromInfo.absolutePath() != toInfo.absolutePath() ||
        fromInfo.fileName().compare(toInfo.fileName(), Qt::CaseInsensitive) == 0 ||
        expectedIdentity.isEmpty())
        throw Error(ExitCode::Config, QStringLiteral("覆盖必须绑定同目录的不同名称及已验身份"),
                    "commit");
    // 日期：2026-11-06；源固定句柄具备正文读取权，先占数据文件额度；属性探针不占正文额度。
    DataFileCredit credit;
    NativeDirectoryLock parent(toInfo.absolutePath(), false);
    const auto from = nativeLongPath(source);
    const auto to = nativeLongPath(destination);
    const auto release = [](void *handle) {
        // 日期：2026-11-06；正常返回、取消和异常均释放源句柄，不能让下一个文件继承占用。
        CloseHandle(handle);
    };
    std::unique_ptr<void, decltype(release)> pinned(nullptr, release);
    QElapsedTimer elapsed;
    elapsed.start();
    DWORD error = ERROR_SUCCESS;
    for (int attempt = 1;; ++attempt) {
        if (check)
            check();
        for (const auto &path : {from, to}) {
            const auto attributes = GetFileAttributesW(reinterpret_cast<LPCWSTR>(path.utf16()));
            if (attributes == INVALID_FILE_ATTRIBUTES) {
                if (path == to && GetLastError() == ERROR_FILE_NOT_FOUND)
                    continue;
                throw Error(ExitCode::Disk, QStringLiteral("无法核对覆盖文件属性"), "commit");
            }
            if (attributes &
                (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE))
                throw Error(ExitCode::Permission, QStringLiteral("覆盖只允许普通文件"), "conflict");
            if (path == to && (attributes & FILE_ATTRIBUTE_READONLY))
                throw Error(ExitCode::Permission, QStringLiteral("覆盖目标为只读文件"), "conflict");
        }
        if (!pinned) {
            // 日期：2026-11-06；共享删除允许本次原子改名，拒绝共享写入保证等待期间正文不能被改写。
            const auto handle = CreateFileW(reinterpret_cast<LPCWSTR>(from.utf16()), GENERIC_READ,
                                            FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr,
                                            OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            if (handle == INVALID_HANDLE_VALUE)
                error = GetLastError();
            else {
                pinned.reset(handle);
                if (replacementIdentity(handle) != expectedIdentity)
                    throw Error(ExitCode::Integrity, QStringLiteral("覆盖源原生身份与持久记录不同"),
                                "commit");
            }
        }
        if (pinned) {
            // 日期：2026-11-06；外部仍可改源名称，每次尝试均重开路径核对固定对象，不能发布同名替身。
            const auto observed =
                CreateFileW(reinterpret_cast<LPCWSTR>(from.utf16()), FILE_READ_ATTRIBUTES,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                            OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
            if (observed == INVALID_HANDLE_VALUE)
                error = GetLastError();
            else {
                std::unique_ptr<void, decltype(release)> current(observed, release);
                if (replacementIdentity(observed) != expectedIdentity)
                    throw Error(ExitCode::Integrity, QStringLiteral("覆盖等待期间源路径已被替换"),
                                "commit");
                if (MoveFileExW(reinterpret_cast<LPCWSTR>(from.utf16()),
                                reinterpret_cast<LPCWSTR>(to.utf16()),
                                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
                    return;
                error = GetLastError();
            }
        }
        const bool retryable = error == ERROR_ACCESS_DENIED || error == ERROR_SHARING_VIOLATION ||
                               error == ERROR_LOCK_VIOLATION;
        if (!retryable || attempt >= 21 || elapsed.elapsed() >= 500)
            throw Error(
                ExitCode::Disk,
                QStringLiteral("原子覆盖失败，系统错误码 %1，已尝试 %2 次").arg(error).arg(attempt),
                retryable ? "commit-busy" : "commit");
        const auto until = qMin<qint64>(500, elapsed.elapsed() + 25);
        while (elapsed.elapsed() < until) {
            if (check)
                check();
            QThread::msleep(5);
        }
    }
}
#endif

// 日期：2026-11-05；Windows锁定父目录并以DELETE句柄验证/删除同一对象，POSIX使用固定父描述符。
void removeReceivedTemporary(const QString &path, const QByteArray &identity, bool directory) {
    const QFileInfo information(path);
#ifdef Q_OS_WIN
    NativeDirectoryLock parent(information.absolutePath(), false);
    const auto native = nativeLongPath(path);
    const auto handle = CreateFileW(
        reinterpret_cast<LPCWSTR>(native.utf16()), DELETE | FILE_READ_ATTRIBUTES, FILE_SHARE_READ,
        nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    if (handle == INVALID_HANDLE_VALUE) {
        if (GetLastError() == ERROR_FILE_NOT_FOUND)
            return;
        throw Error(ExitCode::Disk, QStringLiteral("无法固定待清理临时项"), "receive");
    }
    try {
        BY_HANDLE_FILE_INFORMATION info;
        if (GetFileType(handle) != FILE_TYPE_DISK || !GetFileInformationByHandle(handle, &info) ||
            (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) ||
            bool(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != directory)
            throw Error(ExitCode::Integrity, QStringLiteral("待清理临时项类型已变化"), "receive");
        const auto observed =
            QByteArray::number(static_cast<qulonglong>(info.dwVolumeSerialNumber)) + ':' +
            QByteArray::number(static_cast<qulonglong>(info.nFileIndexHigh)) + ':' +
            QByteArray::number(static_cast<qulonglong>(info.nFileIndexLow));
        if (identity.isEmpty() || observed != identity)
            throw Error(ExitCode::Integrity, QStringLiteral("待清理临时项身份已变化"), "receive");
        FILE_DISPOSITION_INFO disposition;
        disposition.DeleteFile = TRUE;
        if (!SetFileInformationByHandle(handle, FileDispositionInfo, &disposition,
                                        sizeof(disposition)))
            throw Error(ExitCode::Disk, QStringLiteral("自有临时项清理失败，保留证据"), "receive");
    } catch (...) {
        CloseHandle(handle);
        throw;
    }
    if (!CloseHandle(handle))
        throw Error(ExitCode::Disk, QStringLiteral("临时清理句柄关闭失败"), "receive");
#else
    PosixDirectory parent(information.absolutePath(), false);
    parent.removeOwnedTemporary(information.fileName(), identity, directory);
#endif
}

// 日期：2026-11-06；同名别名共用预约；Windows短暂创建拒绝有界重试，持续失败保留分类。
TargetReservation::TargetReservation(const QString &destination) {
    const QFileInfo information(destination);
    if (!QDir::isAbsolutePath(destination) || information.fileName().isEmpty())
        throw Error(ExitCode::Config, QStringLiteral("目标预约需要绝对文件路径"), "conflict");
#ifdef Q_OS_WIN
    parent_.reset(new NativeDirectoryLock(information.absolutePath(), false));
#else
    parent_.reset(new PosixDirectory(information.absolutePath(), false));
#endif
    const auto key =
        QCryptographicHash::hash(
            information.fileName().normalized(QString::NormalizationForm_C).toCaseFolded().toUtf8(),
            QCryptographicHash::Sha256)
            .toHex();
    lock_.reset(
        new QLockFile(QDir(information.absolutePath())
                          .filePath(".dukto-target-" + QString::fromLatin1(key) + ".lock")));
    lock_->setStaleLockTime(0);
#ifdef Q_OS_WIN
    // 日期：2026-11-06；Qt5在CREATE_NEW拒绝后再查询存在性，解锁竞争可被误归为PermissionError。
    // 仅该分类以10ms间隔重试，总预算100ms/最多11次；正常活动锁立即返回，UnknownError绝不重试。
    QElapsedTimer elapsed;
    elapsed.start();
    for (int attempt = 0;; ++attempt) {
        acquired_ = lock_->tryLock(0);
        if (acquired_ || lock_->error() != QLockFile::PermissionError || attempt >= 10)
            break;
        const qint64 remaining = 100 - elapsed.elapsed();
        if (remaining <= 0)
            break;
        QThread::msleep(static_cast<unsigned long>(qMin<qint64>(10, remaining)));
    }
#else
    acquired_ = lock_->tryLock(0);
#endif
    if (!acquired_ && lock_->error() != QLockFile::LockFailedError) {
        const auto qtError = static_cast<int>(lock_->error());
#ifdef Q_OS_WIN
        const auto observed = GetLastError();
        throw Error(ExitCode::Disk,
                    QStringLiteral("reservation-create qt-lock-error=%1 observed-win-error=%2")
                        .arg(qtError)
                        .arg(observed),
                    "conflict");
#else
        throw Error(ExitCode::Disk, QStringLiteral("无法创建目标预约，Qt错误码 %1").arg(qtError),
                    "conflict");
#endif
    }
}

// 日期：2026-11-05；成员逆序析构，QLockFile 在固定父目录释放前清理自己持有的锁。
TargetReservation::~TargetReservation() = default;

// 日期：2026-11-05；活动预约不自动等待或抢占，不按任意时间判定活动进程已失效。
bool TargetReservation::acquired() const {
    return acquired_;
}
} // namespace dukto

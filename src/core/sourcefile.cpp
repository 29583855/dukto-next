#include "sourcefile.h"
#include "error.h"

#include <QDir>
#include <QFileInfo>
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
// 日期：2026-11-04；只作进程内身份比较，明确取字段，避免填充字节导致不确定的变化判断。
QByteArray fileIdentity(int descriptor) {
    QByteArray result;
#ifdef Q_OS_WIN
    const auto handle = reinterpret_cast<HANDLE>(_get_osfhandle(descriptor));
    BY_HANDLE_FILE_INFORMATION info;
    if (GetFileType(handle) != FILE_TYPE_DISK || !GetFileInformationByHandle(handle, &info))
        throw Error(ExitCode::Disk, QStringLiteral("无法读取源文件原生属性"), "read");
    if (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY))
        throw Error(ExitCode::Permission, QStringLiteral("源文件不是普通文件或属于重解析点"),
                    "read");
    for (const auto value :
         {info.dwVolumeSerialNumber, info.nFileIndexHigh, info.nFileIndexLow, info.nFileSizeHigh,
          info.nFileSizeLow, info.ftLastWriteTime.dwHighDateTime,
          info.ftLastWriteTime.dwLowDateTime})
        result += QByteArray::number(static_cast<qulonglong>(value)) + ':';
#else
    struct stat info;
    if (::fstat(descriptor, &info) != 0)
        throw Error(ExitCode::Disk, QStringLiteral("无法读取源文件原生属性"), "read");
    if (!S_ISREG(info.st_mode))
        throw Error(ExitCode::Permission, QStringLiteral("源文件不是普通文件"), "read");
    result = QByteArray::number(static_cast<qulonglong>(info.st_dev)) + ':' +
             QByteArray::number(static_cast<qulonglong>(info.st_ino)) + ':' +
             QByteArray::number(static_cast<qlonglong>(info.st_size)) + ':';
#ifdef Q_OS_MACOS
    for (const auto &time : {info.st_mtimespec, info.st_ctimespec})
#else
    for (const auto &time : {info.st_mtim, info.st_ctim})
#endif
        result += QByteArray::number(static_cast<qlonglong>(time.tv_sec)) + ':' +
                  QByteArray::number(static_cast<qlonglong>(time.tv_nsec)) + ':';
#endif
    return result;
}
} // namespace

// 日期：2026-11-04；Windows 不共享删除，拒绝链接本身；POSIX 通过固定父目录的 openat 打开。
SourceFile::SourceFile(const QString &path) {
    const QFileInfo info(path);
    int descriptor = -1;
#ifdef Q_OS_WIN
    parent_.reset(new NativeDirectoryLock(info.absolutePath(), false));
    auto native = QDir::toNativeSeparators(info.absoluteFilePath());
    if (!native.startsWith("\\\\?\\"))
        native = native.startsWith("\\\\") ? "\\\\?\\UNC\\" + native.mid(2) : "\\\\?\\" + native;
    const auto handle = CreateFileW(
        reinterpret_cast<LPCWSTR>(native.utf16()), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, nullptr);
    if (handle == INVALID_HANDLE_VALUE)
        throw Error(ExitCode::Disk,
                    QStringLiteral("无法安全打开源文件，系统错误码 %1").arg(GetLastError()),
                    "read");
    descriptor = _open_osfhandle(reinterpret_cast<intptr_t>(handle), _O_RDONLY | _O_BINARY);
    if (descriptor < 0) {
        CloseHandle(handle);
        throw Error(ExitCode::Disk, QStringLiteral("无法接管源文件句柄"), "read");
    }
#else
    parent_.reset(new PosixDirectory(info.absolutePath(), false));
    name_ = info.fileName();
    descriptor = parent_->openRead(name_);
#endif
    if (!file_.open(descriptor, QIODevice::ReadOnly, QFileDevice::AutoCloseHandle)) {
#ifdef Q_OS_WIN
        _close(descriptor);
#else
        ::close(descriptor);
#endif
        throw Error(ExitCode::Disk, file_.errorString(), "read");
    }
    identity_ = fileIdentity(file_.handle());
}

// 日期：2026-11-04；成员按声明逆序析构，文件的关闭先于父目录锁的释放。
SourceFile::~SourceFile() = default;

// 日期：2026-11-04；不得把引用交给其他线程或保留到 SourceFile 生命周期之外。
QFile &SourceFile::device() {
    return file_;
}

// 日期：2026-11-04；路径替换不会读取替换后的数据，检测到替换或原生属性变化时拒绝成功。
void SourceFile::verify() const {
    if (fileIdentity(file_.handle()) != identity_)
        throw Error(ExitCode::Integrity, QStringLiteral("读取期间源文件已变化"), "read");
#ifndef Q_OS_WIN
    const int current = parent_->openRead(name_);
    QByteArray observed;
    try {
        observed = fileIdentity(current);
    } catch (...) {
        ::close(current);
        throw;
    }
    ::close(current);
    if (observed != identity_)
        throw Error(ExitCode::Integrity, QStringLiteral("源文件路径在读取期间已被替换"), "read");
#endif
}
} // namespace dukto

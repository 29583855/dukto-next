#if defined(_WIN32) && !defined(_WIN32_WINNT)
#define _WIN32_WINNT 0x0602
#endif
#include "buffercredit.h"
#include "error.h"
#include "privatestore.h"
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QStringList>
#include <array>
#include <cstring>
#include <limits>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <cerrno>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>
#endif

namespace dukto {
namespace {
// 日期：2026-11-07；目录计数和逻辑长度只允许非负有符号64位数，溢出不能变成小额占用。
void accumulate(qint64 &total, qint64 value) {
    if (value < 0 || total > std::numeric_limits<qint64>::max() - value)
        throw Error(ExitCode::Integrity, QStringLiteral("状态占用计数超出64位范围"), "storage");
    total += value;
}

// 日期：2026-11-07；仅按固定后缀计量，不凭文件名断言所有权、任务状态或删除资格。
int category(const QString &name) {
    static const QStringList suffixes{".sqlite",     ".sqlite-journal", ".sqlite-wal",
                                      ".sqlite-shm", ".json",           ".lock"};
    for (int index = 0; index < suffixes.size(); ++index)
        if (name.endsWith(suffixes[index], Qt::CaseSensitive))
            return index;
    return 6;
}
} // namespace

#ifdef Q_OS_WIN
// 日期：2026-11-08；固定父路径后逐项读取原生身份和分配量，不跟随重解析点，只保留一个项和句柄。
void NativeDirectoryLock::visitEntries(
    const std::function<void(const NativeDirectoryEntry &)> &visitor) const {
    const auto before = stamp();
    if (handles_.empty())
        throw Error(ExitCode::Permission, QStringLiteral("状态目录句柄无效"), "storage");
    DWORD length = GetFinalPathNameByHandleW(handles_.back(), nullptr, 0, FILE_NAME_NORMALIZED);
    if (!length || length > 32768)
        throw Error(ExitCode::Disk, QStringLiteral("无法取得固定状态目录路径"), "storage");
    std::vector<wchar_t> buffer(length + 1);
    const auto actual = GetFinalPathNameByHandleW(handles_.back(), buffer.data(),
                                                  DWORD(buffer.size()), FILE_NAME_NORMALIZED);
    if (!actual || actual >= buffer.size())
        throw Error(ExitCode::Disk, QStringLiteral("状态目录路径读取失败"), "storage");
    const auto directory = QString::fromWCharArray(buffer.data(), int(actual));
    const auto pattern = directory + "\\*";
    WIN32_FIND_DATAW data{};
    HANDLE search = FindFirstFileW(reinterpret_cast<LPCWSTR>(pattern.utf16()), &data);
    if (search == INVALID_HANDLE_VALUE) {
        if (GetLastError() == ERROR_FILE_NOT_FOUND && stamp() == before)
            return;
        throw Error(ExitCode::Disk, QStringLiteral("无法枚举私有状态目录"), "storage");
    }
    struct SearchGuard {
        HANDLE value;
        // 日期：2026-11-07；正常结束、取消和回调异常均关闭原生枚举句柄。
        ~SearchGuard() {
            FindClose(value);
        }
    } guard{search};
    for (;;) {
        NativeDirectoryEntry entry;
        entry.name = QString::fromWCharArray(data.cFileName);
        if (entry.name != "." && entry.name != "..") {
            const auto path = directory + '\\' + entry.name;
            const auto handle = CreateFileW(
                reinterpret_cast<LPCWSTR>(path.utf16()), FILE_READ_ATTRIBUTES,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS, nullptr);
            if (handle == INVALID_HANDLE_VALUE)
                throw Error(ExitCode::Disk, QStringLiteral("无法核对状态目录项属性"), "storage");
            BY_HANDLE_FILE_INFORMATION info{};
            const auto type = GetFileType(handle);
            const bool ok = GetFileInformationByHandle(handle, &info);
            FILE_ID_INFO identity{};
            FILE_STANDARD_INFO standard{};
            const bool regular =
                ok && type == FILE_TYPE_DISK &&
                !(info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY |
                                           FILE_ATTRIBUTE_DEVICE));
            const bool details =
                !regular ||
                (GetFileInformationByHandleEx(handle, FileIdInfo, &identity, sizeof(identity)) &&
                 GetFileInformationByHandleEx(handle, FileStandardInfo, &standard,
                                              sizeof(standard)));
            CloseHandle(handle);
            if (!ok || !details)
                throw Error(ExitCode::Disk, QStringLiteral("读取状态目录项属性失败"), "storage");
            if (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)
                entry.kind = NativeDirectoryEntry::Kind::Link;
            else if (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
                entry.kind = NativeDirectoryEntry::Kind::Directory;
            else if (regular) {
                if (standard.Directory || standard.EndOfFile.QuadPart < 0 ||
                    standard.AllocationSize.QuadPart < 0 || !standard.NumberOfLinks)
                    throw Error(ExitCode::Integrity,
                                QStringLiteral("状态文件长度、分配量或链接计数无效"), "storage");
                entry.kind = NativeDirectoryEntry::Kind::Regular;
                entry.bytes = standard.EndOfFile.QuadPart;
                entry.links = standard.NumberOfLinks;
                entry.allocatedBytes = standard.AllocationSize.QuadPart;
                entry.identityPlatform = 2;
                entry.volume = identity.VolumeSerialNumber;
                std::memcpy(entry.identity.data(), identity.FileId.Identifier,
                            entry.identity.size());
            }
            visitor(entry);
        }
        if (!FindNextFileW(search, &data)) {
            if (GetLastError() != ERROR_NO_MORE_FILES)
                throw Error(ExitCode::Disk, QStringLiteral("状态目录枚举未完成"), "storage");
            break;
        }
    }
    if (stamp() != before)
        throw Error(ExitCode::Integrity, QStringLiteral("状态目录在计量期间发生变化"), "storage");
}
#else
// 日期：2026-11-08；固定目录描述符上fstatat取得身份及分配量，不另开数据文件而释放POSIX数据库锁。
void PosixDirectory::visitEntries(
    const std::function<void(const NativeDirectoryEntry &)> &visitor) const {
    const auto before = stamp();
    const int descriptor = ::openat(descriptor_, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (descriptor < 0)
        throw Error(ExitCode::Disk, QStringLiteral("无法打开状态目录枚举流"), "storage");
    DIR *stream = ::fdopendir(descriptor);
    if (!stream) {
        ::close(descriptor);
        throw Error(ExitCode::Disk, QStringLiteral("无法建立状态目录枚举流"), "storage");
    }
    struct StreamGuard {
        DIR *value;
        // 日期：2026-11-07；closedir同时归还独立目录描述符，不能在重复观察或异常后积累句柄。
        ~StreamGuard() {
            ::closedir(value);
        }
    } guard{stream};
    for (;;) {
        errno = 0;
        const auto item = ::readdir(stream);
        if (!item) {
            if (errno)
                throw Error(ExitCode::Disk, QStringLiteral("状态目录枚举未完成"), "storage");
            break;
        }
        const QByteArray name(item->d_name);
        if (name == "." || name == "..")
            continue;
        struct stat info{};
        if (::fstatat(descriptor, item->d_name, &info, AT_SYMLINK_NOFOLLOW) != 0)
            throw Error(ExitCode::Disk, QStringLiteral("无法核对状态目录项属性"), "storage");
        NativeDirectoryEntry entry;
        entry.name = QFile::decodeName(name);
        if (S_ISLNK(info.st_mode))
            entry.kind = NativeDirectoryEntry::Kind::Link;
        else if (S_ISDIR(info.st_mode))
            entry.kind = NativeDirectoryEntry::Kind::Directory;
        else if (S_ISREG(info.st_mode)) {
            if (info.st_size < 0 || !info.st_nlink || info.st_blocks < 0 ||
                quint64(info.st_blocks) > quint64(std::numeric_limits<qint64>::max()) / 512)
                throw Error(ExitCode::Integrity,
                            QStringLiteral("状态文件长度、分配量或链接计数无效"), "storage");
            entry.kind = NativeDirectoryEntry::Kind::Regular;
            entry.bytes = info.st_size;
            entry.links = info.st_nlink;
            entry.allocatedBytes = qint64(info.st_blocks) * 512;
            entry.identityPlatform = 1;
            entry.volume = quint64(info.st_dev);
            auto inode = quint64(info.st_ino);
            for (size_t index = 0; index < sizeof(inode); ++index) {
                entry.identity[index] = static_cast<unsigned char>(inode & 255);
                inode >>= 8;
            }
        }
        visitor(entry);
    }
    if (stamp() != before)
        throw Error(ExitCode::Integrity, QStringLiteral("状态目录在计量期间发生变化"), "storage");
}
#endif

// 日期：2026-11-08；独占维护下逐项观察，统一取消/根核验/缓冲授信；回调抛出时仍归还所有枚举资源。
void PrivateStore::visitStorageEntries(
    const std::function<void(const NativeDirectoryEntry &)> &visitor,
    const std::function<void()> &check) const {
    if (!maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("状态占用计量需要独占维护"), "storage");
    if (!visitor)
        throw Error(ExitCode::Config, QStringLiteral("状态观察回调不能为空"), "storage");
    BufferCredit credit(256 * 1024);
    const auto before = root_->stamp();
    qint64 entries = 0;
    if (check)
        check();
    root_->visitEntries([&](const NativeDirectoryEntry &entry) {
        // 日期：2026-11-08；每项取消、每64项重验，观察接口不保留随文件数增长的对象列表。
        if (check)
            check();
        if (entries % 64 == 0)
            verify();
        accumulate(entries, 1);
        visitor(entry);
    });
    if (check)
        check();
    verify();
    if (root_->stamp() != before)
        throw Error(ExitCode::Integrity, QStringLiteral("状态目录在计量期间发生变化"), "storage");
}

// 日期：2026-11-08；直接普通文件按名称保守合计逻辑长度与系统分配量，不据瞬时身份自动去重或删除。
QJsonObject PrivateStore::storageUsage(const std::function<void()> &check) const {
    const auto observed = QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs);
    std::array<qint64, 7> files{};
    std::array<qint64, 7> bytes{};
    std::array<qint64, 7> allocations{};
    qint64 allocated = 0;
    qint64 entries = 0, regular = 0, logical = 0, directories = 0, links = 0, other = 0, hard = 0;
    visitStorageEntries(
        [&](const NativeDirectoryEntry &entry) {
            // 日期：2026-11-08；七类汇总均为检查过的64位数，硬链接仍按名称保守重复计量。
            accumulate(entries, 1);
            if (entry.kind == NativeDirectoryEntry::Kind::Regular) {
                const int index = category(entry.name);
                accumulate(regular, 1);
                accumulate(logical, entry.bytes);
                accumulate(allocated, entry.allocatedBytes);
                accumulate(files[index], 1);
                accumulate(bytes[index], entry.bytes);
                accumulate(allocations[index], entry.allocatedBytes);
                if (entry.links > 1)
                    accumulate(hard, 1);
            } else if (entry.kind == NativeDirectoryEntry::Kind::Directory)
                accumulate(directories, 1);
            else if (entry.kind == NativeDirectoryEntry::Kind::Link)
                accumulate(links, 1);
            else
                accumulate(other, 1);
        },
        check);
    QJsonArray categories;
    const QStringList names{"sqlite", "rollback", "wal", "shared-memory", "json", "locks", "other"};
    for (int index = 0; index < names.size(); ++index)
        categories.append(QJsonObject{{"kind", names[index]},
                                      {"files", QString::number(files[index])},
                                      {"logicalBytes", QString::number(bytes[index])},
                                      {"allocatedBytes", QString::number(allocations[index])}});
    qint64 sidecars = 0, sidecarAllocated = 0;
    for (const auto index : {1, 2, 3}) {
        accumulate(sidecars, bytes[index]);
        accumulate(sidecarAllocated, allocations[index]);
    }
    return {
        {"eventVersion", 1},
        {"event", "state-storage"},
        {"scope", "direct-private-state"},
        {"stateDirectory", directory_},
        {"observedUtc", observed},
        {"entries", QString::number(entries)},
        {"regularFiles", QString::number(regular)},
        {"logicalBytes", QString::number(logical)},
        {"allocatedBytes", QString::number(allocated)},
        {"sqliteSidecarBytes", QString::number(sidecars)},
        {"sqliteSidecarAllocatedBytes", QString::number(sidecarAllocated)},
        {"excludedDirectories", QString::number(directories)},
        {"excludedLinks", QString::number(links)},
        {"excludedSpecial", QString::number(other)},
        {"hardLinkedNames", QString::number(hard)},
        {"directRegularFilesOnly", directories == 0 && links == 0 && other == 0},
        {"categories", categories},
        {"message",
         QStringLiteral("仅计量状态根直接普通文件的逻辑长度和系统报告分配量；"
                        "硬链接按名称重复计量，不含正文及子目录，不代表独占物理占用或删除资格")}};
}
} // namespace dukto

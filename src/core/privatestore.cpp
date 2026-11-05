#include "privatestore.h"
#include "error.h"
#include "files.h"
#include "sourcefile.h"

#include <QDir>
#include <QFileInfo>
#include <QRegularExpression>
#include <QUuid>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <aclapi.h>
#include <io.h>
#include <sddl.h>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace dukto {
namespace {
#ifdef Q_OS_WIN
// 日期：2026-11-04；访问令牌只取当前用户 SID，不把用户名翻译或组成员身份当作同一安全主体。
QByteArray accountSid() {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
        throw Error(ExitCode::Permission, QStringLiteral("无法取得当前账户访问令牌"), "identity");
    DWORD length = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &length);
    QByteArray bytes(static_cast<int>(length), '\0');
    const bool ok =
        length > 0 && GetTokenInformation(token, TokenUser, bytes.data(), length, &length);
    CloseHandle(token);
    if (!ok)
        throw Error(ExitCode::Permission, QStringLiteral("无法取得当前账户 SID"), "identity");
    const auto sid = reinterpret_cast<TOKEN_USER *>(bytes.data())->User.Sid;
    QByteArray result(static_cast<int>(GetLengthSid(sid)), '\0');
    if (!CopySid(static_cast<DWORD>(result.size()), result.data(), sid))
        throw Error(ExitCode::Permission, QStringLiteral("无法复制当前账户 SID"), "identity");
    return result;
}

// 日期：2026-11-04；只有当前账户可以获得允许 ACE；NULL DACL、其他账户、复杂对象 ACE 均拒绝。
void verifyAcl(HANDLE handle, bool directory) {
    const auto account = accountSid();
    PSID owner = nullptr;
    PACL dacl = nullptr;
    PSECURITY_DESCRIPTOR security = nullptr;
    if (GetSecurityInfo(handle, SE_FILE_OBJECT,
                        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION, &owner, nullptr,
                        &dacl, nullptr, &security) != ERROR_SUCCESS)
        throw Error(ExitCode::Permission, QStringLiteral("无法核对私有状态访问控制"), "identity");
    struct Guard {
        PSECURITY_DESCRIPTOR value;
        // 日期：2026-11-04；GetSecurityInfo 分配的安全描述符始终归还 LocalFree。
        ~Guard() {
            LocalFree(value);
        }
    } guard{security};
    SECURITY_DESCRIPTOR_CONTROL control;
    DWORD revision;
    if (!owner || !dacl || !EqualSid(owner, const_cast<char *>(account.constData())) ||
        !GetSecurityDescriptorControl(security, &control, &revision) ||
        (directory && !(control & SE_DACL_PROTECTED)))
        throw Error(ExitCode::Permission, QStringLiteral("私有状态所有者或继承策略不安全"),
                    "identity");
    bool permitted = false;
    for (DWORD index = 0; index < dacl->AceCount; ++index) {
        void *entry = nullptr;
        if (!GetAce(dacl, index, &entry))
            throw Error(ExitCode::Permission, QStringLiteral("无法检查私有状态 ACE"), "identity");
        const auto header = static_cast<ACE_HEADER *>(entry);
        if (header->AceType != ACCESS_ALLOWED_ACE_TYPE)
            throw Error(ExitCode::Permission, QStringLiteral("私有状态含不受支持的 ACE 类型"),
                        "identity");
        const auto ace = static_cast<ACCESS_ALLOWED_ACE *>(entry);
        if (!EqualSid(const_cast<DWORD *>(&ace->SidStart), const_cast<char *>(account.constData())))
            throw Error(ExitCode::Permission, QStringLiteral("私有状态允许其他账户访问"),
                        "identity");
        if (!(header->AceFlags & INHERIT_ONLY_ACE) && ace->Mask != 0)
            permitted = true;
    }
    if (!permitted)
        throw Error(ExitCode::Permission, QStringLiteral("私有状态未授权当前账户"), "identity");
}

// 日期：2026-11-04；Windows 原生路径统一长路径形式，不改变用户文件名编码。
QString longPath(const QString &path) {
    const auto native = QDir::toNativeSeparators(path);
    if (native.startsWith("\\\\?\\"))
        return native;
    return native.startsWith("\\\\") ? "\\\\?\\UNC\\" + native.mid(2) : "\\\\?\\" + native;
}

// 日期：2026-11-04；显式指定当前账户为所有者，提升权限运行也不依赖默认组所有者。
PSECURITY_DESCRIPTOR privateSecurity() {
    const auto account = accountSid();
    LPWSTR sid = nullptr;
    if (!ConvertSidToStringSidW(const_cast<char *>(account.constData()), &sid))
        throw Error(ExitCode::Permission, QStringLiteral("无法生成账户权限规则"), "identity");
    const auto accountName = QString::fromWCharArray(sid);
    const auto rule = "O:" + accountName + "D:P(A;OICI;FA;;;" + accountName + ')';
    LocalFree(sid);
    PSECURITY_DESCRIPTOR security = nullptr;
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
            reinterpret_cast<LPCWSTR>(rule.utf16()), SDDL_REVISION_1, &security, nullptr))
        throw Error(ExitCode::Permission, QStringLiteral("无法创建私有目录权限规则"), "identity");
    return security;
}

// 日期：2026-11-04；创建时即提供仅当前账户可访问且子项继承的 DACL，秘密写入前不存在宽权限窗口。
void createPrivateDirectory(const QString &path) {
    auto security = privateSecurity();
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), security, FALSE};
    const auto native = longPath(path);
    const bool ok = CreateDirectoryW(reinterpret_cast<LPCWSTR>(native.utf16()), &attributes);
    const auto code = GetLastError();
    LocalFree(security);
    if (!ok && code != ERROR_ALREADY_EXISTS)
        throw Error(ExitCode::Disk, QStringLiteral("创建私有状态目录失败"), "identity");
}
#endif

// 日期：2026-11-04；校验打开的对象权限，避免通过路径检查后重新打开另一个宽权限文件。
void verifyFile(QFile &file) {
#ifdef Q_OS_WIN
    verifyAcl(reinterpret_cast<HANDLE>(_get_osfhandle(file.handle())), false);
#else
    struct stat info;
    if (::fstat(file.handle(), &info) != 0 || info.st_uid != ::geteuid() ||
        (info.st_mode & 0077) != 0 || !S_ISREG(info.st_mode))
        throw Error(ExitCode::Permission, QStringLiteral("私有状态文件的所有者或权限不安全"),
                    "identity");
#endif
}
} // namespace

// 日期：2026-11-04；根已存在时只核对安全性，不自动收紧或更改用户已有目录权限。
PrivateStore::PrivateStore(const QString &directory, bool create)
    : directory_(QDir::cleanPath(QFileInfo(directory).absoluteFilePath())) {
#ifdef Q_OS_WIN
    NativeDirectoryLock parent(QFileInfo(directory_).absolutePath(), false);
    if (create)
        createPrivateDirectory(directory_);
    root_.reset(new NativeDirectoryLock(directory_, false));
#else
    root_.reset(new PosixDirectory(directory_, create));
#endif
    verify();
}

// 日期：2026-11-04；目录句柄由当前实例独占，析构不对状态文件做隐式删除。
PrivateStore::~PrivateStore() = default;

// 日期：2026-11-04；Windows 通过原生安全描述符验证，不能用 QFile 权限标志冒充 ACL 验收。
void PrivateStore::verify() const {
#ifdef Q_OS_WIN
    const auto native = longPath(directory_);
    const auto handle =
        CreateFileW(reinterpret_cast<LPCWSTR>(native.utf16()), READ_CONTROL | FILE_READ_ATTRIBUTES,
                    FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                    FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (handle == INVALID_HANDLE_VALUE)
        throw Error(ExitCode::Permission, QStringLiteral("无法检查私有状态根"), "identity");
    try {
        BY_HANDLE_FILE_INFORMATION info;
        if (!GetFileInformationByHandle(handle, &info) ||
            !(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ||
            (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
            throw Error(ExitCode::Permission, QStringLiteral("私有状态根不是普通目录"), "identity");
        verifyAcl(handle, true);
    } catch (...) {
        CloseHandle(handle);
        throw;
    }
    CloseHandle(handle);
#else
    root_->verifyPrivate();
#endif
}

// 日期：2026-11-04；扩展名可以区分身份/令牌/元数据，其他字符、路径与保留名称一律拒绝。
QString PrivateStore::path(const QString &name) const {
    static const QRegularExpression allowed("\\A[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}\\z");
    if (!allowed.match(name).hasMatch())
        throw Error(ExitCode::Permission, QStringLiteral("私有状态键无效"), "identity");
    validateRelativePath(name);
    return QDir(directory_).filePath(name);
}

// 日期：2026-11-04；大数据库只核对原生权限、文件类型及固定对象，避免整体读取。
qint64 PrivateStore::validateFile(const QString &name) const {
    verify();
    SourceFile source(path(name));
    verifyFile(source.device());
    const auto size = source.device().size();
    source.verify();
    return size;
}

// 日期：2026-11-04；文件不得超过调用方预算，不用 readAll；读取前后均检查固定对象。
QByteArray PrivateStore::read(const QString &name, qint64 maximum) const {
    verify();
    if (maximum <= 0 || maximum > 1024 * 1024)
        throw Error(ExitCode::Config, QStringLiteral("私有状态读取预算无效"), "identity");
    SourceFile source(path(name));
    auto &file = source.device();
    verifyFile(file);
    if (file.size() > maximum)
        throw Error(ExitCode::Config, QStringLiteral("私有状态文件超过预算"), "identity");
    const auto bytes = file.read(maximum + 1);
    if (file.error() != QFileDevice::NoError || bytes.size() > maximum ||
        bytes.size() != file.size())
        throw Error(ExitCode::Disk, QStringLiteral("私有状态文件读取失败"), "identity");
    source.verify();
    return bytes;
}

// 日期：2026-11-04；临时文件名不可预测，Windows 继承受保护根 ACL，POSIX 独占创建 0600。
void PrivateStore::write(const QString &name, const QByteArray &bytes) const {
    verify();
    const auto target = path(name);
    if (bytes.size() > 1024 * 1024)
        throw Error(ExitCode::Config, QStringLiteral("私有状态写入超过预算"), "identity");
    if (QFileInfo::exists(target) || isLinkedPath(target))
        read(name, 1024 * 1024);
#ifdef Q_OS_WIN
    const auto temporary =
        QDir(directory_)
            .filePath(".dukto-" + QUuid::createUuid().toString(QUuid::WithoutBraces) + ".part");
    const auto nativeTemporary = longPath(temporary);
    const auto nativeTarget = longPath(target);
    auto security = privateSecurity();
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), security, FALSE};
    const auto handle = CreateFileW(reinterpret_cast<LPCWSTR>(nativeTemporary.utf16()),
                                    GENERIC_READ | GENERIC_WRITE, 0, &attributes, CREATE_NEW,
                                    FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    LocalFree(security);
    if (handle == INVALID_HANDLE_VALUE)
        throw Error(ExitCode::Disk, QStringLiteral("私有临时状态创建失败"), "identity");
    try {
        verifyAcl(handle, false);
        DWORD written = 0;
        if ((!bytes.isEmpty() && (!WriteFile(handle, bytes.constData(),
                                             static_cast<DWORD>(bytes.size()), &written, nullptr) ||
                                  written != static_cast<DWORD>(bytes.size()))) ||
            !FlushFileBuffers(handle))
            throw Error(ExitCode::Disk, QStringLiteral("私有状态写入或同步失败"), "identity");
    } catch (...) {
        CloseHandle(handle);
        DeleteFileW(reinterpret_cast<LPCWSTR>(nativeTemporary.utf16()));
        throw;
    }
    CloseHandle(handle);
    if (!MoveFileExW(reinterpret_cast<LPCWSTR>(nativeTemporary.utf16()),
                     reinterpret_cast<LPCWSTR>(nativeTarget.utf16()),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileW(reinterpret_cast<LPCWSTR>(nativeTemporary.utf16()));
        throw Error(ExitCode::Disk, QStringLiteral("私有状态原子替换失败"), "identity");
    }
#else
    QString temporary;
    const int descriptor = root_->createTemporary(temporary);
    QFile file;
    if (!file.open(descriptor, QIODevice::WriteOnly, QFileDevice::AutoCloseHandle)) {
        ::close(descriptor);
        root_->removeTemporary(temporary);
        throw Error(ExitCode::Disk, QStringLiteral("无法接管私有临时状态"), "identity");
    }
    try {
        writeAll(file, bytes);
        if (!file.flush() || ::fsync(file.handle()) != 0)
            throw Error(ExitCode::Disk, QStringLiteral("私有状态同步失败"), "identity");
        file.close();
        root_->replaceTemporary(temporary, name);
    } catch (...) {
        file.close();
        root_->removeTemporary(temporary);
        throw;
    }
#endif
}

// 日期：2026-11-04；存在不等于可信，实际加载仍须 read 检查对象类型、所有者和访问权限。
bool PrivateStore::exists(const QString &name) const {
    verify();
    const auto target = path(name);
    return QFileInfo::exists(target) || isLinkedPath(target);
}

// 日期：2026-11-04；状态清理只处理已经辨认出的文件键，删除失败明确保留给下一次清理。
void PrivateStore::remove(const QString &name) const {
    verify();
    const auto target = path(name);
#ifdef Q_OS_WIN
    const auto native = longPath(target);
    if (!DeleteFileW(reinterpret_cast<LPCWSTR>(native.utf16())) &&
        GetLastError() != ERROR_FILE_NOT_FOUND)
        throw Error(ExitCode::Disk, QStringLiteral("私有状态文件清理失败"), "identity");
#else
    root_->removeEntry(name);
#endif
}

// 日期：2026-11-04；目录只用于显式组合状态数据库路径，不输出其中秘密内容。
QString PrivateStore::directory() const {
    return directory_;
}
} // namespace dukto

#include "privatestore.h"
#include "budgetfile.h"
#include "error.h"
#include "files.h"
#include "sourcefile.h"

#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QMutex>
#include <QRegularExpression>
#include <QThread>
#include <QUuid>
#include <limits>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <aclapi.h>
#include <fcntl.h>
#include <io.h>
#include <sddl.h>
#else
#include <cerrno>
#include <sys/file.h>
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

// 日期：2026-11-07；SQLite原生日志仅接受已提升进程的默认Administrators所有者，查询失败即拒绝。
bool defaultSqliteJournalOwner(PSID owner) {
    if (!IsWellKnownSid(owner, WinBuiltinAdministratorsSid))
        return false;
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
        return false;
    struct TokenGuard {
        HANDLE value;
        // 日期：2026-11-07；令牌查询正常返回或分配异常时均关闭原生句柄。
        ~TokenGuard() {
            CloseHandle(value);
        }
    } guard{token};
    DWORD length = 0;
    TOKEN_ELEVATION elevation{};
    if (!GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &length) ||
        !elevation.TokenIsElevated)
        return false;
    GetTokenInformation(token, TokenOwner, nullptr, 0, &length);
    if (length == 0)
        return false;
    QByteArray bytes(static_cast<int>(length), '\0');
    if (!GetTokenInformation(token, TokenOwner, bytes.data(), length, &length))
        return false;
    return EqualSid(owner, reinterpret_cast<TOKEN_OWNER *>(bytes.data())->Owner);
}

// 日期：2026-11-04；只有当前账户可以获得允许 ACE；NULL DACL、其他账户、复杂对象 ACE 均拒绝。
void verifyAcl(HANDLE handle, bool directory, bool sqliteJournal = false) {
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
    const bool ownerAllowed =
        owner && (EqualSid(owner, const_cast<char *>(account.constData())) ||
                  (sqliteJournal && !directory && defaultSqliteJournalOwner(owner)));
    if (!ownerAllowed || !dacl || !GetSecurityDescriptorControl(security, &control, &revision) ||
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
void verifyFile(QFile &file, bool sqliteJournal = false) {
#ifdef Q_OS_WIN
    const auto handle = reinterpret_cast<HANDLE>(_get_osfhandle(file.handle()));
    verifyAcl(handle, false, sqliteJournal);
    BY_HANDLE_FILE_INFORMATION info;
    if (sqliteJournal && (!GetFileInformationByHandle(handle, &info) || info.nNumberOfLinks != 1))
        throw Error(ExitCode::Permission, QStringLiteral("SQLite回滚日志不是独立普通文件"),
                    "identity");
#else
    struct stat info;
    if (::fstat(file.handle(), &info) != 0 || info.st_uid != ::geteuid() ||
        (info.st_mode & 0077) != 0 || !S_ISREG(info.st_mode) ||
        (sqliteJournal && info.st_nlink != 1))
        throw Error(ExitCode::Permission, QStringLiteral("私有状态文件的所有者或权限不安全"),
                    "identity");
#endif
}
} // namespace

class StateUseGuard final {
  public:
    // 日期：2026-11-07；锁文件永久保留且为空，禁止按PID删锁；进程退出由内核释放占用。
    StateUseGuard(const QString &directory, PrivateStore::Use use
#ifndef Q_OS_WIN
                  ,
                  const PosixDirectory &root
#endif
                  )
        : maintenance_(use == PrivateStore::Use::Maintenance)
#ifndef Q_OS_WIN
          ,
          root_(root)
#endif
    {
#ifdef Q_OS_WIN
        const auto name = longPath(QDir(directory).filePath("state-use.lock"));
        auto security = privateSecurity();
        SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), security, FALSE};
        handle_ = CreateFileW(reinterpret_cast<LPCWSTR>(name.utf16()),
                              GENERIC_READ | GENERIC_WRITE | READ_CONTROL,
                              FILE_SHARE_READ | FILE_SHARE_WRITE, &attributes, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        LocalFree(security);
        if (handle_ == INVALID_HANDLE_VALUE)
            throw Error(ExitCode::Permission, QStringLiteral("无法安全打开状态占用锁"),
                        "state-use");
#else
        Q_UNUSED(directory)
        try {
            descriptor_ = root_.openUpdate("state-use.lock", true);
        } catch (const Error &) {
            // 日期：2026-11-07；并发首次创建只重开同名单项，仍由原生接口拒绝链接/特殊文件。
            descriptor_ = root_.openUpdate("state-use.lock", false);
        }
#endif
        try {
            verify();
#ifdef Q_OS_WIN
            OVERLAPPED position{};
            const DWORD flags =
                LOCKFILE_FAIL_IMMEDIATELY | (maintenance_ ? LOCKFILE_EXCLUSIVE_LOCK : 0);
            if (!LockFileEx(handle_, flags, 0, 1, 0, &position))
#else
            int result;
            do {
                result = ::flock(descriptor_, (maintenance_ ? LOCK_EX : LOCK_SH) | LOCK_NB);
            } while (result != 0 && errno == EINTR);
            if (result != 0)
#endif
                throw Error(ExitCode::Permission,
                            QStringLiteral("状态目录正被使用或维护，未取得所需占用锁"),
                            "state-use");
            verify();
        } catch (...) {
            release();
            throw;
        }
    }

    // 日期：2026-11-07；只关闭本实例句柄，不截断、替换或删除其他进程仍需使用的锁文件。
    ~StateUseGuard() {
        release();
    }

    // 日期：2026-11-07；每次访问重验零字节普通文件/私有权限；POSIX另核对路径与已锁inode一致。
    void verify() const {
#ifdef Q_OS_WIN
        BY_HANDLE_FILE_INFORMATION info;
        if (!GetFileInformationByHandle(handle_, &info) ||
            (info.dwFileAttributes &
             (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE)) ||
            info.nNumberOfLinks != 1 || info.nFileSizeHigh != 0 || info.nFileSizeLow != 0)
            throw Error(ExitCode::Permission, QStringLiteral("状态占用锁不是独立空普通文件"),
                        "state-use");
        verifyAcl(handle_, false);
#else
        struct stat info;
        if (::fstat(descriptor_, &info) != 0 || !S_ISREG(info.st_mode) ||
            info.st_uid != ::geteuid() || (info.st_mode & 0077) != 0 || info.st_nlink != 1 ||
            info.st_size != 0)
            throw Error(ExitCode::Permission, QStringLiteral("状态占用锁类型或权限不安全"),
                        "state-use");
        const auto current = root_.fileInformation("state-use.lock");
        if (current.st_dev != info.st_dev || current.st_ino != info.st_ino)
            throw Error(ExitCode::Permission, QStringLiteral("状态占用锁路径已被替换"),
                        "state-use");
#endif
    }

    // 日期：2026-11-07；返回构造时固定模式，锁不支持就地升级以免两个共享使用者互相等待。
    bool maintenance() const {
        return maintenance_;
    }

  private:
    // 日期：2026-11-07；构造异常及析构共用释放路径，不能泄漏原生锁或句柄。
    void release() {
#ifdef Q_OS_WIN
        if (handle_ != INVALID_HANDLE_VALUE) {
            CloseHandle(handle_);
            handle_ = INVALID_HANDLE_VALUE;
        }
#else
        if (descriptor_ >= 0) {
            ::close(descriptor_);
            descriptor_ = -1;
        }
#endif
    }
    bool maintenance_;
#ifdef Q_OS_WIN
    HANDLE handle_ = INVALID_HANDLE_VALUE;
#else
    const PosixDirectory &root_;
    int descriptor_ = -1;
#endif
};

// 日期：2026-11-07；先固定安全根，再取得共享或独占占用；锁的生命周期覆盖本实例的所有使用。
PrivateStore::PrivateStore(const QString &directory, bool create, Use use)
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
    use_.reset(new StateUseGuard(directory_, use
#ifndef Q_OS_WIN
                                 ,
                                 *root_
#endif
                                 ));
    verify();
}

// 日期：2026-11-04；目录句柄由当前实例独占，析构不对状态文件做隐式删除。
PrivateStore::~PrivateStore() = default;

// 日期：2026-11-07；重验根和当前持有的原生占用，路径被替换或权限放宽时不继续访问。
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
    if (use_)
        use_->verify();
}

// 日期：2026-11-08；保留占用锁、永久预算账本及大小写变体，普通状态接口不能读取、替换或删除。
QString PrivateStore::path(const QString &name) const {
    static const QRegularExpression allowed("\\A[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}\\z");
    if (!allowed.match(name).hasMatch() ||
        name.compare("state-use.lock", Qt::CaseInsensitive) == 0 ||
        name.compare("state-budget.bin", Qt::CaseInsensitive) == 0)
        throw Error(ExitCode::Permission, QStringLiteral("私有状态键无效"), "identity");
    validateRelativePath(name);
    return QDir(directory_).filePath(name);
}

// 日期：2026-11-07；核对锁仍有效后返回维护资格，后续清理入口必须显式检查此结果。
bool PrivateStore::maintenance() const {
    verify();
    return use_->maintenance();
}

// 日期：2026-11-04；大数据库只核对原生权限、文件类型及固定对象，避免整体读取。
qint64 PrivateStore::validateFile(const QString &name) const {
    return validateFileObject(name, false);
}

// 日期：2026-11-07；仅独占维护接受规范SQLite回滚日志，不能通过此接口放宽数据库、凭据或WAL。
qint64 PrivateStore::validateSqliteJournal(const QString &name) const {
    if (!maintenance() || !name.endsWith(".sqlite-journal", Qt::CaseSensitive))
        throw Error(ExitCode::Permission, QStringLiteral("SQLite回滚日志校验条件无效"), "identity");
    return validateFileObject(name, true);
}

// 日期：2026-11-07；两种策略共用已打开对象/原生身份核验，只有日志所有者及单链接检查不同。
qint64 PrivateStore::validateFileObject(const QString &name, bool sqliteJournal) const {
    verify();
    SourceFile source(path(name), SourceFile::OpenPolicy::PrivateState);
    // 日期：2026-11-06；共享占用等待后再次核对根ACL，随后仍核对已打开文件的所有者和类型。
    verify();
    verifyFile(source.device(), sqliteJournal);
    const auto size = source.device().size();
    // 日期：2026-11-05；SQLite连接可并发更新页，不把mtime/大小变化误报成源替换；类型/路径/所有者仍重验。
    source.verifyObject();
    verifyFile(source.device(), sqliteJournal);
    return size;
}

// 日期：2026-11-07；私有配置最多重读五个完整换代，普通源/同对象修改/不安全路径均不重试。
QByteArray PrivateStore::read(const QString &name, qint64 maximum) const {
    verify();
    if (maximum <= 0 || maximum > 1024 * 1024)
        throw Error(ExitCode::Config, QStringLiteral("私有状态读取预算无效"), "identity");
    for (int attempt = 1;; ++attempt) {
        SourceFile source(path(name), SourceFile::OpenPolicy::PrivateState);
        // 日期：2026-11-07；每次从新句柄重验根ACL、文件所有者、类型与大小，不复用旧换代正文。
        verify();
        auto &file = source.device();
        verifyFile(file);
        if (file.size() > maximum)
            throw Error(ExitCode::Config, QStringLiteral("私有状态文件超过预算"), "identity");
        const auto bytes = file.read(maximum + 1);
        if (file.error() != QFileDevice::NoError || bytes.size() > maximum ||
            bytes.size() != file.size())
            throw Error(ExitCode::Disk, QStringLiteral("私有状态文件读取失败"), "identity");
        try {
            source.verify();
        } catch (const Error &error) {
            if (error.code != ExitCode::Integrity || error.stage != "read" ||
                !source.pathReplaced())
                throw;
            verify();
            if (attempt >= 5)
                throw Error(ExitCode::Integrity,
                            QStringLiteral("私有状态在读取期间连续替换，请重试"), "read-busy");
            // 日期：2026-11-07；continue先销毁旧正文与句柄，最多保留一次有界读取，不积累换代缓存。
            continue;
        }
        verify();
        verifyFile(file);
        return bytes;
    }
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
    QElapsedTimer elapsed;
    elapsed.start();
    try {
        for (int attempt = 1;; ++attempt) {
            // 日期：2026-11-06；等待期间重验根ACL及当前目标，不将只读、链接或不安全权限当作共享占用。
            verify();
            if (QFileInfo::exists(target) || isLinkedPath(target)) {
                const auto targetAttributes =
                    GetFileAttributesW(reinterpret_cast<LPCWSTR>(nativeTarget.utf16()));
                if (targetAttributes == INVALID_FILE_ATTRIBUTES ||
                    (targetAttributes & (FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_DIRECTORY |
                                         FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE)))
                    throw Error(ExitCode::Permission, QStringLiteral("私有状态替换目标属性不安全"),
                                "identity");
                read(name, 1024 * 1024);
            }
            if (MoveFileExW(reinterpret_cast<LPCWSTR>(nativeTemporary.utf16()),
                            reinterpret_cast<LPCWSTR>(nativeTarget.utf16()),
                            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
                break;
            const auto error = GetLastError();
            const bool busy = error == ERROR_ACCESS_DENIED || error == ERROR_SHARING_VIOLATION ||
                              error == ERROR_LOCK_VIOLATION;
            if (!busy || attempt >= 21 || elapsed.elapsed() >= 500)
                throw Error(ExitCode::Disk,
                            QStringLiteral("私有状态原子替换失败，系统错误码 %1，已尝试 %2 次")
                                .arg(error)
                                .arg(attempt),
                            busy ? "identity-busy" : "identity");
            // 日期：2026-11-06；只等待瞬时共享冲突，新增等待预算500ms/最多21次，不删除原配置或复制回退。
            const auto until = qMin<qint64>(500, elapsed.elapsed() + 25);
            while (elapsed.elapsed() < until)
                QThread::msleep(5);
        }
    } catch (...) {
        DeleteFileW(reinterpret_cast<LPCWSTR>(nativeTemporary.utf16()));
        throw;
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

struct BudgetFile::Implementation {
    const PrivateStore &store;
    QFile file;
    QMutex mutex;
    bool locked = false;
    bool created = false;
    // 日期：2026-11-08；账本描述符受外层状态资格约束，调用方保证PrivateStore先构造后析构。
    explicit Implementation(const PrivateStore &value) : store(value) {
    }
};

// 日期：2026-11-08；复用现有私有安全规则，Windows显式所有者，POSIX相对固定根且不跟随链接。
BudgetFile::BudgetFile(const PrivateStore &store, bool create)
    : implementation_(new Implementation(store)) {
    store.verify();
    if (create && !store.maintenance())
        throw Error(ExitCode::Permission, QStringLiteral("账本初始化需要独占维护"), "budget");
    int descriptor = -1;
#ifdef Q_OS_WIN
    const auto name = longPath(QDir(store.directory_).filePath("state-budget.bin"));
    auto security = privateSecurity();
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), security, FALSE};
    const auto handle = CreateFileW(
        reinterpret_cast<LPCWSTR>(name.utf16()), GENERIC_READ | GENERIC_WRITE | READ_CONTROL,
        FILE_SHARE_READ | FILE_SHARE_WRITE, &attributes, create ? CREATE_NEW : OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    LocalFree(security);
    if (handle == INVALID_HANDLE_VALUE)
        throw Error(ExitCode::Permission, QStringLiteral("无法安全打开永久预算账本"), "budget");
    descriptor = _open_osfhandle(reinterpret_cast<intptr_t>(handle), _O_RDWR | _O_BINARY);
    if (descriptor < 0) {
        CloseHandle(handle);
        throw Error(ExitCode::Disk, QStringLiteral("无法接管预算账本句柄"), "budget");
    }
#else
    descriptor = store.root_->openUpdate("state-budget.bin", create);
#endif
    if (!implementation_->file.open(descriptor, QIODevice::ReadWrite | QIODevice::Unbuffered,
                                    QFileDevice::AutoCloseHandle)) {
#ifdef Q_OS_WIN
        _close(descriptor);
#else
        ::close(descriptor);
#endif
        throw Error(ExitCode::Disk, QStringLiteral("无法接管预算账本文件"), "budget");
    }
    implementation_->created = create;
    verify();
}

// 日期：2026-11-08；QFile先关闭，随后销毁互斥；不删除永久账本或按进程生命期归还额度。
BudgetFile::~BudgetFile() = default;

// 日期：2026-11-08；使用同一打开对象核对权限/类型/单链接，POSIX另核对路径防止锁对象换代。
void BudgetFile::verify() const {
    const auto &state = *implementation_;
    state.store.verify();
    verifyFile(implementation_->file);
#ifdef Q_OS_WIN
    const auto handle = reinterpret_cast<HANDLE>(_get_osfhandle(state.file.handle()));
    BY_HANDLE_FILE_INFORMATION info{};
    if (GetFileType(handle) != FILE_TYPE_DISK || !GetFileInformationByHandle(handle, &info) ||
        (info.dwFileAttributes &
         (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DEVICE)) ||
        info.nNumberOfLinks != 1)
        throw Error(ExitCode::Permission, QStringLiteral("预算账本不是独立普通文件"), "budget");
#else
    struct stat opened{};
    const auto current = state.store.root_->fileInformation("state-budget.bin");
    if (::fstat(state.file.handle(), &opened) != 0 || current.st_dev != opened.st_dev ||
        current.st_ino != opened.st_ino || !S_ISREG(current.st_mode) || current.st_nlink != 1)
        throw Error(ExitCode::Integrity, QStringLiteral("预算账本路径或原生对象已变化"), "budget");
#endif
}

// 日期：2026-11-08；期限覆盖两级锁；用户取消回调不在原生锁内运行，错误不是锁忙时立即失败。
void BudgetFile::lock(const std::function<void()> &check, int timeoutMs) {
    if (timeoutMs < 0 || timeoutMs > 5000)
        throw Error(ExitCode::Config, QStringLiteral("预算锁期限无效"), "budget");
    auto &state = *implementation_;
    QElapsedTimer elapsed;
    elapsed.start();
    while (true) {
        if (check)
            check();
        if (state.mutex.tryLock())
            break;
        if (elapsed.elapsed() >= timeoutMs)
            throw Error(ExitCode::Disk, QStringLiteral("预算账本进程内协调繁忙"), "budget-busy");
        QThread::msleep(2);
    }
    try {
        // 日期：2026-11-08；文件有效性只在持有实例互斥后读取，避免与另一线程解除失败后的关闭竞争。
        if (!state.file.isOpen())
            throw Error(ExitCode::Disk, QStringLiteral("预算账本句柄已失效"), "budget");
        while (true) {
            if (check)
                check();
            bool acquired = false;
#ifdef Q_OS_WIN
            const auto handle = reinterpret_cast<HANDLE>(_get_osfhandle(state.file.handle()));
            OVERLAPPED position{};
            acquired = LockFileEx(handle, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1,
                                  0, &position);
            if (!acquired && GetLastError() != ERROR_LOCK_VIOLATION)
                throw Error(ExitCode::Disk, QStringLiteral("预算账本原生锁失败"), "budget");
#else
            acquired = ::flock(state.file.handle(), LOCK_EX | LOCK_NB) == 0;
            if (!acquired && errno != EWOULDBLOCK && errno != EAGAIN && errno != EINTR)
                throw Error(ExitCode::Disk, QStringLiteral("预算账本原生锁失败"), "budget");
#endif
            if (acquired) {
                state.locked = true;
                verify();
                return;
            }
            if (elapsed.elapsed() >= timeoutMs)
                throw Error(ExitCode::Disk, QStringLiteral("预算账本跨进程协调繁忙"),
                            "budget-busy");
            QThread::msleep(2);
        }
    } catch (...) {
        if (state.locked)
            unlock();
        else
            state.mutex.unlock();
        throw;
    }
}

// 日期：2026-11-08；无需文件删除即可归还原生占用；关闭描述符仍能释放任何未成功解除的内核锁。
void BudgetFile::unlock() noexcept {
    auto &state = *implementation_;
#ifdef Q_OS_WIN
    OVERLAPPED position{};
    const bool released = UnlockFileEx(
        reinterpret_cast<HANDLE>(_get_osfhandle(state.file.handle())), 0, 1, 0, &position);
#else
    const bool released = ::flock(state.file.handle(), LOCK_UN) == 0;
#endif
    if (!released)
        state.file.close();
    state.locked = false;
    state.mutex.unlock();
}

// 日期：2026-11-08；先完成两级锁获取和身份重验，才允许读取或改写账本片段。
BudgetFile::Lock::Lock(BudgetFile &file, const std::function<void()> &check, int timeoutMs)
    : file_(file) {
    file_.lock(check, timeoutMs);
}

// 日期：2026-11-08；调用方异常退出临界区同样归还两级锁。
BudgetFile::Lock::~Lock() {
    file_.unlock();
}

// 日期：2026-11-08；固定片段不得超16KiB，读取不完整或位置溢出均拒绝，不产生无界缓冲。
QByteArray BudgetFile::read(qint64 offset, int bytes) {
    auto &state = *implementation_;
    if (!state.locked || offset < 0 || bytes <= 0 || bytes > 16384 ||
        offset > std::numeric_limits<qint64>::max() - bytes || !state.file.seek(offset))
        throw Error(ExitCode::Integrity, QStringLiteral("预算账本读取范围无效"), "budget");
    const auto result = state.file.read(bytes);
    if (result.size() != bytes)
        throw Error(ExitCode::Integrity, QStringLiteral("预算账本读取不完整"), "budget");
    return result;
}

// 日期：2026-11-08；单次片段有界且不得跳过短写，写入失败后不将尚未持久授信交给业务。
void BudgetFile::write(qint64 offset, const QByteArray &bytes) {
    auto &state = *implementation_;
    if (!state.locked || offset < 0 || bytes.isEmpty() || bytes.size() > 16384 ||
        offset > std::numeric_limits<qint64>::max() - bytes.size() || !state.file.seek(offset) ||
        state.file.write(bytes) != bytes.size())
        throw Error(ExitCode::Disk, QStringLiteral("预算账本写入不完整"), "budget");
}

// 日期：2026-11-08；日志意图和数据各自显式同步；创建目录的持久性在首次初始化末尾另行确认。
void BudgetFile::synchronize() {
    auto &state = *implementation_;
    if (!state.locked || !state.file.flush())
        throw Error(ExitCode::Disk, QStringLiteral("预算账本缓冲同步失败"), "budget");
#ifdef Q_OS_WIN
    if (!FlushFileBuffers(reinterpret_cast<HANDLE>(_get_osfhandle(state.file.handle()))))
#else
    if (::fsync(state.file.handle()) != 0)
#endif
        throw Error(ExitCode::Disk, QStringLiteral("预算账本持久同步失败"), "budget");
#ifndef Q_OS_WIN
    if (state.created)
        state.store.root_->synchronize();
#endif
    state.created = false;
}

// 日期：2026-11-08；目录身份不包含修改时间，合法账本写入不会改变域绑定。
QByteArray BudgetFile::rootIdentity() const {
    return implementation_->store.root_->identity();
}

// 日期：2026-11-08；文件长度来自已打开对象，禁止通过缓存名称属性掩盖截断。
qint64 BudgetFile::size() const {
    return implementation_->file.size();
}
} // namespace dukto

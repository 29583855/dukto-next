#include "sqlitevfs.h"
#include "error.h"
#include <QUuid>
#include <cstddef>
#include <cstring>
#include <limits>
#include <new>

namespace dukto {
struct SqliteVfs::Implementation {
    sqlite3_vfs api{};
    sqlite3_vfs *native = nullptr;
    QByteArray label;
    std::shared_ptr<SqliteFilePolicy> policy;
    quint64 sequence = 0;
    struct File {
        sqlite3_file api{};
        sqlite3_file *native = nullptr;
        Implementation *owner = nullptr;
        QByteArray name;
        quint64 id = 0;
        int flags = 0;
    };

    // 日期：2026-11-07；SQLite的文件缓冲按max_align_t对齐，原生VFS使用包装对象之后的独立空间。
    static size_t nativeOffset() {
        const auto alignment = alignof(std::max_align_t);
        return (sizeof(File) + alignment - 1) / alignment * alignment;
    }

    // 日期：2026-11-07；将SQLite回调文件指针还原为本连接包装，所有转发使用其原生方法表。
    static File *file(sqlite3_file *value) {
        return reinterpret_cast<File *>(value);
    }

    // 日期：2026-11-07；回调事件只临时共享有界名称，不读正文，偏移和长度保持64位。
    static SqliteFileEvent event(File *value, SqliteFileEvent::Action action, qint64 offset = 0,
                                 qint64 bytes = 0, bool extend = false) {
        return {action, value->id, value->name, value->flags, offset, bytes, extend};
    }

    // 日期：2026-11-07；空策略仅转发；接入策略时任何授权错误先返回，原生写入尚未发生。
    int before(const SqliteFileEvent &value) const noexcept {
        return policy ? policy->before(value) : SQLITE_OK;
    }

    // 日期：2026-11-07；只有实际调用过原生方法才发送完成通知，拒绝不伪装成一次失败写入。
    void after(const SqliteFileEvent &value, int result) const noexcept {
        if (policy)
            policy->after(value, result);
    }

    // 日期：2026-11-07；关闭不可因额度拒绝；正常/失败均释放包装内名称，原生关闭结果照实传递。
    static int close(sqlite3_file *handle) noexcept {
        auto value = file(handle);
        const auto notice = event(value, SqliteFileEvent::Action::Close);
        const int result = value->native->pMethods->xClose(value->native);
        value->owner->after(notice, result);
        value->~File();
        return result;
    }

    // 日期：2026-11-07；读取直接交给同一原生句柄，不复制数据或改变SQLite短读语义。
    static int read(sqlite3_file *handle, void *data, int count, sqlite3_int64 offset) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xRead(value->native, data, count, offset);
    }

    // 日期：2026-11-07；长度/偏移溢出先拒绝，每次SQLite写入在触盘前由所属连接策略授信。
    static int write(sqlite3_file *handle, const void *data, int count,
                     sqlite3_int64 offset) noexcept {
        auto value = file(handle);
        if (count < 0 || offset < 0 || offset > std::numeric_limits<qint64>::max() - count)
            return SQLITE_IOERR_WRITE;
        const auto notice = event(value, SqliteFileEvent::Action::Write, offset, count, true);
        const int granted = value->owner->before(notice);
        if (granted != SQLITE_OK)
            return granted;
        const int result = value->native->pMethods->xWrite(value->native, data, count, offset);
        value->owner->after(notice, result);
        return result;
    }

    // 日期：2026-11-07；截断可能扩展文件，缩小和扩展都先通知策略，由真实完成结果对账。
    static int truncate(sqlite3_file *handle, sqlite3_int64 length) noexcept {
        auto value = file(handle);
        if (length < 0)
            return SQLITE_IOERR_TRUNCATE;
        const auto notice = event(value, SqliteFileEvent::Action::Truncate, 0, length, true);
        const int granted = value->owner->before(notice);
        if (granted != SQLITE_OK)
            return granted;
        const int result = value->native->pMethods->xTruncate(value->native, length);
        value->owner->after(notice, result);
        return result;
    }

    // 日期：2026-11-07；同步原封转发，保留SQLite FULL提交和原生持久化的错误。
    static int sync(sqlite3_file *handle, int flags) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xSync(value->native, flags);
    }

    // 日期：2026-11-07；文件长度来自原生句柄，不以请求写入量推定已经实际分配。
    static int size(sqlite3_file *handle, sqlite3_int64 *length) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xFileSize(value->native, length);
    }

    // 日期：2026-11-07；数据库锁沿用对应平台SQLite原生实现，不引入第二套数据库锁协议。
    static int lock(sqlite3_file *handle, int level) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xLock(value->native, level);
    }

    // 日期：2026-11-07；解锁不能被配额阻止，否则会把预算不足变成持久锁泄漏。
    static int unlock(sqlite3_file *handle, int level) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xUnlock(value->native, level);
    }

    // 日期：2026-11-07；保留原生保留锁查询，真实跨进程竞争不由本地状态代替。
    static int reserved(sqlite3_file *handle, int *result) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xCheckReservedLock(value->native, result);
    }

    // 日期：2026-11-07；拦截可扩展磁盘的大小提示/块预分配，VFS身份及文件指针指向当前包装。
    static int control(sqlite3_file *handle, int operation, void *argument) noexcept {
        auto value = file(handle);
        if (operation == SQLITE_FCNTL_FILE_POINTER) {
            *static_cast<sqlite3_file **>(argument) = handle;
            return SQLITE_OK;
        }
        if (operation == SQLITE_FCNTL_VFS_POINTER) {
            *static_cast<sqlite3_vfs **>(argument) = &value->owner->api;
            return SQLITE_OK;
        }
        if (operation == SQLITE_FCNTL_CHUNK_SIZE)
            return SQLITE_NOTFOUND;
        if (operation == SQLITE_FCNTL_SIZE_HINT) {
            const auto length = *static_cast<sqlite3_int64 *>(argument);
            if (length < 0)
                return SQLITE_IOERR_TRUNCATE;
            const auto notice = event(value, SqliteFileEvent::Action::SizeHint, 0, length, true);
            const int granted = value->owner->before(notice);
            if (granted != SQLITE_OK)
                return granted;
            const int result =
                value->native->pMethods->xFileControl(value->native, operation, argument);
            value->owner->after(notice, result);
            return result;
        }
        return value->native->pMethods->xFileControl(value->native, operation, argument);
    }

    // 日期：2026-11-07；扇区大小保留底层平台值，不改变SQLite日志对齐和原子写判断。
    static int sector(sqlite3_file *handle) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xSectorSize(value->native);
    }

    // 日期：2026-11-07；包装仍使用同一原生文件方法，设备能力照实转发。
    static int characteristics(sqlite3_file *handle) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xDeviceCharacteristics(value->native);
    }

    // 日期：2026-11-07；共享内存扩展在映射前通知，长度先核验乘法；SQLite错误不被吞掉。
    static int map(sqlite3_file *handle, int page, int pageSize, int extend,
                   void volatile **result) noexcept {
        auto value = file(handle);
        if (page < 0 || pageSize <= 0 ||
            qint64(page) + 1 > std::numeric_limits<qint64>::max() / pageSize)
            return SQLITE_IOERR_SHMMAP;
        const auto notice = event(value, SqliteFileEvent::Action::MapSharedMemory, 0,
                                  (qint64(page) + 1) * pageSize, extend != 0);
        const int granted = value->owner->before(notice);
        if (granted != SQLITE_OK)
            return granted;
        const int code =
            value->native->pMethods->xShmMap(value->native, page, pageSize, extend, result);
        value->owner->after(notice, code);
        return code;
    }

    // 日期：2026-11-07；WAL共享内存锁仍交给原生SQLite，不因包装改变读写并发语义。
    static int shmLock(sqlite3_file *handle, int offset, int count, int flags) noexcept {
        auto value = file(handle);
        return value->native->pMethods->xShmLock(value->native, offset, count, flags);
    }

    // 日期：2026-11-07；内存屏障直接调用原生实现，不对锁屏障分配或等待应用预算。
    static void barrier(sqlite3_file *handle) noexcept {
        auto value = file(handle);
        value->native->pMethods->xShmBarrier(value->native);
    }

    // 日期：2026-11-07；解除映射及可选删除不得被额度拒绝；完成后策略收到真实清理结果。
    static int unmap(sqlite3_file *handle, int remove) noexcept {
        auto value = file(handle);
        const auto notice =
            event(value, SqliteFileEvent::Action::UnmapSharedMemory, 0, 0, remove != 0);
        const int result = value->native->pMethods->xShmUnmap(value->native, remove);
        value->owner->after(notice, result);
        return result;
    }

    // 日期：2026-11-07；始终返回空映射使SQLite经xRead/xWrite访问，不能从可写映射绕过授信。
    static int fetch(sqlite3_file *, sqlite3_int64, int, void **result) noexcept {
        *result = nullptr;
        return SQLITE_OK;
    }

    // 日期：2026-11-07；本包装不创建正文映射，因此无对应映射需要释放。
    static int unfetch(sqlite3_file *, sqlite3_int64, void *) noexcept {
        return SQLITE_OK;
    }

    // 日期：2026-11-07；每个版本只暴露原生方法支持的能力，避免在不支持WAL的平台调用空函数。
    static const sqlite3_io_methods *methods(int version) {
        static const sqlite3_io_methods v1{
            1,       close,    read,    write,  truncate,        sync,    size,    lock,
            unlock,  reserved, control, sector, characteristics, nullptr, nullptr, nullptr,
            nullptr, nullptr,  nullptr};
        static const sqlite3_io_methods v2{
            2,      close,    read,    write,  truncate,        sync, size,    lock,
            unlock, reserved, control, sector, characteristics, map,  shmLock, barrier,
            unmap,  nullptr,  nullptr};
        static const sqlite3_io_methods v3{
            3,      close,    read,    write,  truncate,        sync, size,    lock,
            unlock, reserved, control, sector, characteristics, map,  shmLock, barrier,
            unmap,  fetch,    unfetch};
        return version >= 3 ? &v3 : version == 2 ? &v2 : &v1;
    }

    // 日期：2026-11-07；打开前可拒绝创建；原生打开失败遵守SQLite关闭约定，分配异常转NOMEM。
    static int open(sqlite3_vfs *vfs, const char *name, sqlite3_file *handle, int flags,
                    int *outFlags) noexcept {
        auto owner = static_cast<Implementation *>(vfs->pAppData);
        File *value = nullptr;
        try {
            value = new (handle) File;
            value->native = reinterpret_cast<sqlite3_file *>(
                reinterpret_cast<unsigned char *>(handle) + nativeOffset());
            value->owner = owner;
            value->name = name ? QByteArray(name) : QByteArray();
            value->flags = flags;
            if (owner->sequence == std::numeric_limits<quint64>::max()) {
                value->~File();
                return SQLITE_FULL;
            }
            value->id = ++owner->sequence;
            const auto notice = event(value, SqliteFileEvent::Action::Open);
            const int granted = owner->before(notice);
            if (granted != SQLITE_OK) {
                value->~File();
                return granted;
            }
            const int result =
                owner->native->xOpen(owner->native, name, value->native, flags, outFlags);
            owner->after(notice, result);
            if (value->native->pMethods)
                value->api.pMethods = methods(value->native->pMethods->iVersion);
            else
                value->~File();
            return result;
        } catch (...) {
            if (value)
                value->~File();
            return SQLITE_NOMEM;
        }
    }

    // 日期：2026-11-07；删除日志同样先通知，名称仍由SQLite生成；本层不推定任意业务文件可删除。
    static int remove(sqlite3_vfs *vfs, const char *name, int syncDirectory) noexcept {
        auto owner = static_cast<Implementation *>(vfs->pAppData);
        try {
            const SqliteFileEvent notice{SqliteFileEvent::Action::Delete, 0, QByteArray(name)};
            const int granted = owner->before(notice);
            if (granted != SQLITE_OK)
                return granted;
            const int result = owner->native->xDelete(owner->native, name, syncDirectory);
            owner->after(notice, result);
            return result;
        } catch (...) {
            return SQLITE_NOMEM;
        }
    }

    // 日期：2026-11-07；访问查询沿用原生路径规则，不能把不存在和权限拒绝合并为成功。
    static int access(sqlite3_vfs *vfs, const char *name, int flags, int *result) noexcept {
        auto self = static_cast<Implementation *>(vfs->pAppData);
        return self->native->xAccess(self->native, name, flags, result);
    }

    // 日期：2026-11-07；路径规范化仍使用原生VFS，原UTF-8路径不由应用自行拼接。
    static int fullPath(sqlite3_vfs *vfs, const char *name, int length, char *result) noexcept {
        auto self = static_cast<Implementation *>(vfs->pAppData);
        return self->native->xFullPathname(self->native, name, length, result);
    }

    // 日期：2026-11-07；随机数转发到原生VFS，随机临时名称不改成可预测的应用序号。
    static int randomness(sqlite3_vfs *vfs, int length, char *result) noexcept {
        auto self = static_cast<Implementation *>(vfs->pAppData);
        return self->native->xRandomness(self->native, length, result);
    }

    // 日期：2026-11-07；SQLite忙等待休眠保持原平台实现和原时限。
    static int sleep(sqlite3_vfs *vfs, int microseconds) noexcept {
        auto self = static_cast<Implementation *>(vfs->pAppData);
        return self->native->xSleep(self->native, microseconds);
    }

    // 日期：2026-11-07；原UTC时间供SQLite内部使用，不混入应用预算的单调时钟。
    static int time(sqlite3_vfs *vfs, double *result) noexcept {
        auto self = static_cast<Implementation *>(vfs->pAppData);
        return self->native->xCurrentTime(self->native, result);
    }

    // 日期：2026-11-07；平台支持64位时间时原样转发，不凭低精度时间冒充原生能力。
    static int time64(sqlite3_vfs *vfs, sqlite3_int64 *result) noexcept {
        auto self = static_cast<Implementation *>(vfs->pAppData);
        return self->native->xCurrentTimeInt64(self->native, result);
    }

    // 日期：2026-11-07；保留底层系统错误诊断，不让SQLite将包装地址当作原生私有上下文。
    static int error(sqlite3_vfs *vfs, int length, char *result) noexcept {
        auto self = static_cast<Implementation *>(vfs->pAppData);
        return self->native->xGetLastError
                   ? self->native->xGetLastError(self->native, length, result)
                   : 0;
    }

    // 日期：2026-11-07；仅注册本连接随机名字，不修改默认VFS；无有效原生方法则明确拒绝启动。
    explicit Implementation(std::shared_ptr<SqliteFilePolicy> input) : policy(std::move(input)) {
        native = sqlite3_vfs_find(nullptr);
        if (!native || native->szOsFile <= 0 || native->mxPathname <= 0 ||
            nativeOffset() > size_t(std::numeric_limits<int>::max() - native->szOsFile))
            throw Error(ExitCode::Runtime, QStringLiteral("SQLite原生VFS不可用"), "sqlite-vfs");
        label = "dukto-" + QUuid::createUuid().toString(QUuid::WithoutBraces).toLatin1();
        api.iVersion = native->iVersion >= 2 && native->xCurrentTimeInt64 ? 2 : 1;
        api.szOsFile = int(nativeOffset()) + native->szOsFile;
        api.mxPathname = native->mxPathname;
        api.zName = label.constData();
        api.pAppData = this;
        api.xOpen = open;
        api.xDelete = remove;
        api.xAccess = access;
        api.xFullPathname = fullPath;
        api.xRandomness = randomness;
        api.xSleep = sleep;
        api.xCurrentTime = time;
        api.xGetLastError = error;
        if (api.iVersion >= 2)
            api.xCurrentTimeInt64 = time64;
        if (sqlite3_vfs_register(&api, 0) != SQLITE_OK)
            throw Error(ExitCode::Runtime, QStringLiteral("无法注册SQLite连接VFS"), "sqlite-vfs");
    }

    // 日期：2026-11-07；数据库关闭后注销随机VFS，连接反复打开不积累全局注册项。
    ~Implementation() {
        sqlite3_vfs_unregister(&api);
    }
};

// 日期：2026-11-07；策略独立属于当前连接，临时库及旁路均通过该连接命名VFS。
SqliteVfs::SqliteVfs(std::shared_ptr<SqliteFilePolicy> policy)
    : implementation_(new Implementation(std::move(policy))) {
}

// 日期：2026-11-07；内部实现最后注销VFS并归还策略引用。
SqliteVfs::~SqliteVfs() = default;

// 日期：2026-11-07；返回稳定注册名副本，使用者不接触VFS原生指针。
QByteArray SqliteVfs::name() const {
    return implementation_->label;
}
} // namespace dukto

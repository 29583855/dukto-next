#if defined(_WIN32) && !defined(_WIN32_WINNT)
#define _WIN32_WINNT 0x0602
#endif
#include "core/files.h"
#include "core/sqliteruntime.h"
#include "core/sqlitevfs.h"
#include <QFileInfo>
#include <QSqlError>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QUuid>
#include <QtTest>
#include <array>
#include <cstring>
#include <limits>
#include <stdexcept>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <winioctl.h>
#else
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace {
using Event = dukto::SqliteFileEvent;

class Policy final : public dukto::SqliteFilePolicy {
  public:
    std::array<Event, 8> beforeEvents{};
    std::array<Event, 8> afterEvents{};
    std::array<int, 8> completed{};
    int observedWriteFlags = 0;
    int badWriteObservations = 0;
    bool refuseWrite = false;

    // 日期：2026-11-08；仅保存每类最近一次观察，拒绝写入仍发生在底层操作之前。
    int before(const Event &event) noexcept override {
        beforeEvents[size_t(event.action)] = event;
        return refuseWrite && event.action == Event::Action::Write ? SQLITE_FULL : SQLITE_OK;
    }

    // 日期：2026-11-08；实际写入必须能观察同一原生普通文件，关闭通知不得伪称关闭后查询。
    void after(const Event &event, int result) noexcept override {
        afterEvents[size_t(event.action)] = event;
        ++completed[size_t(event.action)];
        if (event.action == Event::Action::Write && result == SQLITE_OK) {
            if (!event.observedAfterCall || event.observation.fileResult != SQLITE_OK ||
                event.observation.file.kind != 1)
                ++badWriteObservations;
            else
                observedWriteFlags |= event.flags;
        }
    }
};

class RawFile final {
  public:
    dukto::SqliteVfs owner;
    sqlite3_file *file = nullptr;
    sqlite3_filename filename = nullptr;

    // 日期：2026-11-08；使用真实连接VFS及SQLite正规文件名对象，匿名临时文件直接传空名。
    RawFile(const QString &path, int flags, std::shared_ptr<Policy> policy = {})
        : owner(std::move(policy)) {
        const auto vfs = sqlite3_vfs_find(owner.name().constData());
        if (!path.isEmpty()) {
            const auto name = path.toUtf8();
            const auto journal = name + "-journal";
            const auto wal = name + "-wal";
            filename = sqlite3_create_filename(name.constData(), journal.constData(),
                                               wal.constData(), 0, nullptr);
            if (!filename)
                throw std::bad_alloc();
        }
        file = static_cast<sqlite3_file *>(sqlite3_malloc64(sqlite3_uint64(vfs->szOsFile)));
        if (!file) {
            sqlite3_free_filename(filename);
            throw std::bad_alloc();
        }
        std::memset(file, 0, size_t(vfs->szOsFile));
        int opened = 0;
        const auto result = vfs->xOpen(vfs, filename, file, flags, &opened);
        if (result != SQLITE_OK) {
            close();
            sqlite3_free_filename(filename);
            filename = nullptr;
            throw std::runtime_error(sqlite3_errstr(result));
        }
    }

    // 日期：2026-11-08；先关闭真实文件，再释放SQLite文件名与包装内存，异常同样不泄漏资源。
    ~RawFile() {
        close();
        sqlite3_free_filename(filename);
    }

    // 日期：2026-11-08；测试显式关闭以核验最终通知，析构再次调用不重复关闭。
    int close() {
        int result = SQLITE_OK;
        if (file) {
            if (file->pMethods)
                result = file->pMethods->xClose(file);
            sqlite3_free(file);
            file = nullptr;
        }
        return result;
    }
};

class Connection final {
  public:
    QString name = QUuid::createUuid().toString(QUuid::WithoutBraces);
    QSqlDatabase db;

    // 日期：2026-11-08；真实SQL通过生产Qt完整驱动打开，策略与实际业务使用同一入口。
    Connection(const QString &path, std::shared_ptr<Policy> policy)
        : db(dukto::addSqliteDatabase(name, std::move(policy))) {
        db.setDatabaseName(path);
        if (!db.open())
            throw std::runtime_error(db.lastError().text().toStdString());
    }

    // 日期：2026-11-08；查询须先释放，连接关闭后立即移除Qt注册项。
    ~Connection() {
        db.close();
        db = {};
        QSqlDatabase::removeDatabase(name);
    }
};

// 日期：2026-11-08；逐字段比较身份，不把结构填充字节、长度或路径当成原生对象身份。
bool sameObject(const DuktoSqliteFileInfo &left, const DuktoSqliteFileInfo &right) {
    return left.kind == 1 && right.kind == 1 && left.platform == right.platform &&
           left.volume == right.volume &&
           std::memcmp(left.identity, right.identity, sizeof(left.identity)) == 0;
}

// 日期：2026-11-08；独立系统属性查询核对原生身份/分配量；POSIX只stat路径，不关闭SQLite文件描述符。
bool matchesPath(const DuktoSqliteFileInfo &value, const QString &path) {
#ifdef Q_OS_WIN
    const auto handle = CreateFileW(reinterpret_cast<LPCWSTR>(path.utf16()), FILE_READ_ATTRIBUTES,
                                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                                    OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (handle == INVALID_HANDLE_VALUE)
        return false;
    FILE_ID_INFO identity{};
    FILE_STANDARD_INFO standard{};
    const bool observed =
        GetFileInformationByHandleEx(handle, FileIdInfo, &identity, sizeof(identity)) &&
        GetFileInformationByHandleEx(handle, FileStandardInfo, &standard, sizeof(standard));
    CloseHandle(handle);
    return observed && value.kind == 1 && value.platform == 2 &&
           value.volume == identity.VolumeSerialNumber &&
           std::memcmp(value.identity, identity.FileId.Identifier, sizeof(value.identity)) == 0 &&
           value.logicalBytes == standard.EndOfFile.QuadPart &&
           value.allocatedBytes == standard.AllocationSize.QuadPart &&
           value.links == standard.NumberOfLinks;
#else
    struct stat observed{};
    if (::stat(QFile::encodeName(path).constData(), &observed) != 0)
        return false;
    sqlite3_uint64 inode = 0;
    for (int index = 7; index >= 0; --index)
        inode = (inode << 8) | value.identity[index];
    return value.kind == 1 && value.platform == 1 &&
           value.volume == sqlite3_uint64(observed.st_dev) &&
           inode == sqlite3_uint64(observed.st_ino) && value.logicalBytes == observed.st_size &&
           value.allocatedBytes == sqlite3_int64(observed.st_blocks) * 512 &&
           value.links == sqlite3_int64(observed.st_nlink);
#endif
}

constexpr int Writable = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_MAIN_DB;
} // namespace

class SqliteFileInfoTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-08；真实写入/截断前后各自查询，拒绝后无完成事件且原正文/长度保持。
    void growthTruncationAndRefusal() {
        QTemporaryDir root;
        const auto path = root.filePath(QStringLiteral("中文 #% 实际对象.sqlite"));
        auto policy = std::make_shared<Policy>();
        RawFile handle(path, Writable, policy);
        auto file = handle.file;
        DuktoSqliteFileInfo initial{}, current{};
        QCOMPARE(file->pMethods->xFileControl(file, dukto::SqliteFileInfoControl, &initial),
                 SQLITE_OK);
        QVERIFY(matchesPath(initial, path));
        QCOMPARE(initial.logicalBytes, sqlite3_int64(0));
        const QByteArray body(1024, 'a');
        QCOMPARE(file->pMethods->xWrite(file, body.constData(), body.size(), 4096), SQLITE_OK);
        const auto before = policy->beforeEvents[size_t(Event::Action::Write)];
        const auto after = policy->afterEvents[size_t(Event::Action::Write)];
        QCOMPARE(before.observation.fileResult, SQLITE_OK);
        QCOMPARE(before.observation.file.logicalBytes, sqlite3_int64(0));
        QVERIFY(!before.observedAfterCall);
        QCOMPARE(after.observation.fileResult, SQLITE_OK);
        QCOMPARE(after.observation.file.logicalBytes, sqlite3_int64(5120));
        QVERIFY(after.observedAfterCall);
        QVERIFY(sameObject(initial, after.observation.file));
        QVERIFY(matchesPath(after.observation.file, path));
        QCOMPARE(file->pMethods->xTruncate(file, 8192), SQLITE_OK);
        QCOMPARE(policy->afterEvents[size_t(Event::Action::Truncate)].observation.file.logicalBytes,
                 sqlite3_int64(8192));
        QCOMPARE(file->pMethods->xTruncate(file, 512), SQLITE_OK);
        QCOMPARE(file->pMethods->xFileControl(file, dukto::SqliteFileInfoControl, &current),
                 SQLITE_OK);
        QCOMPARE(current.logicalBytes, sqlite3_int64(512));
        QVERIFY(matchesPath(current, path));
        const auto hash = dukto::hashFile(path);
        const auto completed = policy->completed[size_t(Event::Action::Write)];
        policy->refuseWrite = true;
        QCOMPARE(file->pMethods->xWrite(file, body.constData(), body.size(), 8192), SQLITE_FULL);
        QCOMPARE(policy->completed[size_t(Event::Action::Write)], completed);
        QCOMPARE(dukto::hashFile(path), hash);
        QCOMPARE(file->pMethods->xFileControl(file, dukto::SqliteFileInfoControl, &current),
                 SQLITE_OK);
        QCOMPARE(current.logicalBytes, sqlite3_int64(512));
        QVERIFY(sameObject(initial, current));
        QCOMPARE(handle.close(), SQLITE_OK);
        const auto closed = policy->afterEvents[size_t(Event::Action::Close)];
        QVERIFY(!closed.observedAfterCall);
        QVERIFY(sameObject(initial, closed.observation.file));
        QCOMPARE(policy->badWriteObservations, 0);
    }

    // 日期：2026-11-08；两个连接及真实硬链接归于同一原生身份，独立对象即使同样大小也必须区分。
    void connectionsAndHardLinkAlias() {
        QTemporaryDir root;
        const auto path = root.filePath("first.sqlite");
        const auto alias = root.filePath("alias.sqlite");
        RawFile first(path, Writable), second(path, Writable);
#ifdef Q_OS_WIN
        QVERIFY(CreateHardLinkW(reinterpret_cast<LPCWSTR>(alias.utf16()),
                                reinterpret_cast<LPCWSTR>(path.utf16()), nullptr));
#else
        QVERIFY(::link(QFile::encodeName(path).constData(), QFile::encodeName(alias).constData()) ==
                0);
#endif
        RawFile linked(alias, Writable), other(root.filePath("other.sqlite"), Writable);
        std::array<DuktoSqliteFileInfo, 4> observed{};
        const std::array<sqlite3_file *, 4> files{first.file, second.file, linked.file, other.file};
        for (size_t index = 0; index < files.size(); ++index)
            QCOMPARE(files[index]->pMethods->xFileControl(
                         files[index], dukto::SqliteFileInfoControl, &observed[index]),
                     SQLITE_OK);
        QVERIFY(sameObject(observed[0], observed[1]));
        QVERIFY(sameObject(observed[0], observed[2]));
        QVERIFY(!sameObject(observed[0], observed[3]));
        QCOMPARE(observed[0].links, sqlite3_int64(2));
        QVERIFY(matchesPath(observed[2], alias));
    }

    // 日期：2026-11-08；底层只读写入真实失败后仍重新观察对象，不按错误码把原占用退为零。
    void nativeFailureRetainsActualObservation() {
        QTemporaryDir root;
        const auto path = root.filePath("readonly.sqlite");
        {
            RawFile writable(path, Writable);
            QCOMPARE(writable.file->pMethods->xWrite(writable.file, "kept", 4, 0), SQLITE_OK);
        }
        const auto hash = dukto::hashFile(path);
        auto policy = std::make_shared<Policy>();
        RawFile readonly(path, SQLITE_OPEN_READONLY | SQLITE_OPEN_MAIN_DB, policy);
        const auto code = readonly.file->pMethods->xWrite(readonly.file, "x", 1, 4096);
        QCOMPARE(code & 255, SQLITE_IOERR);
        QCOMPARE(policy->completed[size_t(Event::Action::Write)], 1);
        const auto before = policy->beforeEvents[size_t(Event::Action::Write)];
        const auto after = policy->afterEvents[size_t(Event::Action::Write)];
        QCOMPARE(after.observation.fileResult, SQLITE_OK);
        QCOMPARE(after.observation.file.logicalBytes, sqlite3_int64(4));
        QVERIFY(after.observedAfterCall);
        QVERIFY(sameObject(before.observation.file, after.observation.file));
        QVERIFY(matchesPath(after.observation.file, path));
        QCOMPARE(dukto::hashFile(path), hash);
    }

    // 日期：2026-11-08；匿名删除时关闭的临时对象仍有真实身份和占用，不能把空名称当作零占用。
    void anonymousTemporaryObject() {
        auto policy = std::make_shared<Policy>();
        RawFile handle({},
                       SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_DELETEONCLOSE |
                           SQLITE_OPEN_TEMP_DB,
                       policy);
        const QByteArray bytes(4096, 't');
        QCOMPARE(handle.file->pMethods->xWrite(handle.file, bytes.constData(), bytes.size(), 0),
                 SQLITE_OK);
        DuktoSqliteFileInfo observed{};
        QCOMPARE(handle.file->pMethods->xFileControl(handle.file, dukto::SqliteFileInfoControl,
                                                     &observed),
                 SQLITE_OK);
        QCOMPARE(observed.kind, 1);
        QCOMPARE(observed.logicalBytes, sqlite3_int64(4096));
        QVERIFY(observed.allocatedBytes >= 0);
#ifndef Q_OS_WIN
        QCOMPARE(observed.links, sqlite3_int64(0));
#endif
        QVERIFY(policy->observedWriteFlags & SQLITE_OPEN_TEMP_DB);
        QCOMPARE(policy->badWriteObservations, 0);
    }

    // 日期：2026-11-08；POSIX路径换代后仍观察原已打开对象；Windows原生共享规则拒绝换代也保持身份。
    void heldObjectDoesNotFollowReplacementPath() {
        QTemporaryDir root;
        const auto path = root.filePath("name.sqlite");
        const auto moved = root.filePath("held.sqlite");
        RawFile handle(path, Writable);
        QCOMPARE(handle.file->pMethods->xWrite(handle.file, "original", 8, 0), SQLITE_OK);
        DuktoSqliteFileInfo original{}, observed{};
        QCOMPARE(handle.file->pMethods->xFileControl(handle.file, dukto::SqliteFileInfoControl,
                                                     &original),
                 SQLITE_OK);
#ifdef Q_OS_WIN
        QVERIFY(!QFile::rename(path, moved));
#else
        QVERIFY(QFile::rename(path, moved));
        QFile replacement(path);
        QVERIFY(replacement.open(QIODevice::WriteOnly));
        QCOMPARE(replacement.write("new", 3), qint64(3));
        replacement.close();
        QVERIFY(!matchesPath(original, path));
        QVERIFY(matchesPath(original, moved));
#endif
        QCOMPARE(handle.file->pMethods->xFileControl(handle.file, dukto::SqliteFileInfoControl,
                                                     &observed),
                 SQLITE_OK);
        QVERIFY(sameObject(original, observed));
        QCOMPARE(observed.logicalBytes, sqlite3_int64(8));
    }

    // 日期：2026-11-08；真实稀疏文件超过4GiB时长度仍完整，原生分配量不能被逻辑长度替代。
    void sparseFileHasIndependentAllocation() {
        QTemporaryDir root;
        const auto path = root.filePath("sparse.sqlite");
        RawFile handle(path, Writable);
#ifdef Q_OS_WIN
        HANDLE native = INVALID_HANDLE_VALUE;
        QCOMPARE(handle.file->pMethods->xFileControl(handle.file, SQLITE_FCNTL_WIN32_GET_HANDLE,
                                                     &native),
                 SQLITE_OK);
        DWORD returned = 0;
        QVERIFY(
            DeviceIoControl(native, FSCTL_SET_SPARSE, nullptr, 0, nullptr, 0, &returned, nullptr));
#endif
        constexpr sqlite3_int64 Offset = 5LL * 1024 * 1024 * 1024 + 123;
        QCOMPARE(handle.file->pMethods->xWrite(handle.file, "x", 1, Offset), SQLITE_OK);
        DuktoSqliteFileInfo observed{};
        QCOMPARE(handle.file->pMethods->xFileControl(handle.file, dukto::SqliteFileInfoControl,
                                                     &observed),
                 SQLITE_OK);
        QCOMPARE(observed.logicalBytes, Offset + 1);
        QVERIFY(observed.allocatedBytes > 0);
        QVERIFY(observed.allocatedBytes < 1024 * 1024);
        QVERIFY(matchesPath(observed, path));
    }

    // 日期：2026-11-08；实际共享映射按本机页粒度扩展，已有句柄/无句柄及映射后的真实文件分别核验。
    void sharedMemoryExtentAndActualIdentity() {
        QTemporaryDir root;
        const auto path = root.filePath("shared.sqlite");
        auto policy = std::make_shared<Policy>();
        RawFile handle(path, Writable, policy);
        auto file = handle.file;
        QVERIFY(file->pMethods->iVersion >= 2);
        DuktoSqliteFileInfo observed{};
        QCOMPARE(
            file->pMethods->xFileControl(file, dukto::SqliteSharedMemoryInfoControl, &observed),
            SQLITE_OK);
        QCOMPARE(observed.kind, 0);
        sqlite3_int64 extent = 0;
        QCOMPARE(duktoSqliteSharedMemoryExtent(1, 32768, &extent), SQLITE_OK);
#ifdef Q_OS_WIN
        const sqlite3_int64 regions = 1;
#else
        const auto systemPage = ::sysconf(_SC_PAGESIZE);
        QVERIFY(systemPage > 0);
        const sqlite3_int64 regions = qMax<sqlite3_int64>(1, systemPage / 32768);
#endif
        QCOMPARE(extent, ((1 + regions) / regions) * regions * 32768);
        void volatile *mapped = nullptr;
        QCOMPARE(file->pMethods->xShmMap(file, 1, 32768, 1, &mapped), SQLITE_OK);
        QVERIFY(mapped);
        QCOMPARE(
            file->pMethods->xFileControl(file, dukto::SqliteSharedMemoryInfoControl, &observed),
            SQLITE_OK);
        QVERIFY(matchesPath(observed, path + "-shm"));
        QCOMPARE(observed.logicalBytes, extent);
        QCOMPARE(observed.mappedFileBytes, extent);
        const auto before = policy->beforeEvents[size_t(Event::Action::MapSharedMemory)];
        const auto after = policy->afterEvents[size_t(Event::Action::MapSharedMemory)];
        QCOMPARE(before.observation.sharedMemory.kind, 0);
        QCOMPARE(before.bytes, qint64(extent));
        QVERIFY(sameObject(observed, after.observation.sharedMemory));
        QVERIFY(after.observedAfterCall);
        QCOMPARE(file->pMethods->xShmUnmap(file, 1), SQLITE_OK);
        const auto unmap = policy->afterEvents[size_t(Event::Action::UnmapSharedMemory)];
        QCOMPARE(unmap.observation.sharedMemoryResult, SQLITE_OK);
        QCOMPARE(unmap.observation.sharedMemory.kind, 0);
        QVERIFY(unmap.observedAfterCall);
        sqlite3_int64 rejected = 99;
        QCOMPARE(duktoSqliteSharedMemoryExtent(std::numeric_limits<int>::max(), 32768, &rejected),
                 SQLITE_IOERR_SHMMAP);
        QCOMPARE(rejected, sqlite3_int64(0));
        QCOMPARE(duktoSqliteSharedMemoryExtent(-1, 32768, &rejected), SQLITE_IOERR_SHMMAP);
        QCOMPARE(duktoSqliteSharedMemoryExtent(0, 0, &rejected), SQLITE_IOERR_SHMMAP);
        void volatile *invalid = reinterpret_cast<void *>(1);
        QCOMPARE(file->pMethods->xShmMap(file, -1, 32768, 1, &invalid), SQLITE_IOERR_SHMMAP);
        QVERIFY(!invalid);
        QCOMPARE(file->pMethods->xShmMap(file, 0, 32768, 1, nullptr), SQLITE_MISUSE);
#ifndef Q_OS_WIN
        QCOMPARE(duktoSqliteSharedMemoryExtent(65535, 32768, &rejected), SQLITE_IOERR_SHMMAP);
        QCOMPARE(rejected, sqlite3_int64(0));
#endif
    }

    // 日期：2026-11-08；生产Qt SQL实际journal/WAL与排序溢写均提供句柄观察，不止主库直接API可用。
    void realSqlJournalsWalAndTemporarySort() {
        QTemporaryDir root;
        auto policy = std::make_shared<Policy>();
        Connection connection(root.filePath("sql.sqlite"), policy);
        QSqlQuery query(connection.db);
        QVERIFY(query.exec("CREATE TABLE data(id INTEGER,body BLOB)"));
        QVERIFY(query.exec("INSERT INTO data VALUES(1,zeroblob(4096))"));
        QVERIFY(policy->observedWriteFlags & SQLITE_OPEN_MAIN_DB);
        QVERIFY(policy->observedWriteFlags & SQLITE_OPEN_MAIN_JOURNAL);
        QVERIFY(query.exec("PRAGMA journal_mode=WAL"));
        QVERIFY(query.next());
        QCOMPARE(query.value(0).toString(), QString("wal"));
        query.finish();
        QVERIFY(query.exec("INSERT INTO data VALUES(2,zeroblob(8192))"));
        QVERIFY(policy->observedWriteFlags & SQLITE_OPEN_WAL);
        const auto map = policy->afterEvents[size_t(Event::Action::MapSharedMemory)];
        QCOMPARE(map.observation.sharedMemoryResult, SQLITE_OK);
        QVERIFY(matchesPath(map.observation.sharedMemory, root.filePath("sql.sqlite-shm")));
        QVERIFY(query.exec("PRAGMA cache_size=8"));
        QVERIFY(query.exec("PRAGMA temp_store=FILE"));
        QVERIFY(query.exec("WITH RECURSIVE seq(x) AS (VALUES(3) UNION ALL SELECT x+1 FROM seq "
                           "WHERE x<4096) INSERT INTO data SELECT x,randomblob(2048) FROM seq"));
        query.setForwardOnly(true);
        QVERIFY(query.exec("SELECT id FROM data ORDER BY hex(body) DESC"));
        int rows = 0;
        while (query.next())
            ++rows;
        QCOMPARE(rows, 4096);
        QVERIFY(policy->observedWriteFlags & SQLITE_OPEN_TEMP_JOURNAL);
        QCOMPARE(policy->badWriteObservations, 0);
    }

    // 日期：2026-11-08；错误参数和非原生包装显式失败，不能把无法观察的文件当作零长度成功。
    void invalidAndForeignHandlesFailClosed() {
        DuktoSqliteFileInfo value{};
        QCOMPARE(duktoSqliteNativeFileInfo(nullptr, 0, &value), SQLITE_MISUSE);
        QCOMPARE(duktoSqliteNativeFileInfo(nullptr, 0, nullptr), SQLITE_MISUSE);
        QTemporaryDir root;
        RawFile handle(root.filePath("data.sqlite"), Writable);
        QCOMPARE(duktoSqliteNativeFileInfo(handle.file, 0, &value), SQLITE_NOTFOUND);
        QCOMPARE(value.kind, 0);
        QCOMPARE(
            handle.file->pMethods->xFileControl(handle.file, dukto::SqliteFileInfoControl, nullptr),
            SQLITE_MISUSE);
        QCOMPARE(duktoSqliteSharedMemoryExtent(0, 32768, nullptr), SQLITE_MISUSE);
    }
};

QTEST_GUILESS_MAIN(SqliteFileInfoTests)
#include "sqlite_file_info_tests.moc"

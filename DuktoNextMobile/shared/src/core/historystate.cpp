#include "historystate.h"
#include "buffercredit.h"
#include "error.h"
#include "files.h"
#include "historybudget.h"
#include "sqlitecache.h"
#include "sqliteruntime.h"
#include "sqlitevfs.h"
#include "statesession.h"
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QJsonDocument>
#include <QLockFile>
#include <QSqlQuery>
#include <QUuid>
#include <cstring>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <sys/stat.h>
#endif

namespace dukto {
namespace {
// 日期：2026-11-09；只有固定历史库可进入迁移协议，不能把调用方任意路径当作可管理状态。
void checkedName(const QString &name) {
    if (name != "history.sqlite" && name != "receipts.sqlite")
        throw Error(ExitCode::Config, QStringLiteral("历史数据库名称无效"), "history-state");
}

// 日期：2026-11-09；链接和损坏项同样算存在，后续必须明确拒绝而不是重建覆盖。
bool present(const QString &path) {
    return QFileInfo::exists(path) || isLinkedPath(path);
}

// 日期：2026-11-09；迁移只接受已收敛的单主库，日志/WAL/shm存在时保留现场并要求关闭旧程序。
void noSidecars(const QString &path) {
    for (const auto &suffix : {"-journal", "-wal", "-shm"})
        if (present(path + suffix))
            throw Error(ExitCode::Permission, QStringLiteral("请先关闭旧程序并核对历史数据库日志"),
                        "history-state");
}

// 日期：2026-11-09；旧接收锁的存在不是删除授权；活动或遗留锁一律保留，防止迁移后误报旧任务已中断。
void noLegacyReceivers(const QString &path) {
    if (QFileInfo(path).fileName() != "receipts.sqlite")
        return;
    if (present(path + ".admission.lock"))
        throw Error(ExitCode::Permission,
                    QStringLiteral("旧接收正在准入，请先关闭旧程序并核对接收任务"),
                    "history-state");
    const auto locks = path + ".locks";
    if (!present(locks))
        return;
#ifdef Q_OS_WIN
    NativeDirectoryLock directory(locks, false);
#else
    PosixDirectory directory(locks, false);
#endif
    directory.visitEntries([](const NativeDirectoryEntry &) {
        // 日期：2026-11-09；不依据PID、文件年龄或名称移除旧锁，未知项同样要求人工核对。
        throw Error(ExitCode::Permission,
                    QStringLiteral("旧接收任务锁尚未释放，请先关闭旧程序并核对旧任务"),
                    "history-state");
    });
}

// 日期：2026-11-09；固定大小身份以平台/卷/原生ID编码；内容摘要另外核验，inode复用不会认可不同正文。
QByteArray objectKey(const DuktoSqliteFileInfo &info) {
    return QByteArray::number(info.platform) + ':' + QByteArray::number(info.volume) + ':' +
           QByteArray(reinterpret_cast<const char *>(info.identity), sizeof(info.identity)).toHex();
}

// 日期：2026-11-09；读取SQLite自己持有的文件，不额外开关POSIX同inode描述符而意外释放进程的fcntl锁。
QByteArray readBlock(sqlite3_file *file, qint64 offset, int count) {
    QByteArray bytes(count, Qt::Uninitialized);
    if (file->pMethods->xRead(file, bytes.data(), count, offset) != SQLITE_OK)
        throw Error(ExitCode::Disk, QStringLiteral("旧历史数据库读取失败"), "history-state");
    return bytes;
}
} // namespace

struct HistoryState::Legacy final {
    SqliteCacheCredit cache{1024, true};
    const QString connection =
        "history-source-" + QUuid::createUuid().toString(QUuid::WithoutBraces);
    QString path;
#ifdef Q_OS_WIN
    NativeDirectoryLock parent;
#else
    PosixDirectory parent;
#endif
    QSqlDatabase database;
    sqlite3_file *file = nullptr;
    DuktoSqliteFileInfo info{};
    QByteArray hash;
    std::function<void()> check;

    // 日期：2026-11-09；只读事务持续阻止旧回滚模式数据库提交，迁移与后续新库使用均不修改原件。
    explicit Legacy(const QString &source, std::function<void()> checkpoint)
        : path(source), parent(QFileInfo(source).absolutePath(), false),
          check(std::move(checkpoint)) {
        noSidecars(path);
        database = addSqliteDatabase(connection);
        try {
            database.setDatabaseName(path);
            database.setConnectOptions("QSQLITE_OPEN_READONLY;QSQLITE_BUSY_TIMEOUT=1000");
            if (!database.open())
                throw Error(ExitCode::Disk, QStringLiteral("无法只读打开旧历史数据库"),
                            "history-state");
            cache.configure(database);
            QSqlQuery query(database);
            for (const auto &sql : {"PRAGMA trusted_schema=OFF", "PRAGMA query_only=ON", "BEGIN"})
                if (!query.exec(sql))
                    throw Error(ExitCode::Disk, QStringLiteral("无法固定旧历史数据库快照"),
                                "history-state");
            if (!query.exec("SELECT count(*) FROM sqlite_schema") || !query.next())
                throw Error(ExitCode::Integrity, QStringLiteral("旧历史数据库结构不可读"),
                            "history-state");
            query.finish();
            if (sqlite3_file_control(sqliteHandle(database), "main", SQLITE_FCNTL_FILE_POINTER,
                                     &file) != SQLITE_OK ||
                !file || !file->pMethods ||
                sqlite3_file_control(sqliteHandle(database), "main", SqliteFileInfoControl,
                                     &info) != SQLITE_OK ||
                info.kind != 1 || info.links != 1 || info.logicalBytes < 0 ||
                info.logicalBytes > MaxMetadataBytes)
                throw Error(ExitCode::Integrity,
                            QStringLiteral("旧历史数据库对象或大小不符合迁移条件"),
                            "history-state");
            verifyPath();
            noSidecars(path);
            noLegacyReceivers(path);
            if (info.logicalBytes > 0) {
                const auto header = readBlock(file, 0, 100);
                if (header.left(16) != QByteArray("SQLite format 3\0", 16) || header[18] != 1 ||
                    header[19] != 1)
                    throw Error(ExitCode::Integrity,
                                QStringLiteral("旧历史数据库不是收敛的回滚模式主库"),
                                "history-state");
            }
            if (!query.exec("PRAGMA quick_check(1)") || !query.next() ||
                query.value(0).toString() != "ok" || query.next())
                throw Error(ExitCode::Integrity, QStringLiteral("旧历史数据库完整性检查失败"),
                            "history-state");
            query.finish();
            hash = copy(nullptr);
        } catch (...) {
            close();
            throw;
        }
    }

    // 日期：2026-11-09；旧库只读事务按SQLite自身关闭协议归还锁，不单独关闭其原生文件句柄。
    ~Legacy() {
        close();
    }

    // 日期：2026-11-09；构造失败与正常析构共用注销，页缓存授信在数据库真正关闭后释放。
    void close() {
        database.close();
        database = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection);
    }

    // 日期：2026-11-09；固定父目录与SQLite实际对象逐字段核对；POSIX仅stat，不关闭同inode额外描述符。
    void verifyPath() const {
#ifdef Q_OS_WIN
        const auto handle =
            CreateFileW(reinterpret_cast<LPCWSTR>(path.utf16()), FILE_READ_ATTRIBUTES,
                        FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                        FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (handle == INVALID_HANDLE_VALUE)
            throw Error(ExitCode::Integrity, QStringLiteral("旧历史数据库路径不可核验"),
                        "history-state");
        FILE_ID_INFO identity{};
        FILE_STANDARD_INFO standard{};
        FILE_ATTRIBUTE_TAG_INFO attributes{};
        const bool same =
            GetFileInformationByHandleEx(handle, FileIdInfo, &identity, sizeof(identity)) &&
            GetFileInformationByHandleEx(handle, FileStandardInfo, &standard, sizeof(standard)) &&
            GetFileInformationByHandleEx(handle, FileAttributeTagInfo, &attributes,
                                         sizeof(attributes)) &&
            !(attributes.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) && !standard.Directory &&
            standard.NumberOfLinks == 1 && info.platform == 2 &&
            info.volume == identity.VolumeSerialNumber &&
            std::memcmp(info.identity, identity.FileId.Identifier, sizeof(info.identity)) == 0 &&
            info.logicalBytes == standard.EndOfFile.QuadPart;
        CloseHandle(handle);
#else
        parent.verify();
        const auto current = parent.fileInformation(QFileInfo(path).fileName());
        sqlite3_uint64 inode = 0;
        for (int index = 7; index >= 0; --index)
            inode = (inode << 8) | info.identity[index];
        const bool same = S_ISREG(current.st_mode) && current.st_nlink == 1 && info.platform == 1 &&
                          info.volume == sqlite3_uint64(current.st_dev) &&
                          inode == sqlite3_uint64(current.st_ino) &&
                          info.logicalBytes == current.st_size;
#endif
        if (!same)
            throw Error(ExitCode::Integrity, QStringLiteral("旧历史数据库路径已变化"),
                        "history-state");
    }

    // 日期：2026-11-09；256KiB固定授信逐块散列/复制，源读事务保持；不把整库或所有记录载入内存。
    QByteArray copy(QIODevice *target) const {
        BufferCredit credit(BufferSize);
        QCryptographicHash digest(QCryptographicHash::Sha256);
        for (qint64 offset = 0; offset < info.logicalBytes;) {
            if (check)
                check();
            const auto bytes =
                readBlock(file, offset, int(qMin(BufferSize, info.logicalBytes - offset)));
            digest.addData(bytes);
            if (target)
                writeAll(*target, bytes);
            offset += bytes.size();
        }
        verifyPath();
        noSidecars(path);
        noLegacyReceivers(path);
        return digest.result();
    }
};

// 日期：2026-11-09；成员直到工厂完成全部校验才返回给数据库调用方。
HistoryState::HistoryState() = default;

// 日期：2026-11-09；逆序先关闭旧源读事务，再释放受保护历史根与其协调会话。
HistoryState::~HistoryState() = default;

// 日期：2026-11-09；写前准备凭据与独占发布可重入，未知非空目标、源变化和不完整标记均拒绝覆盖。
std::shared_ptr<HistoryState> HistoryState::open(const QString &parent, const QString &name,
                                                 std::function<void()> check) {
    checkedName(name);
    if (check)
        check();
    auto result = std::shared_ptr<HistoryState>(new HistoryState);
    result->name_ = name;
    const auto source = QDir(parent).absoluteFilePath(name);
    if (present(source))
        result->legacy_.reset(new Legacy(source, check));
    result->store_ = StateSession::root(parent, "history", true, PrivateStore::Use::Shared, check);
    auto &store = *result->store_;
    result->budget_.reset(new HistoryBudget(result->store_, parent));
    result->budget_->admit(name, result->legacy_ ? result->legacy_->info.logicalBytes : 0);
    result->budget_->admit(name + ".origin.json", 65536);
    QLockFile initialization(QDir(store.directory()).filePath(name + ".migration.lock"));
    initialization.setStaleLockTime(0);
    if (!initialization.tryLock(5000))
        throw Error(ExitCode::Permission, QStringLiteral("历史数据库正在迁移，请稍后重试"),
                    "history-state");
    const auto marker = name + ".origin.json";
    const auto root = QString::fromLatin1(store.identity().toHex());
    const auto object =
        result->legacy_ ? QString::fromLatin1(objectKey(result->legacy_->info)) : QString();
    const auto hash = result->legacy_ ? result->legacy_->hash
                                      : QCryptographicHash::hash({}, QCryptographicHash::Sha256);
    const QJsonObject origin{
        {"version", 1},
        {"root", root},
        {"name", name},
        {"source", result->legacy_ ? "legacy" : "absent"},
        {"object", object},
        {"sha256", QString::fromLatin1(hash.toHex())},
        {"bytes", QString::number(result->legacy_ ? result->legacy_->info.logicalBytes : 0)}};
    bool complete = false;
    if (store.exists(marker)) {
        QJsonParseError error{};
        const auto document = QJsonDocument::fromJson(store.read(marker), &error);
        auto observed = document.object();
        const auto state = observed.take("state");
        if (error.error != QJsonParseError::NoError || !document.isObject() || observed != origin ||
            (state != "prepared" && state != "complete"))
            throw Error(ExitCode::Integrity,
                        QStringLiteral("旧历史数据库或迁移凭据已变化，原件已保留"),
                        "history-state");
        complete = state == "complete";
    } else {
        if (store.exists(name))
            throw Error(ExitCode::Integrity, QStringLiteral("历史目标缺少迁移凭据，拒绝覆盖"),
                        "history-state");
        auto prepared = origin;
        prepared.insert("state", "prepared");
        store.write(marker, QJsonDocument(prepared).toJson(QJsonDocument::Compact));
    }
    if (check)
        check();
    if (!complete) {
        if (!store.exists(name))
            store.create(name, result->legacy_ ? result->legacy_->info.logicalBytes : 0,
                         [&](QIODevice &target) {
                             // 日期：2026-11-09；正文与准备凭据摘要必须相同，复制期间旧库改变不得发布。
                             if (result->legacy_ && result->legacy_->copy(&target) != hash)
                                 throw Error(ExitCode::Integrity,
                                             QStringLiteral("旧历史数据库复制期间变化"),
                                             "history-state");
                         });
        if (check)
            check();
        store.validateFile(name);
        if (hashFile(QDir(store.directory()).filePath(name)) != hash)
            throw Error(ExitCode::Integrity,
                        QStringLiteral("历史迁移目标与准备凭据不符，原件已保留"), "history-state");
        auto done = origin;
        done.insert("state", "complete");
        store.write(marker, QJsonDocument(done).toJson(QJsonDocument::Compact));
    }
    store.validateSqlitePath(name);
    return result;
}

// 日期：2026-11-09；只路由固定接收库；普通显式Catalog路径继续保留原有调用语义。
std::shared_ptr<HistoryState> HistoryState::catalog(const QString &path) {
    const QFileInfo info(path);
    if (info.fileName() != "receipts.sqlite")
        return {};
    auto parent = info.absolutePath();
    if (QFileInfo(parent).fileName() == "history" &&
        present(QDir(parent).filePath("state-domain.bin")))
        parent = QFileInfo(parent).absolutePath();
    return open(parent, "receipts.sqlite");
}

// 日期：2026-11-09；目标连接关闭前调用方持续持有本对象，GC不能跨越其共享根寿命。
QString HistoryState::path() const {
    store_->validateSqlitePath(name_);
    return QDir(store_->directory()).filePath(name_);
}

// 日期：2026-11-09；SQLite原生观察与不跟随链接的私有路径属性相同才允许使用，POSIX不打开额外主库描述符。
void HistoryState::validate(const QSqlDatabase &database) const {
    budget_->check();
    const auto expected = store_->validateSqlitePath(name_);
    DuktoSqliteFileInfo observed{};
    if (!database.isOpen() ||
        database.databaseName() != QDir(store_->directory()).filePath(name_) ||
        sqlite3_file_control(sqliteHandle(database), "main", SqliteFileInfoControl, &observed) !=
            SQLITE_OK ||
        observed.kind != 1 || observed.platform != expected.identityPlatform ||
        observed.volume != expected.volume ||
        std::memcmp(observed.identity, expected.identity.data(), expected.identity.size()) != 0 ||
        observed.links != 1)
        throw Error(ExitCode::Integrity, QStringLiteral("历史数据库连接与受保护路径不一致"),
                    "history-state");
}
// 日期：2026-11-09；策略寿命由Qt驱动覆盖全部派生文件，且持续保留同一历史根共享资格。
std::shared_ptr<SqliteFilePolicy> HistoryState::policy() const {
    return budget_->connection();
}
} // namespace dukto

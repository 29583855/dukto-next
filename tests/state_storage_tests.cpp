#if defined(_WIN32) && !defined(_WIN32_WINNT)
#define _WIN32_WINNT 0x0602
#endif
#include "core/buffercredit.h"
#include "core/error.h"
#include "core/files.h"
#include "core/historystate.h"
#include "core/privatestore.h"
#include "core/sqliteruntime.h"
#include "core/sqlitevfs.h"
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QProcess>
#include <QSqlDatabase>
#include <QSqlQuery>
#include <QTemporaryDir>
#include <QUuid>
#include <QtTest>
#include <cstdlib>
#include <cstring>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <io.h>
#include <windows.h>
#include <winioctl.h>
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace {
constexpr qint64 LargeLength = 4294967296LL + 19;

struct Connection {
    QString name = QUuid::createUuid().toString();
    QSqlDatabase database = dukto::addSqliteDatabase(name);
    // 日期：2026-11-08；测试固定驱动的真实句柄与枚举观察可交叉核对，使用独立命名连接。
    explicit Connection(const QString &path) {
        database.setDatabaseName(path);
    }
    // 日期：2026-11-08；先销毁本地连接引用再注销，断言提前返回也不会泄漏连接。
    ~Connection() {
        database.close();
        database = QSqlDatabase();
        QSqlDatabase::removeDatabase(name);
    }
};

// 日期：2026-11-08；真实子进程只测试SQLite锁，故意不取得应用状态锁，避免把维护拒绝误当数据库互斥。
int attemptSqliteWrite(const QString &path) {
    Connection connection(path);
    if (!connection.database.open())
        return 91;
    auto handle = dukto::sqliteHandle(connection.database);
    sqlite3_busy_timeout(handle, 0);
    return sqlite3_exec(handle, "INSERT INTO payload VALUES(2)", nullptr, nullptr, nullptr);
}

// 日期：2026-11-09；只在真实准备凭据或独占正文已发布边界退出，不给生产程序加入故障开关。
void crashHistoryMigration(const QString &parent, bool published) {
    dukto::HistoryState::open(parent, "history.sqlite", [&]() {
        // 日期：2026-11-09；通过实际文件观察中断边界，重启必须复用相同迁移凭据。
        if (QFileInfo::exists(parent + "/history/history.sqlite.origin.json") &&
            QFileInfo::exists(parent + "/history/history.sqlite") == published)
            std::_Exit(published ? 50 : 49);
    });
    std::_Exit(90);
}

// 日期：2026-11-07；只建立逻辑长度探针，Windows先启用稀疏属性，避免实际分配四GiB。
bool sparse(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadWrite))
        return false;
#ifdef Q_OS_WIN
    DWORD returned = 0;
    if (!DeviceIoControl(reinterpret_cast<HANDLE>(_get_osfhandle(file.handle())), FSCTL_SET_SPARSE,
                         nullptr, 0, nullptr, 0, &returned, nullptr))
        return false;
#endif
    return file.resize(LargeLength);
}

// 日期：2026-11-07；独立解析固定类别，避免只比较总数而漏计SQLite旁路。
QJsonObject group(const QJsonObject &report, const QString &name) {
    for (const auto &value : report["categories"].toArray())
        if (value.toObject()["kind"].toString() == name)
            return value.toObject();
    return {};
}

// 日期：2026-11-07；实际小缓存写事务产生热日志，退出绕过SQLite析构以保留真实恢复现场。
void leaveJournal(const QString &state) {
    dukto::PrivateStore store(state, true);
    store.write("live.sqlite", {});
    auto db = QSqlDatabase::addDatabase("QSQLITE", "storage-crash");
    db.setDatabaseName(state + "/live.sqlite");
    if (!db.open())
        std::_Exit(91);
    QSqlQuery query(db);
    for (const auto &sql : {"PRAGMA cache_size=8", "PRAGMA cache_spill=ON",
                            "CREATE TABLE payload(value BLOB)", "BEGIN IMMEDIATE"})
        if (!query.exec(sql))
            std::_Exit(92);
    for (int index = 0; index < 64; ++index)
        if (!query.exec("INSERT INTO payload VALUES(zeroblob(65536))"))
            std::_Exit(93);
    QFile journal(state + "/live.sqlite-journal");
    if (!journal.open(QIODevice::ReadOnly) || journal.read(8).toHex() != "d9d505f920a163d7")
        std::_Exit(94);
    std::_Exit(47);
}

// 日期：2026-11-07；真实命令行进程使用测试构建同目录程序，不经shell且等待有界。
bool invoke(QProcess &process, const QStringList &arguments) {
    auto program = QCoreApplication::applicationDirPath() + "/dukto-cli";
#ifdef Q_OS_WIN
    program += ".exe";
#endif
    process.start(program, arguments);
    return process.waitForFinished(30000) && process.exitStatus() == QProcess::NormalExit;
}
} // namespace

class StateStorageTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-09；两种生产历史库都保留原件，迁移后的修改不会回写旧文件；真实子进程验证旧库写锁。
    void protectedHistoryMigration_data() {
        QTest::addColumn<QString>("name");
        QTest::newRow("gui-history") << QString("history.sqlite");
        QTest::newRow("receive-receipts") << QString("receipts.sqlite");
    }

    // 日期：2026-11-09；多连接共享新历史根，关闭其中一个仍阻止旧库写入，最后一个退出才归还锁。
    void protectedHistoryMigration() {
        QFETCH(QString, name);
        QTemporaryDir root;
        const auto source = root.filePath(name);
        {
            Connection original(source);
            QVERIFY(original.database.open());
            QSqlQuery query(original.database);
            QVERIFY(query.exec("CREATE TABLE payload(value INTEGER)"));
            QVERIFY(query.exec("INSERT INTO payload VALUES(1)"));
        }
        const auto originalHash = dukto::hashFile(source);
        const auto baseline = QSqlDatabase::connectionNames();
        auto first = dukto::HistoryState::open(root.path(), name);
        auto second = dukto::HistoryState::open(root.path(), name);
        QCOMPARE(first->path(), root.filePath("history/" + name));
        QCOMPARE(first->path(), second->path());
        QCOMPARE(dukto::hashFile(first->path()), originalHash);
        QVERIFY_EXCEPTION_THROWN(dukto::PrivateStore(root.filePath("history"), false,
                                                     dukto::PrivateStore::Use::Maintenance),
                                 dukto::Error);
        const auto attempt = [&]() {
            // 日期：2026-11-09；新进程直接使用SQLite，不能把状态维护锁的拒绝当作旧库读锁生效。
            QProcess child;
            child.start(QCoreApplication::applicationFilePath(), {"--try-sqlite-write", source});
            if (!child.waitForFinished(10000) || child.exitStatus() != QProcess::NormalExit)
                return -1;
            return child.exitCode();
        };
        QCOMPARE(attempt(), SQLITE_BUSY);
        first.reset();
        QCOMPARE(attempt(), SQLITE_BUSY);
        {
            Connection destination(second->path());
            QVERIFY(destination.database.open());
            QSqlQuery query(destination.database);
            QVERIFY(query.exec("INSERT INTO payload VALUES(9)"));
        }
        second.reset();
        QCOMPARE(QSqlDatabase::connectionNames(), baseline);
        QCOMPARE(dukto::hashFile(source), originalHash);
        {
            auto reopened = dukto::HistoryState::open(root.path(), name);
            Connection destination(reopened->path());
            QVERIFY(destination.database.open());
            QSqlQuery query(destination.database);
            QVERIFY(query.exec("SELECT sum(value) FROM payload"));
            QVERIFY(query.next());
            QCOMPARE(query.value(0).toInt(), 10);
        }
        QCOMPARE(attempt(), SQLITE_OK);
        QVERIFY_EXCEPTION_THROWN(dukto::HistoryState::open(root.path(), name), dukto::Error);
        QVERIFY(QFileInfo::exists(root.filePath("history/" + name)));
    }

    // 日期：2026-11-09；初次使用无旧库时创建私有空库和完整凭据，不允许后来出现的旧库冒充相同来源。
    void protectedHistoryAbsentAndUnknownTarget() {
        QTemporaryDir root;
        {
            auto state = dukto::HistoryState::open(root.path(), "history.sqlite");
            dukto::PrivateStore store(root.filePath("history"));
            QCOMPARE(store.validateFile("history.sqlite"), qint64(0));
            QCOMPARE(QJsonDocument::fromJson(store.read("history.sqlite.origin.json"))
                         .object()["state"]
                         .toString(),
                     QString("complete"));
            auto reopened = dukto::HistoryState::open(root.path(), "history.sqlite");
            QCOMPARE(reopened->path(), state->path());
            store.write("receipts.sqlite", "unknown target");
            QVERIFY_EXCEPTION_THROWN(dukto::HistoryState::open(root.path(), "receipts.sqlite"),
                                     dukto::Error);
            QCOMPARE(store.read("receipts.sqlite"), QByteArray("unknown target"));
        }
        Connection late(root.filePath("history.sqlite"));
        QVERIFY(late.database.open());
        QVERIFY_EXCEPTION_THROWN(dukto::HistoryState::open(root.path(), "history.sqlite"),
                                 dukto::Error);
    }

    // 日期：2026-11-09；对已活动主库重复路径/连接核验不能释放SQLite写锁，真实外部进程仍被拒绝。
    void protectedHistoryPathValidationKeepsSqliteLocks() {
        QTemporaryDir root;
        auto state = dukto::HistoryState::open(root.path(), "history.sqlite");
        Connection writer(state->path());
        QVERIFY(writer.database.open());
        QSqlQuery query(writer.database);
        QVERIFY(query.exec("CREATE TABLE payload(value INTEGER)"));
        QVERIFY(query.exec("BEGIN IMMEDIATE"));
        QVERIFY(query.exec("INSERT INTO payload VALUES(1)"));
        {
            auto other = dukto::HistoryState::open(root.path(), "history.sqlite");
            QCOMPARE(other->path(), state->path());
            state->validate(writer.database);
            other->validate(writer.database);
        }
        QProcess child;
        child.start(QCoreApplication::applicationFilePath(), {"--try-sqlite-write", state->path()});
        QVERIFY(child.waitForFinished(10000));
        QCOMPARE(child.exitStatus(), QProcess::NormalExit);
        QCOMPARE(child.exitCode(), SQLITE_BUSY);
        QVERIFY(query.exec("ROLLBACK"));
    }

    // 日期：2026-11-09；任一旧旁路文件与损坏正文均拒绝迁移，不能创建新库掩盖原件。
    void protectedHistoryRejectsUnsafeSource() {
        QTemporaryDir root;
        const auto source = root.filePath("history.sqlite");
        {
            Connection original(source);
            QVERIFY(original.database.open());
            QSqlQuery query(original.database);
            QVERIFY(query.exec("CREATE TABLE payload(value INTEGER)"));
        }
        const auto originalHash = dukto::hashFile(source);
        for (const auto suffix : {"-journal", "-wal", "-shm"}) {
            QFile sidecar(source + suffix);
            QVERIFY(sidecar.open(QIODevice::WriteOnly));
            QCOMPARE(sidecar.write("preserved"), qint64(9));
            sidecar.close();
            QVERIFY_EXCEPTION_THROWN(dukto::HistoryState::open(root.path(), "history.sqlite"),
                                     dukto::Error);
            QCOMPARE(dukto::hashFile(source), originalHash);
            QVERIFY(!QFileInfo::exists(root.filePath("history")));
            QVERIFY(sidecar.remove());
        }
        QFile file(source);
        QVERIFY(file.open(QIODevice::WriteOnly | QIODevice::Truncate));
        QCOMPARE(file.write("broken history"), qint64(14));
        file.close();
        const auto brokenHash = dukto::hashFile(source);
        const auto connections = QSqlDatabase::connectionNames();
        QVERIFY_EXCEPTION_THROWN(dukto::HistoryState::open(root.path(), "history.sqlite"),
                                 dukto::Error);
        QCOMPARE(QSqlDatabase::connectionNames(), connections);
        QCOMPARE(dukto::hashFile(source), brokenHash);
        QVERIFY(!QFileInfo::exists(root.filePath("history")));
    }

    // 日期：2026-11-09；准备凭据后和正文发布后真实进程退出，重启分别创建或核验同一目标，不重复迁移。
    void protectedHistoryCrashRecovery_data() {
        QTest::addColumn<bool>("published");
        QTest::newRow("prepared") << false;
        QTest::newRow("published") << true;
    }

    // 日期：2026-11-09；中断重入要求原源身份与摘要未变，正文及状态原件分别独立核对。
    void protectedHistoryCrashRecovery() {
        QFETCH(bool, published);
        QTemporaryDir root;
        const auto source = root.filePath("history.sqlite");
        {
            Connection original(source);
            QVERIFY(original.database.open());
            QSqlQuery query(original.database);
            QVERIFY(query.exec("CREATE TABLE payload(value INTEGER)"));
            QVERIFY(query.exec("INSERT INTO payload VALUES(1)"));
        }
        const auto hash = dukto::hashFile(source);
        QProcess child;
        child.start(
            QCoreApplication::applicationFilePath(),
            {"--crash-history-migration", root.path(), published ? "published" : "prepared"});
        QVERIFY(child.waitForFinished(20000));
        QCOMPARE(child.exitStatus(), QProcess::NormalExit);
        QCOMPARE(child.exitCode(), published ? 50 : 49);
        {
            dukto::PrivateStore store(root.filePath("history"));
            QCOMPARE(QJsonDocument::fromJson(store.read("history.sqlite.origin.json"))
                         .object()["state"]
                         .toString(),
                     QString("prepared"));
            QCOMPARE(store.exists("history.sqlite"), published);
        }
        {
            auto state = dukto::HistoryState::open(root.path(), "history.sqlite");
            QCOMPARE(dukto::hashFile(state->path()), hash);
            dukto::PrivateStore store(root.filePath("history"));
            QCOMPARE(QJsonDocument::fromJson(store.read("history.sqlite.origin.json"))
                         .object()["state"]
                         .toString(),
                     QString("complete"));
        }
        QCOMPARE(dukto::hashFile(source), hash);
    }
    // 日期：2026-11-07；超32位逻辑长度、七类计数、正文保密和缓冲归还均用真实文件独立核验。
    void logicalLengthsAndCategories() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        store.write("large.sqlite", {});
        QVERIFY(sparse(store.directory() + "/large.sqlite"));
        const QByteArray secret("private-payload");
        QCOMPARE(secret.size(), 15);
        for (const auto &name : {"data.sqlite-journal", "data.sqlite-wal", "data.sqlite-shm",
                                 "credential.json", "task.lock", "unknown.bin"})
            store.write(name, secret);
        const auto connections = QSqlDatabase::connectionNames();
        const auto used = dukto::BufferCredit::usage().value("used");
        const auto report = store.storageUsage();
        QCOMPARE(report["event"].toString(), QString("state-storage"));
        QCOMPARE(report["entries"].toString(), QString("8"));
        QCOMPARE(report["regularFiles"].toString(), QString("8"));
        QCOMPARE(report["logicalBytes"].toString(), QString::number(LargeLength + 90));
        QCOMPARE(report["sqliteSidecarBytes"].toString(), QString("45"));
        QVERIFY(report["allocatedBytes"].toString().toLongLong() >= 0);
        QVERIFY(report["allocatedBytes"].toString().toLongLong() < LargeLength);
        qint64 allocated = 0;
        for (const auto &value : report["categories"].toArray())
            allocated += value.toObject()["allocatedBytes"].toString().toLongLong();
        QCOMPARE(report["allocatedBytes"].toString(), QString::number(allocated));
        QCOMPARE(report["categories"].toArray().size(), 7);
        QCOMPARE(group(report, "locks")["files"].toString(), QString("2"));
        QCOMPARE(group(report, "other")["logicalBytes"].toString(), QString("15"));
        QVERIFY(report["directRegularFilesOnly"].toBool());
        QVERIFY(!QJsonDocument(report).toJson().contains(secret));
        QCOMPARE(store.read("credential.json"), secret);
        QCOMPARE(QSqlDatabase::connectionNames(), connections);
        QCOMPARE(dukto::BufferCredit::usage().value("used"), used);
    }

    // 日期：2026-11-07；只观察热日志原属性，不打开数据库恢复或更改库/日志任一原字节。
    void hotJournalIsObservedWithoutRecovery() {
        QTemporaryDir root;
        const auto state = root.filePath("state");
        QProcess process;
        process.start(QCoreApplication::applicationFilePath(), {"--leave-journal", state});
        QVERIFY(process.waitForFinished(30000));
        QCOMPARE(process.exitCode(), 47);
        const auto database = state + "/live.sqlite";
        const auto journal = database + "-journal";
        const auto databaseHash = dukto::hashFile(database);
        const auto journalHash = dukto::hashFile(journal);
        const auto journalBytes = QFileInfo(journal).size();
        QVERIFY(journalBytes > 0);
        const auto expected = QFileInfo(database).size() + journalBytes;
        dukto::PrivateStore store(state, false, dukto::PrivateStore::Use::Maintenance);
        const auto connections = QSqlDatabase::connectionNames();
        const auto report = store.storageUsage();
        QCOMPARE(report["logicalBytes"].toString(), QString::number(expected));
        QCOMPARE(report["sqliteSidecarBytes"].toString(), QString::number(journalBytes));
        QCOMPARE(dukto::hashFile(database), databaseHash);
        QCOMPARE(dukto::hashFile(journal), journalHash);
        QCOMPARE(QSqlDatabase::connectionNames(), connections);
    }

    // 日期：2026-11-07；硬链接按名称保守重复计量并明确报告，不授予任何删除资格。
    void hardLinksCountPerName() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        store.write("origin.bin", "abc");
        const auto source = store.directory() + "/origin.bin";
        const auto target = store.directory() + "/alias.bin";
#ifdef Q_OS_WIN
        QVERIFY(CreateHardLinkW(reinterpret_cast<LPCWSTR>(target.utf16()),
                                reinterpret_cast<LPCWSTR>(source.utf16()), nullptr));
#else
        QCOMPARE(
            ::link(QFile::encodeName(source).constData(), QFile::encodeName(target).constData()),
            0);
#endif
        const auto report = store.storageUsage();
        QCOMPARE(report["logicalBytes"].toString(), QString("6"));
        QCOMPARE(report["hardLinkedNames"].toString(), QString("2"));
        QCOMPARE(store.read("origin.bin"), QByteArray("abc"));
        QVERIFY(QFileInfo::exists(target));
    }

    // 日期：2026-11-08；目录原生身份与实际SQLite句柄一致，硬链接共用身份而等长独立文件不同。
    void nativeIdentityMatchesSqliteAndAliases() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        store.write("object.sqlite", {});
        Connection connection(store.directory() + "/object.sqlite");
        QVERIFY(connection.database.open());
        QSqlQuery query(connection.database);
        QVERIFY(query.exec("CREATE TABLE payload(value)"));
        QVERIFY(query.exec("INSERT INTO payload VALUES(zeroblob(8192))"));
        const auto source = store.directory() + "/object.sqlite";
        const auto alias = store.directory() + "/alias.sqlite";
#ifdef Q_OS_WIN
        QVERIFY(CreateHardLinkW(reinterpret_cast<LPCWSTR>(alias.utf16()),
                                reinterpret_cast<LPCWSTR>(source.utf16()), nullptr));
#else
        QCOMPARE(
            ::link(QFile::encodeName(source).constData(), QFile::encodeName(alias).constData()), 0);
#endif
        store.write("separate.bin", {});
        {
            QFile separate(store.directory() + "/separate.bin");
            QVERIFY(separate.open(QIODevice::ReadWrite));
            QVERIFY(separate.resize(QFileInfo(source).size()));
        }
        DuktoSqliteFileInfo native{};
        QCOMPARE(sqlite3_file_control(dukto::sqliteHandle(connection.database), "main",
                                      dukto::SqliteFileInfoControl, &native),
                 SQLITE_OK);
        dukto::NativeDirectoryEntry original, linked, separate;
        qint64 allocated = 0;
        store.visitStorageEntries([&](const dukto::NativeDirectoryEntry &entry) {
            // 日期：2026-11-08；仅保存三份固定夹具观察，生产接口没有按文件数增长的缓存。
            if (entry.name == "object.sqlite")
                original = entry;
            else if (entry.name == "alias.sqlite")
                linked = entry;
            else if (entry.name == "separate.bin")
                separate = entry;
            if (entry.kind == dukto::NativeDirectoryEntry::Kind::Regular)
                allocated += entry.allocatedBytes;
        });
        QCOMPARE(original.identityPlatform, native.platform);
        QCOMPARE(original.volume, quint64(native.volume));
        QVERIFY(std::memcmp(original.identity.data(), native.identity, original.identity.size()) ==
                0);
        QCOMPARE(original.bytes, qint64(native.logicalBytes));
        QCOMPARE(original.allocatedBytes, qint64(native.allocatedBytes));
        QCOMPARE(original.links, quint64(2));
        QCOMPARE(linked.identityPlatform, original.identityPlatform);
        QCOMPARE(linked.volume, original.volume);
        QVERIFY(linked.identity == original.identity);
        QCOMPARE(linked.allocatedBytes, original.allocatedBytes);
        QVERIFY(separate.identity != original.identity || separate.volume != original.volume);
        const auto report = store.storageUsage();
        QCOMPARE(report["allocatedBytes"].toString(), QString::number(allocated));
        QCOMPARE(report["hardLinkedNames"].toString(), QString("2"));
    }

    // 日期：2026-11-08；共享模式和空回调明确拒绝，回调异常归还授信且后续相同观察仍可完成。
    void visitorFailureIsReusable() {
        QTemporaryDir root;
        const auto state = root.filePath("state");
        const auto used = dukto::BufferCredit::usage().value("used");
        {
            dukto::PrivateStore shared(state, true);
            QVERIFY_EXCEPTION_THROWN(
                shared.visitStorageEntries([](const dukto::NativeDirectoryEntry &) {
                    // 日期：2026-11-08；此回调在共享实例上不可达。
                    QFAIL("Shared observer must not run");
                }),
                dukto::Error);
        }
        dukto::PrivateStore store(state, false, dukto::PrivateStore::Use::Maintenance);
        store.write("keep.json", "preserve");
        QVERIFY_EXCEPTION_THROWN(store.visitStorageEntries({}), dukto::Error);
        for (int round = 0; round < 64; ++round) {
            int visited = 0;
            QVERIFY_EXCEPTION_THROWN(
                store.visitStorageEntries([&](const dukto::NativeDirectoryEntry &) {
                    // 日期：2026-11-08；第一项回调真实抛出，不允许吞掉错误后继续或输出成功。
                    ++visited;
                    throw dukto::Error(dukto::ExitCode::Cancelled, "visitor interrupted",
                                       "storage");
                }),
                dukto::Error);
            QCOMPARE(visited, 1);
            QCOMPARE(dukto::BufferCredit::usage().value("used"), used);
        }
        QCOMPARE(store.storageUsage()["logicalBytes"].toString(), QString("8"));
        QCOMPARE(store.read("keep.json"), QByteArray("preserve"));
    }

    // 日期：2026-11-08；有界枚举后真实第二进程仍被SQLite写锁拒绝，提交后原第二进程命令可成功。
    void inventoryPreservesSqliteWriteLock() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        store.write("locked.sqlite", {});
        const auto path = store.directory() + "/locked.sqlite";
        Connection connection(path);
        QVERIFY(connection.database.open());
        QSqlQuery query(connection.database);
        QVERIFY(query.exec("CREATE TABLE payload(value)"));
        QVERIFY(query.exec("BEGIN IMMEDIATE"));
        QVERIFY(query.exec("INSERT INTO payload VALUES(1)"));
        QVERIFY(store.storageUsage()["regularFiles"].toString().toLongLong() >= 2);
        QProcess competitor;
        const QStringList args{"--try-sqlite-write", path};
        competitor.start(QCoreApplication::applicationFilePath(), args);
        QVERIFY(competitor.waitForFinished(30000));
        QCOMPARE(competitor.exitStatus(), QProcess::NormalExit);
        QCOMPARE(competitor.exitCode(), int(SQLITE_BUSY));
        QVERIFY(query.exec("COMMIT"));
        competitor.start(QCoreApplication::applicationFilePath(), args);
        QVERIFY(competitor.waitForFinished(30000));
        QCOMPARE(competitor.exitStatus(), QProcess::NormalExit);
        QCOMPARE(competitor.exitCode(), 0);
        QVERIFY(query.exec("SELECT COUNT(*) FROM payload"));
        QVERIFY(query.next());
        QCOMPARE(query.value(0).toInt(), 2);
    }

    // 日期：2026-11-07；子目录只计排除项，不递归读取大数据或把子目录内容算作直接状态。
    void nestedDataIsExcluded() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        QVERIFY(QDir(store.directory()).mkdir("nested"));
        QVERIFY(sparse(store.directory() + "/nested/large.bin"));
        const auto report = store.storageUsage();
        QCOMPARE(report["logicalBytes"].toString(), QString("0"));
        QCOMPARE(report["excludedDirectories"].toString(), QString("1"));
        QVERIFY(!report["directRegularFilesOnly"].toBool());
        QCOMPARE(QFileInfo(store.directory() + "/nested/large.bin").size(), LargeLength);
    }

    // 日期：2026-11-07；原生符号链接目标不跟随；仅无Windows建链权限时保留明确跳过。
    void nativeSymbolicLinkIsExcluded() {
        QTemporaryDir root;
        QVERIFY(sparse(root.filePath("outside.bin")));
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        const auto source = root.filePath("outside.bin");
        const auto target = store.directory() + "/linked.bin";
#ifdef Q_OS_WIN
        if (!CreateSymbolicLinkW(reinterpret_cast<LPCWSTR>(target.utf16()),
                                 reinterpret_cast<LPCWSTR>(source.utf16()), 2)) {
            const auto firstError = GetLastError();
            if (firstError != ERROR_PRIVILEGE_NOT_HELD && firstError != ERROR_INVALID_PARAMETER)
                QFAIL("Native symbolic link creation failed for a reason other than privilege");
            if (!CreateSymbolicLinkW(reinterpret_cast<LPCWSTR>(target.utf16()),
                                     reinterpret_cast<LPCWSTR>(source.utf16()), 0)) {
                if (GetLastError() != ERROR_PRIVILEGE_NOT_HELD)
                    QFAIL("Native symbolic link creation failed for a reason other than privilege");
                QSKIP("Windows account cannot create a native symbolic link");
            }
        }
#else
        QVERIFY(QFile::link(source, target));
#endif
        const auto report = store.storageUsage();
        QCOMPARE(report["logicalBytes"].toString(), QString("0"));
        QCOMPARE(report["excludedLinks"].toString(), QString("1"));
        QVERIFY(!report["directRegularFilesOnly"].toBool());
        QCOMPARE(QFileInfo(source).size(), LargeLength);
    }

#ifndef Q_OS_WIN
    // 日期：2026-11-07；真实FIFO只查不跟随元数据，不以读正文方式打开而阻塞计量。
    void fifoIsExcludedWithoutOpeningBody() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        QCOMPARE(::mkfifo(QFile::encodeName(store.directory() + "/pipe").constData(), 0600), 0);
        const auto report = store.storageUsage();
        QCOMPARE(report["logicalBytes"].toString(), QString("0"));
        QCOMPARE(report["excludedSpecial"].toString(), QString("1"));
        QVERIFY(!report["directRegularFilesOnly"].toBool());
    }
#endif

    // 日期：2026-11-07；维护边界、逐项取消、枚举期真实目录变更拒绝和失败后再次查询均实际执行。
    void maintenanceCancellationAndMutation() {
        QTemporaryDir root;
        const auto state = root.filePath("state");
        {
            dukto::PrivateStore shared(state, true);
            QVERIFY_EXCEPTION_THROWN(shared.storageUsage(), dukto::Error);
        }
        dukto::PrivateStore store(state, false, dukto::PrivateStore::Use::Maintenance);
        store.write("original.json", "preserve");
        const auto used = dukto::BufferCredit::usage().value("used");
        int calls = 0;
        try {
            store.storageUsage([&]() {
                // 日期：2026-11-07；第一个目录项抛取消，真实异常退栈必须释放计量额度及枚举句柄。
                if (++calls == 2)
                    throw dukto::Error(dukto::ExitCode::Cancelled, "cancel fixture", "test");
            });
            QFAIL("Cancellation was ignored");
        } catch (const dukto::Error &error) {
            QCOMPARE(error.code, dukto::ExitCode::Cancelled);
        }
        QCOMPARE(dukto::BufferCredit::usage().value("used"), used);
        QCOMPARE(store.storageUsage()["logicalBytes"].toString(), QString("8"));
        calls = 0;
        try {
            store.storageUsage([&]() {
                // 日期：2026-11-07；真实创建新目录项使枚举时间戳变化，不能输出混合快照成功。
                if (++calls == 2) {
                    store.write("added.json", "new");
#ifdef Q_OS_WIN
                    // 日期：2026-11-08；Windows目录句柄也可能延迟更新时间，显式设置可观测的原生写时间。
                    const auto path = QDir::toNativeSeparators(store.directory());
                    const auto handle = CreateFileW(
                        reinterpret_cast<LPCWSTR>(path.utf16()),
                        FILE_READ_ATTRIBUTES | FILE_WRITE_ATTRIBUTES,
                        FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
                    if (handle == INVALID_HANDLE_VALUE)
                        qFatal("Cannot open Windows mutation fixture directory");
                    FILETIME changed{};
                    const bool read = GetFileTime(handle, nullptr, nullptr, &changed);
                    ULARGE_INTEGER ticks{};
                    ticks.LowPart = changed.dwLowDateTime;
                    ticks.HighPart = changed.dwHighDateTime;
                    ticks.QuadPart += 20000000;
                    changed.dwLowDateTime = ticks.LowPart;
                    changed.dwHighDateTime = ticks.HighPart;
                    const bool written = read && SetFileTime(handle, nullptr, nullptr, &changed);
                    CloseHandle(handle);
                    if (!written)
                        qFatal("Cannot set observable Windows directory timestamp");
#else
                    // 日期：2026-11-08；同一时钟刻度内目录时间可能不变，显式设置可观测mtime后再验证拒绝。
                    const auto path = QFile::encodeName(store.directory());
                    struct stat info{};
                    if (::stat(path.constData(), &info) != 0)
                        qFatal("Cannot inspect mutation fixture directory");
                    const timespec times[2]{{0, UTIME_OMIT}, {info.st_mtime + 2, 0}};
                    if (::utimensat(AT_FDCWD, path.constData(), times, AT_SYMLINK_NOFOLLOW) != 0)
                        qFatal("Cannot set an observable directory mutation timestamp");
#endif
                }
            });
            QFAIL("Directory mutation was accepted");
        } catch (const dukto::Error &error) {
            QCOMPARE(error.code, dukto::ExitCode::Integrity);
        }
        QCOMPARE(dukto::BufferCredit::usage().value("used"), used);
        QCOMPARE(store.storageUsage()["logicalBytes"].toString(), QString("11"));
        QCOMPARE(store.read("original.json"), QByteArray("preserve"));
    }

    // 日期：2026-11-07；四千目录项重复计量只输出固定七类，内存授信归还且报告长度不随名称增长。
    void manyEntriesKeepReportBounded() {
        QTemporaryDir root;
        dukto::PrivateStore store(root.filePath("state"), true,
                                  dukto::PrivateStore::Use::Maintenance);
        qint64 expected = 0;
        for (int index = 0; index < 4096; ++index) {
            QFile file(store.directory() + "/item-" + QString::number(index) + ".bin");
            QVERIFY(file.open(QIODevice::WriteOnly | QIODevice::NewOnly));
            const auto count = index % 13 + 1;
            QCOMPARE(file.write(QByteArray(count, 'x')), qint64(count));
            expected += count;
        }
        const auto used = dukto::BufferCredit::usage().value("used");
        for (int index = 0; index < 3; ++index) {
            const auto report = store.storageUsage();
            QCOMPARE(report["regularFiles"].toString(), QString("4097"));
            QCOMPARE(report["logicalBytes"].toString(), QString::number(expected));
            QVERIFY(QJsonDocument(report).toJson(QJsonDocument::Compact).size() < 4096);
            QCOMPARE(dukto::BufferCredit::usage().value("used"), used);
        }
    }

    // 日期：2026-11-07；客户端/服务器各自使用独立真实状态根，覆盖三平台相同命令入口。
    void realCli_data() {
        QTest::addColumn<QString>("command");
        QTest::newRow("client") << QString("client");
        QTest::newRow("serve") << QString("serve");
    }

    // 日期：2026-11-07；独占冲突不等待，JSON和人类输出不泄密，非法参数在创建目录前被拒绝。
    void realCli() {
        QFETCH(QString, command);
        QTemporaryDir root;
        const auto parent = root.filePath(QStringLiteral("客户 状态"));
        QVERIFY(QDir().mkpath(parent));
        const auto state = QDir(parent).filePath(command == "client" ? "transfers" : "service");
        const QByteArray secret("never-print-private-body");
        QCOMPARE(secret.size(), 24);
        const QStringList arguments{command, "storage", "--state-directory", parent};
        QProcess process;
        {
            dukto::PrivateStore shared(state, true);
            shared.write("credential.json", secret);
            QVERIFY(invoke(process, arguments + QStringList{"--json"}));
            QVERIFY(process.exitCode() != 0);
        }
        QVERIFY(invoke(process, arguments + QStringList{"--json"}));
        QCOMPARE(process.exitCode(), 0);
        const auto bytes = process.readAllStandardOutput();
        QVERIFY(!bytes.contains(secret));
        QJsonParseError error;
        const auto report = QJsonDocument::fromJson(bytes, &error).object();
        QCOMPARE(error.error, QJsonParseError::NoError);
        QCOMPARE(report["event"].toString(), QString("state-storage"));
        QCOMPARE(report["stateDirectory"].toString(), QDir::cleanPath(state));
        QCOMPARE(report["logicalBytes"].toString(), QString("24"));
        bool allocatedValid = false;
        const auto allocated = report["allocatedBytes"].toString().toLongLong(&allocatedValid);
        QVERIFY(allocatedValid && allocated >= 0);
        QVERIFY(invoke(process, arguments));
        QCOMPARE(process.exitCode(), 0);
        const auto human = process.readAllStandardOutput();
        QVERIFY(human.contains("24 B"));
        QVERIFY(human.contains("allocated="));
        QVERIFY(human.contains(QStringLiteral("客户 状态").toUtf8()));
        QVERIFY(!human.contains(secret));
        const auto absent = root.filePath("must-not-create");
        QVERIFY(invoke(process, {command, "storage", "--state-directory", absent, "--task",
                                 "00000000-0000-0000-0000-000000000001", "--json"}));
        QCOMPARE(process.exitCode(), 2);
        QVERIFY(!QFileInfo::exists(absent));
        dukto::PrivateStore store(state);
        QCOMPARE(store.read("credential.json"), secret);
    }
};

// 日期：2026-11-07；仅测试子进程提供真实热日志崩溃夹具，生产CLI没有测试开关。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    if (app.arguments().value(1) == "--crash-history-migration")
        crashHistoryMigration(app.arguments().value(2), app.arguments().value(3) == "published");
    if (app.arguments().value(1) == "--try-sqlite-write")
        return attemptSqliteWrite(app.arguments().value(2));
    if (app.arguments().value(1) == "--leave-journal") {
        leaveJournal(app.arguments().value(2));
        return 95;
    }
    StateStorageTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "state_storage_tests.moc"

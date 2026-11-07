#include "core/files.h"
#include "core/sqliteruntime.h"
#include "core/sqlitevfs.h"
#include <QFileInfo>
#include <QSqlError>
#include <QSqlQuery>
#include <QSqlRecord>
#include <QTemporaryDir>
#include <QUrl>
#include <QUuid>
#include <QtTest>
#include <array>
#include <limits>
#include <stdexcept>

namespace {
using Event = dukto::SqliteFileEvent;

class Policy final : public dukto::SqliteFilePolicy {
  public:
    std::array<quint64, 8> started{};
    std::array<quint64, 8> finished{};
    int openedFlags = 0;
    int writtenFlags = 0;
    int refuseFlags = 0;
    int refuseAction = -1;
    quint64 refused = 0;
    qint64 maximumWriteEnd = 0;

    // 日期：2026-11-07；测试策略只保存固定计数和标志，拒绝发生在原生写入/映射前。
    int before(const Event &event) noexcept override {
        const auto action = int(event.action);
        ++started[size_t(action)];
        if (event.action == Event::Action::Open)
            openedFlags |= event.flags;
        if (event.action == Event::Action::Write) {
            writtenFlags |= event.flags;
            maximumWriteEnd = qMax(maximumWriteEnd, event.offset + event.bytes);
        }
        if (action == refuseAction && (!refuseFlags || (event.flags & refuseFlags))) {
            ++refused;
            return SQLITE_FULL;
        }
        return SQLITE_OK;
    }

    // 日期：2026-11-07；仅统计真正调用原生方法后的通知，不在C回调中分配日志或抛异常。
    void after(const Event &event, int) noexcept override {
        ++finished[size_t(event.action)];
    }
};

// 日期：2026-11-07；Qt连接及查询在所属线程内使用，析构先关闭连接再移除注册项。
class Connection final {
  public:
    QString name = QUuid::createUuid().toString(QUuid::WithoutBraces);
    QSqlDatabase db;

    // 日期：2026-11-07；真实驱动安装每连接独立策略，夹具失败保留原生SQL错误供定位。
    Connection(const QString &path, std::shared_ptr<Policy> policy = {})
        : db(dukto::addSqliteDatabase(name, std::move(policy))) {
        db.setDatabaseName(path);
        if (!db.open()) {
            qCritical().noquote() << db.lastError().text();
            throw std::runtime_error(db.lastError().text().toStdString());
        }
    }

    // 日期：2026-11-07；测试查询先析构后到此处，Qt不遗留命名连接或VFS引用。
    ~Connection() {
        db.close();
        db = {};
        QSqlDatabase::removeDatabase(name);
    }
};

// 日期：2026-11-07；取得当前连接主库包装句柄，测试不能误用系统插件的另一份引擎函数。
sqlite3_file *nativeFile(const QSqlDatabase &database) {
    sqlite3_file *result = nullptr;
    const int code = sqlite3_file_control(dukto::sqliteHandle(database), "main",
                                          SQLITE_FCNTL_FILE_POINTER, &result);
    return code == SQLITE_OK ? result : nullptr;
}
} // namespace

class SqliteVfsTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-07；同一引擎版本、Unicode/空值/Blob、预编译绑定、回滚和结果元数据实际执行。
    void engineAndQtContracts() {
        const auto info = dukto::sqliteRuntimeInfo();
        QCOMPARE(info["version"].toString(), QString("3.53.4"));
        QCOMPARE(info["versionNumber"].toInt(), 3053004);
        QVERIFY(info["threadsafe"].toInt() != 0);
        QVERIFY(dukto::sqliteRuntimeAvailable());
        Connection connection(":memory:");
        QVERIFY(dukto::sqliteHandle(connection.db));
        QSqlQuery query(connection.db);
        QVERIFY2(query.exec("CREATE TABLE data(id INTEGER PRIMARY KEY,value TEXT,body BLOB)"),
                 qPrintable(query.lastError().text()));
        QVERIFY(query.prepare("INSERT INTO data(value,body) VALUES(:value,:body)"));
        query.bindValue(":value", QStringLiteral("中文 空格 #?%"));
        query.bindValue(":body", QByteArray("a\0b", 3));
        QVERIFY(query.exec());
        QCOMPARE(query.lastInsertId().toInt(), 1);
        QVERIFY(connection.db.transaction());
        QVERIFY(query.exec("INSERT INTO data VALUES(2,NULL,NULL)"));
        QVERIFY(connection.db.rollback());
        QVERIFY(query.exec("SELECT value,body FROM data"));
        QCOMPARE(query.record().count(), 2);
        QVERIFY(query.next());
        QCOMPARE(query.value(0).toString(), QStringLiteral("中文 空格 #?%"));
        QCOMPARE(query.value(1).toByteArray(), QByteArray("a\0b", 3));
        QVERIFY(!query.next());
    }

    // 日期：2026-11-07；含URI特殊字符的本地路径不丢失；只读拒写；原生文件恢复与旧Qt插件双向可读。
    void pathsReadonlyAndPluginCompatibility() {
        QTemporaryDir root;
#ifdef Q_OS_WIN
        const auto path = root.filePath(QStringLiteral("中文 #% 状态.sqlite"));
#else
        const auto path = root.filePath(QStringLiteral("中文 #?% 状态.sqlite"));
#endif
        {
            Connection connection(path);
            QSqlQuery query(connection.db);
            QVERIFY(query.exec("CREATE TABLE data(value TEXT)"));
            QVERIFY(query.exec("INSERT INTO data VALUES('kept')"));
        }
        QVERIFY(QFileInfo::exists(path));
        const auto hash = dukto::hashFile(path);
        {
            auto db = dukto::addSqliteDatabase("readonly-vfs");
            db.setDatabaseName(path);
            db.setConnectOptions("QSQLITE_OPEN_READONLY");
            QVERIFY2(db.open(), qPrintable(db.lastError().text()));
            {
                QSqlQuery query(db);
                QVERIFY(query.exec("SELECT value FROM data"));
                QVERIFY(query.next());
                QCOMPARE(query.value(0).toString(), QString("kept"));
                QVERIFY(!query.exec("INSERT INTO data VALUES('must-not-write')"));
            }
            db.close();
            db = {};
            QSqlDatabase::removeDatabase("readonly-vfs");
        }
        QCOMPARE(dukto::hashFile(path), hash);
        {
            auto db = QSqlDatabase::addDatabase("QSQLITE", "system-plugin-compatibility");
            db.setDatabaseName(path);
            QVERIFY2(db.open(), qPrintable(db.lastError().text()));
            QVERIFY(!dukto::sqliteHandle(db));
            {
                QSqlQuery query(db);
                QVERIFY(query.exec("SELECT value FROM data"));
                QVERIFY(query.next());
                QCOMPARE(query.value(0).toString(), QString("kept"));
                QVERIFY(query.exec("INSERT INTO data VALUES('old-plugin-write')"));
            }
            db.close();
            db = {};
            QSqlDatabase::removeDatabase("system-plugin-compatibility");
        }
        Connection reopened(path);
        QSqlQuery query(reopened.db);
        QVERIFY(query.exec("SELECT COUNT(*) FROM data"));
        QVERIFY(query.next());
        QCOMPARE(query.value(0).toInt(), 2);
    }

    // 日期：2026-11-07；空路径保留SQLite临时库语义，显式URI的mode保留且外部vfs不能绕过连接策略。
    void temporaryAndExplicitUri() {
        {
            Connection temporary("");
            QSqlQuery query(temporary.db);
            QVERIFY2(query.exec("CREATE TABLE data(value TEXT)"),
                     qPrintable(query.lastError().text()));
            QVERIFY(query.exec("INSERT INTO data VALUES('temporary')"));
            QVERIFY(query.exec("PRAGMA database_list"));
            QVERIFY(query.next());
            QVERIFY(query.value(2).toString().isEmpty());
        }
        QTemporaryDir root;
        const auto path = root.filePath("uri.sqlite");
        {
            Connection original(path);
            QSqlQuery query(original.db);
            QVERIFY(query.exec("CREATE TABLE data(value TEXT)"));
        }
        auto policy = std::make_shared<Policy>();
        auto db = dukto::addSqliteDatabase("explicit-uri", policy);
        db.setDatabaseName(QString::fromUtf8(QUrl::fromLocalFile(path).toEncoded()) +
                           "?mode=ro&vfs=missing-external-vfs");
        db.setConnectOptions(" QSQLITE_OPEN_URI ; QSQLITE_BUSY_TIMEOUT=50 ");
        QVERIFY2(db.open(), qPrintable(db.lastError().text()));
        {
            QSqlQuery query(db);
            QVERIFY(query.exec("SELECT COUNT(*) FROM data"));
            QVERIFY(!query.exec("INSERT INTO data VALUES('refused')"));
            QCOMPARE(policy->writtenFlags, 0);
        }
        db.close();
        db = {};
        QSqlDatabase::removeDatabase("explicit-uri");
    }

    // 日期：2026-11-07；主库直接写入、截断和大小提示拒绝后原文件摘要不变，拒绝无原生完成通知。
    void denyBeforeNativeMutation() {
        QTemporaryDir root;
        const auto path = root.filePath("data.sqlite");
        auto policy = std::make_shared<Policy>();
        Connection connection(path, policy);
        {
            QSqlQuery query(connection.db);
            QVERIFY(query.exec("CREATE TABLE data(value TEXT)"));
            QVERIFY(query.exec("INSERT INTO data VALUES('original')"));
        }
        const auto hash = dukto::hashFile(path);
        auto file = nativeFile(connection.db);
        QVERIFY(file && file->pMethods);
        sqlite3_int64 length = 0;
        QCOMPARE(file->pMethods->xFileSize(file, &length), SQLITE_OK);
        for (const auto action :
             {Event::Action::Write, Event::Action::Truncate, Event::Action::SizeHint}) {
            policy->refuseAction = int(action);
            const auto before = policy->finished[size_t(action)];
            int code = 0;
            if (action == Event::Action::Write) {
                const QByteArray body(4096, 'x');
                code = file->pMethods->xWrite(file, body.constData(), body.size(), length);
            } else if (action == Event::Action::Truncate) {
                code = file->pMethods->xTruncate(file, length + 4096);
            } else {
                sqlite3_int64 hint = length + 4096;
                code = file->pMethods->xFileControl(file, SQLITE_FCNTL_SIZE_HINT, &hint);
            }
            QCOMPARE(code, SQLITE_FULL);
            QCOMPARE(policy->finished[size_t(action)], before);
            QCOMPARE(dukto::hashFile(path), hash);
        }
        QCOMPARE(policy->refused, quint64(3));
        void *mapping = reinterpret_cast<void *>(1);
        QCOMPARE(file->pMethods->xFetch(file, 0, 4096, &mapping), SQLITE_OK);
        QVERIFY(!mapping);
        const auto writes = policy->started[size_t(Event::Action::Write)];
        QCOMPARE(file->pMethods->xWrite(file, "x", 1, std::numeric_limits<qint64>::max()),
                 SQLITE_IOERR_WRITE);
        QCOMPARE(policy->started[size_t(Event::Action::Write)], writes);
    }

    // 日期：2026-11-07；真实SQL事务触发日志拒绝时返回FULL，原行保留；取消拒绝后同连接可正常提交。
    void rollbackJournalRefusalAndRetry() {
        QTemporaryDir root;
        const auto path = root.filePath("journal.sqlite");
        auto policy = std::make_shared<Policy>();
        Connection connection(path, policy);
        QSqlQuery query(connection.db);
        QVERIFY(query.exec("PRAGMA journal_mode=DELETE"));
        QVERIFY(query.exec("CREATE TABLE data(value TEXT)"));
        QVERIFY(query.exec("INSERT INTO data VALUES('original')"));
        const auto hash = dukto::hashFile(path);
        policy->refuseAction = int(Event::Action::Write);
        policy->refuseFlags = SQLITE_OPEN_MAIN_JOURNAL;
        QVERIFY(!query.exec("UPDATE data SET value='refused'"));
        QCOMPARE(query.lastError().nativeErrorCode().toInt() & 255, SQLITE_FULL);
        QVERIFY(policy->refused > 0);
        QCOMPARE(dukto::hashFile(path), hash);
        policy->refuseAction = -1;
        QVERIFY2(query.exec("UPDATE data SET value='retry'"), qPrintable(query.lastError().text()));
        QVERIFY(query.exec("SELECT value FROM data"));
        QVERIFY(query.next());
        QCOMPARE(query.value(0).toString(), QString("retry"));
        QVERIFY(policy->openedFlags & SQLITE_OPEN_MAIN_JOURNAL);
    }

    // 日期：2026-11-07；WAL真实日志写入与共享内存映射均经过策略，映射拒绝发生在底层扩展前。
    void walAndSharedMemory() {
        QTemporaryDir root;
        auto policy = std::make_shared<Policy>();
        Connection connection(root.filePath("wal.sqlite"), policy);
        QSqlQuery query(connection.db);
        QVERIFY(query.exec("PRAGMA journal_mode=WAL"));
        QVERIFY(query.next());
        QCOMPARE(query.value(0).toString(), QString("wal"));
        query.finish();
        QVERIFY(query.exec("CREATE TABLE data(value BLOB)"));
        QVERIFY(query.exec("INSERT INTO data VALUES(zeroblob(65536))"));
        QVERIFY(policy->openedFlags & SQLITE_OPEN_WAL);
        QVERIFY(policy->writtenFlags & SQLITE_OPEN_WAL);
        QVERIFY(policy->finished[size_t(Event::Action::MapSharedMemory)] > 0);
        auto file = nativeFile(connection.db);
        QVERIFY(file && file->pMethods->iVersion >= 2);
        const auto bytes = QFileInfo(root.filePath("wal.sqlite-shm")).size();
        policy->refuseAction = int(Event::Action::MapSharedMemory);
        const auto before = policy->finished[size_t(Event::Action::MapSharedMemory)];
        void volatile *mapping = nullptr;
        QCOMPARE(file->pMethods->xShmMap(file, 16, 32768, 1, &mapping), SQLITE_FULL);
        QCOMPARE(policy->finished[size_t(Event::Action::MapSharedMemory)], before);
        QCOMPARE(QFileInfo(root.filePath("wal.sqlite-shm")).size(), bytes);
        QVERIFY(!mapping);
        policy->refuseAction = -1;
    }

    // 日期：2026-11-07；真实排序溢写文件使用当前连接VFS，不能只观察主库和journal后宣称覆盖临时索引。
    void temporarySortFilesAreIntercepted() {
        QTemporaryDir root;
        auto policy = std::make_shared<Policy>();
        Connection connection(root.filePath("sort.sqlite"), policy);
        QSqlQuery query(connection.db);
        QVERIFY(query.exec("PRAGMA cache_size=8"));
        QVERIFY(query.exec("PRAGMA temp_store=FILE"));
        QVERIFY(query.exec("CREATE TABLE data(id INTEGER,body BLOB)"));
        QVERIFY(query.exec("WITH RECURSIVE seq(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM seq "
                           "WHERE x<4096) INSERT INTO data SELECT x,randomblob(2048) FROM seq"));
        const auto count = policy->started[size_t(Event::Action::Write)];
        policy->openedFlags = 0;
        policy->writtenFlags = 0;
        query.setForwardOnly(true);
        QVERIFY2(query.exec("SELECT id FROM data ORDER BY hex(body) DESC"),
                 qPrintable(query.lastError().text()));
        int rows = 0;
        while (query.next())
            ++rows;
        QCOMPARE(rows, 4096);
        QVERIFY(policy->started[size_t(Event::Action::Write)] > count);
        QVERIFY(policy->openedFlags & SQLITE_OPEN_TEMP_JOURNAL);
        QVERIFY(policy->writtenFlags & SQLITE_OPEN_TEMP_JOURNAL);
    }

    // 日期：2026-11-07；反复关闭连接移除其随机VFS并释放策略，不能在注册表中保留悬空上下文。
    void connectionLifecycleAndIsolation() {
        QTemporaryDir root;
        const auto names = QSqlDatabase::connectionNames();
        for (int index = 0; index < 32; ++index) {
            auto policy = std::make_shared<Policy>();
            std::weak_ptr<Policy> weak = policy;
            QByteArray vfsName;
            {
                Connection connection(root.filePath("reuse.sqlite"), policy);
                policy.reset();
                QSqlQuery query(connection.db);
                QVERIFY(query.exec("CREATE TABLE IF NOT EXISTS data(value TEXT)"));
                sqlite3_vfs *vfs = nullptr;
                QCOMPARE(sqlite3_file_control(dukto::sqliteHandle(connection.db), "main",
                                              SQLITE_FCNTL_VFS_POINTER, &vfs),
                         SQLITE_OK);
                QVERIFY(vfs);
                vfsName = vfs->zName;
                QVERIFY(sqlite3_vfs_find(vfsName.constData()) == vfs);
                QVERIFY(!weak.expired());
            }
            QVERIFY(weak.expired());
            QVERIFY(!sqlite3_vfs_find(vfsName.constData()));
        }
        QCOMPARE(QSqlDatabase::connectionNames(), names);
        auto first = std::make_shared<Policy>();
        auto second = std::make_shared<Policy>();
        Connection refused(root.filePath("first.sqlite"), first);
        Connection allowed(root.filePath("second.sqlite"), second);
        first->refuseAction = int(Event::Action::Write);
        QSqlQuery a(refused.db), b(allowed.db);
        QVERIFY(!a.exec("CREATE TABLE data(value TEXT)"));
        QVERIFY(b.exec("CREATE TABLE data(value TEXT)"));
        QVERIFY(first->refused > 0);
        QCOMPARE(second->refused, quint64(0));
    }
};

QTEST_GUILESS_MAIN(SqliteVfsTests)
#include "sqlite_vfs_tests.moc"

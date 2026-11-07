#include "sqliteruntime.h"
#include "error.h"
#include "qsql_sqlite_p.h"
#include "sqlitevfs.h"
#include <QFileInfo>
#include <QSqlDriverPlugin>
#include <QSqlError>
#include <QUrl>
#include <QUrlQuery>
#include <QVariant>
#include <mutex>
#include <sqlite3.h>

namespace dukto {
namespace {
constexpr auto Driver = "DUKTO_SQLITE";

class ControlledDriver final : public DuktoSQLiteDriver {
  public:
    // 日期：2026-11-07；每个连接独占一个VFS和策略；不依赖执行SQL时的线程局部隐式上下文。
    explicit ControlledDriver(std::shared_ptr<SqliteFilePolicy> policy = {})
        : vfs_(new SqliteVfs(std::move(policy))) {
    }

    // 日期：2026-11-07；派生VFS必须在基类析构前关闭，防止SQLite关闭旁路时引用已销毁上下文。
    ~ControlledDriver() override {
        close();
    }

    // 日期：2026-11-07；仅在首次打开前安装策略；重建VFS不改变命名驱动或Qt连接名。
    void setPolicy(std::shared_ptr<SqliteFilePolicy> policy) {
        if (isOpen())
            throw Error(ExitCode::Config, QStringLiteral("不能更换活动SQLite策略"), "sqlite-vfs");
        vfs_.reset(new SqliteVfs(std::move(policy)));
    }

    // 日期：2026-11-07；URI仅增加固定内部VFS选择，保留只读/超时选项和原路径的UTF-8编码。
    bool open(const QString &database, const QString &user, const QString &password,
              const QString &host, int port, const QString &options) override {
        QUrl uri;
        bool useUri = false;
        for (const auto &option : options.split(';'))
            useUri = useUri || option.trimmed() == "QSQLITE_OPEN_URI";
        if (database.isEmpty()) {
            uri.setScheme("file");
        } else if (database == ":memory:") {
            uri = QUrl("file:dukto-memory-" + QString::fromLatin1(vfs_->name()));
            QUrlQuery query;
            query.addQueryItem("mode", "memory");
            uri.setQuery(query);
        } else if (useUri && database.startsWith("file:")) {
            uri = QUrl::fromEncoded(database.toUtf8(), QUrl::StrictMode);
        } else {
            uri = QUrl::fromLocalFile(QFileInfo(database).absoluteFilePath());
        }
        if (!uri.isValid()) {
            setLastError(
                QSqlError("Dukto SQLite", "Invalid database URI", QSqlError::ConnectionError));
            return false;
        }
        QUrlQuery query(uri);
        query.removeAllQueryItems("vfs");
        query.addQueryItem("vfs", QString::fromLatin1(vfs_->name()));
        uri.setQuery(query);
        return DuktoSQLiteDriver::open(QString::fromUtf8(uri.toEncoded()), user, password, host,
                                       port, options + ";QSQLITE_OPEN_URI");
    }

  private:
    std::unique_ptr<SqliteVfs> vfs_;
};

// 日期：2026-11-07；Qt负责创建器寿命；同进程只注册一次，原QSQLITE插件及其已有连接不被覆盖。
void registerDriver() {
    static std::once_flag once;
    std::call_once(once, []() {
        // 日期：2026-11-07；复用Qt原驱动的完整结果、绑定、事务和通知实现，只有内部类名改变。
        QSqlDatabase::registerSqlDriver(Driver, new QSqlDriverCreator<ControlledDriver>);
    });
}
} // namespace

// 日期：2026-11-07；创建连接时固定自有引擎，不通过默认驱动名动态选择另一份SQLite。
QSqlDatabase addSqliteDatabase(const QString &connection,
                               std::shared_ptr<SqliteFilePolicy> policy) {
    registerDriver();
    auto database = QSqlDatabase::addDatabase(Driver, connection);
    if (policy)
        static_cast<ControlledDriver *>(database.driver())->setPolicy(std::move(policy));
    return database;
}

// 日期：2026-11-07；驱动类型、打开状态及Qt原生句柄元类型必须同时匹配，错误返回空句柄。
sqlite3 *sqliteHandle(const QSqlDatabase &database) {
    if (!database.isOpen() || database.driverName() != Driver ||
        !qobject_cast<DuktoSQLiteDriver *>(database.driver()))
        return nullptr;
    const auto handle = database.driver()->handle();
    if (!handle.isValid() || !handle.typeName() || QByteArray(handle.typeName()) != "sqlite3*")
        return nullptr;
    return *static_cast<sqlite3 *const *>(handle.constData());
}

// 日期：2026-11-07；查询由当前链接引擎直接返回，SQLITE_SOURCE_ID用于核对实际编译来源。
QJsonObject sqliteRuntimeInfo() {
    return {{"version", QString::fromLatin1(sqlite3_libversion())},
            {"versionNumber", sqlite3_libversion_number()},
            {"sourceId", QString::fromLatin1(sqlite3_sourceid())},
            {"threadsafe", sqlite3_threadsafe()},
            {"driver", Driver},
            {"qtDriverSourceVersion", "5.15.2"},
            {"quotaEnforced", false}};
}

// 日期：2026-11-07；诊断检查真实注册名称，与生产创建连接保持同一路径。
bool sqliteRuntimeAvailable() {
    registerDriver();
    return QSqlDatabase::isDriverAvailable(Driver);
}
} // namespace dukto

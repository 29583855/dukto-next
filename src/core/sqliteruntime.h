#pragma once
#include <QJsonObject>
#include <QSqlDatabase>
#include <QString>
#include <memory>

struct sqlite3;

namespace dukto {
class SqliteFilePolicy;
// 日期：2026-11-07；使用固定源码构建的Qt完整SQLite驱动，保留命名连接并避免依赖平台插件私有导出。
QSqlDatabase addSqliteDatabase(const QString &connection,
                               std::shared_ptr<SqliteFilePolicy> policy = {});
// 日期：2026-11-07；只接受本项目驱动持有的真实句柄，禁止将其他插件句柄传给另一份SQLite引擎。
sqlite3 *sqliteHandle(const QSqlDatabase &database);
// 日期：2026-11-07；报告实际链接引擎的版本、源身份和线程支持，不读取业务数据库或正文。
QJsonObject sqliteRuntimeInfo();
// 日期：2026-11-07；只验证本项目驱动可注册，不打开数据库或搜索不受控插件路径。
bool sqliteRuntimeAvailable();
} // namespace dukto

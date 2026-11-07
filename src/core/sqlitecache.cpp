#include "sqlitecache.h"
#include "error.h"
#include "sqliteruntime.h"
#include <QSqlQuery>
#include <QVariant>

namespace dukto {
namespace {
constexpr int TemporaryKiB = 64;

// 日期：2026-11-05；缓存目标限制到已使用的 1/2 MiB，防止溢出或未审查配置消耗控制保留额。
qint64 reservation(int mainKiB) {
    if (mainKiB != 1024 && mainKiB != 2048)
        throw Error(ExitCode::Config, QStringLiteral("SQLite 缓存目标无效"), "budget");
    return qint64(mainKiB + TemporaryKiB) * 1024;
}

// 日期：2026-11-05；固定配置执行后必须读到唯一的预期值，不能把插件忽略配置视作生效。
void setting(const QSqlDatabase &database, const QString &name, qint64 expected) {
    QSqlQuery query(database);
    if (!query.exec("PRAGMA " + name + "=" + QString::number(expected)) ||
        !query.exec("PRAGMA " + name) || !query.next() || query.value(0).toLongLong() != expected ||
        query.next())
        throw Error(ExitCode::Disk, QStringLiteral("无法确认 SQLite 缓存配置"), "budget");
}
} // namespace

// 日期：2026-11-05；数据缓存不能占用控制保留额，构造失败和异常退栈自动归还已有授信。
SqliteCacheCredit::SqliteCacheCredit(int mainKiB, bool control)
    : credit_(reservation(mainKiB), !control), mainKiB_(mainKiB) {
}

// 日期：2026-11-05；仅配置已打开的本线程 SQLite；先设置临时存储再限制两种页缓存。
void SqliteCacheCredit::configure(const QSqlDatabase &database) const {
    if (!database.isOpen() || !sqliteHandle(database))
        throw Error(ExitCode::Config, QStringLiteral("SQLite 缓存需要已打开的连接"), "budget");
    setting(database, "temp_store", 1);
    setting(database, "main.cache_size", -mainKiB_);
    setting(database, "temp.cache_size", -TemporaryKiB);
    setting(database, "mmap_size", 0);
}
} // namespace dukto

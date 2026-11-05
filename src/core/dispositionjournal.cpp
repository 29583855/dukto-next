#include "dispositionjournal.h"
#include "error.h"
#include "files.h"
#include "protocol.h"
#include <QCryptographicHash>
#include <QDir>
#include <QSqlError>
#include <QSqlQuery>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-05；执行绑定参数后的查询，错误不能被解释为空记录或幂等成功。
void execute(QSqlQuery &query) {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("逐项处置日志操作失败"), "disposition");
}

// 日期：2026-11-05；长度前缀明确记录边界，摘要不依赖字符串拼接歧义或平台字节序。
void addRecord(QCryptographicHash &hash, const QByteArray &bytes) {
    const auto size = static_cast<quint32>(bytes.size());
    char prefix[4];
    for (int index = 0; index < 4; ++index)
        prefix[index] = static_cast<char>(size >> (24 - index * 8));
    hash.addData(prefix, 4);
    hash.addData(bytes);
}
} // namespace

// 日期：2026-11-05；已有日志只验证不补建架构；新日志在FULL同步事务中建立版本与不可变绑定。
DispositionJournal::DispositionJournal(PrivateStore &store, const QString &name, const QUuid &task,
                                       StrongManifest &manifest, const QString &conflict,
                                       const std::function<void()> &check)
    : manifest_(manifest), conflict_(conflict), manifestInfo_(manifest.summary()),
      connection_(QUuid::createUuid().toString()) {
    if (task.isNull() || !QStringList{"rename", "fail", "overwrite", "skip"}.contains(conflict))
        throw Error(ExitCode::Config, QStringLiteral("逐项处置的任务或策略无效"), "disposition");
    expectedEntries_ = next::decimal(manifestInfo_["entries"], 10000000);
    expectedBytes_ = static_cast<qint64>(next::decimal(
        manifestInfo_["bytes"], static_cast<quint64>(std::numeric_limits<qint64>::max())));
    binding_ = next::encodeControl({{"version", 1},
                                    {"taskId", task.toString(QUuid::WithoutBraces)},
                                    {"manifest", manifestInfo_},
                                    {"conflict", conflict_}});
    store.exists(name); // 日期：2026-11-05；拼接锁路径之前先验证私有状态键。
    ownership_.reset(new QLockFile(store.directory() + '/' + name + ".lock"));
    ownership_->setStaleLockTime(0);
    if (!ownership_->tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("逐项处置已有活动执行者"), "disposition");
    const bool exists = store.exists(name);
    if (!exists)
        store.write(name, {});
    if (store.validateFile(name) > MaxMetadataBytes)
        throw Error(ExitCode::Disk, QStringLiteral("逐项处置日志超出磁盘预算"), "disposition");
    database_ = QSqlDatabase::addDatabase("QSQLITE", connection_);
    try {
        database_.setDatabaseName(QDir(store.directory()).filePath(name));
        if (!database_.open())
            throw Error(ExitCode::Disk, QStringLiteral("无法打开逐项处置日志"), "disposition");
        sql("PRAGMA busy_timeout=2000");
        cacheCredit_.configure(database_);
        sql("PRAGMA temp_store=FILE");
        if (!exists) {
            sql("PRAGMA page_size=4096");
            sql("PRAGMA max_page_count=65536");
            sql("PRAGMA journal_mode=DELETE");
            sql("PRAGMA synchronous=FULL");
            sql("BEGIN IMMEDIATE");
            try {
                sql("CREATE TABLE binding(spec BLOB NOT NULL)");
                sql("CREATE TABLE items(id INTEGER PRIMARY KEY CHECK(id>0),source TEXT NOT NULL "
                    "UNIQUE CHECK(length(CAST(source AS BLOB))<=4096),"
                    "spec BLOB NOT NULL CHECK(length(spec)<=65536))");
                QSqlQuery query(database_);
                query.prepare("INSERT INTO binding VALUES(?)");
                query.addBindValue(binding_);
                execute(query);
                sql("PRAGMA user_version=1");
                sql("COMMIT");
            } catch (...) {
                database_.rollback();
                throw;
            }
        }
        QSqlQuery version(database_);
        version.prepare("PRAGMA user_version");
        execute(version);
        if (!version.next() || version.value(0).toInt() != 1)
            throw Error(ExitCode::Integrity, QStringLiteral("逐项处置日志版本无效"), "disposition");
        version.finish();
        QSqlQuery binding(database_);
        binding.prepare("SELECT substr(spec,1,65537) FROM binding");
        execute(binding);
        if (!binding.next() || binding.value(0).toByteArray() != binding_ || binding.next())
            throw Error(ExitCode::Integrity, QStringLiteral("逐项处置日志绑定不同"), "disposition");
        binding.finish();
        // 日期：2026-11-05；现有日志的所有记录同样重验，不能仅相信MAX(id)或历史总计。
        const auto state = summary(false, check);
        next_ = next::decimal(state["processedEntries"], expectedEntries_) + 1;
        sql("PRAGMA max_page_count=65536");
        sql("PRAGMA journal_mode=DELETE");
        sql("PRAGMA synchronous=FULL");
    } catch (...) {
        close();
        throw;
    }
}

// 日期：2026-11-05；不删除历史结果或临时SQLite证据，调用者按任务保留期独立管理。
DispositionJournal::~DispositionJournal() {
    close();
}

// 日期：2026-11-05；连接必须由所属线程关闭，注册项在QSqlDatabase副本释放后移除。
void DispositionJournal::close() {
    database_.close();
    database_ = QSqlDatabase();
    QSqlDatabase::removeDatabase(connection_);
}

// 日期：2026-11-05；固定事务和架构指令均须执行成功。
void DispositionJournal::sql(const QString &statement) const {
    QSqlQuery query(database_);
    if (!query.exec(statement))
        throw Error(ExitCode::Disk, QStringLiteral("逐项处置日志事务失败"), "disposition");
}

// 日期：2026-11-05；单行只含冻结清单和规范字段，拒绝非法ID、策略、路径及额外根链。
QJsonObject DispositionJournal::canonicalItem(quint64 file, const QString &path,
                                              const QString &disposition,
                                              quint64 skippedRoot) const {
    if (!file || file > expectedEntries_ ||
        !QStringList{"copied", "skipped"}.contains(disposition) ||
        (disposition == "copied" && skippedRoot) ||
        (disposition == "skipped" && (conflict_ != "skip" || !skippedRoot || skippedRoot > file)))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置的身份或决定无效"), "disposition");
    const auto target = validateRelativePath(path);
    const auto entry = manifest_.entry(file);
    QJsonObject result{{"version", 1},
                       {"entry", entry.publicInfo()},
                       {"path", target},
                       {"disposition", disposition}};
    if (disposition == "skipped")
        result["skippedRoot"] = QString::number(skippedRoot);
    return result;
}

// 日期：2026-11-05；父项按唯一源路径索引有界读取；跳过目录的每个后代必须延续原根及路径。
QJsonObject DispositionJournal::checkedItem(quint64 file, const QString &path,
                                            const QString &disposition, quint64 skippedRoot) const {
    const auto result = canonicalItem(file, path, disposition, skippedRoot);
    const auto entry = manifest_.entry(file);
    const int slash = entry.relative.lastIndexOf('/');
    if (slash < 0) {
        if (path.contains('/') || (disposition == "skipped" && skippedRoot != file))
            throw Error(ExitCode::Integrity, QStringLiteral("顶层处置路径或跳过根无效"),
                        "disposition");
        return result;
    }
    QSqlQuery query(database_);
    query.prepare("SELECT id,substr(spec,1,65537) FROM items WHERE source=?");
    query.addBindValue(entry.relative.left(slash));
    execute(query);
    if (!query.next() || query.value(0).toLongLong() <= 0 || query.value(0).toULongLong() >= file)
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置缺少已记录的父目录"),
                    "disposition");
    const auto parentId = query.value(0).toULongLong();
    const auto parentBytes = query.value(1).toByteArray();
    const auto parent = next::parseControl(parentBytes);
    const auto parentRoot =
        parent.contains("skippedRoot") ? next::decimal(parent["skippedRoot"], expectedEntries_) : 0;
    const auto expected = canonicalItem(parentId, parent["path"].toString(),
                                        parent["disposition"].toString(), parentRoot);
    const auto parentEntry = manifest_.entry(parentId);
    const auto prefix = parent["path"].toString() + '/';
    if (!parentEntry.directory || parentEntry.relative != entry.relative.left(slash) ||
        parent != expected || parentBytes != next::encodeControl(expected) ||
        !path.startsWith(prefix) || path.mid(prefix.size()).contains('/'))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置与父目录映射不同"), "disposition");
    if (parent["disposition"] == "skipped") {
        if (disposition != "skipped" || skippedRoot != parentRoot ||
            path != prefix + entry.relative.mid(slash + 1))
            throw Error(ExitCode::Integrity, QStringLiteral("跳过子树不得改为复制或更换根"),
                        "disposition");
    } else if (disposition == "skipped" && skippedRoot != file) {
        throw Error(ExitCode::Integrity, QStringLiteral("跳过根不属于当前子树"), "disposition");
    }
    return result;
}

// 日期：2026-11-05；重建规范对象并比较原编码，拒绝未知字段、清单篡改及不规范数字。
QJsonObject DispositionJournal::decode(quint64 file, const QByteArray &bytes) const {
    const auto value = next::parseControl(bytes);
    const auto disposition = value["disposition"].toString();
    const auto root =
        value.contains("skippedRoot") ? next::decimal(value["skippedRoot"], expectedEntries_) : 0;
    const auto expected = checkedItem(file, value["path"].toString(), disposition, root);
    if (value != expected || bytes != next::encodeControl(expected))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置内容与冻结清单不同"),
                    "disposition");
    return expected;
}

// 日期：2026-11-05；重复行只读核对；新决定在FULL同步事务提交成功后才更新内存中的固定游标。
void DispositionJournal::append(quint64 file, const QString &path, const QString &disposition,
                                quint64 skippedRoot) {
    const auto value = next::encodeControl(checkedItem(file, path, disposition, skippedRoot));
    if (file < next_) {
        QSqlQuery query(database_);
        query.prepare("SELECT substr(spec,1,65537) FROM items WHERE id=?");
        query.addBindValue(static_cast<qlonglong>(file));
        execute(query);
        if (!query.next() || query.value(0).toByteArray() != value)
            throw Error(ExitCode::Integrity, QStringLiteral("原逐项处置或目标名称已变化"),
                        "disposition");
        return;
    }
    if (file != next_)
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置缺少前面的清单项"), "disposition");
    sql("BEGIN IMMEDIATE");
    try {
        QSqlQuery query(database_);
        query.prepare("INSERT INTO items VALUES(?,?,?)");
        query.addBindValue(static_cast<qlonglong>(file));
        query.addBindValue(manifest_.entry(file).relative);
        query.addBindValue(value);
        execute(query);
        sql("COMMIT");
    } catch (...) {
        database_.rollback();
        throw;
    }
    ++next_;
}

// 日期：2026-11-05；精确读取既有记录，文件是否仍存在由接收核心另行验证。
QJsonObject DispositionJournal::item(quint64 file) const {
    if (!file || file >= next_)
        throw Error(ExitCode::Integrity, QStringLiteral("该项尚无持久处置"), "disposition");
    QSqlQuery query(database_);
    query.prepare("SELECT substr(spec,1,65537) FROM items WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    if (!query.next())
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置记录丢失"), "disposition");
    return decode(file, query.value(0).toByteArray());
}

// 日期：2026-11-05；流式汇总复制/跳过的文件、目录和字节，缺项及总量不符不得产生完整结果。
QJsonObject DispositionJournal::summary(bool requireComplete,
                                        const std::function<void()> &check) const {
    QSqlQuery invalid(database_);
    invalid.prepare("SELECT id FROM items WHERE id<=0 LIMIT 1");
    execute(invalid);
    if (invalid.next())
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置包含非正序号"), "disposition");
    if (invalid.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("逐项处置序号读取失败"), "disposition");
    invalid.finish();
    QCryptographicHash hash(QCryptographicHash::Sha256);
    addRecord(hash, binding_);
    quint64 count = 0, copied = 0, skipped = 0, copiedDirectories = 0, skippedDirectories = 0;
    qint64 copiedBytes = 0, skippedBytes = 0;
    for (;;) {
        QSqlQuery query(database_);
        query.setForwardOnly(true);
        query.prepare("SELECT id,substr(source,1,4097),substr(spec,1,65537) FROM items WHERE id>? "
                      "ORDER BY id LIMIT 100");
        query.addBindValue(static_cast<qlonglong>(count));
        execute(query);
        int rows = 0;
        while (query.next()) {
            if (check)
                check();
            if (count >= expectedEntries_ ||
                query.value(0).toLongLong() != static_cast<qlonglong>(count + 1))
                throw Error(ExitCode::Integrity, QStringLiteral("逐项处置序号不连续"),
                            "disposition");
            ++count;
            ++rows;
            const auto bytes = query.value(2).toByteArray();
            const auto value = decode(count, bytes);
            const auto entry = manifest_.entry(count);
            if (query.value(1).toString() != entry.relative)
                throw Error(ExitCode::Integrity, QStringLiteral("逐项源路径索引已改变"),
                            "disposition");
            const bool isCopied = value["disposition"] == "copied";
            auto &totalBytes = isCopied ? copiedBytes : skippedBytes;
            if (entry.bytes > expectedBytes_ - totalBytes)
                throw Error(ExitCode::Integrity, QStringLiteral("逐项处置字节总量溢出"),
                            "disposition");
            totalBytes += entry.bytes;
            if (isCopied) {
                ++copied;
                copiedDirectories += entry.directory ? 1 : 0;
            } else {
                ++skipped;
                skippedDirectories += entry.directory ? 1 : 0;
            }
            addRecord(hash, bytes);
        }
        if (query.lastError().isValid())
            throw Error(ExitCode::Disk, QStringLiteral("逐项处置汇总读取失败"), "disposition");
        if (rows < 100)
            break;
    }
    const bool complete = count == expectedEntries_;
    if (copiedBytes > expectedBytes_ - skippedBytes ||
        (complete && copiedBytes + skippedBytes != expectedBytes_) ||
        (requireComplete && !complete))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项处置尚未完整匹配冻结清单"),
                    "disposition");
    return {{"version", 1},
            {"taskId", next::parseControl(binding_)["taskId"]},
            {"manifest", manifestInfo_["sha256"]},
            {"conflict", conflict_},
            {"complete", complete},
            {"totalEntries", QString::number(expectedEntries_)},
            {"processedEntries", QString::number(count)},
            {"unexecutedEntries", QString::number(expectedEntries_ - count)},
            {"copiedEntries", QString::number(copied)},
            {"skippedEntries", QString::number(skipped)},
            {"copiedFiles", QString::number(copied - copiedDirectories)},
            {"copiedDirectories", QString::number(copiedDirectories)},
            {"skippedFiles", QString::number(skipped - skippedDirectories)},
            {"skippedDirectories", QString::number(skippedDirectories)},
            {"copiedBytes", QString::number(copiedBytes)},
            {"skippedBytes", QString::number(skippedBytes)},
            {"totalBytes", QString::number(expectedBytes_)},
            {"sha256", QString::fromLatin1(hash.result().toHex())}};
}
} // namespace dukto

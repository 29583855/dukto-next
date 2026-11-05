#include "transferitems.h"
#include "error.h"
#include "protocol.h"
#include "strongmanifest.h"
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSqlError>
#include <QSqlQuery>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-05；每个只读连接取得控制缓存授信；事务固定单页快照，不创建或修复数据库。
class Snapshot final {
  public:
    // 日期：2026-11-05；普通文件权限先核验；SQLite 仅只读打开，错误不泄露本地路径。
    Snapshot(PrivateStore &store, const QString &name)
        : connection_(QUuid::createUuid().toString()), credit_(1024, true) {
        if (store.validateFile(name) > MaxMetadataBytes)
            throw Error(ExitCode::Disk, QStringLiteral("明细数据库超出磁盘预算"), "items");
        database_ = QSqlDatabase::addDatabase("QSQLITE", connection_);
        try {
            database_.setConnectOptions("QSQLITE_OPEN_READONLY");
            database_.setDatabaseName(QDir(store.directory()).filePath(name));
            if (!database_.open())
                throw Error(ExitCode::Disk, QStringLiteral("无法只读打开明细数据库"), "items");
            credit_.configure(database_);
            QSqlQuery query(database_);
            if (!query.exec("PRAGMA busy_timeout=1000") || !query.exec("PRAGMA query_only=ON") ||
                !query.exec("BEGIN"))
                throw Error(ExitCode::Disk, QStringLiteral("无法建立明细快照"), "items");
        } catch (...) {
            close();
            throw;
        }
    }
    // 日期：2026-11-05；查询先于连接析构，读事务回滚不写任何任务数据。
    ~Snapshot() {
        close();
    }
    Snapshot(const Snapshot &) = delete;
    Snapshot &operator=(const Snapshot &) = delete;
    // 日期：2026-11-05；仅供当前线程的短生命周期查询使用，不向其他线程转交连接。
    QSqlDatabase database() const {
        return database_;
    }

  private:
    // 日期：2026-11-05；异常与正常析构共用连接清理，防止注册项随翻页累积。
    void close() {
        database_.close();
        database_ = QSqlDatabase();
        QSqlDatabase::removeDatabase(connection_);
    }
    QString connection_;
    SqliteCacheCredit credit_;
    QSqlDatabase database_;
};

// 日期：2026-11-05；查询错误包括遍历期间的磁盘错误都明确失败，不以空页掩盖损坏。
void execute(QSqlQuery &query) {
    if (!query.exec())
        throw Error(ExitCode::Disk, QStringLiteral("任务明细查询失败"), "items");
}

// 日期：2026-11-05；公开页只含相对路径和历史证据；不把旧日志声称为当前文件重新校验通过。
QJsonObject pageInfo(const TransferTask &task, quint64 after) {
    if (task.id.isNull() || task.entries < 0 || after > static_cast<quint64>(task.entries))
        throw Error(ExitCode::Config, QStringLiteral("任务明细起点无效"), "items");
    return {{"version", 1},
            {"taskId", task.id.toString(QUuid::WithoutBraces)},
            {"taskState", task.state},
            {"taskError", task.error},
            {"direction", task.direction},
            {"conflict", conflictPolicyName(task.conflict)},
            {"manifest", QString::fromLatin1(task.manifest.toHex())},
            {"available", false},
            {"currentContentVerified", false},
            {"entries", QJsonArray{}},
            {"after", QString::number(after)},
            {"more", false}};
}

// 日期：2026-11-05；读取接收日志单行并核对冻结清单；不输出临时名称、原生身份或绝对路径。
QJsonObject itemInfo(QSqlDatabase database, const StrongEntry &entry) {
    auto item = entry.publicInfo();
    item["target"] = "";
    item["disposition"] = "not-executed";
    item["confirmedBytes"] = "0";
    if (!database.isValid())
        return item;
    QSqlQuery query(database);
    query.prepare(entry.directory ? "SELECT spec,target,state,0 FROM directories WHERE id=?"
                                  : "SELECT spec,target,state,confirmed FROM files WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(entry.id));
    execute(query);
    if (query.next()) {
        const auto spec = next::parseControl(query.value(0).toByteArray());
        const auto target = validateRelativePath(query.value(1).toString());
        const auto state = query.value(2).toString();
        const auto confirmed = next::decimal(query.value(3).toString(), entry.bytes);
        if (spec.size() != 2 || spec["entry"].toObject() != entry.publicInfo() ||
            !spec["path"].isString() ||
            !QStringList{"planned", "receiving", "committing", "completed"}.contains(state) ||
            (entry.directory && state == "receiving") ||
            (!entry.directory && state == "completed" && confirmed != quint64(entry.bytes)))
            throw Error(ExitCode::Integrity, QStringLiteral("接收明细与冻结清单不同"), "items");
        validateRelativePath(spec["path"].toString());
        if (QFileInfo(target).path() != QFileInfo(spec["path"].toString()).path())
            throw Error(ExitCode::Integrity, QStringLiteral("接收明细目标父目录不符"), "items");
        item["target"] = target;
        item["disposition"] = state == "completed" ? "copied" : state;
        item["confirmedBytes"] = QString::number(confirmed);
    }
    if (query.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("接收明细读取失败"), "items");
    return item;
}
} // namespace

// 日期：2026-11-05；主键范围翻页最多100项且小于控制帧；只查本页，不重复扫描完整清单或正文。
QJsonObject transferItems(PrivateStore &store, const TransferTask &task,
                          const QString &manifestName, const QString &root, quint64 after) {
    auto result = pageInfo(task, after);
    if (task.manifest.isEmpty()) {
        result["reason"] = "manifest-pending";
        return result;
    }
    Snapshot source(store, manifestName);
    QSqlQuery metadata(source.database());
    metadata.prepare("SELECT value FROM metadata");
    execute(metadata);
    if (!metadata.next())
        throw Error(ExitCode::Integrity, QStringLiteral("任务明细缺少冻结清单"), "items");
    const auto meta = next::parseControl(metadata.value(0).toByteArray());
    if (meta["version"] != 1 || meta["sha256"] != QString::fromLatin1(task.manifest.toHex()) ||
        meta["entries"] != QString::number(task.entries) ||
        meta["bytes"] != QString::number(task.total) ||
        meta["blockBytes"] != QString::number(StrongBlockBytes) || metadata.next())
        throw Error(ExitCode::Integrity, QStringLiteral("明细清单与原任务绑定不同"), "items");
    std::unique_ptr<Snapshot> receiver;
    const auto journalName = "receive-" + task.id.toString(QUuid::WithoutBraces) + ".sqlite";
    if (!store.exists(journalName) && task.state == "completed") {
        result["reason"] = "receive-journal-unavailable";
        return result;
    }
    if (store.exists(journalName)) {
        receiver.reset(new Snapshot(store, journalName));
        QSqlQuery binding(receiver->database());
        binding.prepare("SELECT spec FROM binding");
        execute(binding);
        if (!binding.next())
            throw Error(ExitCode::Integrity, QStringLiteral("接收明细缺少任务绑定"), "items");
        const auto info = next::parseControl(binding.value(0).toByteArray());
        auto expected = QJsonObject{{"version", 1},
                                    {"task", task.id.toString(QUuid::WithoutBraces)},
                                    {"manifest", QString::fromLatin1(task.manifest.toHex())},
                                    {"root", QDir::cleanPath(root)},
                                    {"rootIdentity", info["rootIdentity"]}};
        if (task.conflict != ConflictPolicy::Rename) {
            expected["version"] = 2;
            expected["conflict"] = conflictPolicyName(task.conflict);
        }
        if (info != expected || !info["rootIdentity"].isString() ||
            info["rootIdentity"].toString().isEmpty() || binding.next())
            throw Error(ExitCode::Integrity, QStringLiteral("接收明细身份或策略不同"), "items");
    }
    QSqlQuery query(source.database());
    query.setForwardOnly(true);
    query.prepare(
        "SELECT id,relative,directory,bytes,sha FROM entries WHERE id>? ORDER BY id LIMIT 100");
    query.addBindValue(static_cast<qlonglong>(after));
    execute(query);
    QJsonArray entries;
    quint64 cursor = after;
    while (query.next()) {
        StrongEntry entry{
            query.value(0).toULongLong(), query.value(1).toString(),   {}, query.value(2).toBool(),
            query.value(3).toLongLong(),  query.value(4).toByteArray()};
        if (entry.id != cursor + 1 || entry.id > quint64(task.entries) || entry.bytes < 0 ||
            (query.value(2).toInt() != 0 && query.value(2).toInt() != 1) ||
            (entry.directory && (entry.bytes || !entry.sha256.isEmpty())) ||
            (!entry.directory && entry.sha256.size() != 32))
            throw Error(ExitCode::Integrity, QStringLiteral("明细清单条目损坏"), "items");
        validateRelativePath(entry.relative);
        entries.append(itemInfo(receiver ? receiver->database() : QSqlDatabase(), entry));
        if (QJsonDocument(entries).toJson(QJsonDocument::Compact).size() >
            next::ControlLimit - 2048) {
            entries.removeLast();
            break;
        }
        cursor = entry.id;
    }
    if (query.lastError().isValid() || (cursor == after && after < quint64(task.entries)))
        throw Error(ExitCode::Integrity, QStringLiteral("任务明细未能前进"), "items");
    result["available"] = true;
    result["entries"] = entries;
    result["after"] = QString::number(cursor);
    result["more"] = cursor < quint64(task.entries);
    return result;
}

// 日期：2026-11-05；远端发送完不代表本机落盘；缺少本机冻结清单时明示不可用，禁止制造复制成功。
QJsonObject localDownloadItems(PrivateStore &store, const QUuid &server, const QUuid &client,
                               const TransferTask &task, quint64 after) {
    auto result = pageInfo(task, after);
    const auto name = "download-request-" + task.request.toString(QUuid::WithoutBraces) + ".json";
    const auto manifest = "download-" + task.id.toString(QUuid::WithoutBraces) + ".sqlite";
    if (!store.exists(name) || !store.exists(manifest)) {
        result["reason"] = "local-receipt-unavailable";
        return result;
    }
    const auto binding = next::parseControl(store.read(name));
    auto expected = QJsonObject{{"version", 1},
                                {"server", server.toString(QUuid::WithoutBraces)},
                                {"client", client.toString(QUuid::WithoutBraces)},
                                {"share", task.share},
                                {"path", task.relative},
                                {"root", binding["root"]}};
    if (task.conflict != ConflictPolicy::Rename) {
        expected["version"] = 2;
        expected["conflict"] = conflictPolicyName(task.conflict);
    }
    if (task.direction != "download" || binding != expected || !binding["root"].isString() ||
        !QDir::isAbsolutePath(binding["root"].toString()))
        throw Error(ExitCode::Integrity, QStringLiteral("本地下载明细与服务器或原任务不同"),
                    "items");
    return transferItems(store, task, manifest, binding["root"].toString(), after);
}
} // namespace dukto

#include "transferitems.h"
#include "error.h"
#include "protocol.h"
#include "receiveskipproof.h"
#include "sqliteruntime.h"
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
        database_ = addSqliteDatabase(connection_);
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
            {"failureScope", "receiver-local"},
            {"failureEvidenceAvailable", false},
            {"currentContentVerified", false},
            {"entries", QJsonArray{}},
            {"after", QString::number(after)},
            {"more", false}};
}

// 日期：2026-11-06；按主键读取同一清单快照中的本项或祖先，字段及大小均有固定上限。
StrongEntry manifestEntry(QSqlDatabase database, quint64 file, quint64 count) {
    if (!file || file > count)
        throw Error(ExitCode::Integrity, QStringLiteral("明细祖先序号无效"), "items");
    QSqlQuery query(database);
    query.prepare("SELECT id,substr(relative,1,4097),directory,bytes,substr(sha,1,33),"
                  "typeof(directory),typeof(bytes) FROM entries WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(file));
    execute(query);
    if (!query.next())
        throw Error(ExitCode::Integrity, QStringLiteral("明细清单缺少项目"), "items");
    StrongEntry entry{file,
                      query.value(1).toString(),
                      {},
                      query.value(2).toBool(),
                      query.value(3).toLongLong(),
                      query.value(4).toByteArray()};
    if (query.value(0).toULongLong() != file ||
        (query.value(2).toInt() != 0 && query.value(2).toInt() != 1) || entry.bytes < 0 ||
        query.value(5) != "integer" || query.value(6) != "integer" ||
        (entry.directory ? entry.bytes || !entry.sha256.isEmpty() : entry.sha256.size() != 32) ||
        query.lastError().isValid())
        throw Error(ExitCode::Integrity, QStringLiteral("明细清单项目字段损坏"), "items");
    validateRelativePath(entry.relative);
    return entry;
}

// 日期：2026-11-06；分页证明只访问本项、父项及原跳过根，不依赖当前目标是否仍存在。
QJsonObject itemDecision(QSqlDatabase database, const StrongEntry &entry,
                         const ReceiveSkipProof &proof, bool finals, bool completed) {
    QSqlQuery query(database);
    query.prepare("SELECT 1 FROM skip_decisions WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(entry.id));
    execute(query);
    const bool found = query.next();
    if (query.lastError().isValid())
        throw Error(ExitCode::Disk, QStringLiteral("明细准备记录读取失败"), "items");
    if (!found) {
        if (completed)
            throw Error(ExitCode::Integrity, QStringLiteral("完成明细缺少接收决定"), "items");
        if (finals) {
            query.finish();
            query.prepare("SELECT 1 FROM skip_final WHERE id=?");
            query.addBindValue(static_cast<qlonglong>(entry.id));
            execute(query);
            if (query.next() || query.lastError().isValid())
                throw Error(ExitCode::Integrity, QStringLiteral("最终跳过缺少准备记录"), "items");
        }
        return {};
    }
    const auto decision = proof.decision(entry.id);
    const auto root = next::decimal(decision["skippedRoot"], entry.id);
    if (root && root != entry.id) {
        const auto ancestor = proof.decision(root);
        if (ancestor["action"] != "skip" || ancestor["skippedRoot"] != QString::number(root) ||
            ancestor["entry"].toObject()["type"] != "directory" ||
            !entry.relative.startsWith(ancestor["path"].toString() + '/'))
            throw Error(ExitCode::Integrity, QStringLiteral("明细跳过根不是原冲突祖先"), "items");
    }
    return decision;
}

// 日期：2026-11-06；复制与跳过分别核对原持久证据；不输出临时名称、身份或绝对路径。
QJsonObject itemInfo(QSqlDatabase database, const StrongEntry &entry, bool failures,
                     const ReceiveSkipProof *skip, bool finals, bool completed) {
    auto item = entry.publicInfo();
    item["target"] = "";
    item["disposition"] = "not-executed";
    item["confirmedBytes"] = "0";
    item["lastFailure"] = QJsonValue(QJsonValue::Null);
    if (!database.isValid())
        return item;
    const auto decision =
        skip ? itemDecision(database, entry, *skip, finals, completed) : QJsonObject{};
    QSqlQuery query(database);
    query.prepare(entry.directory ? "SELECT spec,target,state,0 FROM directories WHERE id=?"
                                  : "SELECT spec,target,state,confirmed FROM files WHERE id=?");
    query.addBindValue(static_cast<qlonglong>(entry.id));
    execute(query);
    const bool received = query.next();
    if (received) {
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
    query.finish();
    if (skip) {
        if (decision.isEmpty() && received)
            throw Error(ExitCode::Integrity, QStringLiteral("接收明细缺少原准备决定"), "items");
        if (!decision.isEmpty()) {
            if (decision["action"] == "skip") {
                const auto final = skip->finalDecision(entry.id);
                if (final.isEmpty() && received)
                    throw Error(ExitCode::Integrity, QStringLiteral("准备跳过混入正文接收记录"),
                                "items");
                bool cleaned = true;
                if (!final.isEmpty()) {
                    query.prepare("SELECT cleaned,typeof(cleaned) FROM skip_final WHERE id=?");
                    query.addBindValue(static_cast<qlonglong>(entry.id));
                    execute(query);
                    if (!query.next() || query.value(1) != "integer")
                        throw Error(ExitCode::Integrity, QStringLiteral("跳过清理证据类型无效"),
                                    "items");
                    cleaned = query.value(0).toInt() == 1;
                    if (completed && !cleaned)
                        throw Error(ExitCode::Integrity, QStringLiteral("完成任务仍有未清理跳过"),
                                    "items");
                    query.finish();
                }
                item["target"] = entry.relative;
                item["disposition"] = cleaned ? "skipped" : "committing";
                // 日期：2026-11-06；未清理完成只发布committing，跳过根仅属于最终跳过结果。
                if (cleaned)
                    item["skippedRoot"] = decision["skippedRoot"];
                item["confirmedBytes"] = "0";
            } else if (!received) {
                if (completed)
                    throw Error(ExitCode::Integrity, QStringLiteral("完成明细缺少复制记录"),
                                "items");
                item["target"] = entry.relative;
                item["disposition"] = "planned";
            } else if (item["target"] != entry.relative ||
                       (completed && item["disposition"] != "copied")) {
                throw Error(ExitCode::Integrity, QStringLiteral("跳过策略的复制目标或状态不同"),
                            "items");
            }
        }
    }
    if (failures) {
        query.prepare("SELECT spec,phase,code,stage,resolved,typeof(code),typeof(resolved) "
                      "FROM item_failures WHERE id=?");
        query.addBindValue(static_cast<qlonglong>(entry.id));
        execute(query);
        if (query.next()) {
            const auto code = query.value(2).toLongLong();
            const auto resolved = query.value(4).toLongLong();
            if (next::parseControl(query.value(0).toByteArray()) != entry.publicInfo() ||
                (code != 4 && code != 5 && code != 6) || (resolved != 0 && resolved != 1) ||
                query.value(5).toString() != "integer" || query.value(6).toString() != "integer")
                throw Error(ExitCode::Integrity, QStringLiteral("逐项失败证据与清单不同"), "items");
            item["lastFailure"] = QJsonObject{{"version", 1},
                                              {"phase", query.value(1).toString()},
                                              {"code", static_cast<int>(code)},
                                              {"stage", query.value(3).toString()},
                                              {"resolved", resolved == 1}};
        }
        if (query.lastError().isValid())
            throw Error(ExitCode::Disk, QStringLiteral("逐项失败证据读取失败"), "items");
    }
    validateItemFailure(item, failures);
    return item;
}
} // namespace

// 日期：2026-11-06；仅实际复制或持久跳过可解决原失败，不把批次错误归到全部文件。
void validateItemFailure(const QJsonObject &item, bool available) {
    const auto failure = item["lastFailure"];
    if (failure.isNull())
        return;
    const auto value = failure.toObject();
    const auto code = value["code"].toInt(-1);
    if (!available || !failure.isObject() || value.size() != 5 || value["version"] != 1 ||
        !value["resolved"].isBool() || !value["code"].isDouble() ||
        value["code"].toDouble() != code || (code != 4 && code != 5 && code != 6) ||
        !QStringList{"prepare", "open", "write", "finish"}.contains(value["phase"].toString()) ||
        !QStringList{"receive", "write", "read", "path", "commit", "conflict", "storage"}.contains(
            value["stage"].toString()) ||
        (value["resolved"] == QJsonValue(true) && item["disposition"] != "copied" &&
         item["disposition"] != "skipped"))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项失败证据字段无效"), "items");
}

// 日期：2026-11-06；校验分页项目的规范序号、内容身份、处置与目标，不把跳过计作已接收字节。
void validateTransferItem(const QJsonObject &item, ConflictPolicy conflict, quint64 expectedId) {
    const auto sequence = next::decimal(item["id"], std::numeric_limits<qint64>::max());
    const auto bytes = next::decimal(item["bytes"], std::numeric_limits<qint64>::max());
    const auto confirmed = next::decimal(item["confirmedBytes"], bytes);
    const auto disposition = item["disposition"].toString();
    const auto hash = QByteArray::fromHex(item["sha256"].toString().toLatin1());
    const bool directory = item["type"] == "directory";
    if (sequence != expectedId ||
        !QStringList{"not-executed", "planned", "receiving", "committing", "copied", "skipped"}
             .contains(disposition) ||
        (item["type"] != "file" && !directory) || !item["target"].isString() ||
        (directory ? bytes || confirmed || !hash.isEmpty() : hash.size() != 32) ||
        item["sha256"] != QString::fromLatin1(hash.toHex()) ||
        (disposition == "copied" && confirmed != bytes))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项查询条目无效"), "items");
    const auto path = validateRelativePath(item["path"].toString());
    if (!item["target"].toString().isEmpty())
        validateRelativePath(item["target"].toString());
    if (disposition == "skipped") {
        const auto root = next::decimal(item["skippedRoot"], sequence);
        if (conflict != ConflictPolicy::Skip || confirmed || !root || root > sequence ||
            item["target"] != path)
            throw Error(ExitCode::Integrity, QStringLiteral("逐项跳过结果与原策略或目标不同"),
                        "items");
    } else if (item.contains("skippedRoot")) {
        throw Error(ExitCode::Integrity, QStringLiteral("非跳过结果包含跳过根"), "items");
    }
}

// 日期：2026-11-06；每页最多100项；跳过v3/v4证据只读解释，不迁移、不访问正文或全树扫描。
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
    std::unique_ptr<ReceiveSkipProof> skip;
    bool finals = false;
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
        const auto bindingBytes = binding.value(0).toByteArray();
        const auto info = next::parseControl(bindingBytes);
        auto expected = QJsonObject{{"version", 1},
                                    {"task", task.id.toString(QUuid::WithoutBraces)},
                                    {"manifest", QString::fromLatin1(task.manifest.toHex())},
                                    {"root", QDir::cleanPath(root)},
                                    {"rootIdentity", info["rootIdentity"]}};
        if (task.conflict != ConflictPolicy::Rename) {
            expected["version"] = 2;
            expected["conflict"] = conflictPolicyName(task.conflict);
        }
        if (task.conflict == ConflictPolicy::Skip) {
            finals = info["version"] == 4;
            expected["version"] = finals ? 4 : 3;
        }
        if (info != expected || !info["rootIdentity"].isString() ||
            info["rootIdentity"].toString().isEmpty() ||
            (task.conflict == ConflictPolicy::Skip &&
             bindingBytes != next::encodeControl(expected)) ||
            binding.next())
            throw Error(ExitCode::Integrity, QStringLiteral("接收明细身份或策略不同"), "items");
        if (task.conflict == ConflictPolicy::Skip) {
            binding.finish();
            binding.prepare("SELECT id,source,spec FROM skip_decisions LIMIT 0");
            execute(binding);
            if (finals) {
                binding.finish();
                binding.prepare("SELECT id,spec,cleaned FROM skip_final LIMIT 0");
                execute(binding);
            }
            skip.reset(new ReceiveSkipProof(
                receiver->database(),
                [&](quint64 file) {
                    // 日期：2026-11-06；查找固定在源只读事务内；祖先数量不随目录树规模增长。
                    return manifestEntry(source.database(), file,
                                         static_cast<quint64>(task.entries));
                },
                finals));
        }
    }
    bool failures = false;
    if (receiver) {
        QSqlQuery schema(receiver->database());
        schema.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item_failures'");
        execute(schema);
        failures = schema.next();
    }
    result["failureEvidenceAvailable"] = failures;
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
        entries.append(itemInfo(receiver ? receiver->database() : QSqlDatabase(), entry, failures,
                                skip.get(), finals, task.state == "completed"));
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

// 日期：2026-11-06；本机绑定同时核对策略和计量契约，缺本机清单明示不可用，不制造成功。
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
    if (task.accountingRequired) {
        expected["version"] = 3;
        expected["progress"] = "disposition-v1";
        expected["conflict"] = conflictPolicyName(task.conflict);
    }
    if (task.direction != "download" || binding != expected || !binding["root"].isString() ||
        !QDir::isAbsolutePath(binding["root"].toString()))
        throw Error(ExitCode::Integrity, QStringLiteral("本地下载明细与服务器或原任务不同"),
                    "items");
    return transferItems(store, task, manifest, binding["root"].toString(), after);
}
} // namespace dukto

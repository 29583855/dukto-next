#include "dispositionjournal.h"
#include "error.h"
#include "fileexchange.h"
#include "files.h"
#include "paralleltransfer.h"
#include "service.h"
#include "transferdisposition.h"
#include "transferitems.h"
#include "transferprogress.h"
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonArray>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-04；子交换响应沿用当前请求序号，远端错误必须保留明确退出码和阶段。
QJsonObject control(next::SecureChannel &channel, quint64 correlation, next::Type expected) {
    auto frame = channel.read();
    while (frame.header.correlation == correlation && frame.header.type == next::Type::TaskState &&
           next::parseControl(frame.payload) == QJsonObject{{"state", "busy"}})
        frame = channel.read();
    if (frame.header.correlation != correlation)
        throw Error(ExitCode::Config, QStringLiteral("传输控制响应序号不同"), "transfer");
    const auto value = next::parseControl(frame.payload);
    if (frame.header.type == next::Type::Failure) {
        const auto code = value["code"].toInt(-1);
        if (code < 1 || code > 7 || !value["message"].isString() || !value["stage"].isString())
            throw Error(ExitCode::Config, QStringLiteral("传输错误响应无效"), "transfer");
        throw Error(static_cast<ExitCode>(code), value["message"].toString(),
                    value["stage"].toString());
    }
    if (frame.header.type != expected)
        throw Error(ExitCode::Config, QStringLiteral("传输控制响应类型不同"), "transfer");
    return value;
}

// 日期：2026-11-05；排队消息严格绑定任务；周期心跳只表明等待，不表示获准、块确认或任务完成。
QJsonObject awaitAdmission(next::SecureChannel &channel, quint64 correlation, const QUuid &id,
                           int requested,
                           const std::function<void(const QJsonObject &)> &progress) {
    for (;;) {
        const auto frame = channel.read();
        if (frame.header.correlation != correlation)
            throw Error(ExitCode::Integrity, QStringLiteral("排队响应序号不同"), "scheduler");
        const auto value = next::parseControl(frame.payload);
        if (frame.header.type == next::Type::Failure) {
            const auto code = value["code"].toInt(-1);
            if (code < 1 || code > 7 || !value["message"].isString() || !value["stage"].isString())
                throw Error(ExitCode::Config, QStringLiteral("排队错误响应无效"), "scheduler");
            throw Error(static_cast<ExitCode>(code), value["message"].toString(),
                        value["stage"].toString());
        }
        if (value["taskId"] != id.toString(QUuid::WithoutBraces))
            throw Error(ExitCode::Integrity, QStringLiteral("排队响应任务不同"), "scheduler");
        if (frame.header.type == next::Type::TaskAdmitted) {
            const auto lanes = checkedChannels(value["channels"]);
            if (value.size() != 3 || !value["needManifest"].isBool() || lanes > requested)
                throw Error(ExitCode::Config, QStringLiteral("传输授信响应无效"), "scheduler");
            if (progress) {
                auto event = value;
                event["event"] = "transfer-admitted";
                event["message"] = QStringLiteral("已获准执行，实际并发 %1").arg(lanes);
                progress(event);
            }
            return value;
        }
        if (frame.header.type != next::Type::TaskState ||
            value !=
                QJsonObject{{"taskId", id.toString(QUuid::WithoutBraces)}, {"state", "queued"}})
            throw Error(ExitCode::Config, QStringLiteral("排队心跳字段无效"), "scheduler");
        if (progress) {
            auto event = value;
            event["event"] = "transfer-queued";
            event["message"] = QStringLiteral("正在排队等待可用传输资源，可查询、暂停或取消");
            progress(event);
        }
    }
}

// 日期：2026-11-06；新请求选择双方支持的契约；已存在请求精确匹配旧/新绑定，不能升级或降级。
bool bindAccounting(PrivateStore &local, const QString &name, const QJsonObject &legacy,
                    ConflictPolicy conflict, bool capable, const QString &stage = "transfer") {
    auto explicitBinding = legacy;
    explicitBinding["version"] = 3;
    explicitBinding["progress"] = "disposition-v1";
    explicitBinding["conflict"] = conflictPolicyName(conflict);
    const auto oldBytes = next::encodeControl(legacy);
    const auto newBytes = next::encodeControl(explicitBinding);
    if (local.exists(name)) {
        const auto saved = local.read(name);
        if (saved == oldBytes) {
            if (conflict == ConflictPolicy::Skip)
                throw Error(ExitCode::Integrity, QStringLiteral("跳过请求缺少原必需计量契约"),
                            stage);
            return false;
        }
        if (saved != newBytes)
            throw Error(ExitCode::Integrity, QStringLiteral("请求已绑定其他目标、内容或计量契约"),
                        stage);
        if (!capable)
            throw Error(ExitCode::Config,
                        QStringLiteral("服务器缺少原请求必需计量能力，请升级服务器"), "progress");
        return true;
    }
    if (conflict == ConflictPolicy::Skip && !capable)
        throw Error(ExitCode::Config, QStringLiteral("跳过策略需要完整处置计量能力"), "conflict");
    local.write(name, capable ? newBytes : oldBytes);
    return capable;
}

// 日期：2026-11-06；每个任务快照绑定当前契约和强清单，数字、守恒及已处理量分别校验。
QJsonObject checkedAccounting(const QJsonObject &task, bool required, ConflictPolicy conflict) {
    if (required ? task["accountingVersion"] != QJsonValue(1) : task.contains("accountingVersion"))
        throw Error(ExitCode::Integrity, QStringLiteral("服务器改变了原请求计量契约"), "progress");
    if (!required)
        return {};
    const auto total = next::decimal(task["total"], std::numeric_limits<qint64>::max());
    const auto entries = next::decimal(task["entries"], 10000000);
    const QStringList fields{"copiedBytes",       "skippedBytes",      "discardedBytes",
                             "copiedFiles",       "copiedDirectories", "skippedFiles",
                             "skippedDirectories"};
    if (task["manifest"] == "") {
        if (total || entries || task["bytes"] != "0" || task.contains("receivedBytes") ||
            task.contains("confirmedBytes") || task.contains("restoredBytes") ||
            task.contains("handledBytes"))
            throw Error(ExitCode::Integrity, QStringLiteral("未绑定任务不能携带计量"), "progress");
        for (const auto &key : fields)
            if (task.contains(key))
                throw Error(ExitCode::Integrity, QStringLiteral("未绑定任务不能携带处置"),
                            "progress");
        return {};
    }
    if (!entries)
        throw Error(ExitCode::Integrity, QStringLiteral("必需计量缺少冻结条目"), "progress");
    QJsonObject snapshot{{"bytes", task["receivedBytes"]},
                         {"confirmed", task["confirmedBytes"]},
                         {"restored", task["restoredBytes"]}};
    for (const auto &key : fields)
        snapshot[key] = task[key];
    TransferAccounting meter(total, entries);
    meter.accept(snapshot);
    if (task["bytes"] != QString::number(meter.handled()) ||
        task["handledBytes"] != task["bytes"] ||
        (conflict != ConflictPolicy::Skip &&
         (task["skippedBytes"] != "0" || task["discardedBytes"] != "0" ||
          task["skippedFiles"] != "0" || task["skippedDirectories"] != "0")))
        throw Error(ExitCode::Integrity, QStringLiteral("任务计量与逻辑进度或策略不同"),
                    "progress");
    return snapshot;
}

// 日期：2026-11-06；最终计量必须和独立本机处置摘要一致，新传输还须与实际进度快照逐字段一致。
void checkCompletedAccounting(const QJsonObject &task, const QJsonObject &disposition,
                              ConflictPolicy conflict, const QJsonObject &expected = {}) {
    const auto snapshot = checkedAccounting(task, true, conflict);
    if (disposition["complete"] != QJsonValue(true) ||
        (!expected.isEmpty() && snapshot != expected))
        throw Error(ExitCode::Integrity, QStringLiteral("最终计量与本轮实际进度不同"),
                    "completion");
    for (const auto &key : {"copiedBytes", "skippedBytes", "copiedFiles", "copiedDirectories",
                            "skippedFiles", "skippedDirectories"})
        if (snapshot[key] != disposition[key])
            throw Error(ExitCode::Integrity, QStringLiteral("最终计量与本机处置证据不同"),
                        "completion");
}

// 日期：2026-11-06；初始、就绪与最终任务均核对原请求、冲突策略及持久计量契约。
QUuid checkedTask(const QJsonObject &task, const QUuid &request, const QString &direction,
                  const QString &share, const QString &relative, ConflictPolicy conflict,
                  bool accounting = false) {
    checkedAccounting(task, accounting, conflict);
    const QUuid id(task["taskId"].toString());
    if (id.isNull() || task["taskId"] != id.toString(QUuid::WithoutBraces) ||
        task["requestId"] != request.toString(QUuid::WithoutBraces) ||
        task["direction"] != direction || task["share"] != share || task["path"] != relative ||
        !task["state"].isString() ||
        (conflict == ConflictPolicy::Rename ? task.contains("conflict")
                                            : task["conflict"] != conflictPolicyName(conflict)))
        throw Error(ExitCode::Integrity, QStringLiteral("服务器任务结果与请求不符"), "transfer");
    return id;
}

// 日期：2026-11-04；扫描期间只逐条转发有界心跳，直到收到带冻结清单的就绪任务。
QJsonObject readyTask(next::SecureChannel &channel, quint64 correlation, const QUuid &id,
                      const std::function<void(const QJsonObject &)> &progress) {
    for (;;) {
        const auto frame = channel.read();
        if (frame.header.correlation != correlation)
            throw Error(ExitCode::Config, QStringLiteral("扫描响应序号不同"), "transfer");
        const auto value = next::parseControl(frame.payload);
        if (frame.header.type == next::Type::Failure) {
            const auto code = value["code"].toInt(-1);
            if (code < 1 || code > 7 || !value["message"].isString() || !value["stage"].isString())
                throw Error(ExitCode::Config, QStringLiteral("扫描错误响应无效"), "transfer");
            throw Error(static_cast<ExitCode>(code), value["message"].toString(),
                        value["stage"].toString());
        }
        if (value["taskId"] != id.toString(QUuid::WithoutBraces))
            throw Error(ExitCode::Integrity, QStringLiteral("扫描响应任务身份不同"), "transfer");
        if (frame.header.type == next::Type::Task ||
            (frame.header.type == next::Type::TaskState && value["state"] == "completed"))
            return value;
        if (frame.header.type != next::Type::TaskState || value["state"] != "scanning")
            throw Error(ExitCode::Config, QStringLiteral("扫描响应状态无效"), "transfer");
        if (progress)
            progress(value);
    }
}

// 日期：2026-11-05；完成确认逐字段绑定冻结强清单，拒绝错误总量、条目数及宽松数值转换。
void checkCompletedSummary(const QJsonObject &task, const QJsonObject &summary) {
    if (task["state"] != "completed" || task["manifest"] != summary["sha256"] ||
        task["total"] != summary["bytes"] || task["bytes"] != summary["bytes"] ||
        task["entries"] != summary["entries"] || task["error"] != QJsonValue(0) ||
        task["desired"] != "")
        throw Error(ExitCode::Integrity, QStringLiteral("批次持久完成确认与冻结清单不符"),
                    "transfer");
}

// 日期：2026-11-06；逐字段比较本机完整摘要，错误或缺项不得发送肯定确认。
void confirmDisposition(next::SecureChannel &channel, quint64 correlation,
                        const QJsonObject &summary) {
    if (control(channel, correlation, next::Type::DispositionSummary) != summary)
        throw Error(ExitCode::Integrity, QStringLiteral("收发两端处置摘要不同"), "disposition");
    channel.write(next::Type::DispositionAck, correlation, summary);
}

// 日期：2026-11-06；最终回包同时绑定处置和实际计量，历史观察帧不能充当本次成功。
QJsonObject completedTask(next::SecureChannel &channel, quint64 correlation, const QUuid &id,
                          const QUuid &request, const QString &direction, const QString &share,
                          const QString &relative, const QJsonObject &summary,
                          ConflictPolicy conflict, bool accounting,
                          const QJsonObject &disposition = {}, const QJsonObject &snapshot = {}) {
    const auto value = control(channel, correlation, next::Type::TaskState);
    if (checkedTask(value, request, direction, share, relative, conflict, accounting) != id)
        throw Error(ExitCode::Integrity, QStringLiteral("批次持久完成确认不完整"), "transfer");
    checkCompletedSummary(value, summary);
    if (accounting)
        checkCompletedAccounting(value, disposition, conflict, snapshot);
    if (!disposition.isEmpty() && (value["dispositionSummary"] != disposition ||
                                   value["dispositionConfirmed"] != QJsonValue(true) ||
                                   value.contains("confirmationRequired")))
        throw Error(ExitCode::Integrity, QStringLiteral("最终处置确认缺失或不同"), "disposition");
    return value;
}

// 日期：2026-11-06；只读核验原接收证据；旧模式可据完整证明补齐派生处置，必需计量任务禁止降级。
QJsonObject verifyLocalDownload(PrivateStore &local, const QUuid &id, const QString &destination,
                                const QJsonObject &task, const std::atomic_bool *cancel,
                                ConflictPolicy conflict, const std::function<void()> &pulse = {}) {
    const auto key = id.toString(QUuid::WithoutBraces);
    if (!local.exists("download-" + key + ".sqlite") || !local.exists("receive-" + key + ".sqlite"))
        throw Error(ExitCode::Integrity, QStringLiteral("已完成下载缺少本地清单或接收日志"),
                    "transfer");
    const auto check = [&]() {
        // 日期：2026-11-06；本地重读响应取消；协商新确认时由调用者发有界忙心跳维持原连接。
        if (pulse)
            pulse();
        QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
        if (cancel && cancel->load())
            throw Error(ExitCode::Cancelled, QStringLiteral("本地下载校验已取消"), "transfer");
    };
    StrongManifest manifest(local, "download-" + key + ".sqlite", false, check);
    checkCompletedSummary(task, manifest.summary());
    const auto outcomeName = "disposition-" + key + ".sqlite";
    const auto entries = next::decimal(manifest.summary()["entries"], 10000000);
    std::unique_ptr<DispositionJournal> outcomes;
    quint64 recorded = 0;
    if (local.exists(outcomeName)) {
        outcomes.reset(new DispositionJournal(local, outcomeName, id, manifest,
                                              conflictPolicyName(conflict), check, true));
        recorded = next::decimal(outcomes->summary(false, check)["processedEntries"], entries);
    }
    const bool incomplete = !outcomes || recorded != entries;
    if (incomplete && (conflict == ConflictPolicy::Skip || task.contains("accountingVersion")))
        throw Error(ExitCode::Integrity, QStringLiteral("显式计量任务缺少完整原处置证据"),
                    "completion");
    DurableReceive::verifyCompleted(
        local, "receive-" + key + ".sqlite", id, manifest, destination, conflict, check, {},
        [&](quint64 file, const DurableReceive::Preparation &result) {
            // 日期：2026-11-06；先只读核对完整接收和已有前缀；路径或跳过根不一致时禁止补写。
            if (!outcomes || file > recorded)
                return;
            const auto item = outcomes->item(file);
            const auto skippedRoot = result.skipped ? next::decimal(item["skippedRoot"], file) : 0;
            if (item["path"] != result.path ||
                item["disposition"] != (result.skipped ? "skipped" : "copied") ||
                skippedRoot != result.skippedRoot)
                throw Error(ExitCode::Integrity, QStringLiteral("本地完成接收与原处置不同"),
                            "completion");
        });
    if (incomplete) {
        // 日期：2026-11-06；旧模式全部只读核验通过后才打开派生日志；第二遍有界重验，不改写原接收库或目标。
        outcomes.reset();
        outcomes.reset(new DispositionJournal(local, outcomeName, id, manifest,
                                              conflictPolicyName(conflict), check));
        DurableReceive::verifyCompleted(
            local, "receive-" + key + ".sqlite", id, manifest, destination, conflict, check, {},
            [&](quint64 file, const DurableReceive::Preparation &result) {
                // 日期：2026-11-06；每项仍须是本次重新核验的复制结果，不能由旧数字或文件存在性补造。
                if (result.skipped || result.skippedRoot)
                    throw Error(ExitCode::Integrity, QStringLiteral("旧模式不能补写跳过处置"),
                                "completion");
                outcomes->append(file, result.path, "copied");
            });
    }
    return outcomes->summary(true, check);
}
} // namespace

// 日期：2026-11-06；历史按实际处置重验复制源并恢复跳过回执；原请求计量及双端确认保持。
QJsonObject RemoteClient::upload(const QUuid &requestId, const QString &share,
                                 const QString &relative, PrivateStore &local,
                                 StrongManifest &manifest,
                                 const std::function<void(const QJsonObject &)> &progress,
                                 int channels, ConflictPolicy conflict) {
    checkedChannels(QString::number(channels));
    checkedConflictPolicy(conflictPolicyName(conflict));
    // 日期：2026-11-06；skip独立协商逐项处置，其余策略保持已有交换契约。
    const bool dispositions = conflict == ConflictPolicy::Skip;
    if ((conflict == ConflictPolicy::Fail && !capabilities_.contains("conflict-fail-v1")) ||
        (conflict == ConflictPolicy::Overwrite &&
         !capabilities_.contains("conflict-overwrite-v1")) ||
        (conflict == ConflictPolicy::Skip && (!capabilities_.contains("conflict-skip-v1") ||
                                              !capabilities_.contains("disposition-summary-v1") ||
                                              !capabilities_.contains("disposition-progress-v1") ||
                                              !capabilities_.contains("byte-progress-v1"))))
        throw Error(ExitCode::Config, QStringLiteral("服务器未协商所选冲突策略能力"), "conflict");
    if (requestId.isNull())
        throw Error(ExitCode::Config, QStringLiteral("上传请求UUID无效"), "transfer");
    const auto requestKey = requestId.toString(QUuid::WithoutBraces);
    QLockFile requestLock(local.directory() + "/upload-request-" + requestKey + ".lock");
    requestLock.setStaleLockTime(0);
    if (!requestLock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("本地同一上传请求正在执行"), "transfer");
    const auto bindingInfo = QJsonObject{{"version", 1},
                                         {"server", server_.toString(QUuid::WithoutBraces)},
                                         {"client", profile_.client.toString(QUuid::WithoutBraces)},
                                         {"share", share},
                                         {"path", relative},
                                         {"conflict", conflictPolicyName(conflict)},
                                         {"manifest", manifest.summary()}};
    const auto requestName = "upload-request-" + requestKey + ".json";
    const bool accounting = bindAccounting(local, requestName, bindingInfo, conflict,
                                           capabilities_.contains("disposition-progress-v1") &&
                                               capabilities_.contains("byte-progress-v1") &&
                                               capabilities_.contains("disposition-summary-v1"),
                                           "disposition");
    const auto binding = local.read(requestName);
    QJsonObject create{{"requestId", requestKey},
                       {"share", share},
                       {"path", relative},
                       {"manifest", manifest.summary()}};
    if (conflict != ConflictPolicy::Rename)
        create["conflict"] = conflictPolicyName(conflict);
    const bool summaryProtocol = capabilities_.contains("disposition-summary-v1");
    if (summaryProtocol)
        create["dispositionSummary"] = true;
    const bool queuedProtocol = capabilities_.contains("task-admission-v1");
    if (queuedProtocol)
        create["queue"] = true;
    const bool byteProgress = capabilities_.contains("byte-progress-v1");
    if (byteProgress)
        create["byteProgress"] = true;
    if (accounting)
        create["dispositionProgress"] = true;
    if (channels > 1) {
        if (!capabilities_.contains("parallel-transfer-v1"))
            throw Error(ExitCode::Config, QStringLiteral("服务器未协商多通道能力"), "parallel");
        create["channels"] = QString::number(channels);
    }
    const auto initial = request(next::Type::CreateUpload, next::Type::Task, create);
    const auto id =
        checkedTask(initial, requestId, "upload", share, relative, conflict, accounting);
    const auto key = id.toString(QUuid::WithoutBraces);
    // 日期：2026-11-06；不同请求或服务不得通过重复任务ID接管原发送处置，即使清单相同。
    QLockFile taskLock(local.directory() + "/upload-task-" + key + ".lock");
    taskLock.setStaleLockTime(0);
    if (!taskLock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("本地已有同一上传任务执行者"),
                    "disposition");
    const auto taskName = "upload-task-" + key + ".json";
    const auto taskBinding =
        next::encodeControl({{"requestId", requestKey}, {"binding", next::parseControl(binding)}});
    if (local.exists(taskName)) {
        if (local.read(taskName) != taskBinding)
            throw Error(ExitCode::Integrity, QStringLiteral("上传任务已绑定其他请求"),
                        "disposition");
    } else {
        local.write(taskName, taskBinding);
    }
    bool confirmingDisposition = false;
    QElapsedTimer dispositionHeartbeat;
    dispositionHeartbeat.start();
    const auto dispositionCheck = [&]() {
        // 日期：2026-11-06；日志遍历和完成恢复持续响应取消；缓冲中的最终帧由读取负责校验。
        QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
        if (summaryProtocol && confirmingDisposition && dispositionHeartbeat.elapsed() >= 250) {
            channel_.write(next::Type::TaskState, correlation_, {{"state", "busy"}});
            dispositionHeartbeat.restart();
        }
        if (cancel_ && cancel_->load())
            throw Error(ExitCode::Cancelled, QStringLiteral("上传处置校验已取消"), "disposition");
    };
    DispositionJournal outcomes(local, "upload-disposition-" + key + ".sqlite", id, manifest,
                                conflictPolicyName(conflict), dispositionCheck);
    const auto recoverCompleted = [&](const QJsonObject &task) {
        // 日期：2026-11-06；服务器已完成而本机缺项时，每页独立认证，避免清单规模耗尽会话请求额度。
        checkCompletedSummary(task, manifest.summary());
        confirmingDisposition = true;
        if (summaryProtocol && task["confirmationRequired"] != QJsonValue(true))
            throw Error(ExitCode::Integrity, QStringLiteral("历史任务未要求本次处置确认"),
                        "disposition");
        if (!summaryProtocol)
            close();
        const auto state = outcomes.summary(false, dispositionCheck);
        if (state["complete"] == QJsonValue(true))
            return verifyCompletedSource(manifest, outcomes, dispositionCheck);
        if (!capabilities_.contains("task-items-v1"))
            throw Error(ExitCode::Config,
                        QStringLiteral("本地上传确认缺失，服务器不支持逐项证据恢复，请升级服务器"),
                        "disposition");
        const auto count = next::decimal(manifest.summary()["entries"], 10000000);
        quint64 after = 0;
        do {
            dispositionCheck();
            RemoteClient query(profile_, timeoutMs_, cancel_);
            query.authenticate();
            const auto current = query.manage(id);
            if (checkedTask(current, requestId, "upload", share, relative, conflict, accounting) !=
                id)
                throw Error(ExitCode::Integrity, QStringLiteral("上传恢复任务身份不同"),
                            "disposition");
            checkCompletedSummary(current, manifest.summary());
            const auto page = query.items(id, local, after);
            query.close();
            if (page["available"] != QJsonValue(true) || page["taskState"] != "completed" ||
                page["taskError"] != QJsonValue(0) ||
                page["manifest"] != manifest.summary()["sha256"])
                throw Error(ExitCode::Integrity, QStringLiteral("已完成上传缺少接收端逐项证据"),
                            "disposition");
            for (const auto &value : page["entries"].toArray()) {
                dispositionCheck();
                const auto item = value.toObject();
                const auto entry = manifest.entry(++after);
                const auto expected = entry.publicInfo();
                for (auto field = expected.begin(); field != expected.end(); ++field)
                    if (item[field.key()] != field.value())
                        throw Error(ExitCode::Integrity,
                                    QStringLiteral("上传接收证据与本地冻结条目不同"),
                                    "disposition");
                const bool skipped = item["disposition"] == "skipped";
                if ((!skipped && item["disposition"] != "copied") ||
                    (skipped && conflict != ConflictPolicy::Skip) ||
                    item["confirmedBytes"] != (skipped ? QJsonValue("0") : expected["bytes"]) ||
                    item["target"].toString().isEmpty())
                    throw Error(ExitCode::Integrity, QStringLiteral("上传条目尚无完整持久处置"),
                                "disposition");
                const auto skippedRoot = skipped ? next::decimal(item["skippedRoot"], entry.id) : 0;
                outcomes.append(entry.id, item["target"].toString(), skipped ? "skipped" : "copied",
                                skippedRoot);
            }
            if (page["after"] != QString::number(after) ||
                page["more"] != QJsonValue(after < count))
                throw Error(ExitCode::Integrity, QStringLiteral("上传接收证据分页未覆盖冻结清单"),
                            "disposition");
            if (progress)
                progress(
                    {{"taskId", key},
                     {"event", "receipt-recovery"},
                     {"message",
                      QStringLiteral("正在核对已完成上传的接收确认 %1/%2").arg(after).arg(count)}});
        } while (after < count);
        return verifyCompletedSource(manifest, outcomes, dispositionCheck);
    };
    const auto historicalResult = [&](const QJsonObject &context) {
        // 日期：2026-11-06；本机缺失确认通过独立认证分页补齐，原连接保持到双方摘要确认结束。
        const auto disposition = recoverCompleted(context);
        if (!summaryProtocol)
            return context;
        confirmDisposition(channel_, correlation_, disposition);
        return completedTask(channel_, correlation_, id, requestId, "upload", share, relative,
                             manifest.summary(), conflict, accounting, disposition);
    };
    if (initial["state"] == "completed") {
        const auto result = historicalResult(initial);
        if (progress)
            progress(result);
        return result;
    }
    if (progress)
        progress(initial);
    if (!initial["needManifest"].isBool())
        throw Error(ExitCode::Config, QStringLiteral("上传清单协商字段无效"), "transfer");
    int admittedChannels = 0;
    if (queuedProtocol) {
        const auto admission = awaitAdmission(channel_, correlation_, id, channels, progress);
        admittedChannels = checkedChannels(admission["channels"]);
        if (admission["needManifest"] != initial["needManifest"])
            throw Error(ExitCode::Integrity, QStringLiteral("授信改变了清单交换约定"), "scheduler");
    }
    if (initial["needManifest"].toBool())
        sendStrongManifest(channel_, id, manifest, correlation_);
    auto ready = readyTask(channel_, correlation_, id, progress);
    if (checkedTask(ready, requestId, "upload", share, relative, conflict, accounting) != id)
        throw Error(ExitCode::Integrity, QStringLiteral("上传就绪任务身份不同"), "transfer");
    if (ready["state"] == "completed") {
        const auto result = historicalResult(ready);
        if (progress)
            progress(result);
        return result;
    }
    if (ready["state"] != "transferring" || ready["manifestInfo"].toObject() != manifest.summary())
        throw Error(ExitCode::Integrity, QStringLiteral("上传就绪清单不同"), "transfer");
    if (progress)
        progress(ready);
    const auto completed = [&](const StrongEntry &entry,
                               const DurableReceive::Preparation &result) {
        const auto &path = result.path;
        // 日期：2026-11-06；只有接收端已确认的最终名称才能记copied，写盘失败不得发布完成事件。
        outcomes.append(entry.id, path, result.skipped ? "skipped" : "copied", result.skippedRoot);
        // 日期：2026-11-04；逐文件事件仅含公开名称与最终相对名称，不含源绝对路径和凭据。
        if (progress)
            progress({{"taskId", id.toString(QUuid::WithoutBraces)},
                      {"event", result.skipped ? "file-skipped" : "file-completed"},
                      {"file", QString::number(entry.id)},
                      {"path", path},
                      {"bytes", QString::number(result.skipped ? 0 : entry.bytes)},
                      {"logicalBytes", QString::number(entry.bytes)}});
    };
    TransferProgress meter(channel_, correlation_, id,
                           QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1()),
                           manifest.summary()["bytes"].toString().toLongLong(), false, byteProgress,
                           progress, accounting,
                           next::decimal(manifest.summary()["entries"], 10000000));
    int actual = 1;
    if (channels > 1) {
        const auto ticket = control(channel_, correlation_, next::Type::ChannelTicket);
        ParallelTransfer data(
            ticket, id, QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1()),
            false, dispositions);
        actual = data.lanes();
        if (actual > channels || (admittedChannels && actual != admittedChannels))
            throw Error(ExitCode::Integrity, QStringLiteral("服务器通道数超过请求值"), "parallel");
        if (progress)
            progress({{"taskId", id.toString(QUuid::WithoutBraces)},
                      {"state", "transferring"},
                      {"channels", QString::number(actual)}});
        data.startClients(profile_, timeoutMs_, &manifest);
        data.sendTree(channel_, manifest, correlation_, {}, completed, dispositions);
    } else {
        sendStrongTree(channel_, id, manifest, correlation_, {}, completed, dispositions);
    }
    // 日期：2026-11-06；逐项接收确认必须完整，字节发送结束不能代替处置完整性。
    confirmingDisposition = true;
    const auto disposition = outcomes.summary(true, dispositionCheck);
    if (summaryProtocol)
        confirmDisposition(channel_, correlation_, disposition);
    auto result = completedTask(channel_, correlation_, id, requestId, "upload", share, relative,
                                manifest.summary(), conflict, accounting,
                                summaryProtocol ? disposition : QJsonObject{},
                                accounting ? meter.snapshot() : QJsonObject{});
    result["channels"] = QString::number(actual);
    return result;
}

// 日期：2026-11-06；明细核对任务计量版本及本机原请求契约，下载结果仍取本机日志。
QJsonObject RemoteClient::items(const QUuid &id, PrivateStore &local, quint64 after) {
    if (!capabilities_.contains("task-items-v1"))
        throw Error(ExitCode::Config, QStringLiteral("服务器未提供逐项查询，请先升级服务器"),
                    "items");
    if (id.isNull())
        throw Error(ExitCode::Config, QStringLiteral("任务明细UUID无效"), "items");
    const auto info = request(next::Type::TaskQuery, next::Type::TaskState,
                              {{"taskId", id.toString(QUuid::WithoutBraces)}, {"itemsInfo", true}});
    if (info["taskId"] != id.toString(QUuid::WithoutBraces))
        throw Error(ExitCode::Integrity, QStringLiteral("任务明细身份不同"), "items");
    TransferTask task;
    task.id = id;
    task.request = QUuid(info["requestId"].toString());
    task.direction = info["direction"].toString();
    task.share = info["share"].toString();
    task.relative = info["path"].toString();
    task.state = info["state"].toString();
    task.error = info["error"].toInt(-1);
    task.entries = next::decimal(info["entries"], 10000000);
    task.total = next::decimal(info["total"], std::numeric_limits<qint64>::max());
    task.manifest = QByteArray::fromHex(info["manifest"].toString().toLatin1());
    task.accountingRequired = info.contains("accountingVersion");
    task.conflict = info.contains("conflict") ? checkedConflictPolicy(info["conflict"].toString())
                                              : ConflictPolicy::Rename;
    checkedAccounting(info, task.accountingRequired, task.conflict);
    if (task.request.isNull() || task.error < 0 || task.error > 7 ||
        (task.direction != "upload" && task.direction != "download") ||
        (task.manifest.isEmpty() ? task.entries != 0 || task.total != 0
                                 : task.manifest.size() != 32) ||
        info["manifest"] != QString::fromLatin1(task.manifest.toHex()))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项查询任务字段无效"), "items");
    if (after > static_cast<quint64>(task.entries))
        throw Error(ExitCode::Config, QStringLiteral("任务明细起点无效"), "items");
    auto result = task.direction == "download"
                      ? localDownloadItems(local, server_, profile_.client, task, after)
                      : request(next::Type::TaskQuery, next::Type::TaskState,
                                {{"taskId", id.toString(QUuid::WithoutBraces)},
                                 {"itemsAfter", QString::number(after)}});
    const auto following = next::decimal(result["after"], task.entries);
    if (result["version"] != 1 || result["taskId"] != id.toString(QUuid::WithoutBraces) ||
        result["manifest"] != info["manifest"] || result["direction"] != task.direction ||
        result["conflict"] != conflictPolicyName(task.conflict) || !result["available"].isBool() ||
        !result["more"].isBool() || result["currentContentVerified"] != QJsonValue(false) ||
        !result["entries"].isArray() || result["entries"].toArray().size() > 100 ||
        following < after || (result["more"].toBool() && following == after))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项查询分页响应无效"), "items");
    const bool failureFields =
        task.direction == "download" || capabilities_.contains("task-item-failures-v1") ||
        result.contains("failureEvidenceAvailable") || result.contains("failureScope");
    if (failureFields && (!result["failureEvidenceAvailable"].isBool() ||
                          result["failureScope"] != "receiver-local"))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项失败证据范围无效"), "items");
    quint64 previous = after;
    for (const auto &value : result["entries"].toArray()) {
        const auto entry = value.toObject();
        const auto sequence = next::decimal(entry["id"], task.entries);
        if (sequence != previous + 1)
            throw Error(ExitCode::Integrity, QStringLiteral("逐项查询序号不连续"), "items");
        validateTransferItem(entry, task.conflict, sequence);
        if (failureFields || entry.contains("lastFailure"))
            validateItemFailure(entry, result["failureEvidenceAvailable"].toBool());
        previous = sequence;
    }
    if (previous != following ||
        (result["available"] == QJsonValue(false) &&
         (!result["entries"].toArray().isEmpty() || result["more"].toBool())))
        throw Error(ExitCode::Integrity, QStringLiteral("逐项查询末尾游标不同"), "items");
    return result;
}

// 日期：2026-11-06；下载绑定持久计量契约，按十三字段进度核验本机落盘与最终任务。
QJsonObject RemoteClient::download(const QUuid &requestId, const QString &share,
                                   const QString &relative, PrivateStore &local,
                                   const QString &destination,
                                   const std::function<void(const QJsonObject &)> &progress,
                                   int channels, ConflictPolicy conflict) {
    checkedChannels(QString::number(channels));
    checkedConflictPolicy(conflictPolicyName(conflict));
    // 日期：2026-11-06；skip独立协商逐项处置，其余策略保持已有交换契约。
    const bool dispositions = conflict == ConflictPolicy::Skip;
    if ((conflict == ConflictPolicy::Fail && !capabilities_.contains("conflict-fail-v1")) ||
        (conflict == ConflictPolicy::Overwrite &&
         !capabilities_.contains("conflict-overwrite-v1")) ||
        (conflict == ConflictPolicy::Skip && (!capabilities_.contains("conflict-skip-v1") ||
                                              !capabilities_.contains("disposition-summary-v1") ||
                                              !capabilities_.contains("disposition-progress-v1") ||
                                              !capabilities_.contains("byte-progress-v1"))))
        throw Error(ExitCode::Config, QStringLiteral("服务器未协商所选冲突策略能力"), "conflict");
    if (!QFileInfo(destination).isDir())
        throw Error(ExitCode::Config, QStringLiteral("下载目标目录必须已存在"), "transfer");
    const auto requestKey = requestId.toString(QUuid::WithoutBraces);
    QLockFile requestLock(local.directory() + "/download-request-" + requestKey + ".lock");
    requestLock.setStaleLockTime(0);
    if (!requestLock.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("本地同一下载请求正在执行"), "transfer");
    const auto bindingName = "download-request-" + requestKey + ".json";
    QJsonObject bindingInfo{{"version", 1},
                            {"server", server_.toString(QUuid::WithoutBraces)},
                            {"client", profile_.client.toString(QUuid::WithoutBraces)},
                            {"share", share},
                            {"path", relative},
                            {"root", QFileInfo(destination).absoluteFilePath()}};
    if (conflict != ConflictPolicy::Rename) {
        bindingInfo["version"] = 2;
        bindingInfo["conflict"] = conflictPolicyName(conflict);
    }
    const bool accounting = bindAccounting(local, bindingName, bindingInfo, conflict,
                                           capabilities_.contains("disposition-progress-v1") &&
                                               capabilities_.contains("byte-progress-v1") &&
                                               capabilities_.contains("disposition-summary-v1"));
    QJsonObject create{{"requestId", requestId.toString(QUuid::WithoutBraces)},
                       {"share", share},
                       {"path", relative}};
    if (conflict != ConflictPolicy::Rename)
        create["conflict"] = conflictPolicyName(conflict);
    const bool summaryProtocol = capabilities_.contains("disposition-summary-v1");
    if (summaryProtocol)
        create["dispositionSummary"] = true;
    const bool queuedProtocol = capabilities_.contains("task-admission-v1");
    if (queuedProtocol)
        create["queue"] = true;
    const bool byteProgress = capabilities_.contains("byte-progress-v1");
    if (byteProgress)
        create["byteProgress"] = true;
    if (accounting)
        create["dispositionProgress"] = true;
    if (channels > 1) {
        if (!capabilities_.contains("parallel-transfer-v1"))
            throw Error(ExitCode::Config, QStringLiteral("服务器未协商多通道能力"), "parallel");
        create["channels"] = QString::number(channels);
    }
    bool confirmingDisposition = false;
    QElapsedTimer dispositionHeartbeat;
    dispositionHeartbeat.start();
    const auto dispositionCheck = [&]() {
        // 日期：2026-11-06；本地日志工作仍响应取消；最终帧可已缓存在断开的连接中，连接状态交给协议读取验证。
        QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
        if (summaryProtocol && confirmingDisposition && dispositionHeartbeat.elapsed() >= 250) {
            channel_.write(next::Type::TaskState, correlation_, {{"state", "busy"}});
            dispositionHeartbeat.restart();
        }
        if (cancel_ && cancel_->load())
            throw Error(ExitCode::Cancelled, QStringLiteral("本地处置校验已取消"), "disposition");
    };
    const auto initial = request(next::Type::CreateDownload, next::Type::Task, create);
    const auto id =
        checkedTask(initial, requestId, "download", share, relative, conflict, accounting);
    const auto historicalResult = [&](const QJsonObject &context) {
        // 日期：2026-11-06；先重验本机历史接收，再完成本连接的双向摘要确认，不依赖历史终态直接成功。
        confirmingDisposition = true;
        if (summaryProtocol && context["confirmationRequired"] != QJsonValue(true))
            throw Error(ExitCode::Integrity, QStringLiteral("历史任务未要求本次处置确认"),
                        "disposition");
        if (!summaryProtocol)
            close();
        const auto disposition =
            verifyLocalDownload(local, id, destination, context, cancel_, conflict,
                                summaryProtocol ? dispositionCheck : std::function<void()>{});
        if (!summaryProtocol)
            return context;
        confirmDisposition(channel_, correlation_, disposition);
        const auto value =
            completedTask(channel_, correlation_, id, requestId, "download", share, relative,
                          {{"sha256", context["manifest"]},
                           {"bytes", context["total"]},
                           {"entries", context["entries"]}},
                          conflict, accounting, disposition);
        return value;
    };
    if (initial["state"] == "completed") {
        const auto result = historicalResult(initial);
        if (progress)
            progress(result);
        return result;
    }
    if (progress)
        progress(initial);
    int admittedChannels = 0;
    if (queuedProtocol) {
        const auto admission = awaitAdmission(channel_, correlation_, id, channels, progress);
        admittedChannels = checkedChannels(admission["channels"]);
        if (admission["needManifest"] != initial["needManifest"])
            throw Error(ExitCode::Integrity, QStringLiteral("授信改变了清单交换约定"), "scheduler");
    }
    auto ready = readyTask(channel_, correlation_, id, progress);
    if (checkedTask(ready, requestId, "download", share, relative, conflict, accounting) != id)
        throw Error(ExitCode::Integrity, QStringLiteral("下载就绪任务身份不同"), "transfer");
    if (ready["state"] == "completed") {
        const auto result = historicalResult(ready);
        if (progress)
            progress(result);
        return result;
    }
    if (ready["state"] != "transferring" || !ready["manifestInfo"].isObject())
        throw Error(ExitCode::Config, QStringLiteral("下载就绪状态无效"), "transfer");
    const auto summary = ready["manifestInfo"].toObject();
    const auto expected = QByteArray::fromHex(summary["sha256"].toString().toLatin1());
    const auto key = id.toString(QUuid::WithoutBraces);
    const auto manifestName = "download-" + key + ".sqlite";
    // 日期：2026-11-04；同一任务文件日志有自己的执行锁，导入清单重试先取得独立会话锁。
    QLockFile session(local.directory() + "/download-" + key + ".lock");
    session.setStaleLockTime(0);
    if (!session.tryLock(0))
        throw Error(ExitCode::Permission, QStringLiteral("本地已有同一下载任务执行者"), "transfer");
    for (const auto &name : {manifestName, manifestName + "-journal"})
        if (local.exists(name))
            local.remove(name);
    StrongManifest manifest(local, manifestName, true);
    receiveStrongManifest(channel_, id, manifest, expected, correlation_);
    if (manifest.summary() != summary)
        throw Error(ExitCode::Integrity, QStringLiteral("下载强清单总计不同"), "transfer");
    if (progress)
        progress(ready);
    DurableReceive receiver(local, "receive-" + key + ".sqlite", id, manifest, destination,
                            conflict);
    // 日期：2026-11-06；本地接收结果先持久化再发布事件；缓存授信及分页不随文件数增长。
    DispositionJournal outcomes(local, "disposition-" + key + ".sqlite", id, manifest,
                                conflictPolicyName(conflict), dispositionCheck);
    const auto completed = [&](const StrongEntry &entry,
                               const DurableReceive::Preparation &result) {
        const auto &path = result.path;
        // 日期：2026-11-06；最终处置按实际复制或跳过持久化，跳过目录保留整棵子树的根身份。
        outcomes.append(entry.id, path, result.skipped ? "skipped" : "copied", result.skippedRoot);
        // 日期：2026-11-04；事件逐条输出，十万文件不会累积成内存中的结果数组。
        if (progress)
            progress({{"taskId", key},
                      {"event", result.skipped ? "file-skipped" : "file-completed"},
                      {"file", QString::number(entry.id)},
                      {"path", path},
                      {"bytes", QString::number(result.skipped ? 0 : entry.bytes)},
                      {"logicalBytes", QString::number(entry.bytes)}});
    };
    TransferProgress meter(channel_, correlation_, id, expected,
                           summary["bytes"].toString().toLongLong(), true, byteProgress, progress,
                           accounting, next::decimal(summary["entries"], 10000000));
    int actual = 1;
    if (channels > 1) {
        const auto ticket = control(channel_, correlation_, next::Type::ChannelTicket);
        ParallelTransfer data(ticket, id, expected, true, dispositions);
        actual = data.lanes();
        if (actual > channels || (admittedChannels && actual != admittedChannels))
            throw Error(ExitCode::Integrity, QStringLiteral("服务器通道数超过请求值"), "parallel");
        if (progress)
            progress({{"taskId", id.toString(QUuid::WithoutBraces)},
                      {"state", "transferring"},
                      {"channels", QString::number(actual)}});
        data.startClients(profile_, timeoutMs_);
        data.receiveTree(channel_, manifest, receiver, correlation_, {}, completed, &meter,
                         dispositions);
    } else {
        receiveStrongTree(channel_, id, manifest, receiver, correlation_, {}, completed, &meter,
                          dispositions);
    }
    // 日期：2026-11-06；本地全部处置完整且匹配冻结清单，才接受远端任务完成为本次成功。
    confirmingDisposition = true;
    const auto disposition = outcomes.summary(true, dispositionCheck);
    if (summaryProtocol)
        confirmDisposition(channel_, correlation_, disposition);
    auto result = completedTask(channel_, correlation_, id, requestId, "download", share, relative,
                                manifest.summary(), conflict, accounting,
                                summaryProtocol ? disposition : QJsonObject{},
                                accounting ? meter.snapshot() : QJsonObject{});
    result["channels"] = QString::number(actual);
    return result;
}
} // namespace dukto

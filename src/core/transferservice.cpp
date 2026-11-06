#include "transferservice.h"
#include "dispositionjournal.h"
#include "error.h"
#include "fileexchange.h"
#include "files.h"
#include "paralleltransfer.h"
#include "shares.h"
#include "sourcefile.h"
#include "taskstore.h"
#include "transferitems.h"
#include "transferprogress.h"
#include "transferscheduler.h"
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonArray>
#include <QThread>
#include <limits>

namespace dukto {
namespace {
// 日期：2026-11-04；上传强身份必须为精确小写 SHA-256，fromHex 的宽松行为不能扩大输入集合。
QByteArray sha(const QJsonValue &value) {
    const auto bytes = QByteArray::fromHex(value.toString().toLatin1());
    if (!value.isString() || bytes.size() != 32 || value != QString::fromLatin1(bytes.toHex()))
        throw Error(ExitCode::Integrity, QStringLiteral("传输强清单身份无效"), "task");
    return bytes;
}

// 日期：2026-11-04；只有未绑定强身份的扫描任务可以重建导入库；执行租约保证没有其他使用者。
void resetUnbound(PrivateStore &store, const QString &name) {
    for (const auto &key : {name, name + "-journal"})
        if (store.exists(key))
            store.remove(key);
}
// 日期：2026-11-06；必需计量和独立逐项摘要必须一致；数字完整不能替代持久处置证明。
void checkDispositionAccounting(const TransferTask &task, const QJsonObject &summary) {
    if (!task.accountingRequired)
        return;
    if (task.accounting.isEmpty() || summary["complete"] != QJsonValue(true))
        throw Error(ExitCode::Integrity, QStringLiteral("任务缺少完整计量或处置证据"),
                    "completion");
    for (const auto &key : {"copiedBytes", "skippedBytes", "copiedFiles", "copiedDirectories",
                            "skippedFiles", "skippedDirectories"})
        if (task.accounting[key] != summary[key])
            throw Error(ExitCode::Integrity, QStringLiteral("任务计量与逐项处置不同"),
                        "completion");
}
} // namespace

// 日期：2026-11-05；控制请求重查授权与执行租约，崩溃遗留的排队/扫描也可归一为可恢复中断。
QJsonObject manageTransfer(PrivateStore &store, const Principal &principal,
                           const QJsonObject &request, next::Type type) {
    if (type == next::Type::TaskQuery && request.size() == 1 && request.contains("after")) {
        TaskStore tasks(store);
        auto result = tasks.page(
            principal.client, next::decimal(request["after"], std::numeric_limits<qint64>::max()));
        QJsonArray visible;
        for (const auto &value : result["tasks"].toArray()) {
            const auto task =
                tasks.task(principal.client, QUuid(value.toObject()["taskId"].toString()));
            try {
                const auto root = Shares(store).open(principal, task.share,
                                                     task.direction == "upload" ? Access::Upload
                                                                                : Access::Download);
                if (root->share().root == task.root)
                    visible.append(value);
            } catch (const Error &error) {
                if (error.code != ExitCode::Permission)
                    throw;
            }
        }
        result["tasks"] = visible;
        return result;
    }
    const bool items = type == next::Type::TaskQuery && request.contains("itemsAfter");
    const bool itemsInfo = type == next::Type::TaskQuery && request.contains("itemsInfo");
    const QUuid id(request["taskId"].toString());
    if (request.size() != (items || itemsInfo ? 2 : 1) ||
        (itemsInfo && request["itemsInfo"] != QJsonValue(true)) || id.isNull() ||
        request["taskId"] != id.toString(QUuid::WithoutBraces) ||
        (type != next::Type::TaskQuery && type != next::Type::Pause && type != next::Type::Cancel &&
         type != next::Type::Resume))
        throw Error(ExitCode::Config, QStringLiteral("任务控制字段或操作无效"), "task");
    TaskStore tasks(store);
    auto task = tasks.task(principal.client, id);
    const auto root = Shares(store).open(
        principal, task.share, task.direction == "upload" ? Access::Upload : Access::Download);
    if (root->share().root != task.root)
        throw Error(ExitCode::Permission, QStringLiteral("任务共享根已改配"), "task");
    if (itemsInfo)
        return task.publicInfo();
    if (items) {
        // 日期：2026-11-05；查询不取得执行锁或推进任务；授权仍在服务回包前再次核对。
        if (task.direction != "upload")
            throw Error(ExitCode::Config, QStringLiteral("下载结果须从客户端本地接收记录读取"),
                        "items");
        const auto after = next::decimal(request["itemsAfter"], std::numeric_limits<qint64>::max());
        return transferItems(store, task,
                             "manifest-" + id.toString(QUuid::WithoutBraces) + ".sqlite",
                             root->resolve(task.relative, false), after);
    }
    if (type == next::Type::Pause || type == next::Type::Cancel)
        task = tasks.requestStop(principal.client, id, type == next::Type::Pause);
    auto lease = tasks.tryAcquire(principal.client, id);
    if (lease) {
        task = tasks.task(principal.client, id);
        if (task.desired == "cancel") {
            if (task.state != "cancelling")
                task = tasks.advance(*lease, task.revision, "cancelling", task.processed);
            task = tasks.advance(*lease, task.revision, "cancelled", task.processed);
        } else if (task.desired == "pause" && task.state != "paused") {
            if (task.state != "pausing")
                task = tasks.advance(*lease, task.revision, "pausing", task.processed);
            task = tasks.advance(*lease, task.revision, "paused", task.processed);
        } else if (task.state == "transferring" || task.state == "checking" ||
                   task.state == "verifying" || task.state == "pausing" || task.state == "queued" ||
                   task.state == "scanning") {
            task = tasks.advance(*lease, task.revision, "interrupted", task.processed);
        }
    }
    if (type == next::Type::Resume) {
        if (!lease)
            throw Error(ExitCode::Permission,
                        QStringLiteral("任务仍有活动执行者，请等待停止后恢复"), "task");
        if (task.state == "paused" || task.state == "interrupted")
            task = tasks.advance(*lease, task.revision, "checking", 0);
        else if (task.state != "queued" && task.state != "scanning" && task.state != "committing")
            throw Error(ExitCode::Config, QStringLiteral("当前任务状态不能恢复"), "task");
    }
    auto result = task.publicInfo();
    result["executionActive"] = !lease;
    return result;
}

// 日期：2026-11-06；显式进度绑定必需计量并逐项核对；历史只读核验和旧协议兼容保持。
void serveTransfer(next::SecureChannel &channel, PrivateStore &store, const Principal &principal,
                   const std::function<Principal()> &reauthenticate, const QJsonObject &request,
                   next::Type type, quint64 correlation) {
    const bool upload = type == next::Type::CreateUpload;
    const bool parallel = request.contains("channels");
    const bool byteProgress = request.contains("byteProgress");
    const bool queuedProtocol = request.contains("queue");
    const bool explicitConflict = request.contains("conflict");
    const bool peerDisposition = request.contains("dispositionSummary");
    const bool dispositionProgress = request.contains("dispositionProgress");
    if (explicitConflict && request["conflict"] != QJsonValue("fail") &&
        request["conflict"] != QJsonValue("overwrite"))
        throw Error(ExitCode::Config, QStringLiteral("未协商或未知的冲突策略"), "conflict");
    const auto conflict = explicitConflict ? checkedConflictPolicy(request["conflict"].toString())
                                           : ConflictPolicy::Rename;
    const int channels = parallel ? checkedChannels(request["channels"]) : 1;
    if ((!upload && type != next::Type::CreateDownload) ||
        request.size() != (upload ? 4 : 3) + (parallel ? 1 : 0) + (byteProgress ? 1 : 0) +
                              (queuedProtocol ? 1 : 0) + (explicitConflict ? 1 : 0) +
                              (peerDisposition ? 1 : 0) + (dispositionProgress ? 1 : 0) ||
        (dispositionProgress && (request["dispositionProgress"] != QJsonValue(true) ||
                                 !peerDisposition || !byteProgress)) ||
        (peerDisposition && request["dispositionSummary"] != QJsonValue(true)) ||
        (queuedProtocol && request["queue"] != QJsonValue(true)) ||
        (byteProgress && request["byteProgress"] != QJsonValue(true)) ||
        !request["share"].isString() || !request["path"].isString() ||
        !request["requestId"].isString() || (upload && !request["manifest"].isObject()))
        throw Error(ExitCode::Config, QStringLiteral("创建传输任务字段无效"), "task");
    const QUuid requestId(request["requestId"].toString());
    if (requestId.isNull() || request["requestId"] != requestId.toString(QUuid::WithoutBraces))
        throw Error(ExitCode::Config, QStringLiteral("传输请求 UUID 无效"), "task");
    const auto share = request["share"].toString();
    const auto relative = request["path"].toString();
    const auto access = upload ? Access::Upload : Access::Download;
    auto root = Shares(store).open(principal, share, access);
    const auto selected = root->resolve(relative, false);
    if (upload && !QFileInfo(selected).isDir())
        throw Error(ExitCode::Config, QStringLiteral("上传目标必须为现有授权目录"), "task");
    TaskStore tasks(store, false);
    auto task = tasks.create(principal.client, requestId, upload ? "upload" : "download", share,
                             relative, root->share().root,
                             upload ? sha(request["manifest"].toObject()["sha256"]) : QByteArray(),
                             conflict, dispositionProgress);
    if (task.state == "failed" || task.state == "cancelled")
        throw Error(ExitCode::Config, QStringLiteral("任务已终止；需要新请求 ID 才能创建新传输"),
                    "task");
    auto lease = tasks.acquire(principal.client, task.id);
    const auto key = task.id.toString(QUuid::WithoutBraces);
    const auto manifestName = "manifest-" + key + ".sqlite";
    const bool historical = task.state == "completed" || task.state == "committing";
    QElapsedTimer authorization;
    QElapsedTimer heartbeat;
    authorization.start();
    heartbeat.start();
    bool scanning = !upload || !task.manifest.isEmpty();
    bool waiting = false;
    bool confirming = false;
    const auto work = [&]() {
        // 日期：2026-11-04；授权配置每 250ms 重查，固定根每片段核对；独立控制连接可写停止请求。
        channel.checkpoint("transfer");
        root->verify();
        if (authorization.elapsed() >= 250) {
            const auto current = reauthenticate();
            const auto currentRoot = Shares(store).open(current, share, access);
            if (currentRoot->share().root != task.root)
                throw Error(ExitCode::Permission, QStringLiteral("传输共享根已经改配"), "transfer");
            const auto status = tasks.task(principal.client, task.id);
            if (!status.desired.isEmpty())
                throw Error(ExitCode::Cancelled, QStringLiteral("传输已收到持久暂停或取消请求"),
                            "transfer");
            authorization.restart();
        }
        if ((scanning || waiting || confirming) && heartbeat.elapsed() >= 250) {
            if (confirming)
                channel.write(next::Type::TaskState, correlation, {{"state", "busy"}});
            else
                channel.write(next::Type::TaskState, correlation,
                              {{"taskId", key}, {"state", waiting ? "queued" : "scanning"}});
            heartbeat.restart();
        }
    };
    const auto confirmDisposition = [&](const QJsonObject &summary) {
        // 日期：2026-11-06；等待期间持续检查授权和停止；只接受同序号、全部字段精确相同的确认。
        confirming = true;
        channel.write(next::Type::DispositionSummary, correlation, summary);
        for (;;) {
            work();
            const auto frame = channel.read();
            work();
            const auto value = next::parseControl(frame.payload);
            if (frame.header.correlation != correlation)
                throw Error(ExitCode::Integrity, QStringLiteral("处置摘要确认序号不同"),
                            "disposition");
            if (frame.header.type == next::Type::TaskState &&
                value == QJsonObject{{"state", "busy"}})
                continue;
            if (frame.header.type != next::Type::DispositionAck || value != summary)
                throw Error(ExitCode::Integrity, QStringLiteral("收发两端处置摘要不同"),
                            "disposition");
            return;
        }
    };
    std::unique_ptr<StrongManifest> manifest;
    std::shared_ptr<TransferAdmission> admission;
    try {
        if (historical) {
            // 日期：2026-11-06；核验占用一个全局任务/通道额度，排队不改变原completed/committing记录。
            admission =
                std::make_shared<TransferAdmission>(TransferScheduler::global(), store.directory(),
                                                    principal.client, task.id, 1, queuedProtocol);
            auto initial = task.publicInfo();
            initial["state"] = queuedProtocol ? "queued" : "scanning";
            initial["needManifest"] = false;
            channel.write(next::Type::Task, correlation, initial);
            waiting = queuedProtocol;
            while (!admission->tryStart()) {
                work();
                QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
                QThread::msleep(25);
            }
            waiting = false;
            scanning = true;
            if (queuedProtocol)
                channel.write(next::Type::TaskAdmitted, correlation,
                              {{"taskId", key}, {"needManifest", false}, {"channels", "1"}});
            const auto authorize = [&]() {
                // 日期：2026-11-06；获准及结束均强制重查会话、共享根和停止意图，不依赖定时巡检。
                channel.checkpoint("completion");
                const auto currentRoot = Shares(store).open(reauthenticate(), share, access);
                root->verify();
                if (currentRoot->share().root != task.root ||
                    !tasks.task(principal.client, task.id).desired.isEmpty())
                    throw Error(ExitCode::Permission, QStringLiteral("历史任务核验授权已变化"),
                                "completion");
            };
            authorize();
            manifest.reset(new StrongManifest(store, manifestName, false, work));
            const auto summary = manifest->summary();
            if (summary["sha256"] != QString::fromLatin1(task.manifest.toHex()) ||
                summary["entries"] != QString::number(task.entries) ||
                summary["bytes"] != QString::number(task.total) ||
                (upload && summary != request["manifest"].toObject()))
                throw Error(ExitCode::Integrity, QStringLiteral("历史任务清单与原任务不同"),
                            "completion");
            const auto outcomeName = "disposition-" + key + ".sqlite";
            if (!store.exists(outcomeName))
                throw Error(ExitCode::Integrity, QStringLiteral("历史任务缺少逐项处置证据"),
                            "completion");
            DispositionJournal outcomes(store, outcomeName, task.id, *manifest,
                                        conflictPolicyName(task.conflict), work, true);
            const auto disposition = outcomes.summary(true, work);
            checkDispositionAccounting(task, disposition);
            if (upload) {
                DurableReceive::verifyCompleted(
                    store, "receive-" + key + ".sqlite", task.id, *manifest, selected,
                    task.conflict, work, [&](quint64 id, const QString &target) {
                        // 日期：2026-11-06；接收实际路径必须等于原处置名称，重命名结果不能退回原名。
                        const auto item = outcomes.item(id);
                        if (item["disposition"] != "copied" || item["path"] != target)
                            throw Error(ExitCode::Integrity, QStringLiteral("历史接收与处置不符"),
                                        "completion");
                    });
            } else {
                const auto count = next::decimal(summary["entries"], 10000000);
                const auto baseName = QFileInfo(selected).fileName();
                for (quint64 id = 1; id <= count; ++id) {
                    work();
                    const auto entry = manifest->entry(id);
                    if (entry.relative != baseName && !entry.relative.startsWith(baseName + '/'))
                        throw Error(ExitCode::Integrity, QStringLiteral("历史下载源映射不同"),
                                    "completion");
                    const auto suffix = entry.relative.mid(baseName.size());
                    const auto mapped = relative.isEmpty() ? suffix.mid(1) : relative + suffix;
                    const auto source = root->resolve(mapped, false);
                    if (QDir::cleanPath(entry.source) != QDir::cleanPath(source) ||
                        outcomes.item(id)["disposition"] != "copied")
                        throw Error(ExitCode::Integrity, QStringLiteral("历史下载路径或处置不同"),
                                    "completion");
                    if (entry.directory) {
                        if (!QFileInfo(source).isDir())
                            throw Error(ExitCode::Integrity, QStringLiteral("历史下载目录已变化"),
                                        "completion");
                        continue;
                    }
                    SourceFile input(source);
                    if (input.device().size() != entry.bytes)
                        throw Error(ExitCode::Integrity, QStringLiteral("历史下载源大小已变化"),
                                    "completion");
                    QCryptographicHash hash(QCryptographicHash::Sha256);
                    qint64 remaining = entry.bytes;
                    while (remaining > 0) {
                        work();
                        input.verify();
                        const auto bytes = input.device().read(qMin(remaining, BufferSize));
                        if (bytes.isEmpty())
                            throw Error(ExitCode::Disk, QStringLiteral("历史下载源重读失败"),
                                        "completion");
                        hash.addData(bytes);
                        remaining -= bytes.size();
                    }
                    input.verify();
                    if (hash.result() != entry.sha256)
                        throw Error(ExitCode::Integrity, QStringLiteral("历史下载源正文已变化"),
                                    "completion");
                }
            }
            authorize();
            task = tasks.task(principal.client, task.id);
            if (task.state == "committing")
                task = tasks.advance(*lease, task.revision, "completed", task.total);
            if (peerDisposition) {
                // 日期：2026-11-06；此首帧只报告已核验历史，客户端须补齐本机证据并完成本连接双向确认。
                auto context = task.publicInfo();
                context["confirmationRequired"] = true;
                channel.write(next::Type::TaskState, correlation, context);
                confirmDisposition(disposition);
                authorize();
                auto result = task.publicInfo();
                result["dispositionSummary"] = disposition;
                result["dispositionConfirmed"] = true;
                channel.write(next::Type::TaskState, correlation, result);
            } else {
                channel.write(next::Type::TaskState, correlation, task.publicInfo());
            }
            return;
        }
        // 日期：2026-11-05；旧执行者退出后的状态先恢复到
        // checking，再登记等待；暂停请求仍由原执行者确认。
        // 日期：2026-11-05；已暂停任务只能显式 Resume，重复创建不能在检查/重连竞态中清除停止意图。
        if (task.desired == "cancel" || task.desired == "pause" || task.state == "paused")
            throw Error(ExitCode::Cancelled, QStringLiteral("任务已停止；暂停任务请显式继续"),
                        "transfer");
        if (task.state == "transferring" || task.state == "verifying")
            task = tasks.advance(*lease, task.revision, "interrupted", task.processed);
        if (task.state == "paused" || task.state == "interrupted")
            task = tasks.advance(*lease, task.revision, "checking", 0);
        if (task.state != "queued")
            task = tasks.advance(*lease, task.revision, "queued", task.processed);
        admission = std::make_shared<TransferAdmission>(TransferScheduler::global(),
                                                        store.directory(), principal.client,
                                                        task.id, channels, queuedProtocol);
        if (queuedProtocol) {
            auto initial = task.publicInfo();
            initial["needManifest"] = upload && task.manifest.isEmpty();
            channel.write(next::Type::Task, correlation, initial);
        }
        waiting = queuedProtocol;
        while (!admission->tryStart()) {
            work();
            QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
            QThread::msleep(25);
        }
        waiting = false;
        // 日期：2026-11-05；获准后强制重查会话、共享与停止意图，不依赖上一次 250ms 巡检仍有效。
        const auto admittedRoot = Shares(store).open(reauthenticate(), share, access);
        task = tasks.task(principal.client, task.id);
        if (admittedRoot->share().root != task.root)
            throw Error(ExitCode::Permission, QStringLiteral("排队期间共享根已改配"), "transfer");
        if (!task.desired.isEmpty())
            throw Error(ExitCode::Cancelled, QStringLiteral("排队任务已请求停止"), "transfer");
        task = tasks.advance(*lease, task.revision,
                             task.manifest.isEmpty() ? "scanning" : "checking", 0);
        if (queuedProtocol)
            channel.write(next::Type::TaskAdmitted, correlation,
                          {{"taskId", key},
                           {"needManifest", upload && task.manifest.isEmpty()},
                           {"channels", QString::number(admission->lanes())}});
        else {
            auto initial = task.publicInfo();
            initial["needManifest"] = upload && task.manifest.isEmpty();
            channel.write(next::Type::Task, correlation, initial);
        }
        if (task.manifest.isEmpty()) {
            resetUnbound(store, manifestName);
            manifest.reset(new StrongManifest(store, manifestName, true));
            if (upload) {
                receiveStrongManifest(channel, task.id, *manifest,
                                      sha(request["manifest"].toObject()["sha256"]), correlation,
                                      work);
                if (manifest->summary() != request["manifest"].toObject())
                    throw Error(ExitCode::Integrity, QStringLiteral("上传清单总计与创建请求不同"),
                                "manifest");
            } else {
                manifest->scan({selected}, nullptr, work);
            }
            task = tasks.bindManifest(*lease, manifest->summary());
        } else {
            manifest.reset(new StrongManifest(store, manifestName, false, work));
            if (manifest->summary()["sha256"] != QString::fromLatin1(task.manifest.toHex()) ||
                (upload && manifest->summary() != request["manifest"].toObject()))
                throw Error(ExitCode::Integrity, QStringLiteral("持久任务清单与当前请求不同"),
                            "manifest");
        }
        scanning = false;
        work();
        // 日期：2026-11-04；长清单处理结束后强制重查授权，不能依赖最后一次周期检查仍然有效。
        const auto currentRoot = Shares(store).open(reauthenticate(), share, access);
        if (currentRoot->share().root != task.root)
            throw Error(ExitCode::Permission, QStringLiteral("任务授权根已变化"), "transfer");
        task = tasks.task(principal.client, task.id);
        if (!task.desired.isEmpty() && !(task.state == "paused" && task.desired == "pause"))
            throw Error(ExitCode::Cancelled, QStringLiteral("任务已请求停止"), "transfer");
        if (task.state == "paused" || task.state == "interrupted" || task.state == "transferring" ||
            task.state == "checking" || task.state == "verifying") {
            if (task.state == "transferring" || task.state == "verifying")
                task = tasks.advance(*lease, task.revision, "interrupted", task.processed);
            task = tasks.advance(*lease, task.revision, "checking", 0);
        }
        task = tasks.advance(*lease, task.revision, "transferring", 0);
        auto ready = task.publicInfo();
        ready["manifestInfo"] = manifest->summary();
        std::unique_ptr<ParallelTransfer> data;
        channel.write(next::Type::Task, correlation, ready);
        if (!upload)
            sendStrongManifest(channel, task.id, *manifest, correlation, work);
        if (parallel) {
            // 日期：2026-11-04；清单交换完再发短期票据，十万项清单不能消耗数据连接加入期限。
            data = ParallelTransfer::createServer(store.directory(), principal.client, task.id,
                                                  *manifest, upload, admission->lanes(), admission);
            channel.write(next::Type::ChannelTicket, correlation, data->ticket());
        }
        // 日期：2026-11-06；单/多通道实际完成按清单顺序持久化，未完成或失败项不能补成copied。
        DispositionJournal outcomes(store, "disposition-" + key + ".sqlite", task.id, *manifest,
                                    conflictPolicyName(task.conflict), work);
        qint64 processed = 0;
        qint64 completedBytes = 0;
        const auto record = [&](qint64 confirmed) {
            // 日期：2026-11-05；只记新增同步字节；空文件和重复快照不重复写任务汇总，文件/块同步仍由接收日志保证。
            if (confirmed <= processed)
                return;
            processed = confirmed;
            const auto current = tasks.task(principal.client, task.id);
            task = tasks.advance(*lease, current.revision, "transferring", processed);
        };
        TransferProgress meter(
            channel, correlation, task.id, task.manifest, task.total, upload, byteProgress,
            [&](const QJsonObject &value) {
                // 日期：2026-11-06；只在已验证进度回调持久化固定十字段，空条目也参与任务修订。
                if (!dispositionProgress) {
                    record(value["bytes"].toString().toLongLong());
                    return;
                }
                QJsonObject snapshot{{"bytes", value["receivedBytes"]},
                                     {"confirmed", value["confirmedBytes"]},
                                     {"restored", value["restoredBytes"]}};
                for (const auto &key :
                     {"copiedBytes", "skippedBytes", "discardedBytes", "copiedFiles",
                      "copiedDirectories", "skippedFiles", "skippedDirectories"})
                    snapshot[key] = value[key];
                const auto current = tasks.task(principal.client, task.id);
                if (current.accounting != snapshot)
                    task = tasks.recordAccounting(*lease, current.revision, snapshot);
                else
                    task = current;
                processed = task.processed;
            },
            dispositionProgress, static_cast<quint64>(task.entries));
        const auto completed = [&](const StrongEntry &entry,
                                   const DurableReceive::Preparation &result) {
            const auto &path = result.path;
            // 日期：2026-11-06；当前公开三种策略均为copied；skip仍拒绝，后续须协商显式处置。
            outcomes.append(entry.id, path, result.skipped ? "skipped" : "copied",
                            result.skippedRoot);
            // 日期：2026-11-05；文件完成与跨文件已确认块取较大值，避免多文件窗口完成时进度回退。
            completedBytes += result.skipped ? 0 : entry.bytes;
            if (!dispositionProgress)
                record(completedBytes);
        };
        if (upload) {
            DurableReceive receiver(store, "receive-" + key + ".sqlite", task.id, *manifest,
                                    selected, task.conflict);
            if (data)
                data->receiveTree(channel, *manifest, receiver, correlation, work, completed,
                                  &meter);
            else
                receiveStrongTree(channel, task.id, *manifest, receiver, correlation, work,
                                  completed, &meter);
        } else {
            if (data)
                data->sendTree(channel, *manifest, correlation, work, completed);
            else
                sendStrongTree(channel, task.id, *manifest, correlation, work, completed);
        }
        // 日期：2026-11-06；最终任务状态之前完整重验，不能用字节进度相等代替逐项完成。
        confirming = peerDisposition;
        const auto disposition = outcomes.summary(true, work);
        work();
        const auto latest = tasks.task(principal.client, task.id);
        checkDispositionAccounting(latest, disposition);
        task = tasks.advance(*lease, latest.revision, "verifying", processed);
        if (peerDisposition)
            confirmDisposition(disposition);
        // 日期：2026-11-06；确认等待结束强制重新认证，不能让忙心跳或刚失效的权限越过完成边界。
        const auto completionRoot = Shares(store).open(reauthenticate(), share, access);
        root->verify();
        if (completionRoot->share().root != task.root ||
            !tasks.task(principal.client, task.id).desired.isEmpty())
            throw Error(ExitCode::Permission, QStringLiteral("处置确认后任务授权已变化"),
                        "completion");
        task = tasks.advance(*lease, task.revision, "committing", processed);
        task = tasks.advance(*lease, task.revision, "completed", processed);
        auto result = task.publicInfo();
        if (peerDisposition) {
            result["dispositionSummary"] = disposition;
            result["dispositionConfirmed"] = true;
        }
        channel.write(next::Type::TaskState, correlation, result);
    } catch (const Error &error) {
        // 日期：2026-11-06；共享占用耗尽短等待仍保留检查点；显式恢复重验同一临时文件，完整性失败仍终止。
        const auto current = tasks.task(principal.client, task.id);
        if (current.state != "completed" && current.state != "committing" &&
            current.state != "failed" && current.state != "cancelled") {
            if (current.desired == "cancel") {
                task = tasks.advance(*lease, current.revision, "cancelling", current.processed);
                tasks.advance(*lease, task.revision, "cancelled", task.processed);
            } else if (current.desired == "pause") {
                // 日期：2026-11-05；重复创建被拒绝时已是 paused，不能再做非法 paused→pausing 转换。
                if (current.state != "paused") {
                    task = tasks.advance(*lease, current.revision, "pausing", current.processed);
                    tasks.advance(*lease, task.revision, "paused", task.processed);
                }
            } else if (error.code == ExitCode::Network || error.code == ExitCode::Cancelled ||
                       error.code == ExitCode::Config ||
                       (error.code == ExitCode::Disk && error.stage == "commit-busy") ||
                       (error.code == ExitCode::Permission &&
                        (error.stage == "auth" || error.stage == "session" ||
                         error.stage == "scheduler"))) {
                if (current.state == "transferring" || current.state == "checking" ||
                    current.state == "verifying" || current.state == "queued" ||
                    current.state == "scanning")
                    tasks.advance(*lease, current.revision, "interrupted", current.processed);
            } else {
                tasks.advance(*lease, current.revision, "failed", current.processed,
                              static_cast<int>(error.code), error.message.left(200));
            }
        }
        throw;
    }
}
} // namespace dukto

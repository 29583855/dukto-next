#include "transferoperation.h"
#include "service.h"
#include <QCoreApplication>
#include <QEventLoop>
#include <QRegularExpression>
#include <algorithm>

namespace dukto {
// 日期：2026-11-05；拒绝符号、空白、小数、重复选项拼接及超范围值，三平台采用相同契约。
TransferPolicy checkedTransferPolicy(const QString &retries, const QString &deadlineSeconds) {
    static const QRegularExpression decimal("\\A(?:0|[1-9][0-9]*)\\z");
    bool retryOk = false;
    bool deadlineOk = false;
    const auto retryCount = retries.toInt(&retryOk);
    const auto seconds = deadlineSeconds.toInt(&deadlineOk);
    if (!decimal.match(retries).hasMatch() || !decimal.match(deadlineSeconds).hasMatch() ||
        !retryOk || !deadlineOk || retryCount < 0 || retryCount > 3 || seconds < 1 ||
        seconds > 604800)
        throw Error(ExitCode::Config,
                    QStringLiteral("重试须为 0..3 次，总时限须为 1..604800 秒的规范整数"),
                    "arguments");
    return {retryCount, seconds};
}

// 日期：2026-11-05；先验证再启动线程，调用方错误不能留下后台线程或越过时间范围。
TransferOperation::TransferOperation(TransferPolicy policy, const std::atomic_bool *cancel,
                                     std::function<void(const QJsonObject &)> progress)
    : policy_(checkedTransferPolicy(QString::number(policy.retries),
                                    QString::number(policy.deadlineSeconds))),
      cancel_(cancel), progress_(std::move(progress)),
      deadline_(std::chrono::steady_clock::now() + std::chrono::seconds(policy_.deadlineSeconds)),
      monitor_(&TransferOperation::monitor, this) {
}

// 日期：2026-11-05；线程不持有调用方取消指针超过本对象生命周期，析构必须 join。
TransferOperation::~TransferOperation() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        finished_ = true;
    }
    wake_.notify_all();
    monitor_.join();
}

// 日期：2026-11-05；统一原子标志既覆盖本地扫描，也覆盖无事件循环的工作线程。
const std::atomic_bool *TransferOperation::cancellation() const {
    return &stopped_;
}

// 日期：2026-11-05；底层因合成停止报取消时，在外层还原用户取消或固定总期限的原因。
void TransferOperation::check() const {
    if (cancel_ && cancel_->load())
        throw Error(ExitCode::Cancelled, QStringLiteral("传输操作已取消"), "transfer");
    if (std::chrono::steady_clock::now() >= deadline_)
        throw Error(ExitCode::Network, QStringLiteral("传输操作已达到总时限，检查点保留"),
                    "deadline");
}

// 日期：2026-11-05；初始尝试加最多三次重试，共享 250/500/1000ms 退避且不会因重新连接重置总预算。
QJsonObject TransferOperation::run(const std::function<QJsonObject()> &attempt) {
    for (;;) {
        check();
        try {
            auto result = attempt();
            if (result["state"] != "completed")
                check();
            return result;
        } catch (const Error &error) {
            check();
            if (error.code != ExitCode::Network || error.stage == "deadline" ||
                retried_ >= policy_.retries)
                throw;
            const auto delay = 250 * (1 << retried_++);
            if (progress_) {
                QJsonObject event{{"eventVersion", 1},
                                  {"event", "transfer-retrying"},
                                  {"state", "retrying"},
                                  {"retry", retried_},
                                  {"maxRetries", policy_.retries},
                                  {"delayMs", delay},
                                  {"code", static_cast<int>(error.code)},
                                  {"stage", error.stage},
                                  {"message", QStringLiteral("网络中断，%1ms 后进行第 %2/%3 次重试")
                                                  .arg(delay)
                                                  .arg(retried_)
                                                  .arg(policy_.retries)}};
                if (!request_.isNull())
                    event["requestId"] = request_.toString(QUuid::WithoutBraces);
                if (!task_.isNull())
                    event["taskId"] = task_.toString(QUuid::WithoutBraces);
                progress_(event);
            }
            wait(delay);
        }
    }
}

// 日期：2026-11-05；一项操作只允许绑定一次相同请求，查询阶段已消耗的重试预算保持不变。
void TransferOperation::bindRequest(const QUuid &request) {
    if (request.isNull() || (!request_.isNull() && request_ != request))
        throw Error(ExitCode::Integrity, QStringLiteral("传输操作请求身份发生变化"), "transfer");
    request_ = request;
}

// 日期：2026-11-05；任务身份来自核心已经核验的响应，不能把另一个任务的事件混入当前重试。
void TransferOperation::report(QJsonObject event) {
    if (event.contains("requestId") &&
        event["requestId"] != request_.toString(QUuid::WithoutBraces))
        throw Error(ExitCode::Integrity, QStringLiteral("传输进度请求身份不同"), "transfer");
    if (event.contains("taskId")) {
        const QUuid task(event["taskId"].toString());
        if (task.isNull() || event["taskId"] != task.toString(QUuid::WithoutBraces) ||
            (!task_.isNull() && task_ != task))
            throw Error(ExitCode::Integrity, QStringLiteral("传输进度任务身份不同"), "transfer");
        task_ = task;
    }
    event["eventVersion"] = 1;
    if (!event.contains("event"))
        event["event"] = "transfer-state";
    if (progress_)
        progress_(event);
}

// 日期：2026-11-05；断线可能先于远程停止响应，重连先查原任务，不能自动重跑已暂停/取消的任务。
void TransferOperation::resume(RemoteClient &remote, const QUuid &task) {
    if (retried_ && !task_.isNull()) {
        const auto previous = remote.manage(task_);
        const auto state = previous["state"].toString();
        if (previous["desired"] == "pause" || previous["desired"] == "cancel" ||
            state == "paused" || state == "pausing" || state == "cancelled" ||
            state == "cancelling")
            throw Error(ExitCode::Cancelled, QStringLiteral("原任务已请求暂停或取消，停止自动重试"),
                        "task");
    }
    if (!task.isNull() && remote.manage(task)["state"] != "completed")
        remote.manage(task, next::Type::Resume);
}

// 日期：2026-11-05；只忽略完成确认之后的传输/取消错误，格式及完整性错误仍然报告。
void TransferOperation::closeCompleted(RemoteClient &remote) {
    try {
        remote.close();
    } catch (const Error &error) {
        if (error.code != ExitCode::Network && error.code != ExitCode::Cancelled)
            throw;
    }
}

// 日期：2026-11-05；回调在原 Qt 线程运行，不把信号处理或 GUI 操作移入监视线程。
void TransferOperation::wait(int milliseconds) {
    const auto until = std::chrono::steady_clock::now() + std::chrono::milliseconds(milliseconds);
    while (std::chrono::steady_clock::now() < until) {
        check();
        QCoreApplication::processEvents(QEventLoop::AllEvents, 1);
        std::unique_lock<std::mutex> lock(mutex_);
        wake_.wait_until(lock, std::min(until, std::chrono::steady_clock::now() +
                                                   std::chrono::milliseconds(10)));
    }
    check();
}

// 日期：2026-11-05；每个活动操作仅一条监视线程；完成/取消/到期立即归还，不按文件或块创建线程。
void TransferOperation::monitor() {
    std::unique_lock<std::mutex> lock(mutex_);
    while (!finished_) {
        if ((cancel_ && cancel_->load()) || std::chrono::steady_clock::now() >= deadline_) {
            stopped_.store(true);
            wake_.notify_all();
            return;
        }
        wake_.wait_until(lock, std::min(deadline_, std::chrono::steady_clock::now() +
                                                       std::chrono::milliseconds(10)));
    }
}
} // namespace dukto

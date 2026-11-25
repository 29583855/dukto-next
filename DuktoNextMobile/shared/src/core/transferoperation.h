#pragma once

#include "error.h"
#include <QJsonObject>
#include <QUuid>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <thread>

namespace dukto {
class RemoteClient;
struct TransferPolicy {
    int retries = 0;
    int deadlineSeconds = 86400;
};
// 日期：2026-11-05；GUI/CLI 共用严格整数范围，不允许隐式无限重试或取消总期限。
TransferPolicy checkedTransferPolicy(const QString &retries, const QString &deadlineSeconds);

class TransferOperation final {
  public:
    // 日期：2026-11-05；单调总期限自构造开始，监视线程仅合并原子取消，不访问 Qt/磁盘对象。
    TransferOperation(TransferPolicy policy, const std::atomic_bool *cancel,
                      std::function<void(const QJsonObject &)> progress = {});
    // 日期：2026-11-05；唤醒并回收监视线程，正常快速任务不会等待剩余期限。
    ~TransferOperation();
    // 日期：2026-11-05；用于扫描及各控制/数据通道，生命周期覆盖整个操作和所有工作线程。
    const std::atomic_bool *cancellation() const;
    // 日期：2026-11-05；用户取消优先于总期限，期限固定使用网络码 3/deadline 且永不自动重试。
    void check() const;
    // 日期：2026-11-05；只重试网络错误，多个阶段共用同一重试计数和总预算；冻结输入由调用者持有。
    QJsonObject run(const std::function<QJsonObject()> &attempt);
    // 日期：2026-11-05；绑定本次冻结请求，重试事件始终指向同一任务，不依赖 GUI 残留选择。
    void bindRequest(const QUuid &request);
    // 日期：2026-11-05；只保存当前任务的固定大小身份并转发快照，使 GUI/CLI 重试状态一致。
    void report(QJsonObject event);
    // 日期：2026-11-05；重连先遵守远程暂停/取消；已完成原任务跳过 Resume，原请求继续幂等核验。
    void resume(RemoteClient &remote, const QUuid &task);
    // 日期：2026-11-05；持久完成确认优先于会话关闭；关闭断网/取消不撤销已经核验的成功。
    static void closeCompleted(RemoteClient &remote);

  private:
    // 日期：2026-11-05；小步退避仍处理当前线程信号，用户取消/总期限不会等到退避结束。
    void wait(int milliseconds);
    // 日期：2026-11-05；固定检查间隔观察原子取消，截止使用 steady_clock 防系统时间跳变。
    void monitor();
    TransferPolicy policy_;
    const std::atomic_bool *cancel_;
    std::function<void(const QJsonObject &)> progress_;
    const std::chrono::steady_clock::time_point deadline_;
    std::atomic_bool stopped_{false};
    std::mutex mutex_;
    std::condition_variable wake_;
    bool finished_ = false;
    int retried_ = 0;
    QUuid request_;
    QUuid task_;
    std::thread monitor_;
};
} // namespace dukto

#include "transferscheduler.h"
#include "error.h"
#include <algorithm>

namespace dukto {
// 日期：2026-11-05；小规模测试可缩小上界，生产默认 2 个活动任务、100 个等待项、16 个通道。
TransferScheduler::TransferScheduler(int tasks, int waiting, int lanes)
    : maximumTasks_(tasks), maximumWaiting_(waiting), maximumLanes_(lanes) {
    if (tasks < 1 || tasks > 2 || waiting < 1 || waiting > 100 || lanes < 1 || lanes > 16)
        throw Error(ExitCode::Config, QStringLiteral("任务调度器额度无效"), "scheduler");
}

// 日期：2026-11-05；函数静态对象在首次使用时线程安全初始化，不按客户端创建独立预算。
TransferScheduler &TransferScheduler::global() {
    static TransferScheduler value;
    return value;
}

// 日期：2026-11-05；所有计数在同一锁下采样，结果大小固定且不包含任务标识或秘密。
QJsonObject TransferScheduler::usage() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return {{"active", int(active_.size())},
            {"waiting", int(waiting_.size())},
            {"lanes", usedLanes_},
            {"maximumActive", maximumTasks_},
            {"maximumWaiting", maximumWaiting_},
            {"maximumLanes", maximumLanes_}};
}

// 日期：2026-11-05；先完成可失败的分配再发布新主体轮次，异常不会留下计数或队列残项。
void TransferScheduler::enqueue(TransferAdmission *entry) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (int(waiting_.size()) >= maximumWaiting_)
        throw Error(ExitCode::Permission, QStringLiteral("传输等待队列已满，请稍后重试原任务"),
                    "scheduler");
    const auto same = [&](const TransferAdmission *other) {
        // 日期：2026-11-05；不同服务目录可拥有相同 UUID，去重使用目录/主体/任务的完整绑定。
        return other->owner_ == entry->owner_ && other->task_ == entry->task_;
    };
    if (std::any_of(waiting_.begin(), waiting_.end(), same) ||
        std::any_of(active_.begin(), active_.end(), same))
        throw Error(ExitCode::Permission, QStringLiteral("同一传输任务已在执行或等待"),
                    "scheduler");
    waiting_.push_back(entry);
    try {
        if (std::find(turns_.begin(), turns_.end(), entry->owner_) == turns_.end())
            turns_.push_back(entry->owner_);
    } catch (...) {
        waiting_.pop_back();
        throw;
    }
}

// 日期：2026-11-05；主体轮转后同主体仍按提交顺序执行，较晚到达的不同主体无需排在大量同主体项之后。
bool TransferScheduler::start(TransferAdmission *entry) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (entry->lanes_)
        return true;
    if (int(active_.size()) >= maximumTasks_ || usedLanes_ >= maximumLanes_ || turns_.empty())
        return false;
    const auto selected =
        std::find_if(waiting_.begin(), waiting_.end(), [&](const TransferAdmission *item) {
            // 日期：2026-11-05；只有轮转队首主体的首个任务能获准，后来者不能绕过已经登记的任务。
            return item->owner_ == turns_.front();
        });
    if (selected == waiting_.end() || *selected != entry)
        return false;
    int lanes = entry->requested_;
    while (lanes > maximumLanes_ - usedLanes_)
        lanes /= 2;
    entry->lanes_ = lanes;
    usedLanes_ += lanes;
    active_.splice(active_.end(), waiting_, selected);
    const bool remaining =
        std::any_of(waiting_.begin(), waiting_.end(), [&](const TransferAdmission *item) {
            // 日期：2026-11-05；还有等待项才保留该主体轮次，避免空轮次阻塞其他主体。
            return item->owner_ == turns_.front();
        });
    if (remaining)
        turns_.splice(turns_.end(), turns_, turns_.begin());
    else
        turns_.pop_front();
    return true;
}

// 日期：2026-11-05；析构路径仅移除已存在节点，不分配内存；数据线程持有引用时不会提前释放。
void TransferScheduler::release(TransferAdmission *entry) noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto waiting = std::find(waiting_.begin(), waiting_.end(), entry);
    if (waiting != waiting_.end()) {
        waiting_.erase(waiting);
        const bool remaining =
            std::any_of(waiting_.begin(), waiting_.end(), [&](const TransferAdmission *item) {
                // 日期：2026-11-05；只检查该主体是否仍有等待项，活动项不占等待轮次。
                return item->owner_ == entry->owner_;
            });
        if (!remaining)
            turns_.remove(entry->owner_);
    }
    const auto active = std::find(active_.begin(), active_.end(), entry);
    if (active != active_.end()) {
        usedLanes_ -= entry->lanes_;
        active_.erase(active);
    }
    entry->lanes_ = 0;
}

// 日期：2026-11-05；参数核对在入队前完成；旧客户端不能等待时失败会主动撤销已登记的节点。
TransferAdmission::TransferAdmission(TransferScheduler &scheduler, const QString &directory,
                                     const QUuid &owner, const QUuid &task, int requested,
                                     bool canWait)
    : scheduler_(scheduler), owner_(directory + "\n" + owner.toString(QUuid::WithoutBraces)),
      task_(task), requested_(requested) {
    if (directory.isEmpty() || owner.isNull() || task.isNull() ||
        (requested != 1 && requested != 2 && requested != 4 && requested != 8 && requested != 16))
        throw Error(ExitCode::Config, QStringLiteral("任务调度参数无效"), "scheduler");
    scheduler_.enqueue(this);
    if (!canWait && !tryStart()) {
        scheduler_.release(this);
        throw Error(ExitCode::Permission,
                    QStringLiteral("传输资源繁忙，请稍后重试；升级客户端可自动排队等待"),
                    "scheduler");
    }
}

// 日期：2026-11-05；共享令牌最后释放时回收，无论正常完成、强制断开还是处理异常。
TransferAdmission::~TransferAdmission() {
    scheduler_.release(this);
}

// 日期：2026-11-05；只处理内存调度，调用方负责授权、任务租约和协议心跳。
bool TransferAdmission::tryStart() {
    return scheduler_.start(this);
}

// 日期：2026-11-05；获准以后档位固定，等待状态读取同一互斥锁，避免诊断线程的数据竞争。
int TransferAdmission::lanes() const {
    std::lock_guard<std::mutex> lock(scheduler_.mutex_);
    return lanes_;
}
} // namespace dukto

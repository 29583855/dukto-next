#pragma once

#include <QJsonObject>
#include <QString>
#include <QUuid>
#include <list>
#include <mutex>

namespace dukto {
class TransferAdmission;

class TransferScheduler final {
  public:
    // 日期：2026-11-05；任务数、等待数和数据通道由同一个调度器授信，测试可选更小边界。
    explicit TransferScheduler(int tasks = 2, int waiting = 100, int lanes = 16);
    // 日期：2026-11-05；本进程全部新版监听器共用一个有限队列，不因服务目录/主体而重复放大额度。
    static TransferScheduler &global();
    // 日期：2026-11-05；只提供本机固定大小的资源计数，不公开其他主体、任务或排队顺序。
    QJsonObject usage() const;

  private:
    friend class TransferAdmission;
    // 日期：2026-11-05；同主体 FIFO，不同主体进入轮转队列；超过等待额度或同任务重入明确拒绝。
    void enqueue(TransferAdmission *entry);
    // 日期：2026-11-05；只让轮到的主体取得实际可用档位，原子占用任务和数据通道额度。
    bool start(TransferAdmission *entry);
    // 日期：2026-11-05；RAII 退出精确移除等待/活动项并归还额度，绝不留下被取消主体的空轮次。
    void release(TransferAdmission *entry) noexcept;
    mutable std::mutex mutex_;
    std::list<TransferAdmission *> waiting_;
    std::list<TransferAdmission *> active_;
    std::list<QString> turns_;
    int maximumTasks_;
    int maximumWaiting_;
    int maximumLanes_;
    int usedLanes_ = 0;
};

class TransferAdmission final {
  public:
    // 日期：2026-11-05；只登记固定元数据，不分配正文；旧对端不支持等待时必须立即获准，否则可重试繁忙。
    TransferAdmission(TransferScheduler &scheduler, const QString &directory, const QUuid &owner,
                      const QUuid &task, int requested, bool canWait);
    // 日期：2026-11-05；最后一个持有者退出才归还资源，允许数据工作线程共同持有同一令牌。
    ~TransferAdmission();
    TransferAdmission(const TransferAdmission &) = delete;
    TransferAdmission &operator=(const TransferAdmission &) = delete;
    // 日期：2026-11-05；非阻塞尝试，调用方在两次尝试间处理 Qt 事件、取消、撤权和会话期限。
    bool tryStart();
    // 日期：2026-11-05；返回已获准的实际档位，等待时为零；请求值不会冒充已占用通道数。
    int lanes() const;

  private:
    friend class TransferScheduler;
    TransferScheduler &scheduler_;
    QString owner_;
    QUuid task_;
    int requested_;
    int lanes_ = 0;
};
} // namespace dukto

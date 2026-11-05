#pragma once

#include "securechannel.h"

namespace dukto {
class TransferProgress final {
  public:
    // 日期：2026-11-05；单个控制线程拥有进度计量，接收端发布实际字节，发送端只接受绑定后的报告。
    TransferProgress(next::SecureChannel &channel, quint64 correlation, const QUuid &task,
                     const QByteArray &manifest, qint64 total, bool receiver, bool enabled,
                     std::function<void(const QJsonObject &)> update = {});
    // 日期：2026-11-05；数据交换结束后移除观察者，后续任务不能吞掉上一任务的进度帧。
    ~TransferProgress();
    TransferProgress(const TransferProgress &) = delete;
    TransferProgress &operator=(const TransferProgress &) = delete;
    // 日期：2026-11-05；仅将本轮重新读取并校验过的恢复块加入累计值，不从历史数字推断有效数据。
    void restored(qint64 bytes);
    // 日期：2026-11-05；片段真实写入后计量，新增持久字节仅取接收日志已经同步的增量。
    void written(qint64 bytes, qint64 confirmed);
    // 日期：2026-11-05；通常每 250ms 发一条；树结束强制发布最终字节但不声明任务提交完成。
    void publish(bool force = false);
    // 日期：2026-11-05；供持久任务状态记录使用，未校验片段不能计入可恢复进度。
    qint64 confirmed() const;

  private:
    // 日期：2026-11-05；逐字段核对任务/清单/序号及单调有界计数，拒绝伪造、回退和额外字段。
    void accept(const next::Frame &frame);
    // 日期：2026-11-05；只保留一组计数和采样状态，速率排除恢复重读字节，剩余时间可未知。
    void notify();
    next::SecureChannel &channel_;
    quint64 correlation_;
    QUuid task_;
    QByteArray manifest_;
    qint64 total_;
    bool receiver_;
    bool enabled_;
    std::function<void(const QJsonObject &)> update_;
    qint64 bytes_ = 0;
    qint64 confirmed_ = 0;
    qint64 restored_ = 0;
    qint64 previousNetwork_ = 0;
    double speed_ = 0;
    QElapsedTimer throttle_;
    QElapsedTimer sample_;
};
} // namespace dukto

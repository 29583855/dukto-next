#pragma once

#include "securechannel.h"
#include "transferaccounting.h"

namespace dukto {
class TransferProgress final {
  public:
    // 日期：2026-11-06；绑定固定计量及可选显式处置扩展，发送端只接受身份/字段/单调验证后的报告。
    TransferProgress(next::SecureChannel &channel, quint64 correlation, const QUuid &task,
                     const QByteArray &manifest, qint64 total, bool receiver, bool enabled,
                     std::function<void(const QJsonObject &)> update = {},
                     bool dispositions = false, quint64 entries = 0);
    // 日期：2026-11-05；数据交换结束后移除观察者，后续任务不能吞掉上一任务的进度帧。
    ~TransferProgress();
    TransferProgress(const TransferProgress &) = delete;
    TransferProgress &operator=(const TransferProgress &) = delete;
    // 日期：2026-11-05；仅将本轮重新读取并校验过的恢复块加入累计值，不从历史数字推断有效数据。
    void restored(qint64 bytes);
    // 日期：2026-11-05；片段真实写入后计量，新增持久字节仅取接收日志已经同步的增量。
    void written(qint64 bytes, qint64 confirmed);
    // 日期：2026-11-06；显式处置模式逐项记录真实结果，跳过不计入复制；旧版复制模式无需调用。
    void settled(const StrongEntry &entry, bool skipped, bool receivedBody);
    // 日期：2026-11-05；通常每 250ms 发一条；树结束强制发布最终字节但不声明任务提交完成。
    void publish(bool force = false);
    // 日期：2026-11-06；返回已同步或显式跳过的逻辑处理量；实际同步及复制字节在扩展事件分别记录。
    qint64 confirmed() const;
    // 日期：2026-11-06；返回本轮已验证的固定十计数，完成回包须与此实际进度完全一致。
    QJsonObject snapshot() const;

  private:
    // 日期：2026-11-06；逐字段核对身份及单调守恒计数，旧六字段和扩展十三字段不得混用。
    void accept(const next::Frame &frame);
    // 日期：2026-11-06；只保留固定计数和采样状态，速率排除恢复/准备跳过，剩余时间可未知。
    void notify();
    next::SecureChannel &channel_;
    quint64 correlation_;
    QUuid task_;
    QByteArray manifest_;
    qint64 total_;
    bool receiver_;
    bool enabled_;
    std::function<void(const QJsonObject &)> update_;
    bool dispositions_;
    quint64 entries_;
    TransferAccounting accounting_;
    qint64 previousNetwork_ = 0;
    double speed_ = 0;
    QElapsedTimer throttle_;
    QElapsedTimer sample_;
};
} // namespace dukto

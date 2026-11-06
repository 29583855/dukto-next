#pragma once

#include "strongmanifest.h"

namespace dukto {
// 固定大小计量，不保存逐文件集合；真实处置仍由接收日志及强清单验证。
class TransferAccounting final {
  public:
    // 日期：2026-11-06；绑定总字节和条目上限；entries为零仅供旧版纯字节进度使用。
    explicit TransferAccounting(qint64 total, quint64 entries = 0);
    // 日期：2026-11-06；恢复字节必须已重新读取并验证，不能将先前收到的网络字节重新归为恢复。
    void restored(qint64 bytes);
    // 日期：2026-11-06；记录真实接收及同步增量，所有运算先核对剩余额度，避免有符号溢出。
    void written(qint64 bytes, qint64 confirmed);
    // 日期：2026-11-06；按清单顺序归结处置；晚期跳过单列已传输但未复制的丢弃字节。
    void settled(const StrongEntry &entry, bool skipped, bool receivedBody);
    // 日期：2026-11-06；严格接收十个规范十进制计数，逐项及网络增量均须单调，失败保持旧快照。
    void accept(const QJsonObject &value);
    // 日期：2026-11-06；返回固定十字段快照，不含身份、路径或随文件数增长的数据。
    QJsonObject snapshot() const;
    // 日期：2026-11-06；逻辑处理进度等于同步字节加跳过字节减晚期丢弃，不将跳过计入复制。
    qint64 handled() const;
    // 日期：2026-11-06；返回本次实际接收及恢复重读的累计字节。
    qint64 received() const;
    // 日期：2026-11-06；返回已同步的实际数据量，包含晚期裁决为跳过的正文。
    qint64 confirmed() const;
    // 日期：2026-11-06；返回本轮重读且已校验的恢复数据量，用于排除网络速率分子。
    qint64 restoredBytes() const;
    // 日期：2026-11-06；返回尚未到达的逻辑字节，已跳过及晚期丢弃不会重复减少剩余量。
    qint64 remaining() const;

  private:
    // 日期：2026-11-06；校验字节守恒、条目上限及最终完整性，不使用可能溢出的直接求和。
    void validate() const;
    qint64 total_;
    quint64 entries_;
    qint64 bytes_ = 0;
    qint64 confirmed_ = 0;
    qint64 restored_ = 0;
    qint64 copied_ = 0;
    qint64 skipped_ = 0;
    qint64 discarded_ = 0;
    quint64 copiedFiles_ = 0;
    quint64 copiedDirectories_ = 0;
    quint64 skippedFiles_ = 0;
    quint64 skippedDirectories_ = 0;
};
} // namespace dukto

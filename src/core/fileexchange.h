#pragma once

#include "durablereceive.h"
#include "securechannel.h"

namespace dukto {
class TransferProgress;
// 日期：2026-11-04；按有界页交换公开强清单，源绝对路径始终留在发送方本地数据库。
void sendStrongManifest(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                        quint64 correlation, const std::function<void()> &check = {});
// 日期：2026-11-04；导入不可信分页后重算冻结身份，总计和 SHA 全部一致才发布有效清单。
void receiveStrongManifest(next::SecureChannel &channel, const QUuid &task,
                           StrongManifest &manifest, const QByteArray &expected,
                           quint64 correlation, const std::function<void()> &check = {});
// 日期：2026-11-04；按磁盘清单逐项发送目录/文件，结果逐项回调，不在内存累计整棵目录树。
void sendStrongTree(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                    quint64 correlation, const std::function<void()> &check = {},
                    const std::function<void(const StrongEntry &,
                                             const DurableReceive::Preparation &)> &completed = {},
                    bool dispositions = false);
// 日期：2026-11-05；逐项预约目录和恢复文件，空目录也必须收到显式确认。
void receiveStrongTree(
    next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
    DurableReceive &receiver, quint64 correlation, const std::function<void()> &check = {},
    const std::function<void(const StrongEntry &, const DurableReceive::Preparation &)> &completed =
        {},
    TransferProgress *progress = nullptr, bool dispositions = false);
// 日期：2026-11-04；在已认证并绑定任务的 TLS 会话中发送单文件，按接收端已重读确认的块恢复。
QString sendStrongFile(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                       quint64 file, quint64 correlation, const std::function<void()> &check = {},
                       bool dispositions = false, DurableReceive::Preparation *outcome = nullptr);
// 日期：2026-11-05；在已认证 TLS 会话中接收已知清单文件，摘要、同步和最终确认共用持久日志。
QString receiveStrongFile(next::SecureChannel &channel, const QUuid &task, StrongManifest &manifest,
                          DurableReceive &receiver, quint64 file, const QString &destination,
                          quint64 correlation, const std::function<void()> &check = {},
                          TransferProgress *progress = nullptr, bool dispositions = false,
                          DurableReceive::Preparation *outcome = nullptr);
} // namespace dukto

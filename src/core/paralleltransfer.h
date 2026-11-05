#pragma once

#include "durablereceive.h"
#include "securechannel.h"
#include <QThread>
#include <memory>

namespace dukto {
struct ClientProfile;
struct Principal;
struct ParallelState;
class TransferProgress;
class TransferAdmission;

class ParallelTransfer final {
  public:
    // 日期：2026-11-05；共享调度令牌覆盖数据线程完整寿命，最多共享 16 个实际数据工作槽。
    static std::unique_ptr<ParallelTransfer>
    createServer(const QString &state, const QUuid &owner, const QUuid &task,
                 StrongManifest &manifest, bool receiver, int requested,
                 const std::shared_ptr<TransferAdmission> &admission);
    // 日期：2026-11-04；客户端仅接受绑定当前任务和清单的严格票据，不从任务历史重用临时令牌。
    ParallelTransfer(const QJsonObject &ticket, const QUuid &task, const QByteArray &manifest,
                     bool receiver);
    // 日期：2026-11-04；任何退出路径先取消所有本地通道，再等待线程归还缓冲、socket 和 SQLite。
    ~ParallelTransfer();
    ParallelTransfer(const ParallelTransfer &) = delete;
    ParallelTransfer &operator=(const ParallelTransfer &) = delete;
    // 日期：2026-11-04；票据仅通过当前认证 TLS 返回；禁止把该对象作为进度事件或日志输出。
    QJsonObject ticket() const;
    // 日期：2026-11-04；返回协商后的实际数据通道数，资源不足时可能小于用户请求值。
    int lanes() const;
    // 日期：2026-11-04；客户端每条数据连接独立 TLS/认证，socket 和清单均在对应线程创建。
    void startClients(const ClientProfile &profile, int timeoutMs,
                      StrongManifest *sender = nullptr);
    // 日期：2026-11-04；文件元数据走控制连接，块任务由接收端分配到独立数据线程。
    void sendTree(next::SecureChannel &control, StrongManifest &manifest, quint64 correlation,
                  const std::function<void()> &check = {},
                  const std::function<void(const StrongEntry &, const QString &)> &completed = {});
    // 日期：2026-11-05；接收日志仅在当前控制线程访问，数据线程通过每通道一个片段槽交付。
    void
    receiveTree(next::SecureChannel &control, StrongManifest &manifest, DurableReceive &receiver,
                quint64 correlation, const std::function<void()> &check = {},
                const std::function<void(const StrongEntry &, const QString &)> &completed = {},
                TransferProgress *progress = nullptr);
    // 日期：2026-11-04；客户端已经完成 TLS/认证后进入专用数据循环，不与控制 socket 跨线程共享。
    static void clientLane(next::SecureChannel &channel, const QJsonObject &ticket, int lane,
                           const std::shared_ptr<ParallelState> &state,
                           const QPair<QString, QString> &source, quint64 correlation);

  private:
    // 日期：2026-11-04；服务侧包装对象拥有会话生命周期，注册表仅保存弱引用以免累积任务。
    explicit ParallelTransfer(std::shared_ptr<ParallelState> state);
    std::shared_ptr<ParallelState> state_;
    QList<QThread *> workers_;
};

// 日期：2026-11-04；认证后的数据连接只可加入同主体、未过期且仍活动的唯一任务票据。
void serveParallelLane(next::SecureChannel &channel, PrivateStore &store,
                       const Principal &principal, const std::function<Principal()> &reauthenticate,
                       const QJsonObject &request, quint64 correlation);
// 日期：2026-11-04；并发档位固定为 1/2/4/8/16，非法值不得静默改成单线程。
int checkedChannels(const QJsonValue &value);
} // namespace dukto

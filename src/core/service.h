#pragma once

#include "auth.h"
#include "files.h"
#include "identity.h"
#include "securechannel.h"
#include <QSet>
#include <QTcpServer>
#include <QThread>
#include <atomic>

namespace dukto {
class StrongManifest;
struct ParallelState;
struct ClientProfile {
    QString alias;
    QString host;
    quint16 port = 4646;
    QString peerName;
    QByteArray fingerprint;
    QUuid server;
    QUuid client;
    QByteArray credential;
    bool paired = false;
    QByteArray pendingCredential = {};
};
// 日期：2026-11-04；客户端配对前先原子持久保存随机凭据；已有资料只允许相同目标/指纹安全重试。
ClientProfile prepareProfile(PrivateStore &store, const QString &alias, const QString &host,
                             quint16 port, const QString &peerName, const QByteArray &fingerprint);
// 日期：2026-11-04；只从权限核验通过的本地记录读取客户端凭据，CLI 参数不携带访问秘密。
ClientProfile loadProfile(const PrivateStore &store, const QString &alias);
// 日期：2026-11-04；持久保存收到的服务器 ID 与配对确认，失败时保留之前可安全重试的待配对记录。
void saveProfile(PrivateStore &store, const ClientProfile &profile);
// 日期：2026-11-05；读取资料公开目标和指纹供人工核对，绝不公开访问秘密或待轮换秘密。
QJsonObject profileInfo(const PrivateStore &store, const QString &alias);
// 日期：2026-11-05；新秘密先持久保存，轮换回包丢失时先验证新秘密后重试原秘密，串行锁防重复轮换。
QJsonObject rotateProfile(PrivateStore &store, const QString &alias, int timeoutMs,
                          const std::atomic_bool *cancel = nullptr);

// 日期：2026-11-05；核对新旧公开指纹并认证同一服务/主体后原子改pin，目标/权限/秘密及任务身份不变。
QJsonObject migrateProfileFingerprint(PrivateStore &store, const QString &alias,
                                      const QByteArray &expectedFingerprint,
                                      const QByteArray &replacementFingerprint, int timeoutMs,
                                      const std::atomic_bool *cancel = nullptr);

class RemoteClient final {
  public:
    // 日期：2026-11-04；所有连接由客户端主动发起，TLS 身份校验后必须先完成能力协商。
    RemoteClient(const ClientProfile &profile, int timeoutMs,
                 const std::atomic_bool *cancel = nullptr);
    // 日期：2026-11-04；沿已验证 TLS 连接提交一次性凭据及本地已持久化的访问秘密。
    Principal pair(const QByteArray &pairingCredential);
    // 日期：2026-11-04；每个新控制连接证明本地访问凭据，认证成功前不能执行共享操作。
    Principal authenticate();
    // 日期：2026-11-05；只在显式能力协商通过后发送新秘密，响应不含秘密且绑定当前主体。
    Principal rotateCredential(const QByteArray &replacement);
    // 日期：2026-11-04；沿已认证连接分页浏览共享；本地客户端不开放入站端口。
    QJsonObject list(const QString &share, const QString &relative,
                     const QString &cursor = QString());
    // 日期：2026-11-04；通过独立认证连接管理所属任务，暂停响应区分请求与实际状态。
    QJsonObject manage(const QUuid &task, next::Type operation = next::Type::TaskQuery);
    // 日期：2026-11-04；分页取当前主体仍有权限的任务，进程重启后可找回既有请求与任务 ID。
    QJsonObject tasks(quint64 after = 0);
    // 日期：2026-11-05；上传查询远端接收日志，下载核对本机证据；每页有界，不依据发送完成伪造落盘。
    QJsonObject items(const QUuid &task, PrivateStore &local, quint64 after = 0);
    // 日期：2026-11-05；非默认冲突策略先协商能力并绑定请求，上传由接收服务执行。
    QJsonObject upload(const QUuid &request, const QString &share, const QString &relative,
                       StrongManifest &manifest,
                       const std::function<void(const QJsonObject &)> &progress = {},
                       int channels = 1, ConflictPolicy conflict = ConflictPolicy::Rename);
    // 日期：2026-11-05；客户端下载按持久策略执行，本地请求和接收日志均禁止改变原策略。
    QJsonObject download(const QUuid &request, const QString &share, const QString &relative,
                         PrivateStore &local, const QString &destination,
                         const std::function<void(const QJsonObject &)> &progress = {},
                         int channels = 1, ConflictPolicy conflict = ConflictPolicy::Rename);
    // 日期：2026-11-04；仅供新建且已认证的数据线程使用，加入响应不能换成其他会话或通道。
    void runDataLane(const QJsonObject &ticket, int lane,
                     const std::shared_ptr<ParallelState> &state,
                     const QPair<QString, QString> &source);
    // 日期：2026-11-04；显式确认关闭控制会话，避免正常完成被服务端误记为网络异常。
    void close();
    // 日期：2026-11-04；返回握手中实际核对的服务身份，供配对确认后保存。
    QUuid serverId() const;
    // 日期：2026-11-05；返回服务声明的认证时长；旧服务未声明能力时为 0，不能推断无限期。
    int sessionSeconds() const;

  private:
    // 日期：2026-11-04；响应必须同序号且同预期类型，远端错误只显示规范化错误码/阶段/说明。
    QJsonObject request(next::Type type, next::Type response, const QJsonObject &object);
    // 日期：2026-11-04；认证响应不得改变客户端身份或授予格式错误的权限。
    Principal account(const QJsonObject &object) const;
    ClientProfile profile_;
    next::SecureChannel channel_;
    QUuid server_;
    quint64 correlation_ = 0;
    const std::atomic_bool *cancel_ = nullptr;
    bool closed_ = false;
    int timeoutMs_;
    QJsonArray capabilities_;
    int sessionSeconds_ = 0;
};

class ServiceWorker final : public QThread {
    Q_OBJECT
  public:
    // 日期：2026-11-04；监听线程仅转交描述符和不可变配置；TLS/磁盘对象在工作线程内创建。
    ServiceWorker(qintptr descriptor, QString state, ServiceIdentity identity, int timeoutMs,
                  QObject *parent = nullptr);
    // 日期：2026-11-04；原子取消由安全通道固定轮询周期观察，不能从主线程操作 socket。
    void cancel();
    // 日期：2026-11-04；析构等候工作线程清理，防止 TLS 或凭据对象在线程运行时被释放。
    ~ServiceWorker() override;
  signals:
    void event(const QJsonObject &event);

  protected:
    // 日期：2026-11-04；逐状态执行能力、配对或认证；任何未认证/不支持命令明确拒绝。
    void run() override;

  private:
    qintptr descriptor_;
    QString state_;
    ServiceIdentity identity_;
    int timeoutMs_;
    std::atomic_bool cancelled_{false};
};

class ServiceListener final : public QTcpServer {
    Q_OBJECT
  public:
    // 日期：2026-11-04；只加载已有身份；最多 32 个 TLS 连接，其中数据会话合计不超过 16 通道。
    ServiceListener(const QString &state, int timeoutMs, QObject *parent = nullptr);
    // 日期：2026-11-04；停止新连接并取消、等待所有工作线程，关闭服务也能快速归还资源。
    ~ServiceListener() override;
    // 日期：2026-11-04；显式停止所有活动连接，监听对象保留，供 CLI 信号/GUI 统一调用。
    void stop();
    // 日期：2026-11-04；提供可公开核对的服务 ID、指纹和证书有效期，不输出私钥。
    QJsonObject publicInfo() const;
  signals:
    void event(const QJsonObject &event);

  protected:
    // 日期：2026-11-04；额度不足立即关闭新描述符，不创建额外线程或无界等待连接队列。
    void incomingConnection(qintptr descriptor) override;

  private:
    QString state_;
    ServiceIdentity identity_;
    int timeoutMs_;
    QSet<ServiceWorker *> workers_;
};
} // namespace dukto

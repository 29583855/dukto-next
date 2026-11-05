#pragma once

#include "buffercredit.h"
#include "protocol.h"
#include <QElapsedTimer>
#include <QSslConfiguration>
#include <QSslSocket>
#include <atomic>
#include <functional>

namespace dukto {
namespace next {
class SecureChannel final {
  public:
    // 日期：2026-11-04；通道在所属工作线程内创建，固定读缓冲、帧期限及可轮询的取消源。
    explicit SecureChannel(int timeoutMs, const std::atomic_bool *cancel = nullptr);
    // 日期：2026-11-04；失败/销毁立即关闭连接，不把未确认的 TLS 字节当成传输成功。
    ~SecureChannel();
    // 日期：2026-11-04；客户端验证证书链和主机名；固定指纹模式只定向信任同一张自签叶证书。
    void connectTo(const QString &host, quint16 port, const QString &peerName,
                   const QSslConfiguration &configuration, const QByteArray &fingerprint = {});
    // 日期：2026-11-04；服务端只接受已配置证书/私钥的 TLS，不在此层提供匿名业务访问。
    void accept(qintptr descriptor, const QSslConfiguration &configuration);
    // 日期：2026-11-04；按解码器要求读取一帧，头和正文总耗时共享同一期限，拒绝慢速无限续期。
    Frame read();
    // 日期：2026-11-04；每帧写完并排空 Qt 明文/密文队列后返回，不能无限排队数据。
    void write(const Frame &frame);
    // 日期：2026-11-04；控制请求与数据帧共用同一长度、JSON 及写缓冲约束。
    void write(Type type, quint64 correlation, const QJsonObject &object);
    // 日期：2026-11-04；返回已经过握手校验的证书指纹，供配对核对和受保护的信任记录使用。
    QByteArray peerFingerprint() const;
    // 日期：2026-11-04；长扫描/摘要期间定期处理本线程 TLS
    // 事件，检测断开和取消而不读取下一条业务帧。
    void checkpoint(const QString &stage);
    // 日期：2026-11-04；数据循环另观察所属任务的原子取消；指针必须覆盖整个通道使用期间。
    void observeCancellation(const std::atomic_bool *cancel);
    // 日期：2026-11-05；业务认证后把本连接的 TLS/socket 授信转入数据额度，保留取消查询所需额度。
    void classifyAsData();
    // 日期：2026-11-05；限定数据树交换期间的进度观察者；只能在所属线程注册或清除。
    void observeProgress(std::function<void(const Frame &)> handler);

  private:
    // 日期：2026-11-04；所有等待在本线程事件循环处理网络事件，25ms 检查取消，不跨线程碰 socket。
    void waitUntil(const std::function<bool()> &ready, QElapsedTimer &elapsed,
                   const QString &stage);
    // 日期：2026-11-04；检查操作的固定截止时间、取消和 TLS 状态，错误不带凭据/正文。
    void check(QElapsedTimer &elapsed, const QString &stage) const;
    // 日期：2026-11-04；握手完成后再次核对指纹和证书期限，受信 CA 也不能绕过固定指纹要求。
    void handshake();
    BufferCredit credit_{4 * 1024 * 1024};
    QSslSocket socket_;
    int timeoutMs_;
    const std::atomic_bool *cancel_;
    const std::atomic_bool *taskCancel_ = nullptr;
    QString peerName_;
    QByteArray fingerprint_;
    QByteArray peerFingerprint_;
    bool sslErrors_ = false;
    bool used_ = false;
    bool established_ = false;
    std::function<void(const Frame &)> progress_;
};
} // namespace next
} // namespace dukto

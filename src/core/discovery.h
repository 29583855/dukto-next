#pragma once

#include <QElapsedTimer>
#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QMap>
#include <QTimer>
#include <QUdpSocket>

namespace dukto {
class Discovery final : public QObject {
    Q_OBJECT
  public:
    // 日期：2026-11-04；设备表与 datagram 长度均有上限，定时淘汰离线设备。
    explicit Discovery(QObject *parent = nullptr);
    // 日期：2026-11-04；退出时发出原版兼容 Goodbye，不保留发现 socket。
    ~Discovery() override;
    // 日期：2026-11-04；启动绑定，失败返回 false 并通过 errorString 提供原因。
    bool start(quint16 port, const QString &username);
    // 日期：2026-11-04；生成当前有界设备快照，供 GUI 和 CLI 共同使用。
    QJsonArray peers() const;
    // 日期：2026-11-04；更新用户名后广播新签名。
    void setUsername(const QString &username);
    // 日期：2026-11-04；读取 socket 绑定或网络错误。
    QString errorString() const;
    // 日期：2026-11-04；向所有活动 IPv4 广播接口发送发现请求。
    void announce();
  signals:
    void changed();

  private:
    // 日期：2026-11-04；严格解析 R6 数据报并拒绝空包、超长签名和非法端口。
    void read();
    // 日期：2026-11-04；使用单调时间，系统时间调整不影响在线租约。
    void expire();
    // 日期：2026-11-04；生成与原版可互识别的身份签名。
    QByteArray signature() const;
    // 日期：2026-11-04；构建标准/自定义端口的 Hello 数据报。
    QByteArray hello(bool broadcast) const;
    // 日期：2026-11-04；枚举广播地址并发送固定大小数据报。
    void broadcast(const QByteArray &data);
    struct Peer {
        QJsonObject value;
        QMap<QString, qint64> addresses;
    };
    QUdpSocket socket_;
    QTimer timer_;
    QElapsedTimer clock_;
    bool readQueued_ = false;
    QHash<QString, Peer> peers_;
    quint16 port_ = 4644;
    QString username_;
};
} // namespace dukto

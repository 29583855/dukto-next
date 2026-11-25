#pragma once

#include "core/tcplistener.h"
#include <QJsonArray>
#include <QMap>
#include <QNetworkAccessManager>
#include <QObject>
#include <QStringList>

// 日期：2026-11-04；头像仅属于桌面展示，不将图像依赖引入独立 CLI 核心。
class Avatars final : public QObject {
    Q_OBJECT
  public:
    // 日期：2026-11-04；使用已保存的规范 PNG，默认生成不依赖外部资源的人像。
    explicit Avatars(QObject *parent = nullptr);
    // 日期：2026-11-04；销毁前断开回调并取消请求，成员释放期间不再修改缓存。
    ~Avatars() override;
    // 日期：2026-11-04；只监听 R6 约定的传输端口加一，65535 不会溢出成零。
    bool listen(quint16 transferPort);
    // 日期：2026-11-04；按当前设备集合维护最多 256 个缓存，至多四个并发请求。
    void synchronize(const QJsonArray &peers, bool refresh = false);
    // 日期：2026-11-04；返回经过尺寸检查和重新编码的数据 URL，失败时为空。
    QString image(const QString &id) const;
    // 日期：2026-11-04；返回本机头像，不让 QML 直接加载未经验证的输入文件。
    QString localImage() const;
    // 日期：2026-11-04；返回可持久化的有限 PNG 数据。
    QByteArray localPng() const;
    // 日期：2026-11-04；仅接受有限 PNG/JPEG，解码并重新编码为不超过 64 像素的 PNG。
    bool setLocalImage(const QByteArray &encoded);
    // 日期：2026-11-04；供诊断与受控测试确认头像服务实际绑定端口。
    quint16 serverPort() const;
    // 日期：2026-11-04；返回有限待处理数，供资源诊断和截止时间回归验证。
    int pendingRequests() const;
  signals:
    void changed();

  private:
    struct Entry {
        QString address;
        int port = 0;
        QString image;
    };
    // 日期：2026-11-04；仅从受控设备队列补充请求，拒绝代理、重定向及内容压缩。
    void pump();
    // 日期：2026-11-04；提供有请求/连接/时间上限的兼容头像 HTTP 端点。
    void accept();
    QNetworkAccessManager network_;
    dukto::TcpListener server_;
    QMap<QString, Entry> entries_;
    QStringList queue_;
    QByteArray local_;
    int active_ = 0;
    int clients_ = 0;
};

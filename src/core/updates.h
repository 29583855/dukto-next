#pragma once

#include <QNetworkAccessManager>
#include <QPointer>
#include <QTimer>

namespace dukto {
class Updates final : public QObject {
    Q_OBJECT
  public:
    // 日期：2026-11-04；版本检查在创建线程异步运行，响应上限 32 KiB，无匿名参数。
    explicit Updates(QObject *parent = nullptr);
    // 日期：2026-11-04；销毁时断开回调并结束尚未完成的请求。
    ~Updates() override;
    // 日期：2026-11-04；仅 HTTPS 或回环 HTTP，禁止自动重定向，重复检查返回明确状态。
    void check(const QUrl &endpoint, int timeoutMs = 10000);
  signals:
    void completed(bool available, const QString &version, const QUrl &page,
                   const QString &message);

  private:
    // 日期：2026-11-04；分段消费网络缓冲，累计超限立即失败。
    void consume();
    // 日期：2026-11-04；完整响应后验证 JSON 架构、版本号和链接协议。
    void finish();
    // 日期：2026-11-04；释放响应和计时器，只发出一次失败结果。
    void fail(const QString &message);
    QNetworkAccessManager manager_;
    QPointer<QNetworkReply> reply_;
    QTimer timeout_;
    QByteArray data_;
};
} // namespace dukto

#include "updates.h"
#include <QHostAddress>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QVersionNumber>

namespace dukto {
namespace {
constexpr int Maximum = 32768;
// 日期：2026-11-04；严格消费完整版本字符串，禁止无效后缀和不合理段数。
QVersionNumber version(const QString &text) {
    int suffix = 0;
    const auto value = QVersionNumber::fromString(text, &suffix);
    return suffix == text.size() && value.segmentCount() == 3 ? value : QVersionNumber();
}
} // namespace

// 日期：2026-11-04；总截止时间覆盖连接、握手与响应，不因慢速零碎数据无限延长。
Updates::Updates(QObject *parent) : QObject(parent) {
    timeout_.setSingleShot(true);
    connect(&timeout_, &QTimer::timeout, this,
            [this]() { fail(QStringLiteral("检查更新超时，请稍后重试")); });
}

// 日期：2026-11-04；不在析构期间发出面向界面的结果信号。
Updates::~Updates() {
    if (reply_) {
        reply_->disconnect(this);
        reply_->abort();
    }
}

// 日期：2026-11-04；不访问旧站点，端点必须由本项目配置显式提供。
void Updates::check(const QUrl &endpoint, int timeoutMs) {
    if (reply_) {
        emit completed(false, {}, {}, QStringLiteral("正在检查更新，请等待"));
        return;
    }
    const bool local = QHostAddress(endpoint.host()).isLoopback();
    if (!endpoint.isValid() || endpoint.host().isEmpty() || !endpoint.userInfo().isEmpty() ||
        !endpoint.fragment().isEmpty() || timeoutMs < 1 || timeoutMs > 60000 ||
        (endpoint.scheme() != "https" && !(endpoint.scheme() == "http" && local))) {
        emit completed(false, {}, {},
                       QStringLiteral("请配置有效 HTTPS 更新地址（本机测试可用回环 HTTP）"));
        return;
    }
    QNetworkRequest request(endpoint);
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                         QNetworkRequest::ManualRedirectPolicy);
    request.setRawHeader("Accept", "application/json");
    request.setRawHeader("Accept-Encoding", "identity");
    data_.clear();
    reply_ = manager_.get(request);
    reply_->setReadBufferSize(Maximum);
    connect(reply_, &QIODevice::readyRead, this, &Updates::consume);
    connect(reply_, &QNetworkReply::finished, this, &Updates::finish);
    timeout_.start(timeoutMs);
}

// 日期：2026-11-04；只接受固定长度的小型描述，不下载安装包或执行远程内容。
void Updates::consume() {
    if (!reply_)
        return;
    const auto bytes = reply_->read(Maximum + 1 - data_.size());
    data_ += bytes;
    if (data_.size() > Maximum)
        fail(QStringLiteral("更新响应超过 32 KiB 限制"));
}

// 日期：2026-11-04；网络、状态码或描述格式错误均不会显示“已是最新”。
void Updates::finish() {
    consume();
    if (!reply_)
        return;
    const auto status = reply_->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
    if (reply_->error() != QNetworkReply::NoError || status != 200) {
        fail(QStringLiteral("检查更新失败：HTTP %1，%2").arg(status).arg(reply_->errorString()));
        return;
    }
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(data_, &error);
    const auto object = document.object();
    const auto text = object["version"].toString();
    const auto remote = version(text);
    const QUrl page(object["url"].toString());
    if (error.error != QJsonParseError::NoError || object["schema"].toInt() != 1 ||
        remote.isNull() || !page.isValid() || page.scheme() != "https" || page.host().isEmpty() ||
        !page.userInfo().isEmpty()) {
        fail(QStringLiteral("更新描述格式、版本或下载页面无效"));
        return;
    }
    timeout_.stop();
    reply_->deleteLater();
    reply_.clear();
    data_.clear();
    const bool available = QVersionNumber::compare(remote, version(DUKTO_VERSION)) > 0;
    emit completed(available, text, available ? page : QUrl(),
                   available ? QStringLiteral("发现新版本 %1").arg(text)
                             : QStringLiteral("当前已是最新版本"));
}

// 日期：2026-11-04；先断开信号再 abort，避免中止回调重入导致重复报告。
void Updates::fail(const QString &message) {
    timeout_.stop();
    if (reply_) {
        reply_->disconnect(this);
        reply_->abort();
        reply_->deleteLater();
        reply_.clear();
    }
    data_.clear();
    emit completed(false, {}, {}, message);
}
} // namespace dukto

#include "avatars.h"

#include <QBuffer>
#include <QHostAddress>
#include <QImageReader>
#include <QJsonObject>
#include <QNetworkProxy>
#include <QNetworkReply>
#include <QPainter>
#include <QSet>
#include <QTcpSocket>
#include <QTimer>
#include <memory>

namespace {
constexpr int MaxEncoded = 128 * 1024;

// 日期：2026-11-04；检查压缩大小和解码尺寸，仅启用 PNG/JPEG，拒绝 SVG 等外部资源格式。
QByteArray normalized(const QByteArray &encoded) {
    if (encoded.isEmpty() || encoded.size() > MaxEncoded)
        return {};
    QBuffer source;
    source.setData(encoded);
    source.open(QIODevice::ReadOnly);
    QImageReader reader(&source);
    const auto format = reader.format().toLower();
    const auto size = reader.size();
    if ((format != "png" && format != "jpeg" && format != "jpg") || !size.isValid() ||
        size.width() > 1024 || size.height() > 1024)
        return {};
    reader.setAutoTransform(true);
    reader.setScaledSize(size.scaled(64, 64, Qt::KeepAspectRatio));
    auto image = reader.read();
    if (image.isNull() || image.width() > 1024 || image.height() > 1024)
        return {};
    image = image.scaled(64, 64, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    QByteArray png;
    QBuffer target(&png);
    if (!target.open(QIODevice::WriteOnly) || !image.save(&target, "PNG") || png.size() > 32768)
        return {};
    return png;
}

// 日期：2026-11-04；QML 只接收本地规范数据，禁止绕过网络和图像上限自行请求 URL。
QString dataUrl(const QByteArray &png) {
    return png.isEmpty() ? QString()
                         : "data:image/png;base64," + QString::fromLatin1(png.toBase64());
}
} // namespace

// 日期：2026-11-04；默认头像由几何图形生成，无旧版图片、字体或网络依赖。
Avatars::Avatars(QObject *parent) : QObject(parent) {
    network_.setProxy(QNetworkProxy::NoProxy);
    QImage fallback(64, 64, QImage::Format_ARGB32_Premultiplied);
    fallback.fill(QColor("#eeeeee"));
    QPainter painter(&fallback);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(Qt::NoPen);
    painter.setBrush(QColor("#929292"));
    painter.drawEllipse(QRectF(22, 11, 20, 20));
    painter.drawRoundedRect(QRectF(13, 34, 38, 24), 12, 12);
    painter.end();
    QBuffer buffer(&local_);
    buffer.open(QIODevice::WriteOnly);
    fallback.save(&buffer, "PNG");
    connect(&server_, &QTcpServer::newConnection, this, &Avatars::accept);
}

// 日期：2026-11-04；网络与服务对象属于当前线程，清理在缓存成员析构之前完成。
Avatars::~Avatars() {
    for (auto reply : network_.findChildren<QNetworkReply *>()) {
        disconnect(reply, nullptr, this, nullptr);
        reply->abort();
    }
    server_.close();
    for (auto client : server_.findChildren<QTcpSocket *>()) {
        disconnect(client, nullptr, this, nullptr);
        client->abort();
    }
}

// 日期：2026-11-04；头像监听失败独立报告，不抢占或改变传输端口。
bool Avatars::listen(quint16 transferPort) {
    if (transferPort == 65535)
        return false;
    server_.setMaxPendingConnections(8);
    return server_.listen(QHostAddress::AnyIPv4, static_cast<quint16>(transferPort + 1));
}

// 日期：2026-11-04；缓存只包含当前发现的数字地址，不接受签名中伪造的主机或 URL。
void Avatars::synchronize(const QJsonArray &peers, bool refresh) {
    if (refresh) {
        entries_.clear();
        queue_.clear();
    }
    QSet<QString> retained;
    for (const auto &value : peers) {
        if (retained.size() >= 256)
            break;
        const auto peer = value.toObject();
        const auto id = peer["id"].toString();
        const auto address = peer["address"].toString();
        const auto port = peer["port"].toInt();
        const QHostAddress numeric(address);
        if (id.isEmpty() || numeric.isNull() || numeric.isMulticast() ||
            numeric == QHostAddress::AnyIPv4 || numeric == QHostAddress::AnyIPv6 ||
            numeric == QHostAddress::Broadcast || port < 1 || port >= 65535)
            continue;
        retained.insert(id);
        if (entries_.contains(id)) {
            if (entries_[id].address == address && entries_[id].port == port)
                continue;
            queue_.removeAll(id);
        }
        entries_[id] = {address, port, {}};
        queue_.append(id);
    }
    for (auto iterator = entries_.begin(); iterator != entries_.end();)
        if (!retained.contains(iterator.key())) {
            queue_.removeAll(iterator.key());
            iterator = entries_.erase(iterator);
        } else
            ++iterator;
    pump();
}

// 日期：2026-11-04；缺失或下载失败保持默认设备图标，不将错误图片交给 QML。
QString Avatars::image(const QString &id) const {
    return entries_.value(id).image;
}

// 日期：2026-11-04；本机图片同样通过规范编码提供。
QString Avatars::localImage() const {
    return dataUrl(local_);
}

// 日期：2026-11-04；保存副本最大 32 KiB，不能把原始大图写入配置。
QByteArray Avatars::localPng() const {
    return local_;
}

// 日期：2026-11-04；验证失败保留旧头像，避免配置或文件损坏清空显示。
bool Avatars::setLocalImage(const QByteArray &encoded) {
    const auto image = normalized(encoded);
    if (image.isEmpty())
        return false;
    local_ = image;
    emit changed();
    return true;
}

// 日期：2026-11-04；仅返回当前服务的真实端口。
quint16 Avatars::serverPort() const {
    return server_.serverPort();
}

// 日期：2026-11-04；请求完成后活动额度和队列必须归零。
int Avatars::pendingRequests() const {
    return active_ + queue_.size();
}

// 日期：2026-11-04；每次最多四个 128 KiB 响应，三秒总截止时间独立于下载进度。
void Avatars::pump() {
    while (active_ < 4 && !queue_.isEmpty()) {
        const auto id = queue_.takeFirst();
        if (!entries_.contains(id))
            continue;
        const auto entry = entries_[id];
        QUrl url;
        url.setScheme("http");
        url.setHost(entry.address);
        url.setPort(entry.port + 1);
        url.setPath("/dukto/avatar");
        QNetworkRequest request(url);
        request.setAttribute(QNetworkRequest::RedirectPolicyAttribute,
                             QNetworkRequest::ManualRedirectPolicy);
        request.setAttribute(QNetworkRequest::CookieLoadControlAttribute, QNetworkRequest::Manual);
        request.setAttribute(QNetworkRequest::CookieSaveControlAttribute, QNetworkRequest::Manual);
        request.setAttribute(QNetworkRequest::AuthenticationReuseAttribute,
                             QNetworkRequest::Manual);
        request.setRawHeader("Accept-Encoding", "identity");
        auto reply = network_.get(request);
        reply->setReadBufferSize(MaxEncoded + 1);
        ++active_;
        struct Response {
            QByteArray bytes;
            bool invalid = false;
        };
        const auto response = std::make_shared<Response>();
        // 日期：2026-11-04；读到上限后一字节即中止，不能因缺少 Content-Length 无限增长。
        connect(reply, &QNetworkReply::readyRead, this, [reply, response]() {
            response->bytes.append(reply->read(MaxEncoded + 1 - response->bytes.size()));
            if (response->bytes.size() > MaxEncoded || reply->bytesAvailable() > 0) {
                response->invalid = true;
                reply->abort();
            }
        });
        // 日期：2026-11-04；声明压缩或超限时在解码前拒绝，不跟随任意重定向。
        connect(reply, &QNetworkReply::metaDataChanged, this, [reply, response]() {
            const auto encoding = reply->rawHeader("Content-Encoding").toLower();
            if (reply->header(QNetworkRequest::ContentLengthHeader).toLongLong() > MaxEncoded ||
                (!encoding.isEmpty() && encoding != "identity")) {
                response->invalid = true;
                reply->abort();
            }
        });
        auto deadline = new QTimer(reply);
        deadline->setSingleShot(true);
        connect(deadline, &QTimer::timeout, reply, &QNetworkReply::abort);
        deadline->start(3000);
        // 日期：2026-11-04；过期设备响应只释放槽位，不重新加入已移除设备。
        connect(reply, &QNetworkReply::finished, this, [this, reply, response, id, entry]() {
            --active_;
            if (entries_.contains(id) && entries_[id].address == entry.address &&
                entries_[id].port == entry.port && !response->invalid &&
                reply->error() == QNetworkReply::NoError &&
                reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() == 200) {
                entries_[id].image = dataUrl(normalized(response->bytes));
                emit changed();
            }
            reply->deleteLater();
            QTimer::singleShot(0, this, &Avatars::pump);
        });
    }
}

// 日期：2026-11-04；每连接最多 2 KiB 请求、两秒总期限和 32 KiB 响应，忙时断开。
void Avatars::accept() {
    while (server_.hasPendingConnections()) {
        auto client = server_.nextPendingConnection();
        if (clients_ >= 8) {
            client->abort();
            client->deleteLater();
            continue;
        }
        ++clients_;
        client->setReadBufferSize(2049);
        auto deadline = new QTimer(client);
        deadline->setSingleShot(true);
        connect(deadline, &QTimer::timeout, client, &QTcpSocket::abort);
        deadline->start(2000);
        // 日期：2026-11-04；计数在断开时归还，删除前不再处理请求。
        connect(client, &QTcpSocket::disconnected, this, [this, client]() {
            --clients_;
            client->deleteLater();
        });
        // 日期：2026-11-04；只处理一个兼容 GET，其他方法、路径和过长请求返回明确错误。
        connect(client, &QTcpSocket::readyRead, this, [this, client]() {
            if (client->property("answered").toBool())
                return;
            const auto request = client->peek(2049);
            const auto end = request.indexOf("\r\n\r\n");
            if (request.size() > 2048) {
                client->abort();
                return;
            }
            if (end < 0)
                return;
            client->setProperty("answered", true);
            const auto line = request.left(request.indexOf("\r\n"));
            const bool valid =
                line == "GET /dukto/avatar HTTP/1.0" || line == "GET /dukto/avatar HTTP/1.1";
            const auto body = valid ? local_ : QByteArray();
            client->readAll();
            client->write(QByteArray("HTTP/1.0 ") + (valid ? "200 OK" : "404 Not Found") +
                          "\r\nContent-Type: image/png\r\nContent-Length: " +
                          QByteArray::number(body.size()) + "\r\nConnection: close\r\n\r\n" + body);
            client->disconnectFromHost();
        });
    }
}

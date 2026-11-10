#include "discovery.h"

#include <QHostInfo>
#include <QJsonObject>
#include <QNetworkDatagram>
#include <QNetworkInterface>
#include <QNetworkProxy>
#include <QRegularExpression>
#include <QtEndian>

namespace dukto {
// 日期：2026-11-04；网络对象只在创建它的事件循环线程访问。
Discovery::Discovery(QObject *parent) : QObject(parent) {
    // 日期：2026-11-10；局域网套接字显式直连；标准广播与自定义端口回复分别排空。
    for (auto socket : {&socket_, &broadcastSocket_}) {
        socket->setProxy(QNetworkProxy::NoProxy);
        connect(socket, &QUdpSocket::readyRead, this, [this, socket]() { read(socket); });
    }
    // 日期：2026-11-04；每五秒发送有界Hello，支持不能共享标准UDP的原版共存并清理超时设备。
    connect(&timer_, &QTimer::timeout, this, [this]() {
        announce();
        expire();
    });
    timer_.setInterval(5000);
    clock_.start();
}

// 日期：2026-11-04；仅已绑定实例发送退出广播。
Discovery::~Discovery() {
    if (socket_.state() == QAbstractSocket::BoundState)
        broadcast(QByteArray(1, '\x03'));
}

// 日期：2026-11-10；共享标准广播端口，自定义接收端口另设独占UDP回复入口，兼容原版1/2/4/5握手。
bool Discovery::start(quint16 port, const QString &username) {
    if (socket_.state() == QAbstractSocket::BoundState)
        return false;
    bindError_.clear();
    port_ = port;
    username_ = username.left(128);
    const auto shared = QUdpSocket::ShareAddress | QUdpSocket::ReuseAddressHint;
    if (!socket_.bind(QHostAddress::AnyIPv4, port_,
                      port_ == 4644 ? shared : QUdpSocket::DontShareAddress)) {
        bindError_ = socket_.errorString();
        return false;
    }
    port_ = socket_.localPort();
    // 日期：2026-11-10；Darwin原版默认UDP可能完全不允许复用；保留定向入口，主动广播仍可发现。
    if (port_ != 4644)
        broadcastSocket_.bind(QHostAddress::AnyIPv4, 4644, shared);
    announce();
    timer_.start();
    return true;
}

// 日期：2026-11-04；发布对象副本的数量最多 256，防止发现广播填满界面模型。
QJsonArray Discovery::peers() const {
    QJsonArray result;
    for (const auto &peer : peers_) {
        auto value = peer.value;
        value.insert("address", peer.addresses.firstKey());
        value.insert("addresses", QJsonArray::fromStringList(peer.addresses.keys()));
        result.append(value);
    }
    return result;
}

// 日期：2026-11-04；限制身份文本长度后立即通知同网段设备。
void Discovery::setUsername(const QString &username) {
    username_ = username.left(128);
    announce();
}

// 日期：2026-11-04；对外保留 Qt 的具体绑定失败原因。
QString Discovery::errorString() const {
    return bindError_.isEmpty() ? socket_.errorString() : bindError_;
}

// 日期：2026-11-05；本机名可能涉及平台系统服务；只在公告时刷新，用户名改动立即公告。
void Discovery::refreshSignature() {
#ifdef Q_OS_WIN
    const QString platform = "Windows";
#elif defined(Q_OS_MACOS)
    const QString platform = "Macintosh";
#else
    const QString platform = "Linux";
#endif
    signature_ = (username_ + " at " + QHostInfo::localHostName() + " (" + platform + ')').toUtf8();
}

// 日期：2026-11-04；自定义端口显式编码为小端 16 位，不假设宿主字节序。
QByteArray Discovery::hello(bool broadcastFlag) const {
    QByteArray data(
        1, static_cast<char>(port_ == 4644 ? (broadcastFlag ? 1 : 2) : (broadcastFlag ? 4 : 5)));
    if (port_ != 4644) {
        QByteArray bytes(2, '\0');
        qToLittleEndian(port_, reinterpret_cast<uchar *>(bytes.data()));
        data.append(bytes);
    }
    return data + signature_;
}

// 日期：2026-11-04；仅向实际启用且支持广播的 IPv4 接口发送，不依赖跨网段广播。
void Discovery::broadcast(const QByteArray &data) {
    QSet<quint16> destinations{4644, port_};
    // 日期：2026-11-10；两台Mac的原版均独占4644时，Next仍通过已约定的16个备用UDP端口直达对方。
    for (quint16 candidate = 4648; candidate <= 4678; candidate += 2)
        destinations.insert(candidate);
    for (const auto &interface : QNetworkInterface::allInterfaces()) {
        if (!(interface.flags() & QNetworkInterface::IsUp) ||
            !(interface.flags() & QNetworkInterface::CanBroadcast))
            continue;
        for (const auto &address : interface.addressEntries()) {
            if (address.ip().protocol() != QAbstractSocket::IPv4Protocol ||
                address.broadcast().isNull())
                continue;
            for (const auto destination : destinations)
                socket_.writeDatagram(data, address.broadcast(), destination);
        }
    }
}

// 日期：2026-11-04；发现请求是有限的小数据报，不包含任何文件正文。
void Discovery::announce() {
    if (socket_.state() != QAbstractSocket::BoundState)
        return;
    refreshSignature();
    broadcast(hello(true));
}

// 日期：2026-11-04；收到 Goodbye 或租约过期时删除相应设备并刷新界面。
void Discovery::expire() {
    bool removed = false;
    for (auto iterator = peers_.begin(); iterator != peers_.end();) {
        auto &addresses = iterator->addresses;
        for (auto address = addresses.begin(); address != addresses.end();) {
            if (clock_.elapsed() - address.value() > 180000) {
                address = addresses.erase(address);
                removed = true;
            } else
                ++address;
        }
        if (addresses.isEmpty()) {
            iterator = peers_.erase(iterator);
            removed = true;
        } else
            ++iterator;
    }
    if (removed)
        emit changed();
}

// 日期：2026-11-06；每轮最多 64 包/5ms；可读通知至少非阻塞读取一次，恢复 Qt 的后续通知。
void Discovery::read(QUdpSocket *socket) {
    QElapsedTimer slice;
    slice.start();
    int received = 0;
    for (; received < 64 && (received == 0 || slice.elapsed() < 5) &&
           (received == 0 || socket->hasPendingDatagrams());
         ++received) {
        // 日期：2026-11-06；排队续读可能先排空内核队列；迟到的空通知也须读取以重置 Qt 状态。
        const auto packet = socket->receiveDatagram(1024);
        if (!packet.isValid())
            break;
        auto data = packet.data();
        if (data.isEmpty())
            continue;
        const auto type = static_cast<unsigned char>(data[0]);
        data.remove(0, 1);
        if (type == 3) {
            // 日期：2026-11-10；原版R6退出正文固定为Bye Bye，同时保留Next空正文格式。
            if (!data.isEmpty() && data != "Bye Bye")
                continue;
            bool removed = false;
            for (auto iterator = peers_.begin(); iterator != peers_.end();) {
                removed =
                    iterator->addresses.remove(packet.senderAddress().toString()) > 0 || removed;
                if (iterator->addresses.isEmpty()) {
                    iterator = peers_.erase(iterator);
                } else
                    ++iterator;
            }
            if (removed)
                emit changed();
            continue;
        }
        quint16 port = 4644;
        if (type == 4 || type == 5) {
            if (data.size() < 2)
                continue;
            port = qFromLittleEndian<quint16>(reinterpret_cast<const uchar *>(data.constData()));
            data.remove(0, 2);
        } else if (type != 1 && type != 2)
            continue;
        if (port == 0 || data.isEmpty() || data.size() > 512 ||
            (data == signature_ && port == port_) || QString::fromUtf8(data).toUtf8() != data)
            continue;
        // 日期：2026-11-04；R6 无设备 UUID，以完整签名和端口聚合同一设备的有限地址集。
        const auto key = QString::fromUtf8(data) + ':' + QString::number(port);
        if (peers_.size() >= 256 && !peers_.contains(key))
            continue;
        const auto name = QString::fromUtf8(data);
        static const QRegularExpression format("^(.*) at (.*) \\((.*)\\)$");
        const auto parsed = format.match(name);
        const QJsonObject peer{{"id", key},
                               {"port", port},
                               {"name", parsed.hasMatch() ? parsed.captured(1) : name},
                               {"host", parsed.captured(2)},
                               {"platform", parsed.captured(3)}};
        const auto address = packet.senderAddress().toString();
        auto &stored = peers_[key];
        const bool different = stored.value != peer || !stored.addresses.contains(address);
        if (stored.addresses.size() >= 16 && !stored.addresses.contains(address))
            continue;
        stored.value = peer;
        stored.addresses.insert(address, clock_.elapsed());
        if (type == 1 || type == 4)
            socket_.writeDatagram(hello(false), packet.senderAddress(), port);
        if (different)
            emit changed();
    }
    // 日期：2026-11-06；只在仍有包时递交一条续读事件；稍后到达的包由恢复后的可读通知处理。
    if (socket->hasPendingDatagrams() && !readQueued_.contains(socket)) {
        readQueued_.insert(socket);
        QTimer::singleShot(0, this, [this, socket]() {
            // 日期：2026-11-10；每个套接字最多一条续读，析构时由Qt自动撤销回调。
            readQueued_.remove(socket);
            read(socket);
        });
    }
}
} // namespace dukto

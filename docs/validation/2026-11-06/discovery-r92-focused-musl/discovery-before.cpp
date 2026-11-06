#include "discovery.h"

#include <QHostInfo>
#include <QJsonObject>
#include <QNetworkDatagram>
#include <QNetworkInterface>
#include <QRegularExpression>
#include <QtEndian>

namespace dukto {
// 日期：2026-11-04；网络对象只在创建它的事件循环线程访问。
Discovery::Discovery(QObject *parent) : QObject(parent) {
    connect(&socket_, &QUdpSocket::readyRead, this, &Discovery::read);
    // 日期：2026-11-04；每分钟发送 Hello 并清理超时设备。
    connect(&timer_, &QTimer::timeout, this, [this]() {
        announce();
        expire();
    });
    timer_.setInterval(60000);
    clock_.start();
}

// 日期：2026-11-04；仅已绑定实例发送退出广播。
Discovery::~Discovery() {
    if (socket_.state() == QAbstractSocket::BoundState)
        broadcast(QByteArray(1, '\x03'));
}

// 日期：2026-11-04；禁止默默共享发现端口，以便定位 GUI/CLI 重复监听冲突。
bool Discovery::start(quint16 port, const QString &username) {
    port_ = port;
    username_ = username.left(128);
    if (!socket_.bind(QHostAddress::AnyIPv4, port_, QUdpSocket::DontShareAddress))
        return false;
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
    return socket_.errorString();
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
    for (const auto &interface : QNetworkInterface::allInterfaces()) {
        if (!(interface.flags() & QNetworkInterface::IsUp) ||
            !(interface.flags() & QNetworkInterface::CanBroadcast))
            continue;
        for (const auto &address : interface.addressEntries()) {
            if (address.ip().protocol() != QAbstractSocket::IPv4Protocol ||
                address.broadcast().isNull())
                continue;
            socket_.writeDatagram(data, address.broadcast(), 4644);
            if (port_ != 4644)
                socket_.writeDatagram(data, address.broadcast(), port_);
        }
    }
}

// 日期：2026-11-04；发现请求是有限的小数据报，不包含任何文件正文。
void Discovery::announce() {
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

// 日期：2026-11-05；每轮最多 64 个包并限制处理时间，持续发现流量不能长期占住 GUI 事件循环。
void Discovery::read() {
    QElapsedTimer slice;
    slice.start();
    int received = 0;
    for (; received < 64 && slice.elapsed() < 5 && socket_.hasPendingDatagrams(); ++received) {
        const auto packet = socket_.receiveDatagram(1024);
        auto data = packet.data();
        if (data.isEmpty())
            continue;
        const auto type = static_cast<unsigned char>(data[0]);
        data.remove(0, 1);
        if (type == 3) {
            if (!data.isEmpty())
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
    // 日期：2026-11-05；回调刚发送的数据报可能稍后才可读；有收包的批次再查一次。
    // 空批次不续排，始终最多一个事件，不使用忙轮询或阻塞等待占住界面线程。
    if ((received > 0 || socket_.hasPendingDatagrams()) && !readQueued_) {
        readQueued_ = true;
        QTimer::singleShot(0, this, [this]() {
            // 日期：2026-11-05；同一实例最多一条后续排空事件，析构时由 Qt 自动撤销回调。
            readQueued_ = false;
            read();
        });
    }
}
} // namespace dukto

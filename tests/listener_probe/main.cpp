#include "tcplistener.h"
#include <QCoreApplication>
#include <QEventLoop>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QScopedPointer>
#include <QTcpServer>
#include <QTcpSocket>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <utility>

namespace {
class SocketOwner final {
  public:
    // 日期：2026-11-06；失败描述符仅由本探针守卫关闭，不操作系统中的其他监听。
    explicit SocketOwner(int descriptor) : descriptor(descriptor) {
    }
    // 日期：2026-11-06；Qt接管前自动关闭，接管后使用无效标记避免双重关闭。
    ~SocketOwner() {
        if (descriptor >= 0)
            ::close(descriptor);
    }
    int descriptor;
};

// 日期：2026-11-06；只读取本进程监听描述符的实际选项，不用请求地址猜测内核双栈状态。
QJsonObject options(QTcpServer &server) {
    QJsonObject value{{"listening", server.isListening()},
                      {"address", server.serverAddress().toString()},
                      {"port", int(server.serverPort())}};
    for (const auto entry : {std::make_pair(SO_REUSEADDR, "reuseAddress"),
                             std::make_pair(SO_REUSEPORT, "reusePort")}) {
        int enabled = -1;
        socklen_t length = sizeof(enabled);
        const auto result =
            getsockopt(int(server.socketDescriptor()), SOL_SOCKET, entry.first, &enabled, &length);
        value[entry.second] = result == 0 ? enabled : -errno;
    }
    int enabled = -1;
    socklen_t length = sizeof(enabled);
    const auto result =
        getsockopt(int(server.socketDescriptor()), IPPROTO_IPV6, IPV6_V6ONLY, &enabled, &length);
    value["ipv6Only"] = result == 0 ? enabled : -errno;
    return value;
}

// 日期：2026-11-06；实验仅改变新建双栈socket的复用选项，原生绑定失败时保留准确errno。
bool nativeDual(QTcpServer &server, quint16 port, bool reuse, int &error) {
    SocketOwner descriptor(::socket(AF_INET6, SOCK_STREAM, IPPROTO_TCP));
    if (descriptor.descriptor < 0) {
        error = errno;
        return false;
    }
    const int reuseValue = reuse ? 1 : 0;
    const int onlyV6 = 0;
    sockaddr_in6 endpoint{};
#ifdef Q_OS_MACOS
    endpoint.sin6_len = sizeof(endpoint);
#endif
    endpoint.sin6_family = AF_INET6;
    endpoint.sin6_port = htons(port);
    if (setsockopt(descriptor.descriptor, SOL_SOCKET, SO_REUSEADDR, &reuseValue,
                   sizeof(reuseValue)) != 0 ||
        setsockopt(descriptor.descriptor, IPPROTO_IPV6, IPV6_V6ONLY, &onlyV6, sizeof(onlyV6)) !=
            0 ||
        ::bind(descriptor.descriptor, reinterpret_cast<sockaddr *>(&endpoint), sizeof(endpoint)) !=
            0 ||
        ::listen(descriptor.descriptor, 8) != 0) {
        error = errno;
        return false;
    }
    const int accepted = descriptor.descriptor;
    descriptor.descriptor = -1;
    return server.setSocketDescriptor(accepted);
}

// 日期：2026-11-06；对两个自有监听实际建立连接并交换一个字节，记录连接究竟进入哪种协议。
QJsonObject route(QTcpServer &first, QTcpServer &second, const QHostAddress &address,
                  quint16 port) {
    QTcpSocket client;
    client.connectToHost(address, port);
    QJsonObject value{{"address", address.toString()}};
    const bool connected = client.waitForConnected(1000);
    value["connected"] = connected;
    if (!connected) {
        value["error"] = client.errorString();
        return value;
    }
    QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
    if (!first.hasPendingConnections())
        first.waitForNewConnection(10);
    if (second.isListening() && !second.hasPendingConnections())
        second.waitForNewConnection(10);
    QTcpServer *owner = first.hasPendingConnections()    ? &first
                        : second.hasPendingConnections() ? &second
                                                         : nullptr;
    value["owner"] = owner == &first ? "first" : owner == &second ? "second" : "none";
    if (owner) {
        QScopedPointer<QTcpSocket> peer(owner->nextPendingConnection());
        client.write("x", 1);
        client.waitForBytesWritten(1000);
        if (!peer->bytesAvailable())
            peer->waitForReadyRead(1000);
        value["byteVerified"] = peer->readAll() == QByteArray("x");
        peer->abort();
    }
    client.abort();
    return value;
}

// 日期：2026-11-06；每行使用隔离临时端口，分别对照旧Qt/产品及原生复用开关，不修改生产源码。
QJsonObject runCase(bool firstQt, int secondKind) {
    QTcpServer qtFirst;
    dukto::TcpListener productFirst;
    QTcpServer qtSecond;
    dukto::TcpListener productSecond;
    QTcpServer *first = firstQt ? &qtFirst : &productFirst;
    const bool initial = firstQt ? qtFirst.listen(QHostAddress::AnyIPv4)
                                 : productFirst.listen(QHostAddress::AnyIPv4);
    QJsonObject value{{"firstKind", firstQt ? "Qt" : "product"},
                      {"secondKind", secondKind},
                      {"firstBound", initial}};
    if (!initial) {
        value["error"] = first->errorString();
        return value;
    }
    value["firstOptions"] = options(*first);
    const auto port = first->serverPort();
    QTcpServer *second = secondKind == 1 ? &productSecond : &qtSecond;
    int error = 0;
    const bool bound = secondKind == 0   ? qtSecond.listen(QHostAddress::Any, port)
                       : secondKind == 1 ? productSecond.listen(QHostAddress::Any, port)
                                         : nativeDual(qtSecond, port, secondKind == 3, error);
    value["secondBound"] = bound;
    value["nativeError"] = error;
    value["secondOptions"] = options(*second);
    QJsonArray routes;
    for (const auto address : {QHostAddress::LocalHost, QHostAddress::LocalHostIPv6})
        routes.append(route(*first, *second, address, port));
    value["routes"] = routes;
    return value;
}
} // namespace

// 日期：2026-11-06；输出有界诊断数据，结果不冒充修复或正式资格，所有监听随进程关闭。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QJsonArray cases;
    for (bool firstQt : {true, false})
        for (int secondKind = 0; secondKind != 4; ++secondKind)
            cases.append(runCase(firstQt, secondKind));
    const QJsonObject result{
        {"date", "2026-11-06"},
        {"qtVersion", qVersion()},
        {"cases", cases},
        {"secondKinds", QJsonArray{"Qt", "product", "native-no-reuse", "native-reuse"}},
        {"productionModified", false},
        {"releaseQualified", false}};
    const auto bytes = QJsonDocument(result).toJson(QJsonDocument::Indented);
    return std::fwrite(bytes.constData(), 1, size_t(bytes.size()), stdout) == size_t(bytes.size())
               ? 0
               : 1;
}

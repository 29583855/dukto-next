#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QScopedPointer>
#include <QTcpServer>
#include <QTcpSocket>
#include <cerrno>
#include <cstdio>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

namespace {
// 日期：2026-11-06；只读取自有socket复用位，保留Darwin实际返回的非零位值。
int reuse(qintptr descriptor) {
    int value = -1;
    socklen_t length = sizeof(value);
    return getsockopt(int(descriptor), SOL_SOCKET, SO_REUSEADDR, &value, &length) == 0 ? value
                                                                                       : -errno;
}

// 日期：2026-11-06；原生对照在bind前设置选项，Qt模式另在listen后关闭复用，均不修改产品源码。
bool start(QTcpServer &server, int mode) {
    if (mode < 2) {
        if (!server.listen(QHostAddress::AnyIPv4))
            return false;
        if (mode == 1) {
            const int value = 0;
            if (setsockopt(int(server.socketDescriptor()), SOL_SOCKET, SO_REUSEADDR, &value,
                           sizeof(value)) != 0)
                return false;
        }
        return true;
    }
    const auto descriptor = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (descriptor < 0)
        return false;
    const int value = mode == 2 ? 0 : 1;
    sockaddr_in address{};
#ifdef Q_OS_MACOS
    address.sin_len = sizeof(address);
#endif
    address.sin_family = AF_INET;
    if (setsockopt(descriptor, SOL_SOCKET, SO_REUSEADDR, &value, sizeof(value)) != 0 ||
        ::bind(descriptor, reinterpret_cast<sockaddr *>(&address), sizeof(address)) != 0 ||
        ::listen(descriptor, 8) != 0) {
        ::close(descriptor);
        return false;
    }
    return server.setSocketDescriptor(descriptor);
}

// 日期：2026-11-06；正常FIN前读取完整正文，随后关闭监听并尝试原端口立即重启；没有abort替代FIN。
QJsonObject run(int mode, const QHostAddress &secondAddress) {
    QTcpServer first;
    QTcpServer second;
    QJsonObject result{{"mode", mode}, {"secondAddress", secondAddress.toString()}};
    if (!start(first, mode)) {
        result["firstError"] = first.errorString();
        return result;
    }
    const auto port = first.serverPort();
    result["firstReuse"] = reuse(first.socketDescriptor());
    result["secondBound"] = second.listen(secondAddress, port);
    result["secondError"] = second.errorString();
    second.close();
    QTcpSocket client;
    client.connectToHost(QHostAddress::LocalHost, port);
    if (!client.waitForConnected(1000) || !first.waitForNewConnection(1000)) {
        result["connectionError"] = client.errorString();
        return result;
    }
    QScopedPointer<QTcpSocket> peer(first.nextPendingConnection());
    result["acceptedReuse"] = reuse(peer->socketDescriptor());
    const QByteArray payload("graceful restart body");
    const auto written = peer->write(payload);
    peer->flush();
    peer->disconnectFromHost();
    if (peer->state() != QAbstractSocket::UnconnectedState)
        peer->waitForDisconnected(1000);
    if (client.state() != QAbstractSocket::UnconnectedState)
        client.waitForDisconnected(1000);
    result["gracefulClosed"] = peer->state() == QAbstractSocket::UnconnectedState &&
                               client.state() == QAbstractSocket::UnconnectedState;
    result["bodyVerified"] = written == payload.size() && client.readAll() == payload;
    peer.reset();
    first.close();
    QTcpServer restarted;
    result["restartBound"] = restarted.listen(QHostAddress::AnyIPv4, port);
    result["restartError"] = restarted.errorString();
    return result;
}
} // namespace

// 日期：2026-11-06；八组有界独立端口对照选项、后来共享和TIME_WAIT重启，只输出诊断原件。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QJsonArray cases;
    for (int mode = 0; mode < 4; ++mode)
        for (const auto address : {QHostAddress::LocalHost, QHostAddress::Any})
            cases.append(run(mode, address));
    const QJsonObject result{{"date", "2026-11-06"},
                             {"qtVersion", qVersion()},
                             {"modes", QJsonArray{"Qt-default", "Qt-disable-after-listen",
                                                  "native-no-reuse", "native-reuse"}},
                             {"cases", cases},
                             {"productionModifiedByProbe", false},
                             {"releaseQualified", false}};
    const auto bytes = QJsonDocument(result).toJson(QJsonDocument::Indented);
    return std::fwrite(bytes.constData(), 1, size_t(bytes.size()), stdout) == size_t(bytes.size())
               ? 0
               : 1;
}

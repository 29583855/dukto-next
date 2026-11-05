#include "app/avatars.h"
#include <QBuffer>
#include <QImage>
#include <QJsonObject>
#include <QTcpSocket>
#include <QtTest>

class AvatarsTests final : public QObject {
    Q_OBJECT
  private:
    // 日期：2026-11-04；生成有限测试图片，图像验证不依赖真实用户头像。
    QByteArray picture(int width = 64) {
        QImage image(width, 32, QImage::Format_RGB32);
        image.fill(Qt::blue);
        QByteArray bytes;
        QBuffer buffer(&bytes);
        buffer.open(QIODevice::WriteOnly);
        image.save(&buffer, "PNG");
        return bytes;
    }
    // 日期：2026-11-04；独立构造旧版头像端口映射，不共享实现内部 URL。
    QJsonArray peers(quint16 avatarPort) {
        return {QJsonObject{{"id", "fixture"}, {"address", "127.0.0.1"}, {"port", avatarPort - 1}}};
    }
  private slots:
    // 日期：2026-11-04；验证本机编码、同协议下载、无效格式/尺寸及设备移除清理。
    void localAndRemote() {
        Avatars service;
        QVERIFY(service.setLocalImage(picture()));
        const auto previous = service.localPng();
        QVERIFY(!service.setLocalImage("not a picture"));
        QVERIFY(!service.setLocalImage(QByteArray(128 * 1024 + 1, 'x')));
        QVERIFY(!service.setLocalImage(picture(2048)));
        QCOMPARE(service.localPng(), previous);
        QVERIFY(!service.listen(65535));
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        QVERIFY(service.listen(port - 1));
        Avatars client;
        client.synchronize(peers(service.serverPort()));
        QTRY_COMPARE(client.pendingRequests(), 0);
        QCOMPARE(client.image("fixture"), service.localImage());
        client.synchronize({});
        QVERIFY(client.image("fixture").isEmpty());
    }
    // 日期：2026-11-04；拒绝超限、重定向、错误编码、巨大解码尺寸、压缩响应及缓慢服务。
    void rejectsResponses() {
        for (int scenario = 0; scenario < 7; ++scenario) {
            QTcpServer server;
            QVERIFY(server.listen(QHostAddress::LocalHost, 0));
            int connections = 0;
            const auto png = picture(scenario == 3 ? 2048 : 64);
            // 日期：2026-11-04；测试响应端只处理一个有限请求，不访问外部网络。
            connect(
                &server, &QTcpServer::newConnection, &server,
                [this, &server, scenario, png, &connections]() {
                    auto socket = server.nextPendingConnection();
                    ++connections;
                    socket->setReadBufferSize(4096);
                    QObject::connect(socket, &QTcpSocket::disconnected, socket,
                                     &QObject::deleteLater);
                    // 日期：2026-11-04；不同失败场景分别覆盖头部、正文和总截止时间。
                    QObject::connect(
                        socket, &QTcpSocket::readyRead, socket, [socket, scenario, png]() {
                            socket->readAll();
                            if (scenario == 6)
                                return;
                            QByteArray response;
                            if (scenario == 0)
                                response = "HTTP/1.0 200 OK\r\nContent-Length: 131073\r\n\r\n";
                            else if (scenario == 1)
                                response =
                                    "HTTP/1.0 302 Found\r\nLocation: http://127.0.0.1:1/escape\r\n"
                                    "Content-Length: 0\r\n\r\n";
                            else if (scenario == 2)
                                response = "HTTP/1.0 200 OK\r\nContent-Length: 3\r\n\r\nbad";
                            else if (scenario == 4)
                                response = "HTTP/1.0 200 OK\r\n\r\n" + QByteArray(131073, 'x');
                            else
                                response = "HTTP/1.0 200 OK\r\nContent-Length: " +
                                           QByteArray::number(png.size()) +
                                           (scenario == 5 ? "\r\nContent-Encoding: gzip" : "") +
                                           "\r\n\r\n" + png;
                            socket->write(response);
                            socket->disconnectFromHost();
                        });
                });
            Avatars client;
            client.synchronize(peers(server.serverPort()));
            QTRY_COMPARE_WITH_TIMEOUT(client.pendingRequests(), 0, 5000);
            QCOMPARE(connections, 1);
            QVERIFY(client.image("fixture").isEmpty());
        }
    }
    // 日期：2026-11-04；头像服务拒绝未知路径和过长请求，返回后归还连接槽位。
    void rejectsRequests() {
        Avatars service;
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        QVERIFY(service.listen(port - 1));
        for (int scenario = 0; scenario < 3; ++scenario) {
            QTcpSocket client;
            QByteArray response;
            // 日期：2026-11-04；由 Qt 事件循环消费实际服务响应，避免阻塞同线程监听器。
            connect(&client, &QTcpSocket::readyRead, &client,
                    [&client, &response]() { response += client.readAll(); });
            client.connectToHost(QHostAddress::LocalHost, port);
            QVERIFY(client.waitForConnected(1000));
            client.write(scenario == 0   ? "GET /wrong HTTP/1.0\r\n\r\n"
                         : scenario == 1 ? QByteArray(2049, 'x')
                                         : QByteArray("GET /partial"));
            client.flush();
            QTRY_COMPARE_WITH_TIMEOUT(client.state(), QAbstractSocket::UnconnectedState, 3000);
            if (scenario == 0)
                QVERIFY(response.startsWith("HTTP/1.0 404"));
            else
                QVERIFY(response.isEmpty());
        }
    }
};

QTEST_GUILESS_MAIN(AvatarsTests)
#include "avatars_tests.moc"

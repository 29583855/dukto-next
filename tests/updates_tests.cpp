#include "core/updates.h"
#include <QSignalSpy>
#include <QTcpServer>
#include <QTcpSocket>
#include <QtTest>

class UpdatesTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；受控回环覆盖版本/JSON/状态/超限，断言保留实际失败反馈供平台诊断。
    void descriptions() {
        for (int scenario = 0; scenario < 6; ++scenario) {
            QTcpServer server;
            QVERIFY(server.listen(QHostAddress::LocalHost, 0));
            // 日期：2026-11-04；只在完整 GET 请求到达后发送固定测试响应。
            connect(&server, &QTcpServer::newConnection, &server, [&server, scenario]() {
                auto client = server.nextPendingConnection();
                client->setReadBufferSize(4096);
                client->connect(client, &QTcpSocket::disconnected, client, &QObject::deleteLater);
                client->connect(client, &QTcpSocket::readyRead, client, [client, scenario]() {
                    client->readAll();
                    QByteArray body;
                    if (scenario == 0)
                        body =
                            R"({"schema":1,"version":"1.0.0","url":"https://example.com/releases"})";
                    else if (scenario == 1)
                        body =
                            R"({"schema":1,"version":"0.1.0","url":"https://example.com/releases"})";
                    else if (scenario == 2)
                        body =
                            R"({"schema":1,"version":"1.0.0junk","url":"https://example.com/releases"})";
                    else if (scenario == 3)
                        body = "not json";
                    else if (scenario == 4)
                        body = QByteArray(65536, 'x');
                    else
                        body = "unavailable";
                    const auto status = scenario == 5 ? "503 Unavailable" : "200 OK";
                    client->write(QByteArray("HTTP/1.1 ") + status +
                                  "\r\nContent-Length: " + QByteArray::number(body.size()) +
                                  "\r\nConnection: close\r\n\r\n" + body);
                    client->disconnectFromHost();
                });
            });
            dukto::Updates updates;
            QSignalSpy completed(&updates, &dukto::Updates::completed);
            updates.check(QUrl(QString("http://127.0.0.1:%1/version").arg(server.serverPort())));
            QTRY_COMPARE(completed.count(), 1);
            QVERIFY2(completed[0][0].toBool() == (scenario == 0),
                     qPrintable(completed[0][3].toString()));
            if (scenario == 0)
                QCOMPARE(completed[0][1].toString(), QString("1.0.0"));
            if (scenario >= 2)
                QVERIFY(!completed[0][3].toString().contains(QStringLiteral("已是最新")));
        }
    }
    // 日期：2026-11-04；不安全的远程 HTTP、空配置和慢速服务均明确失败，不产生更新链接。
    void invalidAndTimeout() {
        dukto::Updates updates;
        QSignalSpy completed(&updates, &dukto::Updates::completed);
        updates.check(QUrl("http://example.com/version"));
        QCOMPARE(completed.count(), 1);
        QVERIFY(!completed.takeFirst()[0].toBool());
        QTcpServer server;
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        updates.check(QUrl(QString("http://127.0.0.1:%1/version").arg(server.serverPort())), 30);
        QTRY_COMPARE(completed.count(), 1);
        QVERIFY(completed[0][3].toString().contains(QStringLiteral("超时")));
    }
};

QTEST_GUILESS_MAIN(UpdatesTests)
#include "updates_tests.moc"

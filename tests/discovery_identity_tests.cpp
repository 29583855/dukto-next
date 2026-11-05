#include "core/discovery.h"
#include <QNetworkDatagram>
#include <QTest>
#include <QtEndian>

class DiscoveryIdentityTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；真实 UDP 回复必须立即反映用户改名，原端口与 R6 编码保持兼容。
    void announcedIdentityRefreshesAndIgnoresSelf() {
        QUdpSocket reservation;
        QVERIFY(reservation.bind(QHostAddress(QHostAddress::LocalHost), 0));
        const auto port = reservation.localPort();
        reservation.close();
        dukto::Discovery discovery;
        QVERIFY(discovery.start(port, "identity-first"));
        QUdpSocket sender;
        QVERIFY(sender.bind(QHostAddress(QHostAddress::LocalHost), 0));
        QByteArray request(3, '\0');
        request[0] = '\x04';
        qToLittleEndian(sender.localPort(), reinterpret_cast<uchar *>(request.data() + 1));
        request += "identity-remote at station (Linux)";
        QVERIFY(sender.writeDatagram(request, QHostAddress::LocalHost, port) > 0);
        QTRY_VERIFY_WITH_TIMEOUT(sender.hasPendingDatagrams(), 3000);
        auto reply = sender.receiveDatagram(1024).data();
        QVERIFY(reply.size() > 3);
        QCOMPARE(static_cast<unsigned char>(reply[0]), static_cast<unsigned char>(5));
        QCOMPARE(qFromLittleEndian<quint16>(reinterpret_cast<const uchar *>(reply.constData() + 1)),
                 port);
        QVERIFY(reply.mid(3).startsWith("identity-first at "));
        // 日期：2026-11-05；广播端口可能收到真实设备回复，只核对本测试的唯一身份。
        const auto observedNames = [&discovery]() {
            QStringList names;
            for (const auto &value : discovery.peers()) {
                const auto name = value.toObject()["name"].toString();
                if (name.startsWith("identity-"))
                    names.append(name);
            }
            return names;
        };
        QTRY_COMPARE(observedNames(), QStringList{"identity-remote"});

        discovery.setUsername(QStringLiteral("identity-中文-after"));
        QVERIFY(sender.writeDatagram(request, QHostAddress::LocalHost, port) > 0);
        QTRY_VERIFY_WITH_TIMEOUT(sender.hasPendingDatagrams(), 3000);
        reply = sender.receiveDatagram(1024).data();
        QVERIFY(reply.size() > 3);
        QVERIFY(reply.mid(3).startsWith(QStringLiteral("identity-中文-after at ").toUtf8()));
        discovery.announce();
        QVERIFY(sender.writeDatagram(reply, QHostAddress::LocalHost, port) > 0);
        QTest::qWait(50);
        QCOMPARE(observedNames(), QStringList{"identity-remote"});
    }
};

QTEST_GUILESS_MAIN(DiscoveryIdentityTests)
#include "discovery_identity_tests.moc"

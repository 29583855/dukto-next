#include "discovery.h"
#include <QtTest>
class CoreTests final : public QObject {
 Q_OBJECT
 private slots:
 // 日期：2026-11-06；以下两个方法原字节提取，使用真实UDP与原门槛。
    void discoveryYieldsAndRejectsMalformedGoodbye() {
        QUdpSocket reservation;
        QVERIFY(reservation.bind(QHostAddress(QHostAddress::LocalHost), 0));
        const auto port = reservation.localPort();
        reservation.close();
        dukto::Discovery discovery;
        QVERIFY(discovery.start(port, "bounded-discovery-test"));
        QUdpSocket sender;
        QVERIFY(sender.bind(QHostAddress(QHostAddress::LocalHost), 0));
        const QByteArray hello = QByteArray(1, '\x02') + "yield-probe at station (Linux)";
        const auto present = [&]() {
            // 日期：2026-11-05；只检查本测试签名，不把真实网络上的其他设备计入断言。
            for (const auto &value : discovery.peers())
                if (value.toObject()["name"] == "yield-probe")
                    return true;
            return false;
        };
        sender.writeDatagram(hello, QHostAddress::LocalHost, port);
        QTRY_VERIFY(present());
        sender.writeDatagram(QByteArray(1, '\x03') + "invalid-body", QHostAddress::LocalHost, port);
        QTest::qWait(20);
        QVERIFY(present());
        int changes = 0;
        int observedAtTimer = -1;
        bool previous = true;
        connect(&discovery, &dukto::Discovery::changed, this, [&]() {
            // 日期：2026-11-05；每个变更立即递交下一真实数据包，模拟持续有新消息的接收队列。
            const auto current = present();
            if (current == previous)
                return;
            previous = current;
            ++changes;
            if (changes == 1)
                QTimer::singleShot(0, &discovery, [&]() {
                    // 日期：2026-11-05；计时器应在连锁完全排空之前被事件循环处理。
                    observedAtTimer = changes;
                });
            if (changes < 5000)
                sender.writeDatagram(current ? QByteArray(1, '\x03') : hello,
                                     QHostAddress::LocalHost, port);
        });
        sender.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
        QTRY_VERIFY_WITH_TIMEOUT(observedAtTimer >= 0, 5000);
        QVERIFY(observedAtTimer < 5000);
        QTRY_COMPARE_WITH_TIMEOUT(changes, 5000, 10000);
    }

    // 日期：2026-11-04；用两个真实 UDP 地址模拟多网卡，退出其中一张网卡不能删除整台设备。
    void discoveryAggregatesAddresses() {
        QUdpSocket reserve;
        QVERIFY(reserve.bind(QHostAddress(QHostAddress::LocalHost), 0));
        const auto port = reserve.localPort();
        reserve.close();
        dukto::Discovery discovery;
        QVERIFY(discovery.start(port, "test-self"));
        QUdpSocket first;
        QUdpSocket second;
        QVERIFY(first.bind(QHostAddress("127.0.0.1"), 0));
        QVERIFY(second.bind(QHostAddress("127.0.0.2"), 0));
        const QByteArray hello = QByteArray(1, '\x02') + "test at station (Linux)";
        first.writeDatagram(hello, QHostAddress::LocalHost, port);
        second.writeDatagram(hello, QHostAddress::LocalHost, port);
        // 日期：2026-11-04；真实局域网可能同时回包，仅检查此测试签名，避免环境干扰。
        const auto peer = [&discovery]() {
            for (const auto &value : discovery.peers())
                if (value.toObject()["name"] == "test")
                    return value.toObject();
            return QJsonObject();
        };
        QTRY_COMPARE(peer()["addresses"].toArray().size(), 2);
        first.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
        QTRY_COMPARE(peer()["addresses"].toArray().size(), 1);
        QCOMPARE(peer()["address"].toString(), QString("127.0.0.2"));
        second.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
        QTRY_VERIFY(peer().isEmpty());
    }
};
QTEST_GUILESS_MAIN(CoreTests)
#include "probe.moc"

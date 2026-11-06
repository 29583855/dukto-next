#include "discovery.h"
#include <QCoreApplication>
#include <QDebug>
#include <QJsonDocument>
#include <QTimer>
#include <QUdpSocket>

// 日期：2026-11-06；两个真实回环源模拟原聚合测试，原接收逻辑仅附加诊断日志。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QUdpSocket reserve, first, second;
    if (!reserve.bind(QHostAddress(QHostAddress::LocalHost), 0)) return 2;
    const auto port = reserve.localPort();
    reserve.close();
    dukto::Discovery discovery;
    if (!discovery.start(port, "diagnostic-self")) return 3;
    if (!first.bind(QHostAddress("127.0.0.1"), 0) || !second.bind(QHostAddress("127.0.0.2"), 0)) return 4;
    QObject::connect(&discovery, &dukto::Discovery::changed, &app, [&]() {
        // 日期：2026-11-06；每次真实设备表变更保留完整有界快照。
        qInfo().noquote() << "PEERS" << QJsonDocument(discovery.peers()).toJson(QJsonDocument::Compact);
    });
    const auto hello = QByteArray(1, '\x02') + "test at station (Linux)";
    first.writeDatagram(hello, QHostAddress::LocalHost, port);
    second.writeDatagram(hello, QHostAddress::LocalHost, port);
    QTimer::singleShot(300, &app, [&]() {
        // 日期：2026-11-06；先删除第一地址，再单独发送第二地址退出。
        qInfo() << "GOODBYE1" << first.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
    });
    QTimer::singleShot(600, &app, [&]() {
        // 日期：2026-11-06；与原测试相同的单字节Goodbye，记录内核接受长度。
        qInfo() << "GOODBYE2" << second.writeDatagram(QByteArray(1, '\x03'), QHostAddress::LocalHost, port);
    });
    QTimer::singleShot(1500, &app, &QCoreApplication::quit);
    app.exec();
    qInfo().noquote() << "FINAL" << QJsonDocument(discovery.peers()).toJson(QJsonDocument::Compact);
    return 0;
}

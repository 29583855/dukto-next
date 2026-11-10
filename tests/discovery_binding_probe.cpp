#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTextStream>
#include <QUdpSocket>

// 日期：2026-11-10；真实复现原版Any默认绑定，逐项记录IPv4/双栈及复用模式，探针只作定位。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QJsonArray results;
    for (const auto &address :
         {QHostAddress(QHostAddress::AnyIPv4), QHostAddress(QHostAddress::Any)}) {
        for (const auto flags : {QUdpSocket::BindMode(QUdpSocket::DefaultForPlatform),
                                 QUdpSocket::BindMode(QUdpSocket::ShareAddress),
                                 QUdpSocket::BindMode(QUdpSocket::ReuseAddressHint),
                                 QUdpSocket::ShareAddress | QUdpSocket::ReuseAddressHint}) {
            QUdpSocket original;
            const bool originalBound = original.bind(QHostAddress(QHostAddress::Any), 4644);
            QUdpSocket candidate;
            const bool bound = candidate.bind(address, 4644, flags);
            results.append(QJsonObject{{"originalBound", originalBound},
                                       {"address", address.toString()},
                                       {"flags", static_cast<int>(flags)},
                                       {"bound", bound},
                                       {"error", candidate.errorString()}});
        }
    }
    QTextStream(stdout) << QJsonDocument(results).toJson(QJsonDocument::Indented);
    return 0;
}

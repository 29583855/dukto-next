#include <QCoreApplication>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSslCertificate>
#include <QSslConfiguration>
#include <QSslSocket>
#include <QTextStream>

// 日期：2026-11-04；连接本地受信测试服务，实际验证证书/主机名及 TLS 双向数据。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto args = app.arguments();
    if (args.size() != 5)
        return 2;
    QFile certificate(args[1]);
    if (!certificate.open(QIODevice::ReadOnly))
        return 2;
    QSslSocket socket;
    auto configuration = socket.sslConfiguration();
    configuration.setCaCertificates(QSslCertificate::fromData(certificate.readAll()));
    socket.setSslConfiguration(configuration);
    socket.setPeerVerifyMode(QSslSocket::VerifyPeer);
    socket.setPeerVerifyName(args[3]);
    socket.setReadBufferSize(1024);
    socket.connectToHostEncrypted("127.0.0.1", args[2].toUShort());
    const bool encrypted = socket.waitForEncrypted(5000);
    const bool expectFailure = args[4] == "reject";
    bool passed = false;
    if (expectFailure)
        passed = !encrypted && !socket.sslHandshakeErrors().isEmpty();
    else if (encrypted && socket.write("dukto-tls-probe") == 15 &&
             socket.waitForBytesWritten(2000)) {
        if (socket.bytesAvailable() || socket.waitForReadyRead(3000))
            passed = socket.read(1024) == "dukto-tls-probe";
    }
    const QJsonObject result{{"passed", passed},
                             {"encrypted", encrypted},
                             {"expectedRejection", expectFailure},
                             {"protocol", static_cast<int>(socket.sessionProtocol())},
                             {"tlsRuntime", QSslSocket::sslLibraryVersionString()}};
    QTextStream(stdout) << QJsonDocument(result).toJson(QJsonDocument::Compact) << '\n';
    return passed ? 0 : 1;
}

#include "core/error.h"
#include "core/identity.h"
#include "core/securechannel.h"

#include <QCoreApplication>
#include <QFile>
#include <QJsonDocument>
#include <QSslCertificate>
#include <QSslKey>
#include <QTcpServer>
#include <QTextStream>
#include <QThread>
#include <QTimer>
#include <atomic>

namespace {
// 日期：2026-11-04；测试只输出非敏感 JSON，不回显证书、密钥或远端原始正文。
void output(const QJsonObject &object) {
    QTextStream stream(stdout);
    stream.setCodec("UTF-8");
    stream << QJsonDocument(object).toJson(QJsonDocument::Compact) << '\n';
    stream.flush();
}

// 日期：2026-11-04；证书/私钥只从隔离测试文件加载，读取上限固定为 64 KiB。
QByteArray readFile(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("测试材料读取失败"), "test");
    return file.read(65536);
}

class Server final : public QTcpServer {
  public:
    QSslConfiguration configuration;
    int result = 1;
    // 日期：2026-11-04；独立 Python TLS 客户端验证生产服务握手/分帧实现，测试只处理一个连接。
    void incomingConnection(qintptr descriptor) override {
        close();
        try {
            dukto::next::SecureChannel channel(3000);
            channel.accept(descriptor, configuration);
            const auto frame = channel.read();
            if (frame.header.type != dukto::next::Type::Hello || frame.header.correlation != 7 ||
                dukto::next::parseControl(frame.payload)["test"] != "independent-client")
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("测试请求不匹配"),
                                   "test");
            channel.write(dukto::next::Type::HelloAck, 7, {{"test", "server-accepted"}});
            result = 0;
            output({{"event", "result"}, {"passed", true}});
        } catch (const dukto::Error &error) {
            output(error.json());
        }
        QCoreApplication::quit();
    }
};
} // namespace

// 日期：2026-11-04；以生产 SecureChannel 实际连接独立 Python TLS 对端，失败用统一错误码报告。
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto args = app.arguments();
    QElapsedTimer elapsed;
    elapsed.start();
    try {
        if (args.size() == 3 && args[1] == "identity") {
            dukto::PrivateStore store(args[2], true);
            const auto identity = dukto::initializeIdentity(store, {"localhost", "127.0.0.1"});
            output(identity.publicInfo());
            return 0;
        }
        if (args.size() == 4 && args[1] == "server") {
            Server server;
            server.configuration.setLocalCertificate(QSslCertificate(readFile(args[2])));
            server.configuration.setPrivateKey(QSslKey(readFile(args[3]), QSsl::Rsa));
            if (!server.listen(QHostAddress::LocalHost, 0))
                return 1;
            QTimer::singleShot(5000, &app, &QCoreApplication::quit);
            output({{"event", "listening"}, {"port", server.serverPort()}});
            app.exec();
            return server.result;
        }
        if (args.size() != 7 || args[1] != "client")
            return 2;
        auto configuration = QSslConfiguration::defaultConfiguration();
        configuration.setCaCertificates(args[2] == "none"
                                            ? QList<QSslCertificate>()
                                            : QSslCertificate::fromData(readFile(args[2])));
        const QByteArray pin =
            args[5] == "none" ? QByteArray() : QByteArray::fromHex(args[5].toLatin1());
        std::atomic_bool cancelled{false};
        const bool cancel = args[6] == "cancel" || args[6] == "checkpoint-cancel";
        const bool timeout = args[6] == "timeout";
        const int timeoutMs = timeout ? 400 : 3000;
        dukto::next::SecureChannel channel(timeoutMs, &cancelled);
        channel.connectTo("127.0.0.1", args[3].toUShort(), args[4], configuration, pin);
        if (cancel)
            QTimer::singleShot(150, &app, [&cancelled]() {
                // 日期：2026-11-04；测试通过同线程定时器触发生产原子取消路径。
                cancelled.store(true);
            });
        channel.write(dukto::next::Type::Hello, 7,
                      {{"test", "independent-client"}, {"size", "9007199254740993"}});
        if (args[6].startsWith("checkpoint-")) {
            QElapsedTimer work;
            work.start();
            while (work.elapsed() < 2000) {
                // 日期：2026-11-04；模拟没有 read/write 的长扫描，检测远端断开或同线程定时取消。
                channel.checkpoint("scan");
                QThread::msleep(5);
            }
            return 1;
        }
        const auto frame = channel.read();
        if (frame.header.type != dukto::next::Type::HelloAck || frame.header.correlation != 7 ||
            dukto::next::parseControl(frame.payload)["test"] != "server-accepted")
            return 1;
        output({{"passed", true},
                {"elapsedMs", elapsed.elapsed()},
                {"fingerprint", QString::fromLatin1(channel.peerFingerprint().toHex())}});
        return 0;
    } catch (const dukto::Error &error) {
        auto result = error.json();
        result.insert("elapsedMs", elapsed.elapsed());
        output(result);
        return static_cast<int>(error.code);
    }
}

#include "core/error.h"
#include "core/fileexchange.h"
#include "core/files.h"
#include "core/identity.h"
#include "core/service.h"
#include "core/transferprogress.h"
#include <QDir>
#include <QFile>
#include <QTcpServer>
#include <QTemporaryDir>
#include <QThread>
#include <QtTest>
#include <cstdio>

namespace {
const QUuid Task("354dfd1f-b3a9-4779-b4a7-44b54c75d9d5");
constexpr qint64 Bytes = 8 * 1024 * 1024 + 37;

class ExchangeServer final : public QTcpServer {
  public:
    std::function<void(qintptr)> operation;
    QString error;
    // 日期：2026-11-04；测试服务等待自有线程退出，Qt socket 始终在该线程内析构。
    ~ExchangeServer() override {
        if (worker_) {
            worker_->wait();
            delete worker_;
        }
    }
    // 日期：2026-11-04；读取工作结果前完成线程同步，避免并发读写错误文本。
    bool done() {
        return worker_ && worker_->wait(10000);
    }

  protected:
    // 日期：2026-11-04；只接收测试自有的一个连接，真实传输核心在独立工作线程内运行。
    void incomingConnection(qintptr descriptor) override {
        close();
        worker_ = QThread::create([this, descriptor]() {
            // 日期：2026-11-04；记录核心错误供主测试线程断言，不在线程外碰 socket。
            try {
                operation(descriptor);
            } catch (const dukto::Error &failure) {
                error = failure.stage + ": " + failure.message;
            }
        });
        worker_->start();
    }

  private:
    QThread *worker_ = nullptr;
};

// 日期：2026-11-04；接收端清单只从公开分页字段导入，不使用发送端本机源路径。
void importManifest(dukto::StrongManifest &source, dukto::StrongManifest &destination) {
    const auto entry = source.entry(1);
    destination.append({entry.id, entry.relative, "", entry.directory, entry.bytes, entry.sha256});
    for (const auto &value : source.blocks(1)) {
        const auto block = value.toObject();
        destination.appendBlock(1, block["block"].toString().toULongLong(),
                                block["bytes"].toString().toLongLong(),
                                QByteArray::fromHex(block["sha256"].toString().toLatin1()));
    }
    destination.seal(QByteArray::fromHex(source.summary()["sha256"].toString().toLatin1()));
}
} // namespace

class FileExchangeTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-05；双向初始、就绪和最终三处完成确认均覆盖合法总计及八类畸形字段。
    void completedSummary_data() {
        QTest::addColumn<bool>("download");
        QTest::addColumn<int>("stage");
        QTest::addColumn<int>("attack");
        const char *fields[] = {"valid",        "manifest",      "total",
                                "bytes",        "entries",       "error",
                                "desired",      "numeric-total", "missing-manifest",
                                "local-corrupt"};
        for (bool download : {false, true})
            for (int stage = 0; stage < 3; ++stage)
                for (int attack = -1; attack < (download && stage < 2 ? 9 : 8); ++attack) {
                    const auto name = QString("%1-%2-%3")
                                          .arg(download ? "download" : "upload")
                                          .arg(stage)
                                          .arg(fields[attack + 1])
                                          .toLatin1();
                    QTest::newRow(name.constData()) << download << stage << attack;
                }
    }

    // 日期：2026-11-05；真实 TLS 认证对端更改完成总计，不得成功返回或让未经验证的完成态进入 GUI。
    void completedSummary() {
        QFETCH(bool, download);
        QFETCH(int, stage);
        QFETCH(int, attack);
        QTemporaryDir temporary;
        const auto sourcePath = temporary.filePath("data.bin");
        const QByteArray contents(4099, 'c');
        QFile sourceFile(sourcePath);
        QVERIFY(sourceFile.open(QIODevice::WriteOnly));
        QCOMPARE(sourceFile.write(contents), qint64(contents.size()));
        sourceFile.close();
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        dukto::PrivateStore sourceStore(temporary.filePath("source"), true);
        dukto::StrongManifest source(sourceStore, "manifest.sqlite", true);
        source.scan({sourcePath});
        const auto summary = source.summary();
        const auto hash = QByteArray::fromHex(summary["sha256"].toString().toLatin1());
        dukto::PrivateStore local(temporary.filePath("local"), true);
        if (download && stage < 2) {
            const auto key = Task.toString(QUuid::WithoutBraces);
            dukto::StrongManifest cached(local, "download-" + key + ".sqlite", true);
            importManifest(source, cached);
            {
                dukto::DurableReceive receiver(local, "receive-" + key + ".sqlite", Task, cached,
                                               output);
                receiver.open(1, receiver.prepare(1));
                receiver.write(0, 0, contents);
                QCOMPARE(receiver.finish(), QString("data.bin"));
            }
            if (attack == 8) {
                QFile corrupt(output + "/data.bin");
                QVERIFY(corrupt.open(QIODevice::WriteOnly));
                QCOMPARE(corrupt.write(QByteArray(contents.size(), 'z')), qint64(contents.size()));
            }
        }
        dukto::PrivateStore identityStore(temporary.filePath("identity"), true);
        const auto identity = dukto::initializeIdentity(identityStore, {"127.0.0.1"});
        const auto clientId = QUuid::createUuid();
        const auto requestId = QUuid::createUuid();
        QJsonObject result{{"taskId", Task.toString(QUuid::WithoutBraces)},
                           {"requestId", requestId.toString(QUuid::WithoutBraces)},
                           {"direction", download ? "download" : "upload"},
                           {"share", "data"},
                           {"path", ""},
                           {"state", "completed"},
                           {"desired", ""},
                           {"revision", "3"},
                           {"manifest", summary["sha256"]},
                           {"bytes", summary["bytes"]},
                           {"total", summary["bytes"]},
                           {"entries", summary["entries"]},
                           {"error", 0},
                           {"message", ""}};
        if (attack == 0)
            result["manifest"] = QString(64, '0');
        if (attack == 1) {
            result["total"] = "4100";
            result["bytes"] = "4100";
        }
        if (attack == 2)
            result["bytes"] = "4098";
        if (attack == 3)
            result["entries"] = "2";
        if (attack == 4)
            result["error"] = 6;
        if (attack == 5)
            result["desired"] = "cancel";
        if (attack == 6)
            result["total"] = 4099;
        if (attack == 7)
            result.remove("manifest");
        ExchangeServer server;
        server.operation = [&](qintptr descriptor) {
            // 日期：2026-11-05；测试服务只声明基础能力，每次响应沿用真实请求序号及生产 TLS 帧。
            dukto::next::SecureChannel peer(5000);
            peer.accept(descriptor, identity.configuration());
            const auto hello = peer.read();
            peer.write(dukto::next::Type::HelloAck, hello.header.correlation,
                       {{"version", "1.0"},
                        {"serverId", identity.id.toString(QUuid::WithoutBraces)},
                        {"capabilities", QJsonArray{}}});
            const auto authentication = peer.read();
            peer.write(dukto::next::Type::Authenticated, authentication.header.correlation,
                       dukto::Principal{clientId, 1, {{"data", true, true, true}}}.publicInfo());
            const auto create = peer.read();
            const auto correlation = create.header.correlation;
            dukto::PrivateStore store(sourceStore.directory());
            if (stage == 0) {
                peer.write(dukto::next::Type::Task, correlation, result);
            } else {
                auto initial = result;
                initial["state"] = "scanning";
                initial["needManifest"] = true;
                peer.write(dukto::next::Type::Task, correlation, initial);
                if (!download) {
                    dukto::StrongManifest incoming(store, "incoming.sqlite", true);
                    dukto::receiveStrongManifest(peer, Task, incoming, hash, correlation);
                }
                if (stage == 1) {
                    peer.write(dukto::next::Type::TaskState, correlation, result);
                } else {
                    auto ready = initial;
                    ready["state"] = "transferring";
                    ready["manifestInfo"] = summary;
                    peer.write(dukto::next::Type::Task, correlation, ready);
                    if (download) {
                        dukto::StrongManifest sender(store, "manifest.sqlite", false);
                        dukto::sendStrongManifest(peer, Task, sender, correlation);
                        dukto::sendStrongTree(peer, Task, sender, correlation);
                    } else {
                        dukto::StrongManifest incoming(store, "incoming.sqlite", false);
                        dukto::DurableReceive receiver(store, "receive.sqlite", Task, incoming,
                                                       output);
                        dukto::receiveStrongTree(peer, Task, incoming, receiver, correlation);
                    }
                    peer.write(dukto::next::Type::TaskState, correlation, result);
                }
            }
            if (download && stage < 2) {
                const auto close = peer.read();
                if (close.header.type != dukto::next::Type::Close)
                    throw dukto::Error(dukto::ExitCode::Config, "close", "test");
                peer.write(dukto::next::Type::Closed, close.header.correlation, {});
            }
        };
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        const dukto::ClientProfile profile{"test",
                                           "127.0.0.1",
                                           server.serverPort(),
                                           "127.0.0.1",
                                           identity.certificate.digest(QCryptographicHash::Sha256),
                                           identity.id,
                                           clientId,
                                           QByteArray(32, 'x'),
                                           true};
        int completedEvents = 0;
        bool succeeded = false;
        bool rejected = false;
        {
            dukto::RemoteClient client(profile, 5000);
            client.authenticate();
            const auto progress = [&](const QJsonObject &event) {
                // 日期：2026-11-05；只有全部总计与本地文件核验通过后才能把完成态交给使用者。
                if (event["state"] == "completed")
                    ++completedEvents;
            };
            try {
                const auto actual =
                    download ? client.download(requestId, "data", "", local, output, progress)
                             : client.upload(requestId, "data", "", source, progress);
                succeeded = actual["state"] == "completed";
            } catch (const dukto::Error &error) {
                rejected = error.code == dukto::ExitCode::Integrity;
            }
        }
        QVERIFY(server.done());
        QVERIFY2(server.error.isEmpty(), qPrintable(server.error));
        QCOMPARE(succeeded, attack == -1);
        QCOMPARE(rejected, attack != -1);
        QCOMPARE(completedEvents, attack == -1 && stage < 2 ? 1 : 0);
        if (attack == -1 && (download || stage == 2))
            QCOMPARE(dukto::hashFile(output + "/data.bin"), source.entry(1).sha256);
    }

    // 日期：2026-11-05；不可信进度不能越权、回退、换清单或在未协商阶段被当作普通心跳。
    void rejectedProgress_data() {
        QTest::addColumn<int>("attack");
        const char *names[] = {"task",           "manifest",          "correlation", "regression",
                               "over-confirmed", "extra-field",       "numeric",     "total",
                               "unnegotiated",   "restore-regression"};
        for (int index = 0; index < 10; ++index)
            QTest::newRow(names[index]) << index;
    }

    // 日期：2026-11-05；通过真实 TLS 报送一条合法快照后注入错误，观察者验证失败必须终止连接。
    void rejectedProgress() {
        QFETCH(int, attack);
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("identity"), true);
        const auto service = dukto::initializeIdentity(store, {"127.0.0.1"});
        const QByteArray manifest(32, 'x');
        const QJsonObject initial{{"taskId", Task.toString(QUuid::WithoutBraces)},
                                  {"manifest", QString::fromLatin1(manifest.toHex())},
                                  {"bytes", "16"},
                                  {"confirmed", "8"},
                                  {"restored", "0"},
                                  {"total", "32"}};
        ExchangeServer server;
        server.operation = [&](qintptr descriptor) {
            // 日期：2026-11-05；对端只发送测试自有内容，不绕过生产帧编码和 TLS。
            dukto::next::SecureChannel peer(5000);
            peer.accept(descriptor, service.configuration());
            peer.write(dukto::next::Type::Progress, 1, initial);
            auto invalid = initial;
            if (attack == 0)
                invalid["taskId"] = QUuid::createUuid().toString(QUuid::WithoutBraces);
            if (attack == 1)
                invalid["manifest"] = QString(64, 'a');
            if (attack == 3)
                invalid["bytes"] = "8";
            if (attack == 4)
                invalid["confirmed"] = "17";
            if (attack == 5)
                invalid["extra"] = true;
            if (attack == 6)
                invalid["bytes"] = 16;
            if (attack == 7)
                invalid["total"] = "33";
            if (attack == 9)
                invalid["restored"] = "4";
            peer.write(dukto::next::Type::Progress, attack == 2 ? 2 : 1, invalid);
            peer.write(dukto::next::Type::Closed, 1, {});
        };
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        dukto::next::SecureChannel channel(5000);
        channel.connectTo("127.0.0.1", server.serverPort(), "127.0.0.1",
                          QSslConfiguration::defaultConfiguration(),
                          service.certificate.digest(QCryptographicHash::Sha256));
        int accepted = 0;
        dukto::TransferProgress progress(channel, 1, Task, manifest, 32, false, attack != 8,
                                         [&](const QJsonObject &) {
                                             // 日期：2026-11-05；错误快照不得进入使用者回调。
                                             ++accepted;
                                         });
        bool rejected = false;
        try {
            channel.read();
        } catch (const dukto::Error &error) {
            rejected = error.stage == "progress" || error.stage == "protocol";
        }
        QVERIFY(rejected);
        QCOMPARE(accepted, attack == 8 ? 0 : 1);
        QVERIFY(server.done());
    }

    // 日期：2026-11-04；客户端始终主动连接，分别覆盖双向数据和已有块恢复。
    void encryptedRoundtrip_data() {
        QTest::addColumn<bool>("download");
        QTest::addColumn<bool>("resume");
        QTest::addColumn<bool>("slow");
        QTest::newRow("client-sends") << false << false << false;
        QTest::newRow("server-sends") << true << false << false;
        QTest::newRow("client-resumes") << false << true << false;
        QTest::newRow("server-resumes") << true << true << false;
        QTest::newRow("slow-upload-recovery") << false << true << true;
        QTest::newRow("slow-download-recovery") << true << true << true;
    }

    // 日期：2026-11-04；真实 TLS 发送两整块加尾块，逐块确认、全摘要和持久命名均走生产实现。
    void encryptedRoundtrip() {
        QFETCH(bool, download);
        QFETCH(bool, resume);
        QFETCH(bool, slow);
        QTemporaryDir temporary;
        const auto path = temporary.filePath("data.bin");
        QFile data(path);
        QVERIFY(data.open(QIODevice::WriteOnly));
        for (qint64 offset = 0; offset < Bytes; offset += dukto::BufferSize)
            dukto::writeAll(
                data, QByteArray(static_cast<int>(qMin(dukto::BufferSize, Bytes - offset)), 'x'));
        data.close();
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        dukto::PrivateStore sourceStore(temporary.filePath("source"), true);
        dukto::PrivateStore destinationStore(temporary.filePath("destination"), true);
        dukto::StrongManifest source(sourceStore, "manifest.sqlite", true);
        source.scan({path});
        dukto::StrongManifest destination(destinationStore, "manifest.sqlite", true);
        importManifest(source, destination);
        if (resume) {
            dukto::DurableReceive receiver(destinationStore, "receive.sqlite", Task, destination,
                                           temporary.filePath("output"));
            receiver.open(1, "data.bin");
            for (int index = 0; index < 16; ++index)
                receiver.write(0, index * dukto::BufferSize, QByteArray(dukto::BufferSize, 'x'));
        }
        dukto::PrivateStore identityStore(temporary.filePath("identity"), true);
        const auto identity = dukto::initializeIdentity(identityStore, {"127.0.0.1"});
        ExchangeServer server;
        const auto receiverCheck = [&]() {
            // 日期：2026-11-04；模拟每片段慢读，使累计恢复/全文件校验显著长于网络帧超时。
            if (slow)
                QThread::msleep(100);
        };
        server.operation = [&, download](qintptr descriptor) {
            // 日期：2026-11-04；每个线程重新打开自己的 SQLite 连接，私有存储对象不跨线程使用。
            dukto::PrivateStore store(download ? sourceStore.directory()
                                               : destinationStore.directory());
            dukto::StrongManifest manifest(store, "manifest.sqlite", false);
            dukto::next::SecureChannel channel(slow ? 1500 : 5000);
            channel.accept(descriptor, identity.configuration());
            if (download) {
                dukto::sendStrongManifest(channel, Task, manifest, 1);
                dukto::sendStrongFile(channel, Task, manifest, 1, 2);
            } else {
                dukto::StrongManifest wire(store, "wire.sqlite", true);
                dukto::receiveStrongManifest(
                    channel, Task, wire,
                    QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1()), 1);
                dukto::DurableReceive receiver(store, "receive.sqlite", Task, wire,
                                               temporary.filePath("output"));
                dukto::receiveStrongFile(channel, Task, wire, receiver, 1, "data.bin", 2,
                                         receiverCheck);
            }
            const auto close = channel.read();
            if (close.header.type != dukto::next::Type::Close)
                throw dukto::Error(dukto::ExitCode::Config, "close", "test");
            channel.write(dukto::next::Type::Closed, 3, {});
        };
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        dukto::next::SecureChannel channel(slow ? 1500 : 5000);
        channel.connectTo("127.0.0.1", server.serverPort(), "127.0.0.1",
                          QSslConfiguration::defaultConfiguration(),
                          identity.certificate.digest(QCryptographicHash::Sha256));
        QString result;
        QElapsedTimer elapsed;
        elapsed.start();
        if (download) {
            dukto::StrongManifest wire(destinationStore, "wire.sqlite", true);
            dukto::receiveStrongManifest(
                channel, Task, wire,
                QByteArray::fromHex(destination.summary()["sha256"].toString().toLatin1()), 1);
            dukto::DurableReceive receiver(destinationStore, "receive.sqlite", Task, wire,
                                           temporary.filePath("output"));
            result = dukto::receiveStrongFile(channel, Task, wire, receiver, 1, "data.bin", 2,
                                              receiverCheck);
        } else {
            dukto::sendStrongManifest(channel, Task, source, 1);
            result = dukto::sendStrongFile(channel, Task, source, 1, 2);
        }
        channel.write(dukto::next::Type::Close, 3, {});
        QCOMPARE(channel.read().header.type, dukto::next::Type::Closed);
        QVERIFY(server.done());
        QVERIFY2(server.error.isEmpty(), qPrintable(server.error));
        if (slow)
            QVERIFY(elapsed.elapsed() > 3000);
        QCOMPARE(result, QString("data.bin"));
        QCOMPARE(dukto::hashFile(temporary.filePath("output/data.bin")), source.entry(1).sha256);
        QCOMPARE(QDir(temporary.filePath("output")).entryList(QDir::Files | QDir::Hidden),
                 QStringList{"data.bin"});
    }
};

// 日期：2026-11-04；标准错误保留核心诊断，避免 Windows Qt 日志出口隐藏未捕获异常原因。
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    FileExchangeTests tests;
    try {
        return QTest::qExec(&tests, argc, argv);
    } catch (const dukto::Error &error) {
        const auto diagnostic = (error.stage + ": " + error.message).toUtf8();
        std::fprintf(stderr, "%s\n", diagnostic.constData());
        return 32;
    }
}
#include "file_exchange_tests.moc"

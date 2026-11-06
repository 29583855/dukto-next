#include "core/dispositionjournal.h"
#include "core/error.h"
#include "core/fileexchange.h"
#include "core/files.h"
#include "core/identity.h"
#include "core/paralleltransfer.h"
#include "core/service.h"
#include "core/shares.h"
#include "core/taskstore.h"
#include "core/transferdisposition.h"
#include "core/transferprogress.h"
#include "core/transferscheduler.h"
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QJsonDocument>
#include <QProcess>
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
    // 日期：2026-11-06；非阻塞探测供独立服务主线程泵送连接事件，完成后同步错误文本。
    bool completed() {
        return worker_ && worker_->wait(0);
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

// 日期：2026-11-06；独立服务进程拥有监听器与全部数据线程，不与客户机叠加进程内授信。
int parallelDispositionServer(const QString &directory) {
    dukto::PrivateStore setup(directory);
    const auto config = dukto::next::parseControl(setup.read("parallel-fixture.json"));
    const QUuid owner(config["owner"].toString());
    const QUuid task(config["task"].toString());
    const bool download = config["download"].toBool();
    const auto output = config["output"].toString();
    const auto lanes = config["lanes"].toInt();
    const auto scenario = config["scenario"].toInt();
    const auto hash = QByteArray::fromHex(config["manifest"].toString().toLatin1());
    const auto identity = dukto::loadIdentity(setup);
    dukto::TransferScheduler scheduler;
    auto admission =
        std::make_shared<dukto::TransferAdmission>(scheduler, directory, owner, task, lanes, false);
    if (!admission->tryStart())
        throw dukto::Error(dukto::ExitCode::Permission, "fixture admission", "test");
    dukto::ServiceListener listener(directory, 5000);
    if (!listener.listen(QHostAddress::LocalHost, 0))
        throw dukto::Error(dukto::ExitCode::Network, "fixture listen", "test");
    ExchangeServer server;
    server.operation = [&](qintptr descriptor) {
        // 日期：2026-11-06；控制线程独占接收日志，数据线程仍经过生产认证/授权及块分配器。
        dukto::PrivateStore store(directory);
        dukto::StrongManifest incoming(store, "wire.sqlite", true);
        dukto::next::SecureChannel peer(5000);
        peer.accept(descriptor, identity.configuration());
        dukto::receiveStrongManifest(peer, task, incoming, hash, 1);
        std::unique_ptr<dukto::StrongManifest> outgoing;
        if (download)
            outgoing.reset(new dukto::StrongManifest(store, "source.sqlite", false));
        auto &manifest = download ? *outgoing : incoming;
        auto data = dukto::ParallelTransfer::createServer(directory, owner, task, manifest,
                                                          !download, lanes, admission, true);
        peer.write(dukto::next::Type::ChannelTicket, 2, data->ticket());
        dukto::DispositionJournal journal(store, "server-outcome.sqlite", task, manifest, "skip");
        const auto completed = [&](const dukto::StrongEntry &entry,
                                   const dukto::DurableReceive::Preparation &result) {
            // 日期：2026-11-06；结果使用真实持久处置，不用传输字节推测copied。
            journal.append(entry.id, result.path, result.skipped ? "skipped" : "copied",
                           result.skippedRoot);
        };
        if (download) {
            data->sendTree(peer, manifest, 2, {}, completed, true);
        } else {
            bool lateCreated = false;
            dukto::DurableReceive receiver(store, "receive.sqlite", task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            data->receiveTree(
                peer, manifest, receiver, 2,
                [&]() {
                    // 日期：2026-11-06；正文确认后才出现外部目标，验证最终skipped保留原件。
                    if (scenario == 2 && !lateCreated && receiver.confirmed() > 0) {
                        QFile target(output + "/item-00.bin");
                        const QByteArray original("unchanged-original");
                        if (!target.open(QIODevice::WriteOnly) ||
                            target.write(original) != original.size())
                            throw dukto::Error(dukto::ExitCode::Disk, "fixture write", "test");
                        lateCreated = true;
                    }
                },
                completed, nullptr, true);
            store.write("parallel-late.json",
                        dukto::next::encodeControl({{"created", lateCreated}}));
        }
        store.write("parallel-result.json", dukto::next::encodeControl(journal.summary()));
        const auto close = peer.read();
        if (close.header.type != dukto::next::Type::Close || close.header.correlation != 3)
            throw dukto::Error(dukto::ExitCode::Integrity, "close", "test");
        peer.write(dukto::next::Type::Closed, 3, {});
    };
    if (!server.listen(QHostAddress::LocalHost, 0))
        throw dukto::Error(dukto::ExitCode::Network, "fixture control listen", "test");
    const auto ports = dukto::next::encodeControl(
        {{"controlPort", int(server.serverPort())}, {"dataPort", int(listener.serverPort())}});
    std::fprintf(stdout, "%s\n", ports.constData());
    std::fflush(stdout);
    QElapsedTimer deadline;
    deadline.start();
    while (!server.completed()) {
        if (deadline.elapsed() > 30000)
            throw dukto::Error(dukto::ExitCode::Network, "fixture deadline", "test");
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(1);
    }
    if (!server.error.isEmpty())
        throw dukto::Error(dukto::ExitCode::Integrity, server.error, "fixture-server");
    listener.stop();
    return 0;
}

} // namespace

class FileExchangeTests final : public QObject {
    Q_OBJECT
  private slots:

    // 日期：2026-11-06；数据先退出后控制才发送失败；真实TLS必须保留远端磁盘根因。
    void remoteFailureAfterLaneDisconnect_data() {
        QTest::addColumn<int>("reported");
        QTest::newRow("disk") << 5;
        QTest::newRow("permission") << 4;
        QTest::newRow("explicit-control-cancellation") << 7;
        QTest::newRow("abrupt-control") << 0;
        QTest::newRow("wrong-correlation") << -1;
        QTest::newRow("invalid-failure") << -2;
        QTest::newRow("ordinary-confirmation") << -3;
        QTest::newRow("busy-deadline") << -4;
    }

    // 日期：2026-11-06；源清单和每条握手独立构造，断线不能被当作成功或吞掉终态错误。
    void remoteFailureAfterLaneDisconnect() {
        QFETCH(int, reported);
        QTemporaryDir temporary;
        QFile source(temporary.filePath("data.bin"));
        QVERIFY(source.open(QIODevice::WriteOnly));
        QCOMPARE(source.write("body"), qint64(4));
        source.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.scan({source.fileName()});
        const auto hash = QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1());
        const auto service = dukto::initializeIdentity(store, {"127.0.0.1"});
        const auto client = QUuid::createUuid();
        const auto session = QUuid::createUuid().toString(QUuid::WithoutBraces);
        const QJsonObject ticket{{"sessionId", session},
                                 {"taskId", Task.toString(QUuid::WithoutBraces)},
                                 {"manifest", QString::fromLatin1(hash.toHex())},
                                 {"token", QString(64, 'a')},
                                 {"lanes", "1"}};
        // 日期：2026-11-06；阶段耗时独立留档；原两秒通道预算不变，失败计时从数据断开开始。
        QElapsedTimer timeline;
        timeline.start();
        std::atomic<qint64> disconnectedAt{-1};
        std::atomic_bool disconnected{false};
        ExchangeServer lane;
        lane.operation = [&](qintptr descriptor) {
            // 日期：2026-11-06；TLS认证和加入完成后先关闭数据连接，控制错误此时尚未发出。
            {
                dukto::next::SecureChannel peer(2000);
                qInfo() << "terminal fixture lane TLS begin" << timeline.elapsed();
                peer.accept(descriptor, service.configuration());
                qInfo() << "terminal fixture lane TLS ready" << timeline.elapsed();
                const auto hello = peer.read();
                peer.write(dukto::next::Type::HelloAck, hello.header.correlation,
                           {{"version", "1.0"},
                            {"serverId", service.id.toString(QUuid::WithoutBraces)},
                            {"capabilities", QJsonArray{"parallel-transfer-v1"}}});
                const auto auth = peer.read();
                peer.write(dukto::next::Type::Authenticated, auth.header.correlation,
                           dukto::Principal{client, 1, {{"data", true, true, true}}}.publicInfo());
                const auto attach = peer.read();
                peer.write(dukto::next::Type::Attached, attach.header.correlation,
                           {{"sessionId", session}, {"lane", "0"}});
            }
            disconnectedAt = timeline.elapsed();
            disconnected = true;
            qInfo() << "terminal fixture lane disconnected" << disconnectedAt.load();
        };
        QVERIFY(lane.listen(QHostAddress::LocalHost, 0));
        ExchangeServer control;
        std::atomic_bool lateFailureWritten{false};
        control.operation = [&](qintptr descriptor) {
            // 日期：2026-11-06；控制晚300ms返回真实Failure，不凭数据断线猜测错误码。
            dukto::next::SecureChannel peer(2000);
            qInfo() << "terminal fixture control TLS begin" << timeline.elapsed();
            peer.accept(descriptor, service.configuration());
            qInfo() << "terminal fixture control TLS ready" << timeline.elapsed();
            QElapsedTimer deadline;
            deadline.start();
            while (!disconnected.load()) {
                if (deadline.elapsed() > 2000)
                    throw dukto::Error(dukto::ExitCode::Network, "fixture lane deadline", "test");
                // 日期：2026-11-06；SecureTransport完成本端握手后仍须泵送尾部TLS事件，不能休眠饿死对端。
                peer.checkpoint("fixture-lane-wait");
                QThread::msleep(1);
            }
            QThread::msleep(300);
            if (reported) {
                try {
                    if (reported == -3) {
                        peer.write(dukto::next::Type::Completed, 2, {{"ordinary", true}});
                    } else if (reported == -4) {
                        // 日期：2026-11-06；合法busy不断续发仍须在原两秒总期限结束。
                        QElapsedTimer busy;
                        busy.start();
                        while (busy.elapsed() < 2500) {
                            peer.write(dukto::next::Type::TaskState, 2, {{"state", "busy"}});
                            QThread::msleep(50);
                        }
                    } else {
                        peer.writeFailure(
                            reported == -1 ? 9 : 2,
                            {{"code", reported == -2 ? 99 : (reported < 0 ? 5 : reported)},
                             {"stage", "receive"},
                             {"message", "independent terminal failure"}});
                    }
                    lateFailureWritten = true;
                } catch (const dukto::Error &error) {
                    if (error.code != dukto::ExitCode::Network)
                        throw;
                }
            }
        };
        QVERIFY(control.listen(QHostAddress::LocalHost, 0));
        const dukto::ClientProfile profile{"test",
                                           "127.0.0.1",
                                           lane.serverPort(),
                                           "127.0.0.1",
                                           service.certificate.digest(QCryptographicHash::Sha256),
                                           service.id,
                                           client,
                                           QByteArray(32, 'x'),
                                           true};
        int code = 0;
        QString stage;
        qint64 failureElapsed = -1;
        {
            dukto::next::SecureChannel peer(2000);
            qInfo() << "terminal fixture client TLS begin" << timeline.elapsed();
            peer.connectTo("127.0.0.1", control.serverPort(), "127.0.0.1",
                           QSslConfiguration::defaultConfiguration(), profile.fingerprint);
            qInfo() << "terminal fixture client TLS ready" << timeline.elapsed();
            dukto::ParallelTransfer transfer(ticket, Task, hash, false);
            transfer.startClients(profile, 2000, &manifest);
            try {
                transfer.sendTree(peer, manifest, 2);
            } catch (const dukto::Error &error) {
                code = static_cast<int>(error.code);
                stage = error.stage;
            }
            failureElapsed = timeline.elapsed() - disconnectedAt.load();
            qInfo() << "terminal fixture failure" << code << stage << "after lane ms"
                    << failureElapsed;
        }
        QVERIFY(lane.done());
        QVERIFY(control.done());
        QVERIFY2(lane.error.isEmpty(), qPrintable(lane.error));
        QVERIFY2(control.error.isEmpty(), qPrintable(control.error));
        const int expected =
            reported > 0 ? reported
                         : (reported == -1 || reported == -3 ? 6 : (reported == -2 ? 2 : 3));
        QCOMPARE(code, expected);
        if (reported == -4)
            QVERIFY(failureElapsed >= 2000 && failureElapsed < 4000);
        if (reported > 0) {
            QCOMPARE(stage, QString("receive"));
            QVERIFY(lateFailureWritten.load());
        }
    }

    // 日期：2026-11-06；单条真实数据连接足够覆盖门禁状态机，4/16通道业务另有独立进程全量测试。
    void rejectedParallelDisposition_data() {
        QTest::addColumn<int>("stage");
        QTest::addColumn<int>("attack");
        for (int stage = 0; stage < 3; ++stage)
            for (int attack = 0; attack < 10; ++attack)
                QTest::newRow(qPrintable(QString("%1-%2").arg(stage).arg(attack)))
                    << stage << attack;
        QTest::newRow("body-before-decision") << 3 << 0;
        QTest::newRow("body-after-skip") << 4 << 0;
    }

    // 日期：2026-11-06；独立对端只发送畸形控制或未授权块请求，源删除后仍须返回处置错误。
    void rejectedParallelDisposition() {
        QFETCH(int, stage);
        QFETCH(int, attack);
        QTemporaryDir temporary;
        const auto path = temporary.filePath("data.bin");
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        QCOMPARE(file.write("body"), qint64(4));
        file.close();
        QVERIFY(QDir().mkpath(temporary.filePath("output")));
        QFile original(temporary.filePath("output/data.bin"));
        QVERIFY(original.open(QIODevice::WriteOnly));
        QCOMPARE(original.write("original"), qint64(8));
        original.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "source.sqlite", true);
        manifest.scan({path});
        QVERIFY(QFile::remove(path));
        const auto hash = QByteArray::fromHex(manifest.summary()["sha256"].toString().toLatin1());
        const auto service = dukto::initializeIdentity(store, {"127.0.0.1"});
        const auto client = QUuid::createUuid();
        const auto session = QUuid::createUuid().toString(QUuid::WithoutBraces);
        const QJsonObject ticket{{"sessionId", session},
                                 {"taskId", Task.toString(QUuid::WithoutBraces)},
                                 {"manifest", QString::fromLatin1(hash.toHex())},
                                 {"token", QString(64, 'a')},
                                 {"lanes", "1"}};
        const QJsonObject identity{
            {"taskId", ticket["taskId"]}, {"manifest", ticket["manifest"]}, {"file", "1"}};
        std::atomic_bool releaseBody{false};
        std::atomic_int bodyRequests{0};
        std::atomic_int unexpectedBodies{0};
        std::atomic_int controlHeartbeats{0};
        ExchangeServer lane;
        lane.operation = [&](qintptr descriptor) {
            // 日期：2026-11-06；独立数据端完整进行TLS/Hello/认证/加入，再尝试未经控制裁决的块请求。
            dukto::next::SecureChannel peer(3000);
            peer.accept(descriptor, service.configuration());
            const auto hello = peer.read();
            peer.write(dukto::next::Type::HelloAck, hello.header.correlation,
                       {{"version", "1.0"},
                        {"serverId", service.id.toString(QUuid::WithoutBraces)},
                        {"capabilities", QJsonArray{"parallel-transfer-v1"}}});
            const auto auth = peer.read();
            peer.write(dukto::next::Type::Authenticated, auth.header.correlation,
                       dukto::Principal{client, 1, {{"data", true, true, true}}}.publicInfo());
            const auto attach = peer.read();
            peer.write(dukto::next::Type::Attached, attach.header.correlation,
                       {{"sessionId", session}, {"lane", "0"}});
            if (stage >= 3) {
                QElapsedTimer deadline;
                deadline.start();
                while (stage == 4 && !releaseBody.load()) {
                    if (deadline.elapsed() > 3000)
                        throw dukto::Error(dukto::ExitCode::Network, "fixture release deadline",
                                           "test");
                    QThread::msleep(1);
                }
                auto job = identity;
                job["block"] = "0";
                ++bodyRequests;
                peer.write(dukto::next::Type::Attach, attach.header.correlation, job);
            }
            try {
                for (;;) {
                    const auto response = peer.read();
                    if (response.header.type != dukto::next::Type::TaskState)
                        ++unexpectedBodies;
                }
            } catch (const dukto::Error &error) {
                if (error.code != dukto::ExitCode::Network)
                    throw;
            }
        };
        QVERIFY(lane.listen(QHostAddress::LocalHost, 0));
        ExchangeServer control;
        control.operation = [&](qintptr descriptor) {
            // 日期：2026-11-06；逐字段攻击本项准备/最终/回显，数据端始终不提供任何备用源内容。
            dukto::next::SecureChannel peer(3000);
            peer.accept(descriptor, service.configuration());
            const auto readControl = [&]() {
                // 日期：2026-11-06；只消费当前请求的精确busy，数量及总时限有界，不能吞掉畸形响应。
                QElapsedTimer deadline;
                deadline.start();
                for (;;) {
                    const auto frame = peer.read();
                    if (frame.header.type != dukto::next::Type::TaskState)
                        return frame;
                    if (frame.header.correlation != 2 ||
                        dukto::next::parseControl(frame.payload) !=
                            QJsonObject{{"state", "busy"}} ||
                        ++controlHeartbeats > 4 || deadline.elapsed() > 3000)
                        throw dukto::Error(dukto::ExitCode::Integrity, "fixture control heartbeat",
                                           "test");
                }
            };
            auto value = identity;
            value["kind"] = "parallel-file";
            value["path"] = "data.bin";
            value["disposition"] = "skip";
            value["skippedRoot"] = "1";
            auto kind = dukto::next::Type::ItemDisposition;
            quint64 correlation = 2;
            if (stage == 1 || stage == 4) {
                peer.write(kind, correlation, value);
                const auto ack = readControl();
                if (ack.header.type != dukto::next::Type::ItemDispositionAck ||
                    dukto::next::parseControl(ack.payload) != value)
                    throw dukto::Error(dukto::ExitCode::Integrity, "fixture disposition ack",
                                       "test");
                value["disposition"] = "skipped";
                kind = dukto::next::Type::Completed;
                if (stage == 4)
                    releaseBody = true;
            } else if (stage == 2) {
                const auto decision = readControl();
                if (decision.header.type != dukto::next::Type::ItemDisposition ||
                    dukto::next::parseControl(decision.payload) != value)
                    throw dukto::Error(
                        dukto::ExitCode::Integrity,
                        QString("fixture receive decision: type=%1 correlation=%2 payload=%3")
                            .arg(int(decision.header.type))
                            .arg(decision.header.correlation)
                            .arg(QString::fromUtf8(decision.payload)),
                        "test");
                kind = dukto::next::Type::ItemDispositionAck;
            }
            if (attack == 0)
                value["taskId"] = QUuid::createUuid().toString(QUuid::WithoutBraces);
            if (attack == 1)
                value["file"] = "2";
            if (attack == 2)
                value["manifest"] = QString(64, '0');
            if (attack == 3)
                value["path"] = "../escape";
            if (attack == 4)
                value["disposition"] = stage == 1 ? "copied" : "receive";
            if (attack == 5)
                value["skippedRoot"] = "01";
            if (attack == 6)
                value["unknown"] = true;
            if (attack == 7)
                value.remove("path");
            if (attack == 8)
                kind = dukto::next::Type::Attached;
            if (attack == 9)
                correlation = 3;
            if (stage < 3)
                peer.write(kind, correlation, value);
            try {
                const auto response = readControl();
                Q_UNUSED(response);
                throw dukto::Error(dukto::ExitCode::Integrity, "unexpected rejection response",
                                   "test");
            } catch (const dukto::Error &error) {
                if (error.code != dukto::ExitCode::Network)
                    throw;
            }
        };
        QVERIFY(control.listen(QHostAddress::LocalHost, 0));
        const dukto::ClientProfile profile{"test",
                                           "127.0.0.1",
                                           lane.serverPort(),
                                           "127.0.0.1",
                                           service.certificate.digest(QCryptographicHash::Sha256),
                                           service.id,
                                           client,
                                           QByteArray(32, 'x'),
                                           true};
        QString failureStage;
        {
            dukto::next::SecureChannel peer(3000);
            peer.connectTo("127.0.0.1", control.serverPort(), "127.0.0.1",
                           QSslConfiguration::defaultConfiguration(), profile.fingerprint);
            dukto::ParallelTransfer transfer(ticket, Task, hash, stage == 2, true);
            transfer.startClients(profile, 3000, stage == 2 ? nullptr : &manifest);
            try {
                if (stage == 2) {
                    dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest,
                                                   temporary.filePath("output"),
                                                   dukto::ConflictPolicy::Skip);
                    bool forcedHeartbeat = false;
                    transfer.receiveTree(
                        peer, manifest, receiver, 2,
                        [&]() {
                            // 日期：2026-11-06；固定慢准备时序，真实Pulse必须在处置前发出合法心跳。
                            if (!forcedHeartbeat) {
                                QThread::msleep(300);
                                forcedHeartbeat = true;
                            }
                        },
                        {}, nullptr, true);
                } else {
                    transfer.sendTree(peer, manifest, 2, {}, {}, true);
                }
            } catch (const dukto::Error &error) {
                if (error.code == dukto::ExitCode::Integrity ||
                    error.code == dukto::ExitCode::Config)
                    failureStage = error.stage;
            }
        }
        QVERIFY(lane.done());
        QVERIFY(control.done());
        QVERIFY2(lane.error.isEmpty(), qPrintable(lane.error));
        QVERIFY2(control.error.isEmpty(), qPrintable(control.error));
        if (stage == 2)
            QVERIFY(controlHeartbeats.load() > 0);
        QVERIFY(failureStage == "disposition" || failureStage == "parallel" ||
                failureStage == "protocol");
        if (stage >= 3)
            QCOMPARE(failureStage, QString("disposition"));
        QCOMPARE(bodyRequests.load(), stage >= 3 ? 1 : 0);
        QCOMPARE(unexpectedBodies.load(), 0);
        QCOMPARE(dukto::hashFile(temporary.filePath("output/data.bin")),
                 QCryptographicHash::hash("original", QCryptographicHash::Sha256));
    }

    // 日期：2026-11-06；固定清单检验处置路径、规范根、祖先约束及准备至完成的单向变化。
    void dispositionFields_data() {
        QTest::addColumn<int>("attack");
        for (int attack = -4; attack < 20; ++attack)
            QTest::newRow(qPrintable(QString::number(attack))) << attack;
    }

    // 日期：2026-11-06；数据全部由独立常量构造，不用发送编码器替畸形消息做规范化。
    void dispositionFields() {
        QFETCH(int, attack);
        QTemporaryDir temporary;
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        const auto empty = QCryptographicHash::hash({}, QCryptographicHash::Sha256);
        manifest.append({1, "bundle", "", true, 0, {}});
        manifest.append({2, "bundle/a", "", false, 0, empty});
        manifest.append({3, "other", "", true, 0, {}});
        manifest.append({4, "other/b", "", false, 0, empty});
        manifest.seal();
        QJsonObject value{{"path", "bundle/a"}, {"disposition", "skip"}, {"skippedRoot", "1"}};
        dukto::DurableReceive::Preparation prepared{"bundle/a", true, 1};
        bool final = attack == -1 || attack >= 15;
        const dukto::DurableReceive::Preparation *prior = final ? &prepared : nullptr;
        if (final)
            value["disposition"] = "skipped";
        if (attack == -3) {
            value["disposition"] = "receive";
            value["skippedRoot"] = "0";
        }
        if (attack == -2)
            value["skippedRoot"] = "2";
        if (attack == 0)
            value["path"] = "../a";
        if (attack == 1)
            value["path"] = "other/b";
        if (attack == 2)
            value["path"] = 2;
        if (attack == 3)
            value["disposition"] = true;
        if (attack == 4)
            value["disposition"] = "skipped";
        if (attack == 5)
            value["disposition"] = "receive";
        if (attack == 6)
            value["skippedRoot"] = 1;
        if (attack == 7)
            value["skippedRoot"] = "01";
        if (attack == 8)
            value["skippedRoot"] = "0";
        if (attack == 9)
            value["skippedRoot"] = "3";
        if (attack == 10)
            value["skippedRoot"] = "-1";
        if (attack == 11)
            value["skippedRoot"] = "18446744073709551616";
        if (attack == 12)
            value.remove("path");
        if (attack == 13)
            value.remove("disposition");
        if (attack == 14)
            value.remove("skippedRoot");
        if (attack == 15) {
            value["disposition"] = "copied";
            value["skippedRoot"] = "0";
        }
        if (attack == 16)
            value["skippedRoot"] = "2";
        if (attack == 17)
            prepared = {"bundle/a", false, 0};
        if (attack == 18)
            prepared.path = "other/b";
        if (attack == 19)
            value["disposition"] = "skip";
        bool rejected = false;
        try {
            const auto result = dukto::readTransferDisposition(value, manifest, 2, final, prior);
            QCOMPARE(result.path, QString("bundle/a"));
        } catch (const dukto::Error &) {
            rejected = true;
        }
        QCOMPARE(rejected, attack >= 0);
        QJsonObject encoded;
        QVERIFY_EXCEPTION_THROWN(
            dukto::addTransferDisposition(encoded, {"bundle/a", false, 1}, false), dukto::Error);
        QVERIFY_EXCEPTION_THROWN(
            dukto::addTransferDisposition(encoded, {"bundle/a", true, 0}, false), dukto::Error);
    }

    // 日期：2026-11-06；真实TLS覆盖准备帧和最终帧全部身份字段、类型、序号及未协商扩展。
    void rejectedDispositionWire_data() {
        QTest::addColumn<bool>("final");
        QTest::addColumn<bool>("explicitMode");
        QTest::addColumn<int>("attack");
        for (bool final : {false, true})
            for (int attack = -1; attack < (final ? 11 : 14); ++attack)
                QTest::newRow(
                    qPrintable(QString("%1-%2").arg(final ? "final" : "prepare").arg(attack)))
                    << final << true << attack;
        QTest::newRow("legacy-extension-refused") << false << false << 14;
    }

    // 日期：2026-11-06；准备攻击在源文件删除后运行，必须在打开源正文之前拒绝；最后确认使用真实空文件。
    void rejectedDispositionWire() {
        QFETCH(bool, final);
        QFETCH(bool, explicitMode);
        QFETCH(int, attack);
        QTemporaryDir temporary;
        const auto path = temporary.filePath("empty.bin");
        QFile file(path);
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.close();
        dukto::PrivateStore store(temporary.filePath("private"), true);
        dukto::StrongManifest manifest(store, "manifest.sqlite", true);
        manifest.scan({path});
        if (!final)
            QVERIFY(QFile::remove(path));
        const auto service = dukto::initializeIdentity(store, {"127.0.0.1"});
        ExchangeServer server;
        int observedAfterReply = 0;
        server.operation = [&](qintptr descriptor) {
            // 日期：2026-11-06；只修改自有响应，观察对端是否继续发送正文/结束帧；错误路径不伪造成功。
            dukto::next::SecureChannel peer(3000);
            peer.accept(descriptor, service.configuration());
            const auto attach = peer.read();
            if (attach.header.type != dukto::next::Type::Attach || attach.header.correlation != 2)
                throw dukto::Error(dukto::ExitCode::Integrity, "fixture attach", "test");
            auto object = dukto::next::parseControl(attach.payload);
            object["block"] = "0";
            object["bytes"] = "0";
            object["path"] = "empty.bin";
            object["disposition"] = final ? "receive" : "skip";
            object["skippedRoot"] = final ? "0" : "1";
            if (final) {
                peer.write(dukto::next::Type::Attached, 2, object);
                const auto finish = peer.read();
                if (finish.header.type != dukto::next::Type::Finish)
                    throw dukto::Error(dukto::ExitCode::Integrity, "fixture finish", "test");
                object.remove("block");
                object.remove("bytes");
                object["disposition"] = "copied";
            }
            auto kind = final ? dukto::next::Type::Completed : dukto::next::Type::Attached;
            quint64 correlation = 2;
            if (attack == 0)
                object["taskId"] = QUuid::createUuid().toString(QUuid::WithoutBraces);
            if (attack == 1)
                object["file"] = "2";
            if (attack == 2)
                object["manifest"] = QString(64, '0');
            if (attack == 3)
                object["path"] = "../escape";
            if (attack == 4)
                object["disposition"] = final ? "receive" : "skipped";
            if (attack == 5)
                object["skippedRoot"] = 1;
            if (attack == 6)
                object["unknown"] = true;
            if (attack == 7)
                object.remove("path");
            if (attack == 8)
                kind = dukto::next::Type::ItemDisposition;
            if (attack == 9)
                correlation = 9;
            if (attack == 10)
                object["skippedRoot"] = "01";
            if (attack == 11)
                object["block"] = "1";
            if (attack == 12)
                object["bytes"] = "1";
            if (attack == 13)
                object["block"] = 0;
            peer.write(kind, correlation, object);
            try {
                const auto response = peer.read();
                observedAfterReply = static_cast<int>(response.header.type);
                if (attack != -1 || response.header.type != dukto::next::Type::Close)
                    throw dukto::Error(dukto::ExitCode::Integrity,
                                       "unexpected post-rejection frame", "test");
                peer.write(dukto::next::Type::Closed, 3, {});
            } catch (const dukto::Error &error) {
                if (attack == -1 || error.code != dukto::ExitCode::Network)
                    throw;
            }
        };
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        bool rejected = false;
        {
            dukto::next::SecureChannel channel(3000);
            channel.connectTo("127.0.0.1", server.serverPort(), "127.0.0.1",
                              QSslConfiguration::defaultConfiguration(),
                              service.certificate.digest(QCryptographicHash::Sha256));
            try {
                dukto::DurableReceive::Preparation result;
                QCOMPARE(
                    dukto::sendStrongFile(channel, Task, manifest, 1, 2, {}, explicitMode, &result),
                    QString("empty.bin"));
                QCOMPARE(result.skipped, !final);
                channel.write(dukto::next::Type::Close, 3, {});
                QCOMPARE(channel.read().header.type, dukto::next::Type::Closed);
            } catch (const dukto::Error &error) {
                rejected = (error.code == dukto::ExitCode::Integrity ||
                            error.code == dukto::ExitCode::Config) &&
                           (error.stage == "disposition" || error.stage == "transfer" ||
                            error.stage == "protocol");
            }
        }
        QVERIFY(server.done());
        QVERIFY2(server.error.isEmpty(), qPrintable(server.error));
        QCOMPARE(rejected, attack != -1);
        QCOMPARE(observedAfterReply, attack == -1 ? static_cast<int>(dukto::next::Type::Close) : 0);
    }

    // 日期：2026-11-06；覆盖双向4/16条实际TLS数据连接、混合/全跳过、跨16项窗口及末端竞争。
    void parallelDispositions_data() {
        QTest::addColumn<bool>("download");
        QTest::addColumn<int>("lanes");
        QTest::addColumn<int>("scenario");
        for (bool download : {false, true})
            for (int lanes : {4, 16})
                for (int scenario = 0; scenario < 4; ++scenario) {
                    const auto name = QString("%1-%2-%3")
                                          .arg(download ? "download" : "upload")
                                          .arg(lanes)
                                          .arg(scenario)
                                          .toLatin1();
                    QTest::newRow(name.constData()) << download << lanes << scenario;
                }
    }

    // 日期：2026-11-06；仅控制测试夹具协调双方，清单/数据/结果全部使用真实生产TLS与持久日志。
    void parallelDispositions() {
        QFETCH(bool, download);
        QFETCH(int, lanes);
        QFETCH(int, scenario);
        QTemporaryDir temporary;
        const auto input = temporary.filePath("input");
        const auto output = temporary.filePath("output");
        const auto shared = temporary.filePath("shared");
        QVERIFY(QDir().mkpath(input));
        QVERIFY(QDir().mkpath(output));
        QVERIFY(QDir().mkpath(shared));
        const QByteArray contents(4099, 'p');
        const QByteArray original("unchanged-original");
        const auto write = [](const QString &path, const QByteArray &bytes) {
            // 日期：2026-11-06；所有样本写入显式检查完整长度，源删除后不得有备用正文。
            QFile file(path);
            if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size())
                throw dukto::Error(dukto::ExitCode::Disk, "fixture write", "test");
        };
        QStringList paths;
        for (int index = 0; index < 35; ++index) {
            const auto name = QString("item-%1.bin").arg(index, 2, 10, QLatin1Char('0'));
            write(input + '/' + name, index == 34 ? QByteArray{} : contents);
            paths.append(input + '/' + name);
            if (scenario == 1 || (scenario == 0 && index % 2 == 0))
                write(output + '/' + name, original);
        }
        const auto owner = QUuid::createUuid();
        const auto credential = dukto::randomCredential();
        dukto::PrivateStore serviceStore(temporary.filePath("service"), true);
        dukto::PrivateStore clientStore(temporary.filePath("client"), true);
        const auto identity = dukto::initializeIdentity(serviceStore, {"127.0.0.1"});
        const dukto::Grant grant{"data", true, true, true};
        dukto::Shares(serviceStore).set({grant, shared});
        dukto::AuthStore authorization(serviceStore);
        const auto offer = authorization.issue({grant});
        authorization.pair(offer.credential, owner, credential);
        dukto::PrivateStore &sourceStore = download ? serviceStore : clientStore;
        dukto::StrongManifest source(sourceStore, "source.sqlite", true);
        source.scan(paths);
        const auto sourceHash =
            QByteArray::fromHex(source.summary()["sha256"].toString().toLatin1());
        dukto::TaskStore tasks(serviceStore);
        auto task = tasks.create(owner, QUuid::createUuid(), download ? "download" : "upload",
                                 "data", "", shared, download ? QByteArray{} : sourceHash);
        auto lease = tasks.acquire(owner, task.id);
        task = tasks.bindManifest(*lease, source.summary());
        task = tasks.advance(*lease, task.revision, "transferring", 0);
        for (int index = 0; index < 35; ++index)
            if (scenario == 1 || (scenario == 0 && index % 2 == 0))
                QVERIFY(QFile::remove(paths[index]));
        serviceStore.write(
            "parallel-fixture.json",
            dukto::next::encodeControl({{"owner", owner.toString(QUuid::WithoutBraces)},
                                        {"task", task.id.toString(QUuid::WithoutBraces)},
                                        {"download", download},
                                        {"output", output},
                                        {"lanes", lanes},
                                        {"scenario", scenario},
                                        {"manifest", QString::fromLatin1(sourceHash.toHex())}}));
        QProcess server;
        server.setProgram(QCoreApplication::applicationFilePath());
        server.setArguments({"--parallel-disposition-server", serviceStore.directory()});
        server.start();
        QVERIFY(server.waitForStarted(10000));
        QByteArray response;
        QElapsedTimer startup;
        startup.start();
        while (!response.contains('\n') && startup.elapsed() < 10000) {
            server.waitForReadyRead(100);
            response += server.readAllStandardOutput();
        }
        QVERIFY2(response.contains('\n'), server.readAllStandardError().constData());
        const auto ports = dukto::next::parseControl(response.trimmed());
        const dukto::ClientProfile profile{"test",
                                           "127.0.0.1",
                                           quint16(ports["dataPort"].toInt()),
                                           "127.0.0.1",
                                           identity.certificate.digest(QCryptographicHash::Sha256),
                                           identity.id,
                                           owner,
                                           credential,
                                           true};
        QJsonObject senderSummary;
        QJsonObject receiverSummary;
        bool lateCreated = false;
        dukto::next::SecureChannel channel(5000);
        channel.connectTo("127.0.0.1", quint16(ports["controlPort"].toInt()), "127.0.0.1",
                          QSslConfiguration::defaultConfiguration(),
                          identity.certificate.digest(QCryptographicHash::Sha256));
        dukto::sendStrongManifest(channel, task.id, source, 1);
        const auto ticket = channel.read();
        QCOMPARE(ticket.header.type, dukto::next::Type::ChannelTicket);
        QCOMPARE(ticket.header.correlation, quint64(2));
        dukto::ParallelTransfer data(dukto::next::parseControl(ticket.payload), task.id, sourceHash,
                                     download, true);
        data.startClients(profile, 5000, download ? nullptr : &source);
        dukto::DispositionJournal journal(clientStore, "client-outcome.sqlite", task.id, source,
                                          "skip");
        const auto completed = [&](const dukto::StrongEntry &entry,
                                   const dukto::DurableReceive::Preparation &result) {
            // 日期：2026-11-06；客户端独立逐项累积，最终与服务器摘要逐字段比较。
            journal.append(entry.id, result.path, result.skipped ? "skipped" : "copied",
                           result.skippedRoot);
        };
        if (download) {
            dukto::DurableReceive receiver(clientStore, "receive.sqlite", task.id, source, output,
                                           dukto::ConflictPolicy::Skip);
            data.receiveTree(
                channel, source, receiver, 2,
                [&]() {
                    // 日期：2026-11-06；下载同样在正文确认后引入竞争，不能省略服务发送方向。
                    if (scenario == 2 && !lateCreated && receiver.confirmed() > 0) {
                        write(output + "/item-00.bin", original);
                        lateCreated = true;
                    }
                },
                completed, nullptr, true);
            receiverSummary = journal.summary();
        } else {
            data.sendTree(channel, source, 2, {}, completed, true);
            senderSummary = journal.summary();
        }
        channel.write(dukto::next::Type::Close, 3, {});
        QCOMPARE(channel.read().header.type, dukto::next::Type::Closed);
        QVERIFY(server.waitForFinished(10000));
        QCOMPARE(server.exitStatus(), QProcess::NormalExit);
        QVERIFY2(server.exitCode() == 0, server.readAllStandardError().constData());
        const auto remoteSummary =
            dukto::next::parseControl(serviceStore.read("parallel-result.json"));
        if (download)
            senderSummary = remoteSummary;
        else {
            receiverSummary = remoteSummary;
            lateCreated =
                dukto::next::parseControl(serviceStore.read("parallel-late.json"))["created"]
                    .toBool();
        }
        QCOMPARE(senderSummary, receiverSummary);
        const auto expectedCopied = scenario == 0   ? 17
                                    : scenario == 1 ? 0
                                    : scenario == 2 ? 33
                                                    : 34;
        QCOMPARE(senderSummary["copiedBytes"].toString(),
                 QString::number(qint64(expectedCopied) * contents.size()));
        QCOMPARE(lateCreated, scenario == 2);
        for (int index = 0; index < 35; ++index) {
            const auto name = QString("item-%1.bin").arg(index, 2, 10, QLatin1Char('0'));
            const bool skipped =
                scenario == 1 || (scenario == 0 && index % 2 == 0) || (scenario == 2 && index == 0);
            const auto expected = skipped ? original : index == 34 ? QByteArray{} : contents;
            QCOMPARE(dukto::hashFile(output + '/' + name),
                     QCryptographicHash::hash(expected, QCryptographicHash::Sha256));
        }
    }

    // 日期：2026-11-06；双向真实TLS覆盖混合子树、全部跳过、复制和正文结束时的发布竞争。
    void explicitDispositions_data() {
        QTest::addColumn<bool>("download");
        QTest::addColumn<int>("scenario");
        for (bool download : {false, true})
            for (int scenario = 0; scenario < 4; ++scenario) {
                const auto name =
                    QString("%1-%2").arg(download ? "download" : "upload").arg(scenario).toLatin1();
                QTest::newRow(name.constData()) << download << scenario;
            }
    }

    // 日期：2026-11-06；冻结后删除被跳过源文件，只有不打开正文才能通过；双方独立持久摘要必须完全一致。
    void explicitDispositions() {
        QFETCH(bool, download);
        QFETCH(int, scenario);
        QTemporaryDir temporary;
        const auto input = temporary.filePath("input");
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(input + "/b-existing/subtree"));
        QVERIFY(QDir().mkpath(output));
        const QByteArray contents(4099, 's');
        const QByteArray original("preserved-target");
        const auto write = [](const QString &path, const QByteArray &bytes) {
            // 日期：2026-11-06；样本写入失败即终止，不允许缺失原件形成假阳性。
            QFile file(path);
            if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size())
                throw dukto::Error(dukto::ExitCode::Disk, "fixture write", "test");
        };
        write(input + "/a-fresh.bin", contents);
        write(input + "/b-existing/subtree/data.bin", contents);
        write(input + "/c-existing.bin", contents);
        write(input + "/d-empty.bin", {});
        if (scenario < 2) {
            QVERIFY(QDir().mkpath(output + "/b-existing"));
            write(output + "/c-existing.bin", original);
            if (scenario == 1) {
                write(output + "/a-fresh.bin", original);
                write(output + "/d-empty.bin", original);
            }
        }
        dukto::PrivateStore sourceStore(temporary.filePath("source"), true);
        dukto::PrivateStore destinationStore(temporary.filePath("destination"), true);
        dukto::StrongManifest source(sourceStore, "manifest.sqlite", true);
        source.scan(scenario == 2 ? QStringList{input + "/a-fresh.bin"}
                                  : QStringList{input + "/a-fresh.bin", input + "/b-existing",
                                                input + "/c-existing.bin", input + "/d-empty.bin"});
        const auto hash = QByteArray::fromHex(source.summary()["sha256"].toString().toLatin1());
        if (scenario < 2) {
            QVERIFY(QFile::remove(input + "/c-existing.bin"));
            QVERIFY(QDir(input + "/b-existing").removeRecursively());
            if (scenario == 1) {
                QVERIFY(QFile::remove(input + "/a-fresh.bin"));
                QVERIFY(QFile::remove(input + "/d-empty.bin"));
            }
        }
        dukto::PrivateStore identityStore(temporary.filePath("identity"), true);
        const auto identity = dukto::initializeIdentity(identityStore, {"127.0.0.1"});
        QJsonObject senderSummary;
        QJsonObject receiverSummary;
        bool lateCreated = false;
        const auto send = [&](dukto::next::SecureChannel &channel, dukto::PrivateStore &store) {
            // 日期：2026-11-06；每个线程重新打开自己的只读清单及结果日志，禁止跨线程SQLite连接。
            dukto::StrongManifest manifest(store, "manifest.sqlite", false);
            dukto::DispositionJournal journal(store, "send.sqlite", Task, manifest, "skip");
            dukto::sendStrongManifest(channel, Task, manifest, 1);
            dukto::sendStrongTree(
                channel, Task, manifest, 2, {},
                [&](const dukto::StrongEntry &entry,
                    const dukto::DurableReceive::Preparation &result) {
                    // 日期：2026-11-06；发送端只根据本次严格验证的处置累积独立收据。
                    journal.append(entry.id, result.path, result.skipped ? "skipped" : "copied",
                                   result.skippedRoot);
                },
                true);
            senderSummary = journal.summary();
        };
        const auto receive = [&](dukto::next::SecureChannel &channel, dukto::PrivateStore &store) {
            // 日期：2026-11-06；接收端仅从公开分页导入清单，原件及跳过根由生产持久日志裁决。
            dukto::StrongManifest manifest(store, "wire.sqlite", true);
            dukto::receiveStrongManifest(channel, Task, manifest, hash, 1);
            dukto::DurableReceive receiver(store, "receive.sqlite", Task, manifest, output,
                                           dukto::ConflictPolicy::Skip);
            dukto::DispositionJournal journal(store, "receive-outcome.sqlite", Task, manifest,
                                              "skip");
            dukto::receiveStrongTree(
                channel, Task, manifest, receiver, 2,
                [&]() {
                    // 日期：2026-11-06；整文件正文已同步后再创建竞争目标，验证最终裁决能从receive变为skipped。
                    if (scenario == 2 && !lateCreated && receiver.confirmed() == contents.size()) {
                        write(output + "/a-fresh.bin", original);
                        lateCreated = true;
                    }
                },
                [&](const dukto::StrongEntry &entry,
                    const dukto::DurableReceive::Preparation &result) {
                    // 日期：2026-11-06；接收端摘要独立读取真实裁决，不能把已传正文冒充copied。
                    journal.append(entry.id, result.path, result.skipped ? "skipped" : "copied",
                                   result.skippedRoot);
                },
                nullptr, true);
            receiverSummary = journal.summary();
        };
        ExchangeServer server;
        server.operation = [&](qintptr descriptor) {
            // 日期：2026-11-06；真实认证TLS只处理当前测试私有目录，socket及SQLite在工作线程创建销毁。
            dukto::next::SecureChannel peer(5000);
            peer.accept(descriptor, identity.configuration());
            dukto::PrivateStore store(download ? sourceStore.directory()
                                               : destinationStore.directory());
            if (download)
                send(peer, store);
            else
                receive(peer, store);
            const auto close = peer.read();
            if (close.header.type != dukto::next::Type::Close || close.header.correlation != 3)
                throw dukto::Error(dukto::ExitCode::Integrity, "close", "test");
            peer.write(dukto::next::Type::Closed, 3, {});
        };
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        dukto::next::SecureChannel channel(5000);
        channel.connectTo("127.0.0.1", server.serverPort(), "127.0.0.1",
                          QSslConfiguration::defaultConfiguration(),
                          identity.certificate.digest(QCryptographicHash::Sha256));
        if (download)
            receive(channel, destinationStore);
        else
            send(channel, sourceStore);
        channel.write(dukto::next::Type::Close, 3, {});
        QCOMPARE(channel.read().header.type, dukto::next::Type::Closed);
        QVERIFY(server.done());
        QVERIFY2(server.error.isEmpty(), qPrintable(server.error));
        QCOMPARE(senderSummary, receiverSummary);
        const auto expectedCopied = scenario == 0   ? contents.size()
                                    : scenario == 3 ? contents.size() * 3
                                                    : 0;
        QCOMPARE(senderSummary["copiedBytes"].toString(), QString::number(expectedCopied));
        QCOMPARE(lateCreated, scenario == 2);
        const auto sha = [](const QByteArray &bytes) {
            // 日期：2026-11-06；直接从样本常量计算独立期望摘要。
            return QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
        };
        QCOMPARE(dukto::hashFile(output + "/a-fresh.bin"),
                 sha(scenario == 1 || scenario == 2 ? original : contents));
        if (scenario != 2) {
            QCOMPARE(dukto::hashFile(output + "/c-existing.bin"),
                     sha(scenario < 2 ? original : contents));
            QCOMPARE(QFileInfo::exists(output + "/b-existing/subtree"), scenario == 3);
            QCOMPARE(dukto::hashFile(output + "/d-empty.bin"),
                     sha(scenario == 1 ? original : QByteArray{}));
        }
        QVERIFY(QDir(output)
                    .entryList({".dukto-*.part", ".dukto-*.dir"},
                               QDir::Files | QDir::Dirs | QDir::Hidden | QDir::NoDotAndDotDot)
                    .isEmpty());
    }

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
        if (!download && stage < 2) {
            // 日期：2026-11-06；早期完成样本带历史条目确认；本用例仍专门攻击批次确认字段。
            dukto::DispositionJournal previous(
                local, "upload-disposition-" + Task.toString(QUuid::WithoutBraces) + ".sqlite",
                Task, source, "rename");
            previous.append(1, "data.bin", "copied");
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
            if ((download || attack == -1) && stage < 2) {
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
                             : client.upload(requestId, "data", "", local, source, progress);
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
        if (argc == 3 && QString::fromLocal8Bit(argv[1]) == "--parallel-disposition-server")
            return parallelDispositionServer(QString::fromLocal8Bit(argv[2]));
        return QTest::qExec(&tests, argc, argv);
    } catch (const dukto::Error &error) {
        const auto diagnostic = (error.stage + ": " + error.message).toUtf8();
        std::fprintf(stderr, "%s\n", diagnostic.constData());
        return 32;
    }
}
#include "file_exchange_tests.moc"

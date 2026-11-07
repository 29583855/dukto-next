#include "app/serverpanel.h"
#include "core/auth.h"
#include "core/files.h"
#include "core/transferscheduler.h"
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickWidget>
#include <QQuickWindow>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QtTest>

class SlowTestProxy final : public QTcpServer {
  public:
    // 日期：2026-11-05；测试专用回环 TLS 不透明代理，只限制传送节奏，不替代任何业务处理器。
    explicit SlowTestProxy(quint16 target) : target_(target) {
        if (!listen(QHostAddress::LocalHost, 0))
            qFatal("test proxy listen failed");
    }

    // 日期：2026-11-05；只切断测试代理已拥有的连接，监听器继续接受生产 GUI 自动重连。
    void cutConnections() {
        fragmentBytes_ = 4096;
        for (auto socket : findChildren<QTcpSocket *>())
            socket->abort();
    }

    // 日期：2026-11-05；暂停实测完成后恢复代理速率，避免小样本重连在鼠标到达前已全部完成。
    void restoreSpeed() {
        fragmentBytes_ = 16384;
    }

  protected:
    // 日期：2026-11-05；每方向只取 16 KiB，读缓存/写队列均有上限，GUI 可在真实传输期间点击。
    void incomingConnection(qintptr descriptor) override {
        auto client = new QTcpSocket(this);
        auto server = new QTcpSocket(this);
        if (!client->setSocketDescriptor(descriptor)) {
            delete client;
            delete server;
            return;
        }
        client->setReadBufferSize(32768);
        server->setReadBufferSize(32768);
        server->connectToHost(QHostAddress::LocalHost, target_);
        auto timer = new QTimer(this);
        timer->setInterval(10);
        connect(timer, &QTimer::timeout, this, [this, client, server, timer]() {
            // 日期：2026-11-05；慢收端仍背压，不用 readAll 把全部加密正文积累到测试内存。
            for (auto pair : {qMakePair(client, server), qMakePair(server, client)})
                if (pair.second->state() == QAbstractSocket::ConnectedState &&
                    pair.second->bytesToWrite() == 0 && pair.first->bytesAvailable() > 0)
                    pair.second->write(pair.first->read(fragmentBytes_));
            for (auto pair : {qMakePair(client, server), qMakePair(server, client)})
                if (pair.first->state() == QAbstractSocket::UnconnectedState &&
                    pair.first->bytesAvailable() == 0 &&
                    pair.second->state() == QAbstractSocket::ConnectedState)
                    pair.second->disconnectFromHost();
            if (client->state() == QAbstractSocket::UnconnectedState &&
                server->state() == QAbstractSocket::UnconnectedState) {
                // 日期：2026-11-05；先转送断开前残留的 Closed 确认再回收，代理不能提前截断 TLS
                // 尾帧。
                timer->stop();
                client->deleteLater();
                server->deleteLater();
                timer->deleteLater();
            }
        });
        timer->start();
    }

  private:
    quint16 target_;
    int fragmentBytes_ = 16384;
};

class ServerPanelTests final : public QObject {
    Q_OBJECT
  private slots:
    // 日期：2026-11-06；真实QML选择skip并激活下载，验证全跳过计量、逐项文案及源删除后的面板重建恢复。
    void publicSkipQml() {
        QTemporaryDir temporary;
        const auto shared = temporary.filePath("shared");
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(shared + "/目录"));
        QVERIFY(QDir().mkpath(output + "/目录"));
        QFile source(shared + "/目录/file.bin");
        QVERIFY(source.open(QIODevice::WriteOnly));
        QCOMPARE(source.write("source"), qint64(6));
        source.close();
        QFile original(output + "/目录/保留.txt");
        QVERIFY(original.open(QIODevice::WriteOnly));
        QCOMPARE(original.write("original"), qint64(8));
        original.close();
        const auto preserved = dukto::hashFile(original.fileName());
        ServerPanel server(temporary.filePath("server"));
        server.execute("init", {{"names", "127.0.0.1"}});
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        const auto fingerprint = server.identity()["fingerprint"];
        const QVariantMap rights{{"share", "data"},
                                 {"path", shared},
                                 {"upload", true},
                                 {"download", true},
                                 {"browse", true}};
        server.execute("share-add", rights);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        server.execute("pairing", rights);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        const auto credential = server.outcome()["credentialFile"];
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        server.setServing(true, "127.0.0.1", port);
        QVERIFY(server.serving());
        const auto clientPath = temporary.filePath("client");
        QString task;
        {
            ServerPanel client(clientPath);
            client.execute("pair", {{"target", QString("127.0.0.1:%1").arg(port)},
                                    {"fingerprint", fingerprint},
                                    {"credentialFile", credential}});
            QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
            QVERIFY(!client.outcome()["client"].toString().isEmpty());
            QQuickWidget view;
            view.setResizeMode(QQuickWidget::SizeRootObjectToView);
            view.resize(460, 800);
            QSignalSpy warnings(view.engine(), &QQmlEngine::warnings);
            QQmlComponent component(view.engine(), QUrl("qrc:/ui/ServerPage.qml"));
            auto root = component.createWithInitialProperties(
                {{"panel", QVariant::fromValue<QObject *>(&client)}});
            QVERIFY2(root, qPrintable(component.errorString()));
            view.setContent(QUrl("qrc:/ui/ServerPage.qml"), &component, root);
            view.show();
            auto policy = root->findChild<QObject *>("serverConflictPolicy");
            QVERIFY(policy && policy->property("count").toInt() == 4);
            policy->setProperty("currentIndex", 3);
            root->findChild<QObject *>("serverShare")->setProperty("text", "data");
            root->findChild<QObject *>("serverRemotePath")
                ->setProperty("text", QStringLiteral("目录"));
            root->findChild<QObject *>("serverOutput")->setProperty("text", output);
            root->findChild<QObject *>("serverChannelCount")->setProperty("currentIndex", 2);
            // 日期：2026-11-06；生产按钮的QML处理器读取实际控件选项，不能用测试直接传入skip绕过映射。
            auto button = root->findChild<QObject *>("serverDownloadButton");
            QVERIFY(button && button->property("enabled").toBool());
            QVERIFY(QMetaObject::invokeMethod(button, "clicked"));
            QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
            QCOMPARE(client.task()["state"].toString(), QString("completed"));
            QCOMPARE(client.task()["conflict"].toString(), QString("skip"));
            QCOMPARE(client.task()["receivedBytes"].toString(), QString("0"));
            QCOMPARE(client.task()["confirmedBytes"].toString(), QString("0"));
            QCOMPARE(client.task()["copiedBytes"].toString(), QString("0"));
            QCOMPARE(client.task()["skippedBytes"].toString(), QString("6"));
            QCOMPARE(client.task()["skippedFiles"].toString(), QString("1"));
            QCOMPARE(client.task()["skippedDirectories"].toString(), QString("1"));
            task = client.task()["taskId"].toString();
            auto label = root->findChild<QObject *>("serverTransferAccounting");
            QVERIFY(label);
            QVERIFY(label->property("text").toString().contains(QStringLiteral("跳过：6 B")));
            QVERIFY(label->property("text").toString().contains(QStringLiteral("已校验落盘：0 B")));
            QCOMPARE(root->findChild<QObject *>("serverByteProgress")->property("value").toDouble(),
                     1.0);
            QVERIFY(!QFile::exists(output + "/目录/file.bin"));
            QCOMPARE(dukto::hashFile(original.fileName()), preserved);
            client.execute("task-items", {{"taskId", task}, {"after", "0"}});
            QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
            const auto entries = client.itemPage()["entries"].toList();
            QCOMPARE(entries.size(), 2);
            for (const auto &entry : entries)
                QCOMPARE(entry.toMap()["disposition"].toString(), QString("skipped"));
            QVERIFY(warnings.isEmpty());
        }
        QVERIFY(QDir(shared + "/目录").removeRecursively());
        {
            ServerPanel restarted(clientPath);
            restarted.execute("resume", {{"taskId", task}, {"channels", "16"}, {"output", output}});
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QVERIFY2(restarted.task()["state"].toString() == "completed",
                     qPrintable(restarted.status()));
            QCOMPARE(restarted.task()["taskId"].toString(), task);
            QCOMPARE(restarted.task()["receivedBytes"].toString(), QString("0"));
            QCOMPARE(restarted.task()["skippedBytes"].toString(), QString("6"));
        }
        QCOMPARE(dukto::hashFile(original.fileName()), preserved);
        server.setServing(false, "127.0.0.1", port);
    }

    // 日期：2026-11-06；真实TLS上传后重建GUI面板，继续原请求不重扫新增项，复制源变化仍拒绝。
    void uploadManifestAcrossPanelRestart() {
        QTemporaryDir temporary;
        const auto shared = temporary.filePath("shared");
        const auto source = temporary.filePath("source");
        QVERIFY(QDir().mkpath(shared));
        QVERIFY(QDir().mkpath(source));
        QFile payload(source + "/payload.bin");
        QVERIFY(payload.open(QIODevice::WriteOnly));
        QCOMPARE(payload.write("abc"), qint64(3));
        payload.close();
        ServerPanel server(temporary.filePath("server"));
        server.execute("init", {{"names", "127.0.0.1"}});
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        const auto fingerprint = server.identity()["fingerprint"];
        const QVariantMap rights{{"share", "data"},
                                 {"path", shared},
                                 {"upload", true},
                                 {"download", true},
                                 {"browse", true}};
        server.execute("share-add", rights);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        server.execute("pairing", rights);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        const auto credential = server.outcome()["credentialFile"];
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        server.setServing(true, "127.0.0.1", port);
        QVERIFY(server.serving());
        const auto request = QUuid::createUuid().toString(QUuid::WithoutBraces);
        const QVariantMap options{
            {"share", "data"}, {"path", source}, {"requestId", request}, {"channels", "4"}};
        const auto clientPath = temporary.filePath("client");
        QString task;
        {
            ServerPanel client(clientPath);
            client.execute("pair", {{"target", QString("127.0.0.1:%1").arg(port)},
                                    {"fingerprint", fingerprint},
                                    {"credentialFile", credential}});
            QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
            QVERIFY(!client.outcome()["client"].toString().isEmpty());
            client.execute("upload", options);
            QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
            QCOMPARE(client.task()["state"].toString(), QString("completed"));
            task = client.task()["taskId"].toString();
        }
        const auto manifest =
            QDir(clientPath).filePath("transfers/upload-source-" + request + ".sqlite");
        const auto frozen = dukto::hashFile(manifest);
        QFile extra(source + "/new.bin");
        QVERIFY(extra.open(QIODevice::WriteOnly));
        QCOMPARE(extra.write("new"), qint64(3));
        extra.close();
        {
            ServerPanel restarted(clientPath);
            restarted.execute("resume", {{"taskId", task}, {"path", source}, {"channels", "8"}});
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QCOMPARE(restarted.task()["state"].toString(), QString("completed"));
            QCOMPARE(restarted.task()["taskId"].toString(), task);
            QVERIFY(!QFile::exists(shared + "/source/new.bin"));
            QVERIFY(payload.open(QIODevice::WriteOnly | QIODevice::Truncate));
            QCOMPARE(payload.write("xyz"), qint64(3));
            payload.close();
            restarted.execute("upload", options);
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QCOMPARE(restarted.outcome()["code"].toInt(), 6);
            QCOMPARE(restarted.outcome()["stage"].toString(), QString("completion"));
        }
        QCOMPARE(dukto::hashFile(manifest), frozen);
        QCOMPARE(dukto::hashFile(shared + "/source/payload.bin"),
                 QCryptographicHash::hash("abc", QCryptographicHash::Sha256));
        server.setServing(false, "127.0.0.1", port);
    }

    // 日期：2026-11-05；续期和迁移的生产按钮、错误保护、监听重启及原配对身份实际核对。
    void certificateLifecycleQml() {
        QTemporaryDir temporary;
        ServerPanel server(temporary.filePath("server"));
        ServerPanel client(temporary.filePath("client"));
        server.execute("init", {{"names", "127.0.0.1"}, {"certificateDays", "1"}});
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QVERIFY(server.identity()["expiringSoon"].toBool());
        const auto oldPin = server.identity()["fingerprint"].toString();
        const auto serverId = server.identity()["serverId"].toString();
        const auto shared = temporary.filePath("shared");
        QVERIFY(QDir().mkpath(shared));
        const QVariantMap rights{{"share", "docs"},
                                 {"path", shared},
                                 {"browse", true},
                                 {"download", true},
                                 {"upload", true}};
        server.execute("share-add", rights);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        server.execute("pairing", rights);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        const auto credentialFile = server.outcome()["credentialFile"];
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        server.setServing(true, "127.0.0.1", port);
        QVERIFY(server.serving());
        client.execute("pair", {{"target", QString("127.0.0.1:%1").arg(port)},
                                {"fingerprint", oldPin},
                                {"credentialFile", credentialFile}});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        const auto clientId = client.outcome()["client"].toString();
        QVERIFY(!clientId.isEmpty());
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        QSignalSpy warnings(view.engine(), &QQmlEngine::warnings);
        QQmlComponent component(view.engine(), QUrl("qrc:/ui/ServerPage.qml"));
        auto root = component.createWithInitialProperties(
            {{"panel", QVariant::fromValue<QObject *>(&server)}});
        QVERIFY2(root, qPrintable(component.errorString()));
        view.setContent(QUrl("qrc:/ui/ServerPage.qml"), &component, root);
        view.show();
        auto sections = root->findChild<QObject *>("serverSections");
        auto local = root->findChild<QQuickItem *>("serverLocalFlick");
        auto remote = root->findChild<QQuickItem *>("serverClientFlick");
        QVERIFY(sections && local && remote);
        // 日期：2026-11-05；展开布局后等待可见几何连续稳定，再对真实控件投递一次点击，最多三秒。
        const auto click = [&](const char *name, QQuickItem *flick) {
            auto item = root->findChild<QQuickItem *>(name);
            if (!item)
                return false;
            QPointF previous(-1, -1);
            int stable = 0;
            const auto ready = QTest::qWaitFor(
                [&]() {
                    const auto position = item->mapToItem(flick, QPointF()).y();
                    const auto current = flick->property("contentY").toDouble();
                    const auto maximum =
                        qMax(0.0, flick->property("contentHeight").toDouble() - flick->height());
                    flick->setProperty("contentY", qBound(0.0, current + position - 160, maximum));
                    const auto bounds = item->mapRectToItem(flick, item->boundingRect());
                    const auto point = item->mapToScene(item->boundingRect().center());
                    const bool visible = item->isVisible() && item->isEnabled() &&
                                         item->width() > 0 && item->height() > 0 &&
                                         bounds.top() >= 0 && bounds.bottom() <= flick->height() &&
                                         view.rect().contains(point.toPoint());
                    stable = visible && point == previous ? stable + 1 : 0;
                    previous = point;
                    return stable >= 3;
                },
                3000);
            if (!ready)
                return false;
            QTest::mouseClick(&view, Qt::LeftButton, Qt::NoModifier, previous.toPoint());
            return true;
        };
        sections->setProperty("currentIndex", 2);
        QVERIFY(click("serverRenewExpand", local));
        QVERIFY(root->findChild<QObject *>("serverRenewExpand")->property("checked").toBool());
        auto renew = root->findChild<QQuickItem *>("serverRenewButton");
        QVERIFY(renew && !renew->isEnabled());
        QVERIFY(click("serverRenewConfirmed", local));
        QTRY_VERIFY_WITH_TIMEOUT(
            root->findChild<QObject *>("serverRenewConfirmed")->property("checked").toBool(), 3000);
        QTRY_VERIFY_WITH_TIMEOUT(renew->isEnabled(), 3000);
        QVERIFY(click("serverRenewButton", local));
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        const auto newPin = server.identity()["fingerprint"].toString();
        QVERIFY2(newPin != oldPin, qPrintable(server.status()));
        QCOMPARE(server.identity()["serverId"].toString(), serverId);
        QCOMPARE(server.identity()["activeFingerprint"].toString(), oldPin);
        QVERIFY(server.identity()["restartRequired"].toBool());
        QVERIFY(!root->findChild<QObject *>("serverRenewConfirmed")->property("checked").toBool());
        auto status = root->findChild<QQuickItem *>("serverCertificateStatus");
        QVERIFY(status && status->property("text").toString().contains(QStringLiteral("重新启动")));
        const auto y = status->mapToItem(local, QPointF()).y();
        local->setProperty("contentY", local->property("contentY").toDouble() + y - 80);
        QTest::qWait(100);
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-certificate-renewal.png"));
        client.execute("auth", {});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.outcome()["client"].toString(), clientId);
        server.setServing(false, "127.0.0.1", port);
        server.setServing(true, "127.0.0.1", port);
        QVERIFY(server.serving());
        QVERIFY(!server.identity()["restartRequired"].toBool());
        client.execute("auth", {});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.outcome()["code"].toInt(), 4);
        root->setProperty("panel", QVariant::fromValue<QObject *>(&client));
        sections->setProperty("currentIndex", 0);
        QVERIFY(click("serverTrustExpand", remote));
        QVERIFY(click("serverProfileInfoButton", remote));
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.outcome()["fingerprint"].toString(), oldPin);
        root->findChild<QObject *>("serverOldFingerprint")->setProperty("text", oldPin);
        root->findChild<QObject *>("serverNewFingerprint")->setProperty("text", newPin);
        auto trust = root->findChild<QQuickItem *>("serverTrustButton");
        QVERIFY(trust && !trust->isEnabled());
        QVERIFY(click("serverTrustConfirmed", remote));
        QVERIFY(trust->isEnabled());
        QVERIFY(click("serverTrustButton", remote));
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.outcome()["event"].toString(), QString("profile-certificate-updated"));
        QCOMPARE(client.outcome()["serverId"].toString(), serverId);
        QCOMPARE(client.outcome()["fingerprint"].toString(), newPin);
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-certificate-migration.png"));
        client.execute("auth", {});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.outcome()["client"].toString(), clientId);
        QCOMPARE(client.outcome()["revision"].toString(), QString("1"));
        view.resize(360, 560);
        QTest::qWait(100);
        QVERIFY(!view.grabFramebuffer().isNull());
        QCOMPARE(warnings.count(), 0);
        QVERIFY(!client.outcome().contains("credential"));
        server.setServing(false, "127.0.0.1", port);
    }
    // 日期：2026-11-05；两个真实慢下载占用活动任务名额，生产界面第三任务排队时仍可查询/暂停/继续/取消。
    void queuedProductionControls() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        const auto shared = temporary.filePath("shared");
        QVERIFY(QDir().mkpath(shared));
        const auto source = QDir(shared).filePath("queue-body.bin");
        QFile body(source);
        QVERIFY(body.open(QIODevice::WriteOnly));
        for (int index = 0; index < 64; ++index)
            dukto::writeAll(body, QByteArray(1024 * 1024, 'q'));
        body.close();
        ServerPanel server(temporary.filePath("server"));
        server.execute("init", {{"names", "127.0.0.1"}});
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QVERIFY(!server.identity()["serverId"].toString().isEmpty());
        const QVariantMap permissions{{"share", "docs"},
                                      {"path", shared},
                                      {"browse", true},
                                      {"download", true},
                                      {"upload", true}};
        server.execute("share-add", permissions);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        server.setServing(true, "127.0.0.1", port);
        QVERIFY(server.serving());
        SlowTestProxy proxy(port);
        ServerPanel first(temporary.filePath("first"));
        ServerPanel second(temporary.filePath("second"));
        ServerPanel client(temporary.filePath("client"));
        int ordinal = 0;
        for (auto peer : {&first, &second, &client}) {
            server.execute("pairing", permissions);
            QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
            peer->execute("pair", {{"target", QString("127.0.0.1:%1").arg(proxy.serverPort())},
                                   {"fingerprint", server.identity()["fingerprint"]},
                                   {"credentialFile", server.outcome()["credentialFile"]}});
            QTRY_VERIFY_WITH_TIMEOUT(!peer->busy(), 30000);
            QVERIFY2(!peer->outcome()["client"].toString().isEmpty(), qPrintable(peer->status()));
            const auto output = temporary.filePath(QString("output-%1").arg(ordinal++));
            QVERIFY(QDir().mkpath(output));
            if (peer != &client) {
                peer->execute("download", {{"channels", "1"},
                                           {"share", "docs"},
                                           {"remotePath", "queue-body.bin"},
                                           {"output", output}});
                QTRY_VERIFY_WITH_TIMEOUT(peer->task()["state"] == "transferring", 30000);
            }
        }
        QCOMPARE(dukto::TransferScheduler::global().usage()["active"].toInt(), 2);
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        QSignalSpy warnings(view.engine(), &QQmlEngine::warnings);
        QQmlComponent component(view.engine(), QUrl("qrc:/ui/ServerPage.qml"));
        auto root = component.createWithInitialProperties(
            {{"panel", QVariant::fromValue<QObject *>(&client)}});
        QVERIFY2(root, qPrintable(component.errorString()));
        view.setContent(QUrl("qrc:/ui/ServerPage.qml"), &component, root);
        view.show();
        QTest::qWait(200);
        auto sections = root->findChild<QObject *>("serverSections");
        auto clientFlick = root->findChild<QQuickItem *>("serverClientFlick");
        auto taskFlick = root->findChild<QQuickItem *>("serverTaskFlick");
        auto remote = root->findChild<QObject *>("serverRemotePath");
        auto output = root->findChild<QObject *>("serverOutput");
        QVERIFY(sections && clientFlick && taskFlick && remote && output);
        remote->setProperty("text", "queue-body.bin");
        output->setProperty("text", temporary.filePath("output-2"));
        const auto click = [&](const char *name, QQuickItem *flick) {
            // 日期：2026-11-05；滚动生产 Flickable 并实际投递鼠标事件，不能直接调用槽当成按钮测试。
            auto button = root->findChild<QQuickItem *>(name);
            if (!button)
                return false;
            QTest::qWait(60);
            const auto current = flick->property("contentY").toDouble();
            const auto maximum =
                qMax(0.0, flick->property("contentHeight").toDouble() - flick->height());
            flick->setProperty(
                "contentY",
                qBound(0.0, current + button->mapToItem(flick, QPointF()).y() - 180, maximum));
            QTest::qWait(30);
            QTest::mouseClick(&view, Qt::LeftButton, Qt::NoModifier,
                              button->mapToScene(button->boundingRect().center()).toPoint());
            return true;
        };
        QVERIFY(click("serverDownloadButton", clientFlick));
        QTRY_VERIFY_WITH_TIMEOUT(client.busy() && client.task()["state"] == "queued", 30000);
        const auto task = client.task()["taskId"].toString();
        QVERIFY(!task.isEmpty());
        sections->setProperty("currentIndex", 1);
        QTest::qWait(100);
        auto hint = root->findChild<QQuickItem *>("serverQueueHint");
        QVERIFY(hint && hint->isVisible());
        QCOMPARE(dukto::TransferScheduler::global().usage()["waiting"].toInt(), 1);
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-queue.png"));
        QVERIFY(click("serverQueryButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QCOMPARE(client.task()["state"].toString(), QString("queued"));
        QVERIFY(client.task()["executionActive"].toBool());
        QVERIFY(click("serverPauseButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy() && !client.controlBusy(), 30000);
        QVERIFY(click("serverQueryButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QCOMPARE(client.task()["state"].toString(), QString("paused"));
        QVERIFY(!client.task()["executionActive"].toBool());
        QVERIFY(click("serverResumeButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(client.busy() && client.task()["state"] == "queued", 30000);
        QCOMPARE(client.task()["taskId"].toString(), task);
        QVERIFY(click("serverCancelButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy() && !client.controlBusy(), 30000);
        QVERIFY(click("serverQueryButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QCOMPARE(client.task()["state"].toString(), QString("cancelled"));
        QVERIFY(!QFileInfo::exists(temporary.filePath("output-2/queue-body.bin")));
        for (auto peer : {&first, &second}) {
            QCOMPARE(peer->task()["state"].toString(), QString("transferring"));
            peer->execute("cancel", {{"taskId", peer->task()["taskId"]}});
            QTRY_VERIFY_WITH_TIMEOUT(!peer->busy() && !peer->controlBusy(), 30000);
        }
        QTRY_COMPARE_WITH_TIMEOUT(dukto::TransferScheduler::global().usage()["active"].toInt(), 0,
                                  30000);
        QCOMPARE(dukto::TransferScheduler::global().usage()["waiting"].toInt(), 0);
        QCOMPARE(dukto::TransferScheduler::global().usage()["lanes"].toInt(), 0);
        QCOMPARE(warnings.count(), 0);
        server.setServing(false, "127.0.0.1", port);
    }

    // 日期：2026-11-05；真实 TLS 和生产 QML 验证配对、并发双向数据、暂停/重建后继续/取消点击。
    void productionServiceAndQml() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        const auto shared = temporary.filePath("shared");
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(shared));
        QVERIFY(QDir().mkpath(output));
        const auto source = temporary.filePath(QStringLiteral("跨平台.bin"));
        QFile data(source);
        QVERIFY(data.open(QIODevice::WriteOnly));
        for (int index = 0; index < 33; ++index)
            dukto::writeAll(data, QByteArray(256 * 1024, 'g'));
        data.close();
        const auto expected = dukto::hashFile(source);
        ServerPanel server(temporary.filePath("server"));
        server.execute("init", {{"names", "127.0.0.1"}});
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QVERIFY2(!server.identity()["serverId"].toString().isEmpty(), qPrintable(server.status()));
        const QVariantMap permissions{{"share", "docs"},
                                      {"path", shared},
                                      {"browse", true},
                                      {"download", true},
                                      {"upload", true}};
        server.execute("share-add", permissions);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.entries().size(), 1);
        server.execute("pairing", permissions);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        const auto credential = server.outcome()["credentialFile"].toString();
        QVERIFY2(QFileInfo::exists(credential), qPrintable(server.status()));
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        server.setServing(true, "127.0.0.1", port);
        QVERIFY2(server.serving(), qPrintable(server.status()));
        SlowTestProxy proxy(port);
        ServerPanel client(temporary.filePath("client"));
        client.execute("pair", {{"target", QString("127.0.0.1:%1").arg(proxy.serverPort())},
                                {"fingerprint", server.identity()["fingerprint"]},
                                {"credentialFile", credential}});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        const auto clientId = client.outcome()["client"].toString();
        QVERIFY2(!clientId.isEmpty(), qPrintable(client.status()));
        client.execute("upload",
                       {{"share", "docs"}, {"paths", QStringList{source}}, {"channels", "4"}});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.task()["state"].toString(), QString("completed"));
        QCOMPARE(dukto::hashFile(QDir(shared).filePath(QFileInfo(source).fileName())), expected);
        QCOMPARE(client.task()["channels"].toString(), QString("4"));
        const auto uploadedTask = client.task()["taskId"].toString();
        client.execute("task", {{"taskId", uploadedTask}});
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QCOMPARE(client.task()["state"].toString(), QString("completed"));
        QVERIFY(!client.task()["executionActive"].toBool());
        client.execute("list", {{"share", "docs"}});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.listingKind(), QString("listing"));
        QCOMPARE(client.entries().size(), 1);
        QCOMPARE(client.entries()[0].toMap()["name"].toString(), QFileInfo(source).fileName());
        const auto request = QUuid::createUuid().toString(QUuid::WithoutBraces);
        const QVariantMap download{{"channels", "4"},
                                   {"share", "docs"},
                                   {"remotePath", QFileInfo(source).fileName()},
                                   {"output", output},
                                   {"requestId", request}};
        client.execute("download", download);
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.task()["state"].toString(), QString("completed"));
        QCOMPARE(client.task()["channels"].toString(), QString("4"));
        QCOMPARE(client.task()["receivedBytes"], client.task()["total"]);
        const auto downloadedTask = client.task()["taskId"].toString();
        QCOMPARE(dukto::hashFile(QDir(output).filePath(QFileInfo(source).fileName())), expected);
        client.execute("download", download);
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.task()["taskId"].toString(), downloadedTask);
        QCOMPARE(QDir(output).entryList(QDir::Files).size(), 1);
        client.execute("task-items", {{"taskId", downloadedTask}});
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QVERIFY(client.itemPage()["available"].toBool());
        QCOMPARE(client.itemPage()["entries"].toList().size(), 1);
        QCOMPARE(client.itemPage()["entries"].toList()[0].toMap()["disposition"].toString(),
                 QString("copied"));
        client.execute("tasks", {});
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QCOMPARE(client.tasks().size(), 2);
        QVERIFY(!client.tasksMore());
        {
            ServerPanel restarted(temporary.filePath("client"));
            restarted.execute("tasks", {});
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.controlBusy(), 30000);
            QCOMPARE(restarted.tasks().size(), 2);
        }
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        QSignalSpy qmlWarnings(view.engine(), &QQmlEngine::warnings);
        QQmlComponent component(view.engine(), QUrl("qrc:/ui/ServerPage.qml"));
        auto root = component.createWithInitialProperties(
            {{"panel", QVariant::fromValue<QObject *>(&client)}});
        QVERIFY2(root, qPrintable(component.errorString()));
        view.setContent(QUrl("qrc:/ui/ServerPage.qml"), &component, root);
        QCOMPARE(view.status(), QQuickWidget::Ready);
        QVERIFY(view.rootObject());
        view.show();
        QTest::qWait(200);
        auto browse = root->findChild<QQuickItem *>("serverBrowseButton");
        QVERIFY(browse);
        const auto click = [&](QQuickItem *item) {
            // 日期：2026-11-04；沿实际场景位置点击生产按钮，不能直接调用槽冒充交互。
            const auto point = item->mapToScene(item->boundingRect().center()).toPoint();
            QTest::mouseClick(&view, Qt::LeftButton, Qt::NoModifier, point);
        };
        // 日期：2026-11-05；生产按钮实际轮换，随后沿同一主体继续浏览和恢复原任务。
        auto rotate = root->findChild<QQuickItem *>("serverRotateCredential");
        QVERIFY(rotate);
        click(rotate);
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.outcome()["event"].toString(), QString("credential-rotated"));
        QCOMPARE(client.outcome()["client"].toString(), clientId);
        QCOMPARE(client.outcome()["revision"].toString(), QString("2"));
        click(browse);
        QVERIFY(client.busy());
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QCOMPARE(client.outcome()["event"].toString(), QString("listing"));
        QCOMPARE(client.entries().size(), 1);
        const auto picture = view.grabFramebuffer();
        QVERIFY(!picture.isNull());
        QVERIFY(picture.save("Testing/QtTest/server-page.png"));
        auto sections = root->findChild<QObject *>("serverSections");
        QVERIFY(sections);
        sections->setProperty("currentIndex", 1);
        QTest::qWait(100);
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-tasks.png"));
        sections->setProperty("currentIndex", 2);
        QTest::qWait(100);
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-local.png"));
        view.resize(360, 560);
        QTest::qWait(100);
        QVERIFY(!view.grabFramebuffer().isNull());
        view.resize(430, 700);
        auto clientFlick = root->findChild<QQuickItem *>("serverClientFlick");
        auto taskFlick = root->findChild<QQuickItem *>("serverTaskFlick");
        QVERIFY(clientFlick && taskFlick);
        const auto visibleClick = [&](const char *name, QQuickItem *flick) {
            // 日期：2026-11-05；先按真实 Flickable 内容坐标滚动，再向生产窗口投递鼠标点击。
            auto button = root->findChild<QQuickItem *>(name);
            if (!button)
                return false;
            // 日期：2026-11-05；折叠区切换后的 Qt Quick 布局先完成一轮 polish，再计算实际点击位置。
            QTest::qWait(60);
            const auto current = flick->property("contentY").toDouble();
            const auto position = button->mapToItem(flick, QPointF()).y();
            const auto maximum =
                qMax(0.0, flick->property("contentHeight").toDouble() - flick->height());
            flick->setProperty("contentY", qBound(0.0, current + position - 180, maximum));
            QTest::qWait(30);
            click(button);
            return true;
        };
        // 日期：2026-11-05；实际生产按钮查询下载接收证据，模型与目录浏览/任务列表相互独立。
        sections->setProperty("currentIndex", 1);
        QVERIFY(visibleClick("serverItemsFirstButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QCOMPARE(client.itemPage()["taskId"].toString(), downloadedTask);
        QCOMPARE(client.itemPage()["entries"].toList()[0].toMap()["disposition"].toString(),
                 QString("copied"));
        QVERIFY(!client.itemPage()["more"].toBool());
        auto itemsNext = root->findChild<QQuickItem *>("serverItemsNextButton");
        QVERIFY(itemsNext && !itemsNext->isEnabled());
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-task-items.png"));
        const auto interactiveOutput = temporary.filePath("interactive-output");
        QVERIFY(QDir().mkpath(interactiveOutput));
        auto remotePath = root->findChild<QObject *>("serverRemotePath");
        auto savePath = root->findChild<QObject *>("serverOutput");
        auto channels = root->findChild<QObject *>("serverChannelCount");
        QVERIFY(remotePath && savePath && channels);
        remotePath->setProperty("text", QFileInfo(source).fileName());
        savePath->setProperty("text", interactiveOutput);
        channels->setProperty("currentIndex", 2);
        sections->setProperty("currentIndex", 0);
        auto retries = root->findChild<QObject *>("serverRetryCount");
        auto deadline = root->findChild<QObject *>("serverDeadlineSeconds");
        auto conflict = root->findChild<QObject *>("serverConflictPolicy");
        QVERIFY(retries && deadline && conflict);
        QCOMPARE(conflict->property("currentIndex").toInt(), 0);
        conflict->setProperty("currentIndex", 1);
        QCOMPARE(retries->property("currentText").toString(), QString("0"));
        QCOMPARE(deadline->property("text").toString(), QString("86400"));
        QVERIFY(visibleClick("serverShowTransferPolicy", clientFlick));
        retries->setProperty("currentIndex", 3);
        deadline->setProperty("text", "30");
        // 日期：2026-11-05；展开后先等待布局刷新，再滚动，避免用折叠时的旧内容高度截图。
        QTest::qWait(100);
        clientFlick->setProperty(
            "contentY",
            qMax(0.0, clientFlick->property("contentHeight").toDouble() - clientFlick->height()));
        QTest::qWait(100);
        auto deadlineItem = qobject_cast<QQuickItem *>(deadline);
        QVERIFY(deadlineItem);
        QVERIFY(deadlineItem->mapToItem(clientFlick, QPointF(0, deadlineItem->height())).y() <=
                clientFlick->height());
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-transfer-policy.png"));
        QVERIFY(visibleClick("serverDownloadButton", clientFlick));
        QVERIFY(client.busy());
        QTRY_VERIFY_WITH_TIMEOUT(client.task()["state"] == "transferring" &&
                                     client.task()["taskId"] != downloadedTask,
                                 30000);
        const auto interactiveTask = client.task()["taskId"].toString();
        QCOMPARE(client.task()["conflict"].toString(), QString("fail"));
        // 日期：2026-11-05；生产 GUI 在单个大文件完成前必须出现实际字节，进度条与限频快照一致。
        QTRY_VERIFY_WITH_TIMEOUT(client.task()["receivedBytes"].toString().toLongLong() > 0 &&
                                     client.task()["receivedBytes"].toString().toLongLong() <
                                         client.task()["total"].toString().toLongLong(),
                                 30000);
        auto byteProgress = root->findChild<QObject *>("serverByteProgress");
        QVERIFY(byteProgress);
        QVERIFY(byteProgress->property("value").toDouble() > 0 &&
                byteProgress->property("value").toDouble() < 1);
        QVERIFY(client.task()["bytesPerSecond"].toDouble() > 0);
        proxy.cutConnections();
        QTRY_COMPARE_WITH_TIMEOUT(client.task()["state"].toString(), QString("retrying"), 5000);
        QTRY_COMPARE_WITH_TIMEOUT(client.task()["state"].toString(), QString("transferring"),
                                  10000);
        QCOMPARE(client.task()["taskId"].toString(), interactiveTask);
        sections->setProperty("currentIndex", 1);
        QVERIFY(visibleClick("serverPauseButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy() && !client.controlBusy(), 30000);
        QVERIFY(visibleClick("serverQueryButton", taskFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QCOMPARE(client.task()["state"].toString(), QString("paused"));
        proxy.restoreSpeed();
        QVERIFY(!client.task()["executionActive"].toBool());
        {
            // 日期：2026-11-05；重建生产面板后从服务器找回同一任务，实际点击继续并核对原目标内容。
            ServerPanel restarted(temporary.filePath("client"));
            root->setProperty("panel", QVariant::fromValue<QObject *>(&restarted));
            QVERIFY(visibleClick("serverRecoverTasksButton", taskFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.controlBusy(), 30000);
            bool found = false;
            for (const auto &value : restarted.tasks())
                found = found || value.toMap()["taskId"] == interactiveTask;
            QVERIFY(found);
            auto taskField = root->findChild<QObject *>("serverTaskId");
            QVERIFY(taskField);
            taskField->setProperty("text", interactiveTask);
            // 日期：2026-11-05；实际下拉框改回默认后恢复，执行仍必须使用原 fail 策略。
            conflict->setProperty("currentIndex", 0);
            QVERIFY(visibleClick("serverResumeButton", taskFlick));
            QVERIFY(restarted.busy());
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QCOMPARE(restarted.task()["state"].toString(), QString("completed"));
            QCOMPARE(restarted.task()["taskId"].toString(), interactiveTask);
            QCOMPARE(restarted.task()["conflict"].toString(), QString("fail"));
            QCOMPARE(restarted.task()["channels"].toString(), QString("4"));
            QCOMPARE(
                dukto::hashFile(QDir(interactiveOutput).filePath(QFileInfo(source).fileName())),
                expected);
            QCOMPARE(QDir(interactiveOutput).entryList(QDir::Files).size(), 1);
            // 日期：2026-11-05；真实按钮以新请求再次下载到同名目标，fail
            // 必须报冲突且原文件摘要不变。
            sections->setProperty("currentIndex", 0);
            conflict->setProperty("currentIndex", 1);
            QVERIFY(visibleClick("serverDownloadButton", clientFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QCOMPARE(restarted.outcome()["code"].toInt(), 4);
            QCOMPARE(restarted.outcome()["stage"].toString(), QString("conflict"));
            QCOMPARE(
                dukto::hashFile(QDir(interactiveOutput).filePath(QFileInfo(source).fileName())),
                expected);
            QCOMPARE(QDir(interactiveOutput).entryList(QDir::Files).size(), 1);
            const auto failedConflictTask = restarted.task()["taskId"].toString();
            // 日期：2026-11-05；真实按钮查询原下载日志，界面必须显示具体失败原因和未解决状态。
            sections->setProperty("currentIndex", 1);
            taskField->setProperty("text", failedConflictTask);
            QVERIFY(visibleClick("serverItemsFirstButton", taskFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.controlBusy(), 30000);
            QCOMPARE(restarted.itemPage()["taskId"].toString(), failedConflictTask);
            QVERIFY(restarted.itemPage()["failureEvidenceAvailable"].toBool());
            const auto itemFailure =
                restarted.itemPage()["entries"].toList()[0].toMap()["lastFailure"].toMap();
            QCOMPARE(itemFailure["code"].toInt(), 4);
            QCOMPARE(itemFailure["stage"].toString(), QString("conflict"));
            QVERIFY(!itemFailure["resolved"].toBool());
            auto itemList = root->findChild<QQuickItem *>("serverItemsList");
            QVERIFY(itemList);
            QTest::qWait(100);
            const auto content = itemList->property("contentItem").value<QObject *>();
            QVERIFY(content);
            QStringList displayed;
            std::function<void(QQuickItem *)> collectText = [&](QQuickItem *item) {
                // 日期：2026-11-05；仅遍历测试窗口的视觉树，QtQuick委托不一定是其视觉父项的QObject子对象。
                const auto text = item->property("text").toString();
                if (!text.isEmpty())
                    displayed.append(text);
                for (auto child : item->childItems())
                    collectText(child);
            };
            collectText(itemList);
            const auto visibleText = displayed.join('\n');
            QVERIFY2(visibleText.contains(QStringLiteral("本项最近失败")) &&
                         visibleText.contains(QStringLiteral("目标名称冲突")),
                     qPrintable(visibleText));
            const auto currentY = taskFlick->property("contentY").toDouble();
            const auto listY = itemList->mapToItem(taskFlick, QPointF()).y();
            taskFlick->setProperty(
                "contentY", qBound(0.0, currentY + listY - 150,
                                   qMax(0.0, taskFlick->property("contentHeight").toDouble() -
                                                 taskFlick->height())));
            QTest::qWait(100);
            QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-item-failure.png"));
            sections->setProperty("currentIndex", 0);
            conflict->setProperty("currentIndex", 0);
            const auto cancelledOutput = temporary.filePath("cancelled-output");
            QVERIFY(QDir().mkpath(cancelledOutput));
            savePath->setProperty("text", cancelledOutput);
            sections->setProperty("currentIndex", 0);
            QVERIFY(visibleClick("serverDownloadButton", clientFlick));
            QTRY_VERIFY_WITH_TIMEOUT(restarted.task()["state"] == "transferring" &&
                                         restarted.task()["taskId"] != interactiveTask &&
                                         restarted.task()["taskId"] != failedConflictTask,
                                     30000);
            const auto cancelledTask = restarted.task()["taskId"].toString();
            taskField->setProperty("text", cancelledTask);
            sections->setProperty("currentIndex", 1);
            QVERIFY(visibleClick("serverCancelButton", taskFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy() && !restarted.controlBusy(), 30000);
            QVERIFY(visibleClick("serverQueryButton", taskFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.controlBusy(), 30000);
            QCOMPARE(restarted.task()["state"].toString(), QString("cancelled"));
            QVERIFY(!restarted.task()["executionActive"].toBool());
            QVERIFY(visibleClick("serverResumeButton", taskFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QVERIFY(restarted.status().contains(QStringLiteral("操作失败（2）")));
            QVERIFY(
                !QFileInfo::exists(QDir(cancelledOutput).filePath(QFileInfo(source).fileName())));
            // 日期：2026-11-05；真实鼠标启动单通道慢下载，总期限必须结束正文并保持未发布目标。
            const auto deadlineOutput = temporary.filePath("deadline-output");
            QVERIFY(QDir().mkpath(deadlineOutput));
            sections->setProperty("currentIndex", 0);
            savePath->setProperty("text", deadlineOutput);
            channels->setProperty("currentIndex", 0);
            deadline->setProperty("text", "1");
            QVERIFY(visibleClick("serverDownloadButton", clientFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 5000);
            QCOMPARE(restarted.outcome()["code"].toInt(), 3);
            QCOMPARE(restarted.outcome()["stage"].toString(), QString("deadline"));
            QVERIFY(
                !QFileInfo::exists(QDir(deadlineOutput).filePath(QFileInfo(source).fileName())));
            deadline->setProperty("text", "30");
            // 日期：2026-11-05；真实上传空文件与空目录，最终确认后的零字节进度必须为 100%。
            const auto emptySource = temporary.filePath("empty-file.txt");
            const auto emptyTree = temporary.filePath("empty-tree");
            QFile emptyFile(emptySource);
            QVERIFY(emptyFile.open(QIODevice::WriteOnly));
            emptyFile.close();
            QVERIFY(QDir().mkpath(QDir(emptyTree).filePath("nested")));
            restarted.execute("upload", {{"share", "docs"},
                                         {"paths", QStringList{emptySource, emptyTree}},
                                         {"channels", "4"}});
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QCOMPARE(restarted.task()["state"].toString(), QString("completed"));
            QCOMPARE(restarted.task()["total"].toString(), QString("0"));
            QCOMPARE(restarted.task()["receivedBytes"].toString(), QString("0"));
            QCOMPARE(byteProgress->property("value").toDouble(), 1.0);
            QVERIFY(!byteProgress->property("indeterminate").toBool());
            QVERIFY(QFileInfo::exists(QDir(shared).filePath("empty-file.txt")));
            QCOMPARE(QFileInfo(QDir(shared).filePath("empty-file.txt")).size(), qint64(0));
            QVERIFY(QFileInfo(QDir(shared).filePath("empty-tree/nested")).isDir());
            const auto emptyOutput = temporary.filePath("empty-output");
            QVERIFY(QDir().mkpath(emptyOutput));
            for (const auto &path : {QString("empty-file.txt"), QString("empty-tree")}) {
                // 日期：2026-11-05；空文件与纯空目录分别实际下载，不能用模型注入成功状态替代链路。
                restarted.execute("download", {{"share", "docs"},
                                               {"remotePath", path},
                                               {"output", emptyOutput},
                                               {"channels", "4"}});
                QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
                QCOMPARE(restarted.task()["state"].toString(), QString("completed"));
                QCOMPARE(restarted.task()["total"].toString(), QString("0"));
                QCOMPARE(byteProgress->property("value").toDouble(), 1.0);
                QVERIFY(!byteProgress->property("indeterminate").toBool());
            }
            QVERIFY(QFileInfo::exists(QDir(emptyOutput).filePath("empty-file.txt")));
            QCOMPARE(QFileInfo(QDir(emptyOutput).filePath("empty-file.txt")).size(), qint64(0));
            QVERIFY(QFileInfo(QDir(emptyOutput).filePath("empty-tree/nested")).isDir());
            // 日期：2026-11-05；真实下拉框选择覆盖并点击下载，先写已有文件，再验证零字节原子替换与策略显示。
            {
                QFile existing(QDir(emptyOutput).filePath("empty-file.txt"));
                QVERIFY(existing.open(QIODevice::WriteOnly));
                dukto::writeAll(existing, "original");
            }
            sections->setProperty("currentIndex", 0);
            remotePath->setProperty("text", "empty-file.txt");
            savePath->setProperty("text", emptyOutput);
            conflict->setProperty("currentIndex", 2);
            QVERIFY(visibleClick("serverDownloadButton", clientFlick));
            QTRY_VERIFY_WITH_TIMEOUT(!restarted.busy(), 30000);
            QCOMPARE(restarted.task()["state"].toString(), QString("completed"));
            QCOMPARE(restarted.task()["conflict"].toString(), QString("overwrite"));
            QCOMPARE(QFileInfo(QDir(emptyOutput).filePath("empty-file.txt")).size(), qint64(0));
            QVERIFY(root->findChild<QObject *>("serverTaskConflictPolicy")
                        ->property("text")
                        .toString()
                        .contains(QStringLiteral("覆盖")));
            QTest::qWait(50);
            QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-overwrite.png"));
            root->setProperty("panel", QVariant::fromValue<QObject *>(&client));
        }
        QCOMPARE(qmlWarnings.count(), 0);
        QVERIFY(!client.outcome().contains("credential"));
        QVERIFY(!client.outcome().contains("privateKey"));
        auto restricted = permissions;
        restricted["client"] = clientId;
        restricted["download"] = false;
        restricted["upload"] = false;
        server.execute("grant", restricted);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        client.execute("task", {{"taskId", downloadedTask}});
        QTRY_VERIFY_WITH_TIMEOUT(!client.controlBusy(), 30000);
        QVERIFY(client.status().contains(QStringLiteral("操作失败（4）")));
        // 日期：2026-11-05；本机管理必须从真实配对身份生成列表，点击选择并在撤销后自动刷新。
        root->setProperty("panel", QVariant::fromValue<QObject *>(&server));
        sections->setProperty("currentIndex", 2);
        auto localFlick = root->findChild<QQuickItem *>("serverLocalFlick");
        QVERIFY(localFlick);
        // 日期：2026-11-05；生产折叠设置真实点击读取/保存，重建模型后必须读回持久策略，随后恢复默认。
        QVERIFY(visibleClick("serverSessionExpand", localFlick));
        QVERIFY(root->findChild<QObject *>("serverSessionExpand")->property("checked").toBool());
        // 日期：2026-11-07；鼠标事件可能已处理完整异步读取，记录真实忙碌转变而不要求点击返回时仍忙。
        bool sessionReadStarted = false;
        QObject sessionReadObserver;
        connect(&server, &ServerPanel::changed, &sessionReadObserver,
                [&]() { sessionReadStarted = sessionReadStarted || server.busy(); });
        QVERIFY(visibleClick("serverSessionRead", localFlick));
        QVERIFY(sessionReadStarted);
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.outcome()["event"].toString(), QString("session-policy"));
        QCOMPARE(server.sessionSeconds(), 86400);
        auto secondsInput = root->findChild<QObject *>("serverSessionSeconds");
        QVERIFY(secondsInput);
        secondsInput->setProperty("value", 7);
        QVERIFY(visibleClick("serverSessionSave", localFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.sessionSeconds(), 7);
        QCOMPARE(server.outcome()["seconds"].toString(), QString("7"));
        {
            ServerPanel reloaded(server.directory());
            reloaded.execute("session-show", {});
            QTRY_VERIFY_WITH_TIMEOUT(!reloaded.busy(), 30000);
            QCOMPARE(reloaded.sessionSeconds(), 7);
        }
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-session-policy.png"));
        secondsInput->setProperty("value", 86400);
        QVERIFY(visibleClick("serverSessionSave", localFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.sessionSeconds(), 86400);
        QVERIFY(visibleClick("serverSessionExpand", localFlick));
        QVERIFY(visibleClick("serverClientsRefresh", localFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.outcome()["event"].toString(), QString("clients"));
        QCOMPARE(server.clients().size(), 1);
        QVERIFY(!server.clientsMore());
        QCOMPARE(server.clients()[0].toMap()["client"].toString(), clientId);
        QCOMPARE(server.clients()[0].toMap()["revision"].toString(), QString("3"));
        auto list = root->findChild<QQuickItem *>("serverClientsList");
        QVERIFY(list);
        QQuickItem *entry = nullptr;
        const auto findEntry = [&]() {
            // 日期：2026-11-05；虚拟列表委托属于 contentItem，沿实际可视子项查找生产按钮。
            auto content = list->property("contentItem").value<QQuickItem *>();
            if (content)
                for (auto item : content->childItems())
                    if (item->objectName() == "serverClientEntry")
                        entry = item;
            return entry != nullptr;
        };
        QTRY_VERIFY(findEntry());
        const auto current = localFlick->property("contentY").toDouble();
        const auto position = list->mapToItem(localFlick, QPointF()).y();
        localFlick->setProperty("contentY", current + position - 100);
        QTest::qWait(100);
        click(entry);
        auto selected = root->findChild<QObject *>("serverClientId");
        auto rights = root->findChild<QObject *>("serverClientPermissions");
        QVERIFY(selected && rights);
        QCOMPARE(selected->property("text").toString(), clientId);
        QVERIFY(rights->property("text").toString().contains(QStringLiteral("docs：浏览")));
        QVERIFY(!rights->property("text").toString().contains(QStringLiteral("下载")));
        QVERIFY(visibleClick("serverClientRevoke", localFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.outcome()["event"].toString(), QString("clients"));
        QCOMPARE(server.clients().size(), 1);
        QVERIFY(server.clients()[0].toMap()["revoked"].toBool());
        QCOMPARE(server.clients()[0].toMap()["revision"].toString(), QString("4"));
        QVERIFY(rights->property("text").toString().contains(QStringLiteral("已撤销")));
        QVERIFY(view.grabFramebuffer().save("Testing/QtTest/server-clients.png"));
        view.resize(360, 560);
        QTest::qWait(100);
        QVERIFY(!view.grabFramebuffer().isNull());
        QCOMPARE(qmlWarnings.count(), 0);
        client.execute("auth", {});
        QTRY_VERIFY_WITH_TIMEOUT(!client.busy(), 30000);
        QVERIFY(client.status().contains(QStringLiteral("操作失败（4）")));
        {
            // 日期：2026-11-05；真实授权存储生成超过一页主体，生产分页按钮替换模型而不累积历史页。
            dukto::PrivateStore store(QDir(server.directory()).filePath("service"));
            dukto::AuthStore auth(store);
            for (int index = 1; index <= 102; ++index) {
                const auto id = QUuid(
                    QString("00000000-0000-0000-0000-%1").arg(index, 12, 16, QLatin1Char('0')));
                const auto offer = auth.issue({{"docs", true, false, false}});
                auth.pair(offer.credential, id, dukto::randomCredential());
            }
        }
        QVERIFY(visibleClick("serverClientsRefresh", localFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.clients().size(), 100);
        QVERIFY(server.clientsMore());
        const auto firstCursor = server.clientsAfter();
        QVERIFY(visibleClick("serverClientsNext", localFlick));
        QTRY_VERIFY_WITH_TIMEOUT(!server.busy(), 30000);
        QCOMPARE(server.clients().size(), 3);
        QVERIFY(!server.clientsMore());
        QVERIFY(server.clientsAfter() > firstCursor);
        QCOMPARE(qmlWarnings.count(), 0);
        server.setServing(false, "127.0.0.1", port);
        QVERIFY(!server.serving());
    }
};

// 日期：2026-11-04；软件渲染与产品一致，GUI 结果是真实 QML 加载和 TLS 数据，非界面模型假对象。
int main(int argc, char **argv) {
    qRegisterMetaType<QList<QQmlError>>("QList<QQmlError>");
#ifdef Q_OS_WIN
    qputenv("QT_QPA_FONTDIR", (qEnvironmentVariable("WINDIR") + "/Fonts").toUtf8());
#endif
    QQuickWindow::setSceneGraphBackend(QSGRendererInterface::Software);
    QApplication application(argc, argv);
    ServerPanelTests tests;
    return QTest::qExec(&tests, argc, argv);
}
#include "server_panel_tests.moc"

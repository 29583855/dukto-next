#include "app/controller.h"
#include "core/buffercredit.h"
#include "core/files.h"
#include <QApplication>
#include <QClipboard>
#include <QDragEnterEvent>
#include <QDragMoveEvent>
#include <QDropEvent>
#include <QFont>
#include <QGlyphRun>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMetaMethod>
#include <QMimeData>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickTextDocument>
#include <QQuickWidget>
#include <QQuickWindow>
#include <QRawFont>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTextDocument>
#include <QTextLayout>
#include <QtEndian>
#include <QtTest>
#include <memory>

// 日期：2026-11-07；只在隔离Qt剪贴板中记录正文请求次数，保持QMimeData真实文本转换路径。
class CountingClipboardData final : public QMimeData {
  public:
    // 日期：2026-11-07；计数器独立于Qt接管的MIME对象存活，不复制或保存系统剪贴板内容。
    CountingClipboardData(std::shared_ptr<int> reads, const QString &text)
        : reads_(std::move(reads)) {
        setText(text);
    }

  protected:
    // 日期：2026-11-07；只有实际取正文才计数，格式查询与界面刷新本身不应读取正文。
    QVariant retrieveData(const QString &mimeType, QVariant::Type type) const override {
        if (mimeType == QStringLiteral("text/plain"))
            ++*reads_;
        return QMimeData::retrieveData(mimeType, type);
    }

  private:
    std::shared_ptr<int> reads_;
};

// 日期：2026-11-07；独立慢接收端从接管原生描述符之前即限制Qt预读，避免平台事件时序抢先收完。
class CancellationPeer final : public QTcpServer {
  protected:
    // 日期：2026-11-07；先设64KiB读取上限再发布连接；父对象管理失败连接和待接管套接字。
    void incomingConnection(qintptr descriptor) override {
        auto socket = new QTcpSocket(this);
        socket->setReadBufferSize(64 * 1024);
        if (!socket->setSocketDescriptor(descriptor)) {
            socket->deleteLater();
            return;
        }
        addPendingConnection(socket);
    }
};

class UiTests final : public QObject {
    Q_OBJECT
  private:
    // 日期：2026-11-04；Repeater 委托的对象所有权与视觉父项不同，沿实际场景查找控件。
    QQuickItem *findItem(QQuickItem *parent, const QString &name) {
        if (parent->objectName() == name)
            return parent;
        for (auto child : parent->childItems())
            if (auto found = findItem(child, name))
                return found;
        return nullptr;
    }

    // 日期：2026-11-05；渲染并完成待处理布局后按实际场景位置点击，不直接调用控制器或控件槽。
    void click(QQuickWidget &view, QQuickItem *item) {
        QVERIFY(item);
        QVERIFY(!view.grabFramebuffer().isNull());
        const auto point = item->mapToScene(item->boundingRect().center()).toPoint();
        QVERIFY(item->isVisible() && item->isEnabled());
        QVERIFY(view.rect().contains(point));
        QTest::mouseClick(&view, Qt::LeftButton, Qt::NoModifier, point);
    }

  private slots:

    // 日期：2026-11-07；GUI共用诊断导出核验活动监听、JSON白名单及同名保护，不打开系统选择器。
    void localDiagnosticExport() {
        QTemporaryDir root;
        QVERIFY(root.isValid());
        Controller controller(0, nullptr, root.path());
        controller.acceptTerms();
        const auto path = root.filePath(QStringLiteral("本地诊断.json"));
        QVERIFY(controller.exportDiagnosticsTo(QUrl::fromLocalFile(path)));
        QFile report(path);
        QVERIFY(report.open(QIODevice::ReadOnly));
        const auto bytes = report.readAll();
        report.close();
        const auto object = QJsonDocument::fromJson(bytes).object();
        QCOMPARE(object["event"].toString(), QString("doctor"));
        QCOMPARE(object["peer"].toObject()["status"].toString(), QString("not-requested"));
        bool active = false;
        for (const auto &value : object["checks"].toArray()) {
            const auto check = value.toObject();
            if (check["id"] == "tcp-listener")
                active = check["status"] == "active-in-this-instance";
        }
        QVERIFY(active);
        QVERIFY(!bytes.contains(root.path().toUtf8()));
        QVERIFY(!controller.exportDiagnosticsTo(QUrl::fromLocalFile(path)));
        QVERIFY(report.open(QIODevice::ReadOnly));
        QCOMPARE(report.readAll(), bytes);
        QVERIFY(!controller.exportDiagnosticsTo(QUrl("https://invalid.example/report.json")));
        QQuickWidget view;
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.resize(430, 700);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        QVERIFY(view.rootObject());
        view.show();
        QTRY_VERIFY(!view.grabFramebuffer().isNull());
        auto settings = view.rootObject()->findChild<QObject *>("settingsDialog");
        QVERIFY(settings);
        QVERIFY(QMetaObject::invokeMethod(settings, "open"));
        QTRY_VERIFY(settings->property("opened").toBool());
        auto button = findItem(view.quickWindow()->contentItem(), "exportDiagnosticReportButton");
        QVERIFY(button);
        QCOMPARE(button->property("text").toString(), QStringLiteral("导出本地诊断"));
    }

    // 日期：2026-11-07；原版中止后下一批崩溃的对照场景，分别覆盖新版实际发送和接收取消。
    void cancelThenTransferAgainThroughQml_data() {
        QTest::addColumn<QString>("phase");
        QTest::newRow("send") << QString("send");
        QTest::newRow("receive-header") << QString("receive-header");
        QTest::newRow("receive-partial") << QString("receive-partial");
    }

    // 日期：2026-11-07；实际点击生产取消按钮，部分数据后结束且释放临时额度，同一控制器随后双向成功。
    void cancelThenTransferAgainThroughQml() {
        QFETCH(QString, phase);
        const bool outgoing = phase == "send";
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", output);
        settings.setValue("terms", true);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        view.activateWindow();
        view.setFocus();
        auto root = view.rootObject();
        QVERIFY(root);
        auto cancel = root->findChild<QQuickItem *>("legacyCancelButton");
        QVERIFY(cancel);
        QTRY_VERIFY(!cancel->isVisible());
        const auto before = dukto::BufferCredit::usage()["dataUsed"].toString();
        CancellationPeer slow;
        QVERIFY(slow.listen(QHostAddress::LocalHost, 0));
        QTcpSocket incoming;
        std::unique_ptr<QTcpSocket> peer;
        const qint64 declared = 32 * 1024 * 1024;
        // 日期：2026-11-07；独立构造小端R6头，不借用被测收发编码器。
        const auto number = [](qint64 value) {
            QByteArray bytes(8, '\0');
            qToLittleEndian(value, reinterpret_cast<uchar *>(bytes.data()));
            return bytes;
        };
        qint64 observed = 0;
        if (outgoing) {
            QFile source(temporary.filePath("cancel.bin"));
            QVERIFY(source.open(QIODevice::WriteOnly));
            const QByteArray block(64 * 1024, 'x');
            for (int index = 0; index < declared / block.size(); ++index)
                QCOMPARE(source.write(block), qint64(block.size()));
            source.close();
            QVERIFY(controller.sendDropped("127.0.0.1", slow.serverPort(),
                                           {QUrl::fromLocalFile(source.fileName())}));
            QTRY_VERIFY(slow.hasPendingConnections());
            peer.reset(slow.nextPendingConnection());
            QVERIFY(peer);
            QTRY_VERIFY(peer->bytesAvailable() >= 16);
            const auto header = peer->read(16);
            QCOMPARE(qFromLittleEndian<qint64>(reinterpret_cast<const uchar *>(header.constData())),
                     qint64(1));
            QCOMPARE(
                qFromLittleEndian<qint64>(reinterpret_cast<const uchar *>(header.constData() + 8)),
                declared);
            QTRY_VERIFY(peer->bytesAvailable() > 32);
            QVERIFY(peer->bytesAvailable() <= 64 * 1024);
            observed = 16;
        } else {
            incoming.connectToHost(QHostAddress::LocalHost, port);
            QVERIFY(incoming.waitForConnected(2000));
            const auto frame = phase == "receive-header"
                                   ? number(1)
                                   : number(1) + number(declared) + QByteArray("cancel.bin\0", 11) +
                                         number(declared) + QByteArray(64 * 1024, 'x');
            QCOMPARE(incoming.write(frame), qint64(frame.size()));
            incoming.flush();
            if (phase == "receive-partial")
                QTRY_VERIFY(
                    !QDir(output).entryList({"*.part"}, QDir::Files | QDir::Hidden).isEmpty());
        }
        QTRY_VERIFY(controller.busy() && cancel->isVisible());
        click(view, cancel);
        QTRY_VERIFY2_WITH_TIMEOUT(!controller.busy(), qPrintable(controller.status()), 5000);
        QVERIFY(controller.status().contains(QStringLiteral("取消")));
        QTRY_VERIFY(!cancel->isVisible());
        if (outgoing) {
            // 日期：2026-11-07；取消后有界排空独立对端，确认EOF与部分正文；不等待原文件完整发送。
            peer->setReadBufferSize(256 * 1024);
            QObject::connect(peer.get(), &QTcpSocket::readyRead, peer.get(),
                             [&]() { observed += peer->readAll().size(); });
            observed += peer->readAll().size();
            QTRY_COMPARE_WITH_TIMEOUT(peer->state(), QAbstractSocket::UnconnectedState, 5000);
            observed += peer->readAll().size();
            QVERIFY(observed > 32 && observed < declared);
        } else {
            QTRY_VERIFY(QDir(output).entryList({"*.part"}, QDir::Files | QDir::Hidden).isEmpty());
            QVERIFY(!QFileInfo::exists(QDir(output).filePath("cancel.bin")));
            incoming.abort();
        }
        QTRY_COMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), before);
        const auto nextOutput = temporary.filePath("next-output");
        QVERIFY(QDir().mkpath(nextOutput));
        dukto::LegacyListener receiver(nextOutput, 3000);
        QVERIFY(receiver.listen(QHostAddress::LocalHost, 0));
        QSignalSpy result(&receiver, &dukto::LegacyListener::result);
        QFile nextSource(temporary.filePath("next.bin"));
        const QByteArray payload = QStringLiteral("中止后同实例继续\ncafé 🚀\n").toUtf8();
        QVERIFY(nextSource.open(QIODevice::WriteOnly));
        QCOMPARE(nextSource.write(payload), qint64(payload.size()));
        nextSource.close();
        QVERIFY(controller.sendDropped("127.0.0.1", receiver.serverPort(),
                                       {QUrl::fromLocalFile(nextSource.fileName())}));
        QTRY_COMPARE_WITH_TIMEOUT(result.count(), 1, 5000);
        QCOMPARE(result[0][0].toInt(), 0);
        QTRY_VERIFY(!controller.busy());
        QCOMPARE(dukto::hashFile(nextSource.fileName()),
                 dukto::hashFile(QDir(nextOutput).filePath("next.bin")));
        QTcpSocket next;
        next.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(next.waitForConnected(2000));
        const auto frame = number(1) + number(payload.size()) + QByteArray("after.bin\0", 10) +
                           number(payload.size()) + payload;
        QCOMPARE(next.write(frame), qint64(frame.size()));
        next.flush();
        QFile received(QDir(output).filePath("after.bin"));
        QTRY_VERIFY2_WITH_TIMEOUT(received.exists(), qPrintable(controller.status()), 5000);
        QTRY_VERIFY(!controller.busy());
        QVERIFY(received.open(QIODevice::ReadOnly));
        QCOMPARE(received.readAll(), payload);
        QTRY_COMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), before);
    }

    // 日期：2026-11-07；生产QML的一百次进度通知不得重读剪贴板，空值禁用且点击发送必须读取最新正文。
    void clipboardAvailabilityDoesNotReadOnProgress() {
        QCOMPARE(QGuiApplication::platformName(), QString("offscreen"));
        auto clipboard = QApplication::clipboard();
        struct ClipboardReset final {
            // 日期：2026-11-07；包括断言提前返回在内，始终清空本测试的隔离Qt剪贴板。
            ~ClipboardReset() {
                QApplication::clipboard()->clear();
            }
        } reset;
        auto reads = std::make_shared<int>(0);
        clipboard->setMimeData(new CountingClipboardData(reads, QString(32768, QChar(0x6c49))));
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", temporary.path());
        settings.setValue("terms", true);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        dukto::LegacyListener receiver(temporary.path(), 3000);
        QVERIFY(receiver.listen(QHostAddress::LocalHost, 0));
        QSignalSpy result(&receiver, &dukto::LegacyListener::result);
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        view.activateWindow();
        view.setFocus();
        auto root = view.rootObject();
        QVERIFY(root);
        click(view, root->findChild<QQuickItem *>("manualSendButton"));
        auto dialog = root->findChild<QObject *>("sendDialog");
        QVERIFY(dialog);
        QTRY_VERIFY(dialog->property("opened").toBool());
        auto host = root->findChild<QQuickItem *>("hostInput");
        click(view, host);
        QTRY_VERIFY(host->hasActiveFocus());
        QTest::keyClicks(&view, QString("127.0.0.1:%1").arg(receiver.serverPort()));
        QTRY_COMPARE(host->property("text").toString(),
                     QString("127.0.0.1:%1").arg(receiver.serverPort()));
        auto action = findItem(view.quickWindow()->contentItem(), "sendAction1");
        QVERIFY(action);
        QTRY_VERIFY(action->isVisible() && action->isEnabled());
        const int before = *reads;
        QVERIFY(before > 0);
        for (int index = 0; index < 100; ++index)
            QVERIFY(QMetaObject::invokeMethod(&controller, "stateChanged", Qt::DirectConnection));
        QCoreApplication::processEvents();
        QCOMPARE(*reads, before);
        clipboard->clear();
        QTRY_VERIFY(!action->isEnabled());
        const auto text = QStringLiteral("最新正文\ncafé 🚀");
        auto replacementReads = std::make_shared<int>(0);
        clipboard->setMimeData(new CountingClipboardData(replacementReads, text));
        QTRY_VERIFY(action->isEnabled());
        const int beforeSend = *replacementReads;
        click(view, action);
        QTRY_COMPARE_WITH_TIMEOUT(result.count(), 1, 5000);
        QCOMPARE(result[0][0].toInt(), 0);
        QCOMPARE(result[0][1].value<dukto::LegacyResult>().json()["text"].toString(), text);
        QTRY_VERIFY(!controller.busy());
        QCOMPARE(*replacementReads, beforeSend + 1);
    }

    // 日期：2026-11-07；真实点击发送时授信不足必须保留草稿及窗口，解除占用后同一草稿可重试成功。
    void rejectedTextKeepsDraftThroughQml() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", temporary.path());
        settings.setValue("terms", true);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        dukto::LegacyListener receiver(temporary.path(), 3000);
        QVERIFY(receiver.listen(QHostAddress::LocalHost, 0));
        QSignalSpy result(&receiver, &dukto::LegacyListener::result);
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        view.activateWindow();
        view.setFocus();
        auto root = view.rootObject();
        QVERIFY(root);
        click(view, root->findChild<QQuickItem *>("manualSendButton"));
        auto sendDialog = root->findChild<QObject *>("sendDialog");
        QVERIFY(sendDialog);
        QTRY_VERIFY(sendDialog->property("opened").toBool());
        auto host = root->findChild<QQuickItem *>("hostInput");
        click(view, host);
        QTRY_VERIFY(host->hasActiveFocus());
        QTest::keyClicks(&view, QString("127.0.0.1:%1").arg(receiver.serverPort()));
        QTRY_COMPARE(host->property("text").toString(),
                     QString("127.0.0.1:%1").arg(receiver.serverPort()));
        auto action = findItem(view.quickWindow()->contentItem(), "sendAction0");
        QVERIFY(action);
        QTRY_VERIFY(action->isVisible() && action->isEnabled());
        click(view, action);
        auto dialog = root->findChild<QObject *>("textDialog");
        QVERIFY(dialog);
        QTRY_VERIFY(dialog->property("opened").toBool());
        auto editor = root->findChild<QQuickItem *>("textEditor");
        QVERIFY(editor);
        const auto draft = QStringLiteral("保存我的草稿\nUnicode café 🚀");
        editor->setProperty("text", draft);
        const auto before = dukto::BufferCredit::usage()["dataUsed"].toString().toLongLong();
        {
            dukto::BufferCredit saturated(120 * 1024 * 1024 - before, true);
            click(view, root->findChild<QQuickItem *>("sendTextSubmitButton"));
            QTest::qWait(300);
            QVERIFY(!controller.busy());
            QCOMPARE(result.count(), 0);
            QVERIFY2(dialog->property("visible").toBool(), "Rejected send closed the text editor");
            QCOMPARE(editor->property("text").toString(), draft);
            QVERIFY(dialog->property("sendError").toString().contains(QStringLiteral("授信")));
            auto error = root->findChild<QQuickItem *>("sendTextError");
            QVERIFY(error && error->isVisible());
        }
        QCOMPARE(dukto::BufferCredit::usage()["dataUsed"].toString().toLongLong(), before);
        click(view, root->findChild<QQuickItem *>("sendTextSubmitButton"));
        QTRY_COMPARE_WITH_TIMEOUT(result.count(), 1, 5000);
        QCOMPARE(result[0][0].toInt(), 0);
        QCOMPARE(qvariant_cast<dukto::LegacyResult>(result[0][1]).json()["text"].toString(), draft);
        QTRY_VERIFY(!dialog->property("visible").toBool());
        QTRY_VERIFY(!sendDialog->property("visible").toBool());
        QTRY_VERIFY(!controller.busy());
        QTRY_COMPARE(editor->property("text").toString(), QString());
    }

    // 日期：2026-11-05；产品最小尺寸与默认尺寸均须打开完整面板，禁止只验单独ServerPage。
    void serverEntryThroughMainQml_data() {
        QTest::addColumn<QSize>("size");
        QTest::newRow("compact") << QSize(360, 560);
        QTest::newRow("default") << QSize(430, 700);
    }

    // 日期：2026-11-05；从生产主窗口实际点击服务器入口，必须只打开一个根级全屏面板。
    void serverEntryThroughMainQml() {
        QFETCH(QSize, size);
        // 日期：2026-11-05；按Qt实际回退字体整形中文标签，字形0必须失败，不能把方框截图计为显示通过。
        const auto sample =
            QStringLiteral("服务器连接与文件任务本机共享返回下载上传设备最近关于设置");
        QTextLayout textLayout(sample, QApplication::font());
        textLayout.beginLayout();
        auto line = textLayout.createLine();
        QVERIFY(line.isValid());
        line.setLineWidth(8192);
        textLayout.endLayout();
        int glyphCount = 0;
        int missingGlyphs = 0;
        QJsonArray families;
        for (const auto &run : textLayout.glyphRuns()) {
            families.append(run.rawFont().familyName());
            for (const auto glyph : run.glyphIndexes()) {
                ++glyphCount;
                if (glyph == 0)
                    ++missingGlyphs;
            }
        }
        const QJsonObject fontCoverage{{"sample", sample},
                                       {"glyphCount", glyphCount},
                                       {"missingGlyphs", missingGlyphs},
                                       {"fontFamilies", families},
                                       {"passed", glyphCount > 0 && missingGlyphs == 0}};
        QVERIFY2(fontCoverage["passed"].toBool(),
                 QJsonDocument(fontCoverage).toJson(QJsonDocument::Compact).constData());
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", output);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(size);
        QSignalSpy warnings(view.engine(), &QQmlEngine::warnings);
        QVERIFY(warnings.isValid());
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        auto root = view.rootObject();
        QVERIFY(root);
        auto terms = root->findChild<QObject *>("termsDialog");
        QVERIFY(terms);
        QTRY_VERIFY(terms->property("visible").toBool());
        QTRY_VERIFY(terms->property("opened").toBool());
        QVERIFY(terms->property("x").toDouble() >= 0 && terms->property("y").toDouble() >= 0);
        QVERIFY(terms->property("height").toDouble() <= view.height());
        QVERIFY(QDir().mkpath("Testing/QtTest"));
        QVERIFY(view.grabFramebuffer().save(
            QString("Testing/QtTest/main-terms-%1x%2.png").arg(size.width()).arg(size.height())));
        click(view, root->findChild<QQuickItem *>("acceptTermsButton"));
        QTRY_VERIFY(controller.termsAccepted());
        QTRY_VERIFY(!terms->property("visible").toBool());
        click(view, root->findChild<QQuickItem *>("serverPageButton"));
        const auto panels = root->findChildren<QObject *>("serverDialog");
        QCOMPARE(panels.size(), 1);
        auto panel = panels.first();
        QTRY_VERIFY(panel->property("visible").toBool());
        QTRY_VERIFY(panel->property("opened").toBool());
        QCOMPARE(panel->property("width").toInt(), view.width());
        QCOMPARE(panel->property("height").toInt(), view.height());
        QCOMPARE(panel->property("x").toInt(), 0);
        QCOMPARE(panel->property("y").toInt(), 0);
        auto content = panel->property("contentItem").value<QQuickItem *>();
        QVERIFY(content);
        QCOMPARE(content->property("panel").value<QObject *>(), controller.server());
        auto sections = findItem(content, "serverSections");
        auto profile = findItem(content, "serverProfile");
        QVERIFY(sections && profile);
        profile->setProperty("text", "main-window-profile");
        const QStringList tabs{"serverTaskTab", "serverLocalTab", "serverConnectionTab"};
        for (int index = 0; index < tabs.size(); ++index) {
            const auto target = findItem(content, tabs[index]);
            QVERIFY(target);
            click(view, target);
            QTRY_COMPARE(sections->property("currentIndex").toInt(), (index + 1) % 3);
        }
        QVERIFY(QDir().mkpath("Testing/QtTest"));
        const auto image = view.grabFramebuffer();
        const auto stem =
            QString("Testing/QtTest/main-server-%1x%2").arg(size.width()).arg(size.height());
        QVERIFY(image.save(stem + ".png"));
        const QJsonObject geometry{
            {"platform", QGuiApplication::platformName()},
            {"chineseGlyphCoverage", fontCoverage},
            {"requestedSize", QJsonArray{size.width(), size.height()}},
            {"logicalSize", QJsonArray{view.width(), view.height()}},
            {"pixels", QJsonArray{image.width(), image.height()}},
            {"devicePixelRatio", view.devicePixelRatioF()},
            {"popupInstances", root->findChildren<QObject *>("serverDialog").size()}};
        QFile evidence(stem + ".json");
        QVERIFY(evidence.open(QIODevice::WriteOnly));
        const auto encoded = QJsonDocument(geometry).toJson();
        QCOMPARE(evidence.write(encoded), qint64(encoded.size()));
        evidence.close();
        for (int attempt = 0; attempt < 2; ++attempt) {
            click(view, findItem(content, "serverBackButton"));
            QTRY_VERIFY(!panel->property("visible").toBool());
            click(view, root->findChild<QQuickItem *>("serverPageButton"));
            QTRY_VERIFY(panel->property("opened").toBool());
            QCOMPARE(root->findChildren<QObject *>("serverDialog").size(), 1);
            QCOMPARE(panel->property("contentItem").value<QQuickItem *>(), content);
            QCOMPARE(profile->property("text").toString(), QString("main-window-profile"));
        }
        // 日期：2026-11-05；父窗口变化时同一弹层跟随实际内容区域，不能沿用旧窗口尺寸。
        view.resize(size.width() + 40, size.height() + 20);
        QTRY_COMPARE(panel->property("width").toInt(), view.width());
        QTRY_COMPARE(panel->property("height").toInt(), view.height());
        click(view, findItem(content, "serverBackButton"));
        QTRY_VERIFY(!panel->property("visible").toBool());
        QCOMPARE(warnings.count(), 0);
    }

    // 日期：2026-11-06；小量段落即检出原布局放大，最大正文分别覆盖大量换行、长单行及Unicode边界。
    void receivedLargeTextThroughQml_data() {
        QTest::addColumn<QByteArray>("payload");
        QTest::newRow("paragraph-boundary") << QByteArray(2049, '\n');
        QTest::newRow("maximum-paragraphs") << QByteArray(8 * 1024 * 1024, '\n');
        QTest::newRow("maximum-single-line") << QByteArray(8 * 1024 * 1024, 'x');
        auto unicode = QString(16383, 'x') + QString::fromUtf8("🚀") + QString(16383, 'y') +
                       QString::fromUtf8("🚀中文\r\n");
        unicode += QChar(0);
        unicode += QChar(0x2029);
        QTest::newRow("unicode-boundaries") << unicode.toUtf8();
    }

    // 日期：2026-11-06；真实R6入站触发生产QML，有限布局、翻页、尾页、复制全文与历史重开必须一起通过。
    void receivedLargeTextThroughQml() {
        QFETCH(QByteArray, payload);
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", output);
        settings.setValue("termsAccepted", true);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        controller.acceptTerms();
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        auto root = view.rootObject();
        QVERIFY(root);
        auto dialog = root->findChild<QObject *>("textDialog");
        auto editor = root->findChild<QQuickItem *>("textEditor");
        QVERIFY(dialog && editor);
        auto listener = controller.findChild<dukto::LegacyListener *>();
        QVERIFY(listener);
        QJsonArray events;
        connect(listener, &dukto::LegacyListener::event, &view,
                [&events](const QJsonObject &event) { events.append(event); });
        connect(listener, &dukto::LegacyListener::result, &view,
                [&events](int code, const dukto::LegacyResult &result) {
                    const auto &value = result.json();
                    events.append(QJsonObject{{"event", value["event"]},
                                              {"exitCode", code},
                                              {"message", value["message"]}});
                });
        QTcpSocket sender;
        sender.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(sender.waitForConnected(2000));
        QByteArray header(16, '\0');
        qToLittleEndian<qint64>(1, reinterpret_cast<uchar *>(header.data()));
        qToLittleEndian<qint64>(payload.size(), reinterpret_cast<uchar *>(header.data() + 8));
        header.append("___DUKTO___TEXT___\0", 19);
        QByteArray size(8, '\0');
        qToLittleEndian<qint64>(payload.size(), reinterpret_cast<uchar *>(size.data()));
        QCOMPARE(sender.write(header + size + payload),
                 qint64(header.size() + size.size() + payload.size()));
        sender.flush();
        // 日期：2026-11-06；保留原15秒期限，失败时区分收包、持久化与弹窗动画状态。
        const auto diagnostics = [&]() {
            return QJsonDocument(
                       QJsonObject{
                           {"status", controller.status()},
                           {"dialogVisible", dialog->property("visible").toBool()},
                           {"dialogOpened", dialog->property("opened").toBool()},
                           {"pageCount", controller.property("receivedTextPageCount").toInt()},
                           {"historyCount", controller.history().size()},
                           {"senderState", sender.state()},
                           {"senderPendingBytes", QString::number(sender.bytesToWrite())},
                           {"senderError", sender.errorString()},
                           {"viewVisible", view.isVisible()},
                           {"windowExposed", view.quickWindow()->isExposed()},
                           {"events", events}})
                .toJson(QJsonDocument::Compact);
        };
        QTRY_VERIFY2_WITH_TIMEOUT(dialog->property("opened").toBool(), diagnostics().constData(),
                                  15000);
        QVERIFY(!view.grabFramebuffer().isNull());
        auto document = editor->property("textDocument").value<QQuickTextDocument *>();
        QVERIFY(document && document->textDocument());
        const auto firstBlocks = document->textDocument()->blockCount();
        QVERIFY2(firstBlocks <= 513,
                 qPrintable(QString("Unbounded document paragraphs: %1").arg(firstBlocks)));
        QVERIFY(editor->property("text").toString().size() <= 16384);
        QVERIFY(controller.property("receivedTextPaged").toBool());
        auto next = findItem(view.quickWindow()->contentItem(), "textNextPageButton");
        auto previous = findItem(view.quickWindow()->contentItem(), "textPreviousPageButton");
        QVERIFY(next && previous);
        QVERIFY(!previous->isEnabled());
        const auto first = controller.property("receivedTextPage").toString();
        click(view, next);
        QTRY_VERIFY(controller.property("receivedTextHasPrevious").toBool());
        QVERIFY(document->textDocument()->blockCount() <= 513);
        click(view, previous);
        QCOMPARE(controller.property("receivedTextPage").toString(), first);
        const int pages = controller.property("receivedTextPageCount").toInt();
        QVERIFY(pages > 1);
        QVERIFY(QMetaObject::invokeMethod(&controller, "changeReceivedTextPage",
                                          Q_ARG(int, pages - 1)));
        QVERIFY(!controller.property("receivedTextHasNext").toBool());
        QVERIFY(!next->isEnabled());
        QVERIFY(document->textDocument()->blockCount() <= 513);
        QVERIFY(editor->property("text").toString().size() <= 16384);
        QVERIFY(editor->property("selectedText").toString().isEmpty());
        click(view, root->findChild<QQuickItem *>("copyTextButton"));
        const auto original = QString::fromUtf8(payload.constData(), payload.size());
        QCOMPARE(QApplication::clipboard()->text(), original);
        const auto history = controller.history();
        QCOMPARE(history.size(), 1);
        const auto id = history[0].toMap()["id"].toString();
        QVERIFY(!id.isEmpty());
        QVERIFY(QMetaObject::invokeMethod(dialog, "close"));
        QTRY_VERIFY(!dialog->property("visible").toBool());
        QTRY_VERIFY(controller.property("receivedTextPage").toString().isEmpty());
        controller.openHistory(id);
        QTRY_VERIFY(dialog->property("opened").toBool());
        QCOMPARE(controller.property("receivedTextPage").toString(), first);
        QVERIFY(document->textDocument()->blockCount() <= 513);
        click(view, root->findChild<QQuickItem *>("copyTextButton"));
        QCOMPARE(QApplication::clipboard()->text(), original);
        QVERIFY(QMetaObject::invokeMethod(dialog, "close"));
        QTRY_VERIFY(!dialog->property("visible").toBool());
        QTRY_COMPARE(dukto::BufferCredit::usage()["dataUsed"].toString(), QString("0"));
        QApplication::clipboard()->clear();
        const auto name =
            QString("text-preview-%1.json").arg(QString::fromLatin1(QTest::currentDataTag()));
        QFile evidence(name);
        QVERIFY(evidence.open(QIODevice::WriteOnly));
        const QJsonObject result{{"payloadBytes", payload.size()},
                                 {"firstPageBlocks", firstBlocks},
                                 {"pageCount", pages},
                                 {"maximumPageCharacters", 16384},
                                 {"maximumPageBreaks", 512},
                                 {"clipboardFullTextVerified", true},
                                 {"historyReopenVerified", true},
                                 {"creditReleased", true},
                                 {"passed", true}};
        const auto bytes = QJsonDocument(result).toJson();
        QCOMPARE(evidence.write(bytes), qint64(bytes.size()));
    }

    // 日期：2026-11-04；通过生产 QML 实测混合拖放、剪贴板发送及收到文本的选区/全文复制。
    void dragClipboardAndTextThroughQml() {
        QTemporaryDir temporary;
        QVERIFY(temporary.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, temporary.path());
        const auto output = temporary.filePath("output");
        QVERIFY(QDir().mkpath(output));
        QSettings settings(QSettings::IniFormat, QSettings::UserScope, "DuktoNext", "Desktop");
        settings.setValue("output", output);
        settings.sync();
        QTcpServer reservation;
        QVERIFY(reservation.listen(QHostAddress::LocalHost, 0));
        const auto port = reservation.serverPort();
        reservation.close();
        Controller controller(port, nullptr, temporary.filePath("state"));
        dukto::LegacyListener receiver(output, 3000, nullptr, temporary.filePath("rx.sqlite"));
        QVERIFY(receiver.listen(QHostAddress::LocalHost, 0));
        QSignalSpy result(&receiver, &dukto::LegacyListener::result);
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        QVERIFY(view.acceptDrops());
        auto root = view.rootObject();
        QVERIFY(root);
        auto terms = root->findChild<QObject *>("termsDialog");
        QVERIFY(terms);
        QTRY_VERIFY(terms->property("visible").toBool());
        auto accept = root->findChild<QQuickItem *>("acceptTermsButton");
        click(view, accept);
        QTRY_VERIFY(controller.termsAccepted());
        QTRY_VERIFY(!terms->property("visible").toBool());
        click(view, root->findChild<QQuickItem *>("manualSendButton"));
        auto dialog = root->findChild<QObject *>("sendDialog");
        QVERIFY(dialog);
        QTRY_VERIFY(dialog->property("visible").toBool());
        QTRY_VERIFY(dialog->property("opened").toBool());
        auto host = root->findChild<QQuickItem *>("hostInput");
        click(view, host);
        QTest::keyClicks(&view, QString("127.0.0.1:%1").arg(receiver.serverPort()));
        QCOMPARE(host->property("text").toString(),
                 QString("127.0.0.1:%1").arg(receiver.serverPort()));
        const auto filePath = temporary.filePath(QStringLiteral("单文件.txt"));
        QFile file(filePath);
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write("mixed drop payload\n");
        file.close();
        const auto tree = temporary.filePath(QStringLiteral("目录"));
        QVERIFY(QDir().mkpath(tree + "/empty"));
        QFile zero(tree + "/zero");
        QVERIFY(zero.open(QIODevice::WriteOnly));
        zero.close();
        QMimeData mime;
        mime.setUrls({QUrl::fromLocalFile(filePath), QUrl::fromLocalFile(tree)});
        auto area = root->findChild<QQuickItem *>("sendDropArea");
        QVERIFY(area);
        QVERIFY(area->width() > 0 && area->height() > 0);
        const auto point =
            area->mapToScene(QPointF(area->width() / 2, area->height() - 16)).toPoint();
        QDragEnterEvent enter(point, Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(&view, &enter);
        QVERIFY(enter.isAccepted());
        QVERIFY(area->property("containsDrag").toBool());
        QDragMoveEvent move(point, Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(&view, &move);
        QSignalSpy dropped(area, SIGNAL(dropped(QQuickDropEvent *)));
        QVERIFY(dropped.isValid());
        QDropEvent drop(point, Qt::CopyAction, &mime, Qt::LeftButton, Qt::NoModifier);
        QApplication::sendEvent(&view, &drop);
        QVERIFY(drop.isAccepted());
        QCOMPARE(dropped.count(), 1);
        QVERIFY(!dialog->property("visible").toBool());
        QTRY_VERIFY2_WITH_TIMEOUT(result.count() == 1, qPrintable(controller.status()), 5000);
        QCOMPARE(result[0][0].toInt(), 0);
        QTRY_VERIFY(!controller.busy());
        QVERIFY(!dialog->property("visible").toBool());
        QCOMPARE(dukto::hashFile(filePath),
                 dukto::hashFile(output + QStringLiteral("/单文件.txt")));
        QVERIFY(QFileInfo(output + QStringLiteral("/目录/empty")).isDir());
        QCOMPARE(QFileInfo(output + QStringLiteral("/目录/zero")).size(), qint64(0));
        // 日期：2026-11-04；offscreen 剪贴板与真实桌面隔离，验证按钮随空值及正文变化。
        auto clipboard = QApplication::clipboard();
        clipboard->clear();
        click(view, root->findChild<QQuickItem *>("manualSendButton"));
        auto clipboardButton = findItem(view.quickWindow()->contentItem(), "sendAction1");
        QVERIFY(clipboardButton);
        QTRY_VERIFY(!clipboardButton->isEnabled());
        const auto content = QStringLiteral("收到的文本\ncafé 🚀\n<img src='http://127.0.0.1/a'>");
        clipboard->setText(content);
        QTRY_VERIFY(clipboardButton->isEnabled());
        click(view, clipboardButton);
        QTRY_COMPARE(result.count(), 2);
        QCOMPARE(result[1][0].toInt(), 0);
        QCOMPARE(result[1][1].value<dukto::LegacyResult>().json().value("text").toString(),
                 content);
        QTRY_VERIFY(!controller.busy());

        // 日期：2026-11-04；从独立 TCP 发送方接收文本，再用键盘选择及鼠标点击实际复制控件。
        QTcpSocket sender;
        sender.connectToHost(QHostAddress::LocalHost, port);
        QVERIFY(sender.waitForConnected(2000));
        const auto number = [](qint64 value) {
            QByteArray bytes(8, '\0');
            qToLittleEndian(value, reinterpret_cast<uchar *>(bytes.data()));
            return bytes;
        };
        const auto payload = content.toUtf8();
        sender.write(number(1) + number(payload.size()) + "___DUKTO___TEXT___" + '\0' +
                     number(payload.size()) + payload);
        sender.flush();
        auto textDialog = root->findChild<QObject *>("textDialog");
        QVERIFY(textDialog);
        QTRY_VERIFY(textDialog->property("visible").toBool());
        QTRY_VERIFY(textDialog->property("opened").toBool());
        auto editor = root->findChild<QQuickItem *>("textEditor");
        QVERIFY(editor);
        QCOMPARE(editor->property("textFormat").toInt(), 0);
        QCOMPARE(editor->property("text").toString(), content);
        QVERIFY(editor->property("readOnly").toBool());
        click(view, editor);
        QTRY_VERIFY(editor->hasActiveFocus());
        QTest::keyClick(&view, Qt::Key_Home, Qt::ControlModifier);
        QTest::keyClick(&view, Qt::Key_Right, Qt::ShiftModifier);
        QTest::keyClick(&view, Qt::Key_Right, Qt::ShiftModifier);
        QCOMPARE(editor->property("selectedText").toString(), QStringLiteral("收到"));
        click(view, root->findChild<QQuickItem *>("copyTextButton"));
        QCOMPARE(clipboard->text(), QStringLiteral("收到"));
        click(view, editor);
        QTest::keyClick(&view, Qt::Key_Home, Qt::ControlModifier);
        QVERIFY(editor->property("selectedText").toString().isEmpty());
        click(view, root->findChild<QQuickItem *>("copyTextButton"));
        QCOMPARE(clipboard->text(), content);
    }
};

// 日期：2026-11-07；默认offscreen隔离剪贴板；原生只准运行服务器入口和兼容取消，拒绝混入其他槽。
int main(int argc, char **argv) {
    const auto native = qgetenv("DUKTO_TEST_UI_PLATFORM");
    if (!native.isEmpty() && native != "windows" && native != "cocoa" && native != "xcb" &&
        native != "wayland")
        return 2;
    qputenv("QT_QPA_PLATFORM", native.isEmpty() ? QByteArray("offscreen") : native);
    QApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
    QApplication::setAttribute(Qt::AA_UseHighDpiPixmaps);
    qRegisterMetaType<QList<QQmlError>>("QList<QQmlError>");
#ifdef Q_OS_WIN
    qputenv("QT_QPA_FONTDIR", (qEnvironmentVariable("WINDIR", "C:/Windows") + "/Fonts").toUtf8());
#endif
    QQuickWindow::setSceneGraphBackend(QSGRendererInterface::Software);
    QApplication app(argc, argv);
#ifdef Q_OS_WIN
    // 日期：2026-11-05；与产品主入口使用相同Windows字体，布局和点击坐标按实际应用字体计算。
    QApplication::setFont(QFont("Microsoft YaHei UI", 10));
#endif
    if (!native.isEmpty()) {
        if (QGuiApplication::platformName().toLatin1() != native)
            return 2;
        const QStringList allowed{"serverEntryThroughMainQml", "cancelThenTransferAgainThroughQml"};
        bool selected = false;
        for (const auto &argument : app.arguments().mid(1)) {
            for (int index = UiTests::staticMetaObject.methodOffset();
                 index < UiTests::staticMetaObject.methodCount(); ++index) {
                const auto name =
                    QString::fromLatin1(UiTests::staticMetaObject.method(index).name());
                if (argument == name || argument.startsWith(name + ':')) {
                    if (!allowed.contains(name))
                        return 2;
                    selected = true;
                }
            }
        }
        if (!selected)
            return 2;
    }
    UiTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "ui_tests.moc"

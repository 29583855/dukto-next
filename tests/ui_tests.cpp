#include "app/controller.h"
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
#include <QMimeData>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickWidget>
#include <QQuickWindow>
#include <QRawFont>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTextLayout>
#include <QtEndian>
#include <QtTest>

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

// 日期：2026-11-05；默认offscreen隔离剪贴板；显式原生模式只准执行不接触剪贴板的服务器入口测试。
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
    if (!native.isEmpty() && (QGuiApplication::platformName().toLatin1() != native ||
                              !app.arguments().contains("serverEntryThroughMainQml") ||
                              app.arguments().contains("dragClipboardAndTextThroughQml")))
        return 2;
    UiTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "ui_tests.moc"

#include "app/controller.h"
#include "core/files.h"
#include <QApplication>
#include <QClipboard>
#include <QDragEnterEvent>
#include <QDragMoveEvent>
#include <QDropEvent>
#include <QMimeData>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickWidget>
#include <QQuickWindow>
#include <QSignalSpy>
#include <QTemporaryDir>
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

    // 日期：2026-11-04；按照真实 QML 控件的场景位置点击，不能直接调用控制器伪装交互。
    void click(QQuickWidget &view, QQuickItem *item) {
        QVERIFY(item);
        const auto point = item->mapToScene(item->boundingRect().center()).toPoint();
        QTest::mouseClick(&view, Qt::LeftButton, Qt::NoModifier, point);
    }

  private slots:
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
        QCOMPARE(result[1][1].toJsonObject().value("text").toString(), content);
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

// 日期：2026-11-04；软件渲染配合隔离的 offscreen 平台测试真实 QML，不连接用户剪贴板。
int main(int argc, char **argv) {
    qputenv("QT_QPA_PLATFORM", "offscreen");
#ifdef Q_OS_WIN
    qputenv("QT_QPA_FONTDIR", (qEnvironmentVariable("WINDIR", "C:/Windows") + "/Fonts").toUtf8());
#endif
    QQuickWindow::setSceneGraphBackend(QSGRendererInterface::Software);
    QApplication app(argc, argv);
    UiTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "ui_tests.moc"

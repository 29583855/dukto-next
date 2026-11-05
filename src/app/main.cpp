#include "controller.h"
#include "core/error.h"

#include <QApplication>
#include <QCommandLineParser>
#include <QCryptographicHash>
#include <QDir>
#include <QFileInfo>
#include <QFont>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalServer>
#include <QLocalSocket>
#include <QLockFile>
#include <QQmlContext>
#include <QQmlError>
#include <QQuickItem>
#include <QQuickWidget>
#include <QQuickWindow>
#include <QSaveFile>
#include <QScreen>
#include <QStandardPaths>
#include <QTextStream>
#include <QTimer>

// 日期：2026-11-04；跨平台 GUI 入口，使用 Qt Quick 2 与独立于原版的单实例通道。
int main(int argc, char **argv) {
    QApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
    QApplication::setAttribute(Qt::AA_UseHighDpiPixmaps);
    QQuickWindow::setSceneGraphBackend(QSGRendererInterface::Software);
    QApplication app(argc, argv);
#ifdef Q_OS_WIN
    QApplication::setFont(QFont("Microsoft YaHei UI", 10));
#endif
    QApplication::setOrganizationName("DuktoNext");
    QApplication::setApplicationName("Dukto Next");
    QApplication::setApplicationVersion(DUKTO_VERSION);
    QCommandLineParser parser;
    parser.addOption({"port", "Legacy discovery/receive port", "port", "4644"});
    parser.addOption({"self-test", "Load QML, render and exit; no transfer is started"});
    parser.addOption({"screenshot", "Save GUI self-test rendering", "path"});
    parser.addOption({"render-report", "Save actual native self-test window geometry", "path"});
    parser.addOption({"data-directory", "Use an isolated data/configuration directory", "path"});
    if (!parser.parse(app.arguments()))
        return 2;
    bool valid = false;
    const auto port = parser.value("port").toUInt(&valid);
    if (!valid || port == 0 || port > 65535)
        return 2;
    try {
        const auto dataDirectory =
            parser.isSet("data-directory")
                ? QFileInfo(parser.value("data-directory")).absoluteFilePath()
                : QString();
        if (!dataDirectory.isEmpty()) {
            if (!QDir().mkpath(dataDirectory))
                return 5;
            QSettings::setDefaultFormat(QSettings::IniFormat);
            QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, dataDirectory);
        }
        const auto identity =
            QCryptographicHash::hash(
                (dataDirectory.isEmpty()
                     ? QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)
                     : dataDirectory)
                    .toUtf8(),
                QCryptographicHash::Sha256)
                .toHex()
                .left(24);
        const auto singleName =
            QString("dukto-next-%1-%2").arg(QString::fromLatin1(identity)).arg(port);
        QLocalSocket previous;
        previous.connectToServer(singleName);
        if (previous.waitForConnected(200)) {
            previous.write("activate");
            previous.waitForBytesWritten(200);
            return 0;
        }
        const auto lockDirectory =
            dataDirectory.isEmpty()
                ? QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation)
                : dataDirectory;
        if (!QDir().mkpath(lockDirectory))
            return 5;
        QLockFile instanceLock(QDir(lockDirectory).filePath(singleName + ".lock"));
        if (!instanceLock.tryLock(0)) {
            previous.abort();
            previous.connectToServer(singleName);
            if (!previous.waitForConnected(2000))
                return 3;
            previous.write("activate");
            previous.waitForBytesWritten(200);
            return 0;
        }
        QLocalServer singleton;
        if (!singleton.listen(singleName)) {
            if (!QLocalServer::removeServer(singleName) || !singleton.listen(singleName))
                return 3;
        }
        Controller controller(static_cast<quint16>(port), nullptr, dataDirectory);
        QQuickWidget window;
        window.setResizeMode(QQuickWidget::SizeRootObjectToView);
        window.setWindowTitle(QStringLiteral("Dukto Next"));
        window.setMinimumSize(360, 560);
        window.resize(430, 700);
        window.rootContext()->setContextProperty("controller", &controller);
        window.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        window.setSource(QUrl("qrc:/ui/Main.qml"));
        if (window.status() == QQuickWidget::Error) {
            for (const auto &error : window.errors())
                QTextStream(stderr) << error.toString() << '\n';
            return 1;
        }
        // 日期：2026-11-04；重复启动只激活已有窗口，不抢占网络端口。
        QObject::connect(&singleton, &QLocalServer::newConnection, &window, [&]() {
            auto socket = singleton.nextPendingConnection();
            if (socket) {
                socket->close();
                socket->deleteLater();
            }
            window.showNormal();
            window.raise();
            window.activateWindow();
        });
        // 日期：2026-11-04；截图期间临时隐藏窗口，完成捕获后恢复。
        QObject::connect(&controller, &Controller::captureVisibility, &window,
                         [&](bool visible) { window.setVisible(visible); });
        window.show();
        if (parser.isSet("self-test")) {
            // 日期：2026-11-05；保存真实窗口/屏幕/帧缓冲几何，原生小屏幕可缩窗，测试不能假设固定可用高度。
            QTimer::singleShot(800, &app, [&]() {
                const auto rendered = window.grabFramebuffer();
                bool passed = !rendered.isNull() && window.status() == QQuickWidget::Ready;
                if (parser.isSet("screenshot"))
                    passed = passed && rendered.save(parser.value("screenshot"));
                if (parser.isSet("render-report")) {
                    const auto available = window.screen()->availableGeometry();
                    const auto frame = window.frameGeometry();
                    const auto root = window.rootObject();
                    const QJsonObject geometry{
                        {"platform", QGuiApplication::platformName()},
                        {"requestedSize", QJsonArray{430, 700}},
                        {"logicalSize", QJsonArray{window.width(), window.height()}},
                        {"rootSize",
                         QJsonArray{root ? root->width() : 0, root ? root->height() : 0}},
                        {"availableScreen", QJsonArray{available.width(), available.height()}},
                        {"frameSize", QJsonArray{frame.width(), frame.height()}},
                        {"devicePixelRatio", window.devicePixelRatioF()},
                        {"renderedPixels", QJsonArray{rendered.width(), rendered.height()}}};
                    const auto bytes = QJsonDocument(geometry).toJson();
                    QSaveFile report(parser.value("render-report"));
                    passed = report.open(QIODevice::WriteOnly) &&
                             report.write(bytes) == bytes.size() && report.commit() && passed;
                }
                app.exit(passed ? 0 : 1);
            });
        }
        const int result = app.exec();
        return result;
    } catch (const dukto::Error &error) {
        QTextStream(stderr) << error.message << '\n';
        return static_cast<int>(error.code);
    } catch (const std::exception &error) {
        QTextStream(stderr) << error.what() << '\n';
        return 1;
    }
}

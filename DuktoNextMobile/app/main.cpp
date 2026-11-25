#include "controller.h"
#include "core/error.h"
#include "mobilefiles.h"

#include <QDir>
#include <QGuiApplication>
#include <QImage>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QStandardPaths>
#include <QTextStream>
#include <QTimer>

// 日期：2026-11-25；移动宿主复用传输与服务器控制器，用户文件与身份资料分开保存。
int main(int argc, char *argv[]) {
    QGuiApplication::setAttribute(Qt::AA_EnableHighDpiScaling);
    QGuiApplication application(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("DuktoNext"));
    QCoreApplication::setApplicationName(QStringLiteral("Mobile"));
    QCoreApplication::setApplicationVersion(QStringLiteral("0.1.0"));
    const bool smoke = application.arguments().contains(QStringLiteral("--smoke-test"));
    try {
        const auto storage = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
        if (!QDir().mkpath(storage))
            return 2;
        MobileFiles files;
        Controller controller(4644, nullptr, storage);
        QQmlApplicationEngine engine;
        engine.rootContext()->setContextProperty(QStringLiteral("controller"), &controller);
        engine.rootContext()->setContextProperty(QStringLiteral("mobileFiles"), &files);
        engine.rootContext()->setContextProperty(QStringLiteral("applicationVersion"),
                                                 application.applicationVersion());
        bool qmlFailed = false;
        QObject::connect(&engine, &QQmlEngine::warnings, &application,
                         [&qmlFailed](const QList<QQmlError> &) { qmlFailed = true; });
        engine.load(QUrl(QStringLiteral("qrc:/mobile/MobileWindow.qml")));
        if (engine.rootObjects().isEmpty())
            return 3;
        if (smoke) {
            QTimer::singleShot(1500, &application, [&] {
                auto window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
                const auto frame = window ? window->grabWindow() : QImage();
                if (qmlFailed || frame.isNull() ||
                    !frame.save(QStringLiteral("mobile-smoke.png"))) {
                    application.exit(4);
                    return;
                }
                QTextStream(stdout)
                    << "Mobile QML loaded, controller initialized, frame rendered\n";
                application.exit(0);
            });
        }
        return application.exec();
    } catch (const dukto::Error &error) {
        QTextStream(stderr) << error.what() << '\n';
        return static_cast<int>(error.code);
    } catch (const std::exception &error) {
        QTextStream(stderr) << error.what() << '\n';
        return 1;
    }
}

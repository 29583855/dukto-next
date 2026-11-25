#include "controller.h"
#include "core/error.h"
#include "mobilefiles.h"
#include "mobilelifecycle.h"

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
        MobileLifecycle lifecycle(controller);
        QQmlApplicationEngine engine;
        engine.rootContext()->setContextProperty(QStringLiteral("controller"), &controller);
        engine.rootContext()->setContextProperty(QStringLiteral("mobileFiles"), &files);
        engine.rootContext()->setContextProperty(QStringLiteral("mobileLifecycle"), &lifecycle);
        engine.rootContext()->setContextProperty(QStringLiteral("applicationVersion"),
                                                 application.applicationVersion());
        bool qmlFailed = false;
        QObject::connect(&engine, &QQmlEngine::warnings, &application,
                         [&qmlFailed](const QList<QQmlError> &) { qmlFailed = true; });
        engine.load(QUrl(QStringLiteral("qrc:/mobile/MobileWindow.qml")));
        if (engine.rootObjects().isEmpty())
            return 3;
        QTimer smokeTimer;
        int smokeStep = 0;
        if (smoke) {
            smokeTimer.setInterval(700);
            QObject::connect(&smokeTimer, &QTimer::timeout, &application, [&] {
                auto root = engine.rootObjects().first();
                auto window = qobject_cast<QQuickWindow *>(root);
                const QStringList names{"welcome", "devices", "history",   "about",        "server",
                                        "send",    "files",   "landscape", "landscape-end"};
                const auto frame = window ? window->grabWindow() : QImage();
                if (qmlFailed || frame.isNull() ||
                    !frame.save(QStringLiteral("mobile-smoke-%1.png").arg(names.at(smokeStep)))) {
                    application.exit(4);
                    return;
                }
                // 日期：2026-11-25；切换真实界面并留图，缺少控件或QML告警均使门禁失败。
                const auto invoke = [root](const char *name, const char *method) {
                    const auto item = root->findChild<QObject *>(QString::fromLatin1(name));
                    if (!item)
                        QTextStream(stderr) << "Smoke control missing: " << name << "\n";
                    return item && QMetaObject::invokeMethod(item, method);
                };
                bool ok = true;
                if (smokeStep == 0) {
                    controller.acceptTerms();
                    ok = invoke("termsDialog", "close");
                } else if (smokeStep == 1 || smokeStep == 2) {
                    auto tabs = root->findChild<QObject *>(QStringLiteral("mainTabs"));
                    ok = tabs && tabs->setProperty("currentIndex", smokeStep);
                } else if (smokeStep == 3) {
                    ok = invoke("serverDialog", "open");
                } else if (smokeStep == 4) {
                    ok = invoke("serverDialog", "close") && invoke("sendDialog", "open");
                } else if (smokeStep == 5) {
                    ok = invoke("sendDialog", "close") && invoke("mobileFilesDialog", "open");
                } else if (smokeStep == 6) {
                    ok = invoke("mobileFilesDialog", "close");
                    window->resize(820, 430);
                } else if (smokeStep == 7) {
                    auto about = root->findChild<QObject *>(QStringLiteral("aboutScroll"));
                    ok = about &&
                         about->setProperty("contentY",
                                            qMax(0.0, about->property("contentHeight").toDouble() -
                                                          about->property("height").toDouble()));
                } else {
                    QTextStream(stdout) << "Mobile QML loaded and nine real views rendered\n";
                    application.exit(0);
                    return;
                }
                if (!ok) {
                    application.exit(5);
                    return;
                }
                ++smokeStep;
            });
            smokeTimer.start();
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

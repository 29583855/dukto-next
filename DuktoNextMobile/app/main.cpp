#include "controller.h"
#include "core/error.h"
#include "mobiledatadir.h"
#include "mobilefiles.h"
#include "mobilelifecycle.h"
#include "popupcontextguard.h"
#ifdef DUKTO_MOBILE_HOST_TEST
#include "uistress.h"
#endif

#include <QDebug>
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
    // 日期：2026-11-25；启动日志只含阶段和状态，不记录用户路径、文件内容或服务器凭据。
    qInfo() << "MobileStartup application-created";
    QObject::connect(&application, &QGuiApplication::lastWindowClosed, &application,
                     [] { qInfo() << "MobileStartup last-window-closed"; });
    QObject::connect(&application, &QCoreApplication::aboutToQuit, &application,
                     [] { qInfo() << "MobileStartup about-to-quit"; });
    const bool smoke = application.arguments().contains(QStringLiteral("--smoke-test"));
    try {
        const auto storage = mobile::applicationDataDirectory();
        if (!QDir().mkpath(storage))
            return 2;
        qInfo() << "MobileStartup storage-ready";
        MobileFiles files;
        qInfo() << "MobileStartup files-ready";
        Controller controller(4644, nullptr, storage);
        qInfo() << "MobileStartup controller-ready";
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
        if (engine.rootObjects().isEmpty()) {
            qCritical() << "MobileStartup qml-root-missing";
            return 3;
        }
        qInfo() << "MobileStartup qml-ready";
        PopupContextGuard popupContexts(engine.rootObjects().first(), &engine);
        QTimer smokeTimer;
        int smokeStep = 0;
        if (smoke) {
            smokeTimer.setInterval(700);
            QObject::connect(&smokeTimer, &QTimer::timeout, &application, [&] {
                auto root = engine.rootObjects().first();
                auto window = qobject_cast<QQuickWindow *>(root);
                const QStringList names{"welcome",   "devices",      "history", "about",
                                        "server",    "discard",      "send",    "files",
                                        "landscape", "landscape-end"};
                const auto frame = window ? window->grabWindow() : QImage();
                if (qmlFailed || frame.isNull() ||
                    !frame.save(QStringLiteral("mobile-smoke-%1.png").arg(names.at(smokeStep)))) {
                    application.exit(4);
                    return;
                }
                // 日期：2026-11-25；十画面包含续传确认弹窗，缺少控件或QML告警均使门禁失败。
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
                    ok = invoke("discardUploadDialog", "open");
                } else if (smokeStep == 5) {
                    ok = invoke("discardUploadDialog", "close") &&
                         invoke("serverDialog", "close") && invoke("sendDialog", "open");
                } else if (smokeStep == 6) {
                    ok = invoke("sendDialog", "close") && invoke("mobileFilesDialog", "open");
                } else if (smokeStep == 7) {
                    ok = invoke("mobileFilesDialog", "close");
                    window->resize(820, 430);
                } else if (smokeStep == 8) {
                    auto about = root->findChild<QObject *>(QStringLiteral("aboutScroll"));
                    ok = about &&
                         about->setProperty("contentY",
                                            qMax(0.0, about->property("contentHeight").toDouble() -
                                                          about->property("height").toDouble()));
                } else {
                    QTextStream(stdout) << "Mobile QML loaded and ten real views rendered\n";
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
#ifdef DUKTO_MOBILE_HOST_TEST
        if (application.arguments().contains(QStringLiteral("--stress-test")))
            startUiStress(engine, controller, qmlFailed);
#endif
        qInfo() << "MobileStartup event-loop-start";
        const int result = application.exec();
        qInfo() << "MobileStartup event-loop-end" << result;
        return result;
    } catch (const dukto::Error &error) {
        qCritical() << "MobileStartup core-exception" << static_cast<int>(error.code)
                    << error.stage;
        QTextStream(stderr) << error.what() << '\n';
        return static_cast<int>(error.code);
    } catch (const std::exception &error) {
        qCritical() << "MobileStartup standard-exception";
        QTextStream(stderr) << error.what() << '\n';
        return 1;
    }
}

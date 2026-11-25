#include "core/discovery.h"
#include "core/error.h"
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QStandardPaths>
#include <QDir>
#include <QSslSocket>
#include <openssl/crypto.h>

// 日期：2026-11-25；最小移动宿主先验证QML、网络和原生加密运行库，完整控制器随后接入。
int main(int argc, char *argv[]) {
    QGuiApplication application(argc, argv);
    QCoreApplication::setOrganizationName(QStringLiteral("DuktoNext"));
    QCoreApplication::setApplicationName(QStringLiteral("Mobile"));
    const auto storage = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
    if (!QDir().mkpath(storage))
        return 2;
    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("buildStatus"),
        QStringLiteral("C++14 / Qt %1 / %2 / TLS %3")
            .arg(QString::fromLatin1(qVersion()), QString::fromLatin1(OpenSSL_version(OPENSSL_VERSION)),
                 QSslSocket::supportsSsl() ? QStringLiteral("可用") : QStringLiteral("不可用")));
    engine.load(QUrl(QStringLiteral("qrc:/mobile/Bootstrap.qml")));
    if (engine.rootObjects().isEmpty())
        return 3;
    return application.exec();
}

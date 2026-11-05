#include "app/serverpanel.h"
#include <QApplication>
#include <QFile>
#include <QJsonDocument>
#include <QQmlComponent>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickWidget>
#include <QQuickWindow>
#include <QtTest>
#include <cstdio>

namespace {
// 日期：2026-11-05；测试事件只含公开状态，不导出客户端凭据或文件正文；每条立即刷新避免管道背压。
void report(const QJsonObject &event) {
    const auto bytes = QJsonDocument(event).toJson(QJsonDocument::Compact) + '\n';
    std::fwrite(bytes.constData(), 1, static_cast<size_t>(bytes.size()), stdout);
    std::fflush(stdout);
}
} // namespace

// 日期：2026-11-05；独立 GUI 测试进程加载生产面板和 QML，通过真实按钮启动、找回和继续任务。
int main(int argc, char **argv) {
    QQuickWindow::setSceneGraphBackend(QSGRendererInterface::Software);
    QApplication application(argc, argv);
    if (argc != 2)
        return 2;
    QFile input(application.arguments()[1]);
    if (!input.open(QIODevice::ReadOnly) || input.size() > 65536)
        return 2;
    QJsonParseError parse;
    const auto options = QJsonDocument::fromJson(input.readAll(), &parse).object();
    if (parse.error != QJsonParseError::NoError ||
        !QStringList{"download", "resume"}.contains(options["operation"].toString()))
        return 2;
    ServerPanel panel(options["state"].toString());
    QQuickWidget view;
    view.setResizeMode(QQuickWidget::SizeRootObjectToView);
    view.resize(430, 700);
    bool warned = false;
    QObject::connect(view.engine(), &QQmlEngine::warnings, &application,
                     [&](const QList<QQmlError> &) {
                         // 日期：2026-11-05；加载或运行期 QML 警告不能被当作成功画面忽略。
                         warned = true;
                         application.exit(1);
                     });
    QQmlComponent component(view.engine(), QUrl("qrc:/ui/ServerPage.qml"));
    auto root =
        component.createWithInitialProperties({{"panel", QVariant::fromValue<QObject *>(&panel)}});
    if (!root)
        return 1;
    view.setContent(QUrl("qrc:/ui/ServerPage.qml"), &component, root);
    if (view.status() != QQuickWidget::Ready)
        return 1;
    view.show();
    const auto setText = [&](const char *name, const QString &value) {
        // 日期：2026-11-05；只填生产界面的输入字段，传输操作仍由按钮连接的生产方法执行。
        auto field = root->findChild<QObject *>(name);
        return field && field->setProperty("text", value);
    };
    const auto click = [&](const char *buttonName, const char *flickName) {
        // 日期：2026-11-05；滚动实际 Flickable 后投递鼠标点击，不直接调用传输槽来替代按钮。
        auto button = root->findChild<QQuickItem *>(buttonName);
        auto flick = root->findChild<QQuickItem *>(flickName);
        if (!button || !flick || !button->isEnabled())
            return false;
        const auto current = flick->property("contentY").toDouble();
        const auto position = button->mapToItem(flick, QPointF()).y();
        const auto maximum =
            qMax(0.0, flick->property("contentHeight").toDouble() - flick->height());
        flick->setProperty("contentY", qBound(0.0, current + position - 180, maximum));
        QTest::qWait(30);
        const auto point = button->mapToScene(button->boundingRect().center()).toPoint();
        QTest::mouseClick(&view, Qt::LeftButton, Qt::NoModifier, point);
        return true;
    };
    int phase = 0;
    QObject::connect(&panel, &ServerPanel::changed, &application, [&]() {
        // 日期：2026-11-05；仅发最后面板快照；另一个进程必须实际重认证查询历史才能找回任务。
        report({{"event", "gui-state"},
                {"task", QJsonObject::fromVariantMap(panel.task())},
                {"busy", panel.busy()},
                {"controlBusy", panel.controlBusy()}});
        if (phase == 1 && !panel.controlBusy()) {
            const auto tasks = panel.tasks();
            bool found = false;
            for (const auto &task : tasks)
                found = found || task.toMap()["taskId"].toString() == options["taskId"].toString();
            if (!found || !setText("serverTaskId", options["taskId"].toString())) {
                application.exit(1);
                return;
            }
            phase = 2;
            report({{"event", "gui-task-recovered"}, {"taskId", options["taskId"]}});
            QTimer::singleShot(0, &application, [&]() {
                // 日期：2026-11-05；查询收尾后再从真实按钮继续，不在 changed 信号内重入操作槽。
                if (!click("serverResumeButton", "serverTaskFlick"))
                    application.exit(1);
            });
        } else if (phase == 2 && !panel.busy() && !panel.controlBusy()) {
            phase = 3;
            const auto result = QJsonObject::fromVariantMap(panel.task());
            const auto completed = result["state"] == "completed" && !warned;
            report({{"event", "gui-finished"},
                    {"passed", completed},
                    {"task", result},
                    {"outcome", QJsonObject::fromVariantMap(panel.outcome())}});
            application.exit(completed ? 0 : 1);
        }
    });
    QTimer::singleShot(250, &application, [&]() {
        // 日期：2026-11-05；每次新进程都要求生产 QML 实际渲染，之后才触发用户输入和操作。
        auto sections = root->findChild<QObject *>("serverSections");
        auto channels = root->findChild<QObject *>("serverChannelCount");
        const auto picture = view.grabFramebuffer();
        if (!sections || !channels || picture.isNull() || warned ||
            !picture.save(options["screenshot"].toString()) ||
            !setText("serverShare", options["share"].toString()) ||
            !setText("serverRemotePath", options["remotePath"].toString()) ||
            !setText("serverOutput", options["output"].toString()) ||
            !setText("serverRequest", options["requestId"].toString())) {
            application.exit(1);
            return;
        }
        const auto index =
            QStringList{"1", "2", "4", "8", "16"}.indexOf(options["channels"].toString());
        if (index < 0 || !channels->setProperty("currentIndex", index)) {
            application.exit(2);
            return;
        }
        report({{"event", "gui-ready"}, {"platform", QGuiApplication::platformName()}});
        if (options["operation"] == "resume") {
            sections->setProperty("currentIndex", 1);
            phase = 1;
            if (!click("serverRecoverTasksButton", "serverTaskFlick"))
                application.exit(1);
        } else {
            phase = 2;
            if (!click("serverDownloadButton", "serverClientFlick"))
                application.exit(1);
        }
    });
    QTimer::singleShot(180000, &application, [&]() {
        // 日期：2026-11-05；测试进程有独立总截止，不因进度或重试无限延长。
        application.exit(3);
    });
    return application.exec();
}

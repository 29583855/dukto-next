#include "uistress.h"
#include "controller.h"
#include <QCoreApplication>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMap>
#include <QQmlApplicationEngine>
#include <QQuickWindow>
#include <QRegularExpression>
#include <QSet>
#include <QTextStream>
#include <QTimer>
#include <memory>

namespace {
// 日期：2026-11-25；读取当前RSS而非历史峰值，缺少测量证据即失败。
qint64 residentKiB() {
    QFile status(QStringLiteral("/proc/self/status"));
    if (!status.open(QIODevice::ReadOnly))
        return -1;
    const auto match = QRegularExpression(QStringLiteral("VmRSS:\\s+(\\d+)\\s+kB"))
                           .match(QString::fromLatin1(status.readAll()));
    return match.hasMatch() ? match.captured(1).toLongLong() : -1;
}
// 日期：2026-11-25；按类型及直接父级归组，诊断压力操作中持续增加的实际存活对象。
QJsonObject objectGroups(QObject *root, QObject *engine) {
    QSet<QObject *> objects;
    for (auto scope : {root, engine})
        for (auto object : scope->findChildren<QObject *>())
            objects.insert(object);
    QMap<QString, int> groups;
    for (auto object : objects) {
        auto parent = object->parent();
        QString key = QString::fromLatin1(object->metaObject()->className());
        if (parent)
            key += QStringLiteral(" <- ") + QString::fromLatin1(parent->metaObject()->className()) +
                   QStringLiteral("[") + parent->objectName() + QStringLiteral("]");
        ++groups[key];
    }
    QJsonObject result;
    for (auto it = groups.cbegin(); it != groups.cend(); ++it)
        result.insert(it.key(), it.value());
    return result;
}
struct State {
    int step = 0;
    int cycles = 0;
    int baselineObjects = 0;
    qint64 baselineKiB = 0;
    qint64 lastKiB = 0;
    int lastObjects = 0;
    QJsonArray samples;
    QJsonObject baselineGroups;
};
} // namespace
// 日期：2026-11-25；真实控件经过30轮预热后持续190轮，超过16MiB或32个存活对象增长使门禁失败。
void startUiStress(QQmlApplicationEngine &engine, Controller &controller, bool &qmlFailed) {
    auto timer = new QTimer(&engine);
    auto state = std::make_shared<State>();
    controller.acceptTerms();
    auto root = engine.rootObjects().first();
    auto window = qobject_cast<QQuickWindow *>(root);
    const auto invoke = [root](const char *name, const char *method) {
        auto object = root->findChild<QObject *>(QString::fromLatin1(name));
        return object && QMetaObject::invokeMethod(object, method);
    };
    if (!window || !invoke("termsDialog", "close")) {
        QCoreApplication::exit(6);
        return;
    }
    timer->setInterval(20);
    QObject::connect(timer, &QTimer::timeout, &engine, [&, timer, state, root, window, invoke] {
        bool ok = !qmlFailed;
        if (state->step < 3) {
            auto tabs = root->findChild<QObject *>(QStringLiteral("mainTabs"));
            ok = ok && tabs && tabs->setProperty("currentIndex", state->step);
        } else if (state->step == 3)
            ok = ok && invoke("serverDialog", "open");
        else if (state->step == 4)
            ok = ok && invoke("discardUploadDialog", "open");
        else if (state->step == 5)
            ok = ok && invoke("discardUploadDialog", "close");
        else if (state->step == 6)
            ok = ok && invoke("serverDialog", "close");
        else if (state->step == 7)
            ok = ok && invoke("sendDialog", "open");
        else if (state->step == 8)
            ok = ok && invoke("sendDialog", "close");
        else if (state->step == 9)
            ok = ok && invoke("mobileFilesDialog", "open");
        else if (state->step == 10)
            ok = ok && invoke("mobileFilesDialog", "close");
        else {
            engine.collectGarbage();
            ok = ok && !window->grabWindow().isNull();
            ++state->cycles;
            if (state->cycles == 30 || state->cycles % 10 == 0) {
                state->lastKiB = residentKiB();
                state->lastObjects = root->findChildren<QObject *>().size() +
                                     engine.findChildren<QObject *>().size();
                state->samples.append(QJsonObject{{"cycle", state->cycles},
                                                  {"rssKiB", double(state->lastKiB)},
                                                  {"objects", state->lastObjects}});
                ok = ok && state->lastKiB > 0;
                if (state->cycles == 30) {
                    state->baselineKiB = state->lastKiB;
                    state->baselineObjects = state->lastObjects;
                    state->baselineGroups = objectGroups(root, &engine);
                }
            }
            if (state->cycles >= 220) {
                ok = ok && state->lastKiB - state->baselineKiB <= 16384 &&
                     state->lastObjects - state->baselineObjects <= 32;
                QJsonObject report{{"date", "2026-11-25"},
                                   {"cycles", state->cycles},
                                   {"warmupCycles", 30},
                                   {"rssGrowthKiB", double(state->lastKiB - state->baselineKiB)},
                                   {"objectGrowth", state->lastObjects - state->baselineObjects},
                                   {"rssBudgetKiB", 16384},
                                   {"objectBudget", 32},
                                   {"passed", ok},
                                   {"deviceTestsPassed", false},
                                   {"baselineGroups", state->baselineGroups},
                                   {"finalGroups", objectGroups(root, &engine)},
                                   {"samples", state->samples}};
                QFile output(QStringLiteral("mobile-ui-stress.json"));
                ok = output.open(QIODevice::WriteOnly) &&
                     output.write(QJsonDocument(report).toJson()) > 0 && ok;
                timer->stop();
                QTextStream(stdout) << "UI stress: " << state->cycles << " cycles, RSS growth "
                                    << state->lastKiB - state->baselineKiB << " KiB, object growth "
                                    << state->lastObjects - state->baselineObjects << "\n";
                QCoreApplication::exit(ok ? 0 : 6);
                return;
            }
        }
        if (!ok) {
            timer->stop();
            QCoreApplication::exit(6);
            return;
        }
        state->step = (state->step + 1) % 12;
    });
    timer->start();
}

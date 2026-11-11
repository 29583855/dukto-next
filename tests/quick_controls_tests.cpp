#include "app/controller.h"
#include "app/stablescrollbar.h"

#include <QAccessible>
#include <QApplication>
#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickWidget>
#include <QQuickWindow>
#include <QSet>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QtGui/private/qguiapplication_p.h>
#include <QtTest>
#include <qpa/qplatformaccessibility.h>
#include <qpa/qplatformintegration.h>

class QuickControlsTests final : public QObject {
    Q_OBJECT

  private:
    // 日期：2026-11-11；沿对象和视觉树合并收集，覆盖弹层及ScrollView隐式创建的滚动条。
    void collect(QObject *object, QSet<QQuickScrollBar *> &bars, QSet<QObject *> &seen) {
        if (!object || seen.contains(object))
            return;
        seen.insert(object);
        if (auto bar = qobject_cast<QQuickScrollBar *>(object))
            bars.insert(bar);
        for (auto child : object->children())
            collect(child, bars, seen);
        if (auto item = qobject_cast<QQuickItem *>(object)) {
            for (auto child : item->childItems())
                collect(child, bars, seen);
        }
    }

    // 日期：2026-11-11；通过真实辅助功能动作信号核对每次操作只移动一个步长。
    void verifySingleActions(QQuickScrollBar *bar) {
        QObject *attached = nullptr;
        for (auto child : bar->children()) {
            if (QByteArray(child->metaObject()->className()) == "QQuickAccessibleAttached")
                attached = child;
        }
        QVERIFY(attached);
        bar->setStepSize(0.05);
        bar->setSize(0.1);
        bar->setPosition(0.2);
        QVERIFY(QMetaObject::invokeMethod(attached, "increaseAction", Qt::DirectConnection));
        QVERIFY2(qAbs(bar->position() - 0.25) < 0.000001,
                 qPrintable(QString("increase moved to %1 instead of 0.25").arg(bar->position())));
        QVERIFY(QMetaObject::invokeMethod(attached, "decreaseAction", Qt::DirectConnection));
        QVERIFY(qAbs(bar->position() - 0.2) < 0.000001);
    }

  private slots:
    // 日期：2026-11-11；同一生产页面重复激活5000次，所有显式和隐式滚动条均不得重复执行动作。
    void productionPageRepeatedActivation() {
        QTemporaryDir state;
        QVERIFY(state.isValid());
        Controller controller(0, nullptr, state.path());
        controller.acceptTerms();
        QQuickWidget view;
        view.setResizeMode(QQuickWidget::SizeRootObjectToView);
        view.resize(430, 700);
        view.rootContext()->setContextProperty("controller", &controller);
        view.rootContext()->setContextProperty("applicationVersion", DUKTO_VERSION);
        QSignalSpy warnings(view.engine(), &QQmlEngine::warnings);
        view.setSource(QUrl("qrc:/ui/Main.qml"));
        QCOMPARE(view.status(), QQuickWidget::Ready);
        view.show();
        auto popup = view.rootObject()->findChild<QObject *>("serverDialog");
        QVERIFY(popup);
        QVERIFY(QMetaObject::invokeMethod(popup, "open"));
        QTRY_VERIFY(popup->property("opened").toBool());
        QVERIFY(!view.grabFramebuffer().isNull());
        auto accessibility = QGuiApplicationPrivate::platformIntegration()->accessibility();
        QVERIFY(accessibility);
        accessibility->setActive(true);
        QVERIFY(QAccessible::isActive());
        QSet<QQuickScrollBar *> bars;
        QSet<QObject *> seen;
        collect(view.rootObject(), bars, seen);
        collect(view.quickWindow()->contentItem(), bars, seen);
        qInfo() << "Production scrollbars:" << bars.size();
        QVERIFY(bars.size() >= 15);
        for (auto bar : bars)
            QVERIFY2(qobject_cast<StableScrollBar *>(bar), bar->metaObject()->className());
        for (int count = 0; count < 5000; ++count)
            accessibility->setActive(true);
        for (auto bar : bars)
            verifySingleActions(bar);
        for (int count = 0; count < 8; ++count) {
            accessibility->setActive(false);
            accessibility->setActive(true);
            accessibility->setActive(true);
        }
        for (auto bar : bars)
            verifySingleActions(bar);
        QCOMPARE(warnings.count(), 0);
    }

    // 日期：2026-11-11；在辅助功能已启用后创建和销毁控件，实例状态独立且动作始终单步。
    void createAfterActivation() {
        auto accessibility = QGuiApplicationPrivate::platformIntegration()->accessibility();
        QVERIFY(accessibility);
        accessibility->setActive(true);
        QQmlEngine engine;
        QQmlComponent component(&engine);
        component.setData("import QtQuick 2.15\nimport QtQuick.Controls 2.15\n"
                          "ScrollBar { width: 10; height: 200; size: 0.1; stepSize: 0.05 }",
                          QUrl("qrc:/activation-test.qml"));
        for (int count = 0; count < 32; ++count) {
            QScopedPointer<QObject> object(component.create());
            QVERIFY2(object, qPrintable(component.errorString()));
            auto bar = qobject_cast<StableScrollBar *>(object.data());
            QVERIFY(bar);
            for (int repeat = 0; repeat < 64; ++repeat)
                accessibility->setActive(true);
            verifySingleActions(bar);
        }
    }
};

// 日期：2026-11-11；回归测试与产品使用相同软件渲染及兼容样式，不依赖电脑输入法或截图工具。
int main(int argc, char **argv) {
    qRegisterMetaType<QList<QQmlError>>("QList<QQmlError>");
    QQuickWindow::setSceneGraphBackend(QSGRendererInterface::Software);
    QApplication application(argc, argv);
    QuickControlsTests tests;
    return QTest::qExec(&tests, argc, argv);
}

#include "quick_controls_tests.moc"

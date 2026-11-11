#include "stablescrollbar.h"

#include <QCoreApplication>
#include <QQmlEngine>
#include <QQuickStyle>
#include <QtQuick/private/qquickaccessibleattached_p.h>

// 日期：2026-11-11；保留Qt滚动条的鼠标、触摸、键盘及辅助功能实现。
StableScrollBar::StableScrollBar(QQuickItem *parent) : QQuickScrollBar(parent) {
}

#if QT_CONFIG(accessibility)
// 日期：2026-11-11；重复激活去重；停用不依赖全局启用状态，重新启用只保留一份动作连接。
void StableScrollBar::accessibilityActiveChanged(bool active) {
    if (activationSeen_ && accessibilityActive_ == active)
        return;
    activationSeen_ = true;
    accessibilityActive_ = active;
    QQuickControl::accessibilityActiveChanged(active);
    auto attached = qobject_cast<QQuickAccessibleAttached *>(
        qmlAttachedPropertiesObject<QQuickAccessibleAttached>(this, false));
    if (!attached)
        return;
    if (active) {
        setAccessibleProperty("pressed", isPressed());
        connect(attached, &QQuickAccessibleAttached::increaseAction, this,
                &QQuickScrollBar::increase, Qt::UniqueConnection);
        connect(attached, &QQuickAccessibleAttached::decreaseAction, this,
                &QQuickScrollBar::decrease, Qt::UniqueConnection);
    } else {
        disconnect(attached, &QQuickAccessibleAttached::increaseAction, this,
                   &QQuickScrollBar::increase);
        disconnect(attached, &QQuickAccessibleAttached::decreaseAction, this,
                   &QQuickScrollBar::decrease);
    }
}
#endif

// 日期：2026-11-11；在QML加载前注册局部兼容样式，同时覆盖ScrollView隐式创建的滚动条。
static void registerStableScrollBar() {
    // 日期：2026-11-11；显式保留Qt5.15继承属性版本，避免minimumSize等带修订号属性被隐藏。
    qmlRegisterRevision<QQuickItem, 15>("Dukto.Compatibility", 1, 15);
    qmlRegisterRevision<QQuickControl, 15>("Dukto.Compatibility", 1, 15);
    qmlRegisterRevision<QQuickScrollBar, 15>("Dukto.Compatibility", 1, 15);
    qmlRegisterType<StableScrollBar, 15>("Dukto.Compatibility", 1, 15, "StableScrollBar");
    QQuickStyle::addStylePath(QStringLiteral("qrc:/styles"));
    QQuickStyle::setStyle(QStringLiteral("DuktoCompat"));
    QQuickStyle::setFallbackStyle(QStringLiteral("Default"));
}

Q_COREAPP_STARTUP_FUNCTION(registerStableScrollBar)

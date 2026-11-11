#include "stablescrollbar.h"

#include <QCoreApplication>
#include <QQmlEngine>
#include <QQuickStyle>

// 日期：2026-11-11；保留Qt滚动条的鼠标、触摸、键盘及辅助功能实现。
StableScrollBar::StableScrollBar(QQuickItem *parent) : QQuickScrollBar(parent) {
}

#if QT_CONFIG(accessibility)
// 日期：2026-11-11；首次激活与停用仍交给Qt处理，相同状态通知不累加信号连接。
void StableScrollBar::accessibilityActiveChanged(bool active) {
    if (activationSeen_ && accessibilityActive_ == active)
        return;
    activationSeen_ = true;
    accessibilityActive_ = active;
    QQuickScrollBar::accessibilityActiveChanged(active);
}
#endif

// 日期：2026-11-11；在QML加载前注册局部兼容样式，同时覆盖ScrollView隐式创建的滚动条。
static void registerStableScrollBar() {
    qmlRegisterType<StableScrollBar>("Dukto.Compatibility", 1, 0, "StableScrollBar");
    QQuickStyle::addStylePath(QStringLiteral("qrc:/styles"));
    QQuickStyle::setStyle(QStringLiteral("DuktoCompat"));
    QQuickStyle::setFallbackStyle(QStringLiteral("Default"));
}

Q_COREAPP_STARTUP_FUNCTION(registerStableScrollBar)

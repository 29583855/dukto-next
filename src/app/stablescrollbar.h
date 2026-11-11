#pragma once

#include <QtQml/qqml.h>
#include <QtQuickTemplates2/private/qquickscrollbar_p.h>

// 日期：2026-11-11；限制Qt5滚动条重复激活辅助功能时的连接数量，保持原生操作语义。
class StableScrollBar : public QQuickScrollBar {
    Q_OBJECT

  public:
    // 日期：2026-11-11；激活状态按控件实例保存，销毁重建不会继承旧对象的状态。
    explicit StableScrollBar(QQuickItem *parent = nullptr);

  protected:
#if QT_CONFIG(accessibility)
    // 日期：2026-11-11；按实例维护激活状态和唯一动作连接，停用时直接解除已有连接。
    void accessibilityActiveChanged(bool active) override;
#endif

  private:
    bool activationSeen_ = false;
    bool accessibilityActive_ = false;
};

// 日期：2026-11-11；保留Qt滚动条的附加属性工厂，供ScrollView使用ScrollBar.vertical/horizontal。
QML_DECLARE_TYPEINFO(StableScrollBar, QML_HAS_ATTACHED_PROPERTIES)

#pragma once
#include <QObject>

// 日期：2026-11-25；为当前移动QML静态弹窗补齐Qt5遮罩创建上下文的关闭生命周期。
class PopupContextGuard : public QObject {
  public:
    // 日期：2026-11-25；在根QML加载后、首次打开前登记弹窗，保留原控件及辅助功能。
    explicit PopupContextGuard(QObject *root, QObject *parent = nullptr);
};

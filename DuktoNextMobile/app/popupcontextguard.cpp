#include "popupcontextguard.h"
#include <QQmlContext>
#include <QSet>
#include <QtQuickTemplates2/private/qquickpopup_p.h>

// 日期：2026-11-25；Qt5先删除遮罩再发closed，此时仅延迟销毁本次动态遮罩上下文。
PopupContextGuard::PopupContextGuard(QObject *root, QObject *parent) : QObject(parent) {
    for (auto popup : root->findChildren<QQuickPopup *>()) {
        QSet<QQmlContext *> original;
        for (auto context :
             popup->findChildren<QQmlContext *>(QString(), Qt::FindDirectChildrenOnly))
            original.insert(context);
        connect(popup, &QQuickPopup::closed, popup, [popup, original] {
            // 日期：2026-11-25；不清理声明上下文或任意子对象，只处理Qt遮罩创建的直接动态上下文。
            for (auto context :
                 popup->findChildren<QQmlContext *>(QString(), Qt::FindDirectChildrenOnly))
                if (!original.contains(context) && context->contextObject() == popup)
                    context->deleteLater();
        });
    }
}

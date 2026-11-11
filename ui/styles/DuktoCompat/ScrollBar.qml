import QtQuick 2.15
import Dukto.Compatibility 1.15

// 日期：2026-11-11；沿用Qt模板的交互和辅助功能，所有显式及隐式滚动条共用激活去重。
StableScrollBar {
    id: control

    implicitWidth: Math.max(implicitBackgroundWidth + leftInset + rightInset,
                           implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                            implicitContentHeight + topPadding + bottomPadding)
    padding: 2
    visible: policy !== StableScrollBar.AlwaysOff
    minimumSize: orientation === Qt.Horizontal ? height / width : width / height

    contentItem: Rectangle {
        implicitWidth: 6
        implicitHeight: 6
        radius: Math.min(width, height) / 2
        color: control.pressed ? "#777777" : "#aaaaaa"
        opacity: control.policy === StableScrollBar.AlwaysOn || control.active ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 200
            }
        }
    }
}

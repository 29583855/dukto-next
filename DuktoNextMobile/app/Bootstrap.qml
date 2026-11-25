import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    visible: true
    width: 430
    height: 760
    title: "Dukto Next Mobile · 开发验证版"
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        Label { text: "Dukto Next"; font.pixelSize: 30; color: "#159ca0" }
        Label { text: "Android / iOS 工具链验证"; font.pixelSize: 20 }
        Label { text: buildStatus; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Label { text: "此页为编译验证入口，尚未通过真机验收。"; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Item { Layout.fillHeight: true }
    }
}

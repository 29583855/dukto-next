import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: window
    width: 430
    height: 820
    visible: true
    title: "Dukto Next"
    property string browsing: mobileFiles.documents
    property bool directoryMode: false
    property var fileRows: []

    // 日期：2026-11-25；单页最多512项，先清模型再重载，界面不累积旧条目。
    function refreshFiles() { fileRows = mobileFiles.entries(browsing) }
    // 日期：2026-11-25；返回上层仅允许应用文档目录范围。
    function goUp() {
        if (browsing !== mobileFiles.documents) {
            browsing = browsing.substring(0, browsing.lastIndexOf("/"))
            refreshFiles()
        }
    }
    header: ColumnLayout {
        spacing: 0
        ToolBar {
            Layout.fillWidth: true
            RowLayout {
                anchors.fill: parent
                Label { text: "Dukto Next"; textFormat: Text.PlainText; Layout.fillWidth: true; leftPadding: 12 }
                Button {
                    text: "应用文件"
                    enabled: !mobileFiles.busy
                    onClicked: {
                        window.directoryMode = false
                        window.browsing = mobileFiles.documents
                        window.refreshFiles()
                        filesDialog.open()
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: mobileFiles.message.length ? mobileFiles.message : "请保持应用在前台；默认端口4644，与原版互通"
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.pixelSize: 12
            padding: 6
        }
        BusyIndicator { running: mobileFiles.busy; visible: running; Layout.alignment: Qt.AlignHCenter; implicitHeight: 32 }
    }
    Loader { anchors.fill: parent; source: "qrc:/ui/Main.qml" }
    Connections {
        target: mobileFiles
        // 日期：2026-11-25；目录选择由应用沙箱浏览器完成，不请求整个手机存储权限。
        function onDirectoryRequested(title) {
            window.directoryMode = true
            window.browsing = mobileFiles.documents
            filesDialog.title = title
            window.refreshFiles()
            filesDialog.open()
        }
        // 日期：2026-11-25；触屏主题色不依赖桌面Widgets。
        function onColorRequested() { colorDialog.open() }
        function onChanged() { if (filesDialog.opened) window.refreshFiles() }
    }
    Dialog {
        id: filesDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(window.width - 16, 700)
        height: Math.max(260, window.height - 80)
        title: window.directoryMode ? "选择应用目录" : "应用文件"
        standardButtons: window.directoryMode ? Dialog.Ok | Dialog.Cancel : Dialog.Close
        onAccepted: mobileFiles.finishDirectory(window.browsing)
        onRejected: { if (window.directoryMode) mobileFiles.finishDirectory("") }
        contentItem: ColumnLayout {
            Label { text: window.browsing; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
            RowLayout {
                Button { text: "上层"; enabled: window.browsing !== mobileFiles.documents; onClicked: window.goUp() }
                Button { text: "刷新"; onClicked: window.refreshFiles() }
                Button { text: "新建目录"; onClicked: newDirectoryDialog.open() }
            }
            RowLayout {
                visible: !window.directoryMode
                Button { text: "导入文件"; enabled: !mobileFiles.busy; onClicked: mobileFiles.importIntoDocuments(false) }
                Button { text: "导入目录"; enabled: !mobileFiles.busy; onClicked: mobileFiles.importIntoDocuments(true) }
            }
            Label { text: "每页最多显示512项。点目录进入，点文件通过系统导出。"; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ListView {
                clip: true
                Layout.fillWidth: true
                Layout.fillHeight: true
                model: window.fileRows
                delegate: ItemDelegate {
                    width: ListView.view.width
                    text: (modelData.directory ? "[目录] " : "") + modelData.name
                    contentItem: Label { text: parent.text; textFormat: Text.PlainText; elide: Text.ElideMiddle; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (modelData.directory) { window.browsing = modelData.path; window.refreshFiles() }
                        else if (!window.directoryMode) mobileFiles.exportPath(modelData.path)
                    }
                }
                ScrollBar.vertical: ScrollBar {}
            }
        }
    }
    Dialog {
        id: newDirectoryDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(window.width - 32, 400)
        title: "新建目录"
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: TextField { id: directoryName; placeholderText: "目录名称"; maximumLength: 128 }
        onAccepted: {
            if (!mobileFiles.createDirectory(window.browsing, directoryName.text)) directoryName.text = ""
            window.refreshFiles()
        }
    }
    Dialog {
        id: colorDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(window.width - 32, 380)
        title: "选择主题色"
        standardButtons: Dialog.Close
        contentItem: Flow {
            spacing: 10
            Repeater {
                model: ["#009688", "#1976d2", "#673ab7", "#e91e63", "#ef6c00", "#455a64"]
                Button {
                    width: 90
                    height: 56
                    background: Rectangle { color: modelData; radius: 6 }
                    onClicked: { controller.setThemeColor(modelData); colorDialog.close() }
                    Accessible.name: "主题色 " + modelData
                }
            }
        }
    }
}

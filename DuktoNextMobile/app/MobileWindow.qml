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

    property string listedDirectory: ""
    property var fileCursors: [""]
    property int filePage: 0
    property string nextCursor: ""

    // 日期：2026-11-25；切换目录重置名称游标，每页模型最多512项。
    function refreshFiles() {
        if (listedDirectory !== browsing) {
            listedDirectory = browsing
            fileCursors = [""]
            filePage = 0
        }
        var result = mobileFiles.entries(browsing, fileCursors[filePage])
        fileRows = result.rows
        nextCursor = result.next
    }
    // 日期：2026-11-25；仅保存各页游标，刷新不累加文件对象。
    function nextFiles() {
        if (!nextCursor.length) return
        var cursors = fileCursors.slice(0, filePage + 1)
        cursors.push(nextCursor)
        fileCursors = cursors
        filePage++
        refreshFiles()
    }
    // 日期：2026-11-25；返回上层仅允许应用文档目录范围。
    function goUp() {
        if (browsing !== mobileFiles.documents) {
            browsing = browsing.substring(0, browsing.lastIndexOf("/"))
            refreshFiles()
        }
    }
    // 日期：2026-11-26；窗口固定横向尺寸，分享提示换行只决定高度，避免布局反向重排。
    header: Column {
        id: mobileHeader
        objectName: "mobileHeader"
        width: window.width
        property var incomingShare: mobileFiles.incoming
        Label {
            width: parent.width
            visible: mobileLifecycle.message.length > 0
            text: mobileLifecycle.message
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            padding: 6
        }
        Label {
            width: parent.width
            visible: Number(mobileHeader.incomingShare.files || 0) > 0 || String(mobileHeader.incomingShare.text || "").length > 0 || String(mobileHeader.incomingShare.error || "").length > 0
            text: "系统分享：" + (mobileHeader.incomingShare.files || 0) + "项文件" + (String(mobileHeader.incomingShare.text || "").length ? "，含文字" : "") + "。请选择设备发送，或在服务器页上传。" + (mobileHeader.incomingShare.error ? "\n" + mobileHeader.incomingShare.error : "")
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            padding: 6
        }
        Button {
            text: "丢弃待处理系统分享"
            visible: Number(mobileHeader.incomingShare.files || 0) > 0 || String(mobileHeader.incomingShare.text || "").length > 0 || String(mobileHeader.incomingShare.error || "").length > 0
            enabled: !mobileFiles.busy
            onClicked: mobileFiles.discardIncoming()
        }
        spacing: 0
        ToolBar {
            width: parent.width
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
            width: parent.width
            text: mobileFiles.message.length ? mobileFiles.message : "请保持应用在前台；默认端口4644，与原版互通"
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.pixelSize: 12
            padding: 6
        }
        BusyIndicator { running: mobileFiles.busy; visible: running; anchors.horizontalCenter: parent.horizontalCenter; implicitHeight: 32 }
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
        objectName: "mobileFilesDialog"
        parent: Overlay.overlay
        modal: true
        anchors.centerIn: parent
        width: Math.min(window.width - 16, 700)
        height: Math.max(0, window.height - 32)
        title: window.directoryMode ? "选择应用目录" : "应用文件"
        standardButtons: window.directoryMode ? Dialog.Ok | Dialog.Cancel : Dialog.Close
        onAccepted: mobileFiles.finishDirectory(window.browsing)
        onRejected: { if (window.directoryMode) mobileFiles.finishDirectory("") }
        contentItem: ColumnLayout {
            Label { text: window.browsing; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true; Layout.minimumWidth: 0 }
            // 日期：2026-11-26；操作按钮随可用宽度自动换行，避免手机窄屏上右侧按钮被裁切。
            Flow {
                objectName: "mobileFilesActions"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 0
                spacing: 6
                Button { text: "上层"; enabled: window.browsing !== mobileFiles.documents; onClicked: window.goUp() }
                Button { text: "刷新"; onClicked: window.refreshFiles() }
                Button { text: "新建目录"; onClicked: newDirectoryDialog.open() }
                Button { text: "导出目录"; visible: !window.directoryMode; enabled: !mobileFiles.busy; onClicked: mobileFiles.exportPath(window.browsing) }
            }
            Flow {
                objectName: "mobileFilesImports"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Layout.preferredWidth: 0
                spacing: 6
                visible: !window.directoryMode
                Button { text: "导入文件"; enabled: !mobileFiles.busy; onClicked: mobileFiles.importIntoDocuments(false) }
                Button { text: "导入目录"; enabled: !mobileFiles.busy; onClicked: mobileFiles.importIntoDocuments(true) }
            }
            Button {
                text: "清理旧暂存"
                enabled: !mobileFiles.busy && !controller.busy && !controller.server.busy
                onClicked: cleanupDialog.open()
            }
            Label { text: "每页最多512项，可继续翻页。点目录进入，点文件通过系统导出。"; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true; Layout.minimumWidth: 0 }
            RowLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Button { Layout.minimumWidth: 0; Layout.fillWidth: true; text: "上一页"; enabled: window.filePage > 0; onClicked: { window.filePage--; window.refreshFiles() } }
                Label { Layout.minimumWidth: 0; Layout.fillWidth: true; text: "第" + (window.filePage + 1) + "页 / 本页" + window.fileRows.length + "项"; textFormat: Text.PlainText; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter }
                Button { Layout.minimumWidth: 0; Layout.fillWidth: true; text: "下一页"; enabled: window.nextCursor.length > 0; onClicked: window.nextFiles() }
            }
            ListView {
                clip: true
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 0
                Layout.minimumHeight: 0
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
        id: cleanupDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(window.width - 32, 460)
        title: "清理旧暂存"
        standardButtons: Dialog.Ok | Dialog.Cancel
        // 日期：2026-11-26；用固定可用宽度的列计算自然高度，避免换行正文与弹窗高度循环依赖。
        contentItem: Column {
            width: cleanupDialog.availableWidth
            Label {
                width: parent.width
                text: "清理本次启动前遗留且没有上传任务引用的导入快照。用户文档、本次导入和可续传上传会保留。删除后不能撤回。"
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
            }
        }
        onAccepted: mobileFiles.cleanUnusedImports()
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

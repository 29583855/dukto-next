import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    // 日期：2026-11-04；远端名称、路径和状态使用纯文本，避免富文本图片绕过资源限制。

    id: root

    property color accent: controller.themeColor
    property string targetHost: ""
    property int targetPort: 4644

    width: 430
    height: 700
    color: "white"

    // 日期：2026-11-04；等窗口进入事件循环后再显示首次说明，避免加载阶段弹窗被忽略。
    Timer {
        interval: 0
        running: true
        repeat: false
        onTriggered: {
            if (!controller.termsAccepted)
                termsDialog.open();

        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabBar {
            id: tabs

            implicitWidth: 360
            Layout.fillWidth: true
            Layout.preferredHeight: 68

            TabButton {
                width: tabs.width / 3
                text: "设备"

                contentItem: Label {
                    textFormat: Text.PlainText
                    text: parent.text
                    color: parent.checked ? root.accent : "#a4a4a4"
                    font.pixelSize: 27
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                background: Rectangle {
                    color: "white"
                }

            }

            TabButton {
                width: tabs.width / 3
                text: "最近"

                contentItem: Label {
                    textFormat: Text.PlainText
                    text: parent.text
                    color: parent.checked ? root.accent : "#a4a4a4"
                    font.pixelSize: 27
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                background: Rectangle {
                    color: "white"
                }

            }

            TabButton {
                width: tabs.width / 3
                text: "关于"

                contentItem: Label {
                    textFormat: Text.PlainText
                    text: parent.text
                    color: parent.checked ? root.accent : "#a4a4a4"
                    font.pixelSize: 27
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }

                background: Rectangle {
                    color: "white"
                }

            }

        }

        StackLayout {
            currentIndex: tabs.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true

            Item {
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 14

                    RowLayout {
                        spacing: 12

                        Rectangle {
                            width: 60
                            height: 60
                            color: "#f0f0f0"

                            Image {
                                anchors.fill: parent
                                source: controller.localAvatar
                                fillMode: Image.PreserveAspectFit
                            }

                        }

                        ColumnLayout {
                            Label {
                                textFormat: Text.PlainText
                                text: controller.username + "（本机）"
                                font.pixelSize: 17
                                color: "#555"
                            }

                            Label {
                                textFormat: Text.PlainText
                                text: "准备接收文件、文件夹和文本"
                                font.pixelSize: 12
                                color: "#888"
                            }

                        }

                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 1
                        color: root.accent
                        opacity: 0.6
                    }

                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: controller.peers
                        spacing: 8

                        Label {
                            textFormat: Text.PlainText
                            anchors.centerIn: parent
                            visible: parent.count === 0
                            text: "等待局域网设备…\n也可以输入 IP 或主机名直接发送"
                            color: "#999"
                            horizontalAlignment: Text.AlignHCenter
                            lineHeight: 1.6
                        }

                        delegate: ItemDelegate {
                            width: ListView.view.width
                            height: 76
                            onClicked: {
                                root.targetHost = modelData.address;
                                root.targetPort = modelData.port;
                                hostInput.text = modelData.address;
                                portInput.value = modelData.port;
                                sendDialog.open();
                            }

                            contentItem: RowLayout {
                                Rectangle {
                                    width: 54
                                    height: 54
                                    color: root.accent

                                    Label {
                                        textFormat: Text.PlainText
                                        anchors.centerIn: parent
                                        text: "▣"
                                        color: "white"
                                        font.pixelSize: 28
                                        visible: modelData.avatar.length === 0
                                    }

                                    Image {
                                        anchors.fill: parent
                                        source: modelData.avatar
                                        fillMode: Image.PreserveAspectFit
                                    }

                                }

                                ColumnLayout {
                                    Label {
                                        textFormat: Text.PlainText
                                        text: modelData.name
                                        font.pixelSize: 17
                                        color: "#555"
                                    }

                                    Label {
                                        textFormat: Text.PlainText
                                        text: modelData.host + " · " + modelData.platform
                                        color: "#888"
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }

                                }

                            }

                        }

                        ScrollBar.vertical: ScrollBar {
                        }

                    }

                    Button {
                        text: "IP 连接 · 发送到指定设备"
                        objectName: "manualSendButton"
                        Layout.fillWidth: true
                        onClicked: sendDialog.open()
                    }

                    Button {
                        text: "服务器 · 上传 / 下载"
                        objectName: "serverPageButton"
                        Layout.fillWidth: true
                        onClicked: serverDialog.open()
                    }

                    Button {
                        text: "刷新设备"
                        flat: true
                        onClicked: controller.refresh()
                    }

                }

            }

            ListView {
                Layout.margins: 18
                clip: true
                model: controller.history

                Label {
                    textFormat: Text.PlainText
                    anchors.centerIn: parent
                    text: "尚无传输记录"
                    color: "#999"
                    visible: parent.count === 0
                }

                delegate: ItemDelegate {
                    width: ListView.view.width
                    height: 90
                    onClicked: {
                        controller.openHistory(modelData.id);
                    }

                    contentItem: ColumnLayout {
                        Label {
                            textFormat: Text.PlainText
                            text: modelData.message
                            color: "#555"
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }

                        Label {
                            textFormat: Text.PlainText
                            text: modelData.hasText ? "文本 · 点击查看" : (modelData.path || "发送任务")
                            color: "#777"
                            Layout.fillWidth: true
                            elide: Text.ElideMiddle
                        }

                        Label {
                            textFormat: Text.PlainText
                            text: modelData.time + " · " + modelData.bytes + " B" + (modelData.peer ? " · " + modelData.peer : "")
                            color: "#999"
                            font.pixelSize: 11
                            Layout.fillWidth: true
                            elide: Text.ElideMiddle
                        }

                    }

                }

                ScrollBar.vertical: ScrollBar {
                }

            }

            Flickable {
                clip: true
                contentHeight: about.height + 48

                ColumnLayout {
                    id: about

                    x: 24
                    y: 24
                    width: parent.width - 48
                    spacing: 16

                    Label {
                        textFormat: Text.PlainText
                        text: "Dukto Next"
                        font.pixelSize: 40
                        font.weight: Font.Light
                        color: root.accent
                    }

                    Label {
                        textFormat: Text.PlainText
                        text: "版本 " + applicationVersion + " · C++14 / Qt5"
                        color: "#777"
                    }

                    Label {
                        textFormat: Text.PlainText
                        text: "以 Emanuele Colombo 的 Dukto R6 为功能与交互参考。\n新工程采用共用传输核心与独立命令行。"
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                        lineHeight: 1.5
                    }

                    Label {
                        textFormat: Text.PlainText
                        text: "许可证：GPL-3.0-or-later"
                        color: "#777"
                    }

                    Label {
                        textFormat: Text.PlainText
                        text: "R6 兼容传输适用于可信局域网。旧协议不提供认证、加密或远端完整性确认。"
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                        lineHeight: 1.5
                    }

                    Label {
                        textFormat: Text.PlainText
                        text: "CLI：dukto-cli --help"
                        // 日期：2026-11-05；macOS 使用随系统提供的 Menlo，避免不存在的字体别名警告。
                        font.family: Qt.platform.os === "osx" ? "Menlo" : "monospace"
                        color: "#777"
                    }

                    Label {
                        textFormat: Text.PlainText
                        text: "配置、日志与接收目录按平台标准位置保存。"
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                    }

                    Label {
                        textFormat: Text.PlainText
                        text: controller.updateMessage
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                    }

                    TextField {
                        id: updateInput

                        Layout.fillWidth: true
                        text: controller.updateEndpoint
                        placeholderText: "HTTPS 更新描述地址"
                        selectByMouse: true
                    }

                    Button {
                        text: "检查更新"
                        onClicked: controller.checkUpdates(updateInput.text)
                    }

                    Button {
                        text: "打开新版本发布页"
                        visible: controller.updateAvailable
                        onClicked: controller.openUpdatePage()
                    }

                }

            }

        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: statusColumn.implicitHeight + 16
            color: "#f5f7f4"

            ColumnLayout {
                id: statusColumn

                anchors.fill: parent
                anchors.margins: 8

                Label {
                    textFormat: Text.PlainText
                    text: controller.status
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                    color: "#666"
                    font.pixelSize: 12
                }

                RowLayout {
                    visible: controller.busy

                    ProgressBar {
                        Layout.fillWidth: true
                        value: controller.progress
                    }

                    Button {
                        text: "取消"
                        flat: true
                        onClicked: controller.cancel()
                    }

                }

            }

        }

        Rectangle {
            Layout.fillWidth: true
            height: 60
            color: root.accent

            RowLayout {
                anchors.fill: parent
                anchors.margins: 4

                Repeater {
                    model: ["接收目录", "本机地址", "设置"]

                    Button {
                        Layout.fillWidth: true
                        text: modelData
                        flat: true
                        onClicked: {
                            if (index === 0)
                                controller.openPath(controller.outputDirectory);
                            else if (index === 1)
                                addressDialog.open();
                            else
                                settingsDialog.open();
                        }

                        contentItem: Label {
                            textFormat: Text.PlainText
                            text: parent.text
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter

                        }

                    }

                }

            }

        }

    }

    // 日期：2026-11-05；服务器弹层由主窗口唯一持有，首页入口可访问，避免落入重复按钮的局部作用域。
    Popup {
        id: serverDialog

        objectName: "serverDialog"
        width: root.width
        height: root.height
        padding: 0
        modal: true
        closePolicy: Popup.CloseOnEscape

        contentItem: ServerPage {
            panel: controller.server
            accent: root.accent
            onCloseRequested: serverDialog.close()
        }

    }

    Dialog {
        id: sendDialog

        objectName: "sendDialog"
        title: "发送数据"
        anchors.centerIn: parent
        width: Math.min(root.width - 24, 440)
        height: Math.min(root.height - 30, 560)
        modal: true
        standardButtons: Dialog.Close

        DropArea {
            objectName: "sendDropArea"
            anchors.fill: parent
            enabled: !controller.busy && hostInput.text.trim().length > 0
            onEntered: drag.accepted = drag.hasUrls
            onDropped: {
                if (controller.sendDropped(hostInput.text.trim(), portInput.value, drop.urls)) {
                    drop.acceptProposedAction();
                    sendDialog.close();
                } else {
                    drop.accepted = false;
                }
            }
        }

        contentItem: ScrollView {
            clip: true

            ColumnLayout {
                width: sendDialog.availableWidth
                spacing: 10

                Label {
                    textFormat: Text.PlainText
                    text: "目标 IP 或主机名"
                    color: "#777"
                }

                TextField {
                    id: hostInput

                    objectName: "hostInput"
                    Layout.fillWidth: true
                    placeholderText: "192.168.1.10"
                    selectByMouse: true
                }

                RowLayout {
                    Label {
                        textFormat: Text.PlainText
                        text: "端口"
                    }

                    SpinBox {
                        id: portInput

                        from: 1
                        to: 65535
                        value: 4644
                        editable: true
                    }

                }

                Repeater {
                    model: ["发送文字", "发送剪贴板文本", "发送文件", "发送文件夹", "发送屏幕截图"]

                    Button {
                        objectName: "sendAction" + index
                        Layout.fillWidth: true
                        text: modelData
                        enabled: !controller.busy && hostInput.text.trim().length > 0 && (index !== 1 || controller.clipboardAvailable)
                        onClicked: {
                            root.targetHost = hostInput.text.trim();
                            root.targetPort = portInput.value;
                            if (index === 0) {
                                textEditor.readOnly = false;
                                textEditor.text = "";
                                textDialog.open();
                            } else if (index === 1)
                                controller.sendClipboard(root.targetHost, root.targetPort);
                            else if (index === 2)
                                controller.sendFiles(root.targetHost, root.targetPort);
                            else if (index === 3)
                                controller.sendFolder(root.targetHost, root.targetPort);
                            else
                                controller.sendScreenshot(root.targetHost, root.targetPort);
                            if (index !== 0)
                                sendDialog.close();

                        }
                    }

                }

                Label {
                    textFormat: Text.PlainText
                    text: "也可以拖入本地文件或文件夹发送。"
                    color: "#888"
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }

            }

        }

    }

    Dialog {
        id: textDialog

        objectName: "textDialog"
        title: textEditor.readOnly ? "收到的文本" : "发送文字"
        anchors.centerIn: parent
        width: root.width - 24
        height: root.height - 80
        modal: true
        standardButtons: Dialog.Close

        contentItem: ColumnLayout {
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true

                TextArea {
                    id: textEditor

                    objectName: "textEditor"
                    textFormat: TextEdit.PlainText
                    selectByMouse: true
                    selectByKeyboard: true
                    persistentSelection: true
                    wrapMode: TextEdit.Wrap
                    placeholderText: "输入文本…"
                }

            }

            RowLayout {
                Button {
                    text: "复制"
                    objectName: "copyTextButton"
                    onClicked: controller.copyText(textEditor.selectedText.length ? textEditor.selectedText : textEditor.text)
                }

                Button {
                    text: "发送"
                    visible: !textEditor.readOnly
                    enabled: !controller.busy
                    onClicked: {
                        controller.sendText(root.targetHost, root.targetPort, textEditor.text);
                        textDialog.close();
                        sendDialog.close();
                    }
                }

            }

        }

    }

    Dialog {
        id: settingsDialog

        title: "设置"
        anchors.centerIn: parent
        width: root.width - 24
        height: Math.min(root.height - 24, 590)
        modal: true
        standardButtons: Dialog.Close

        contentItem: ScrollView {
            clip: true

            ColumnLayout {
                width: settingsDialog.availableWidth
                spacing: 12

                Label {
                    textFormat: Text.PlainText
                    text: "接收目录"
                    color: "#777"
                }

                Label {
                    textFormat: Text.PlainText
                    text: controller.outputDirectory
                    wrapMode: Text.WrapAnywhere
                    Layout.fillWidth: true
                }

                Button {
                    text: "更换接收目录"
                    enabled: !controller.busy
                    onClicked: controller.chooseOutputDirectory()
                }

                Label {
                    textFormat: Text.PlainText
                    text: "主题颜色"
                    color: "#777"
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 8

                    Repeater {
                        model: ["#268600", "#0078d4", "#008c95", "#7a42ad", "#be2c54", "#c95513", "#a87000", "#4c6878", "#484848"]

                        Rectangle {
                            width: 30
                            height: 30
                            color: modelData
                            border.width: controller.themeColor === modelData ? 3 : 0
                            border.color: "#bbb"

                            MouseArea {
                                anchors.fill: parent
                                onClicked: controller.setThemeColor(modelData)
                            }

                        }

                    }

                }

                Button {
                    text: "自定义颜色"
                    onClicked: controller.chooseThemeColor()
                }

                Button {
                    text: "更换头像"
                    onClicked: controller.chooseAvatar()
                }

                Label {
                    textFormat: Text.PlainText
                    text: "显示名称"
                    color: "#777"
                }

                TextField {
                    id: userInput

                    text: controller.username
                    Layout.fillWidth: true
                    maximumLength: 128
                }

                Button {
                    text: "保存名称"
                    onClicked: controller.setUsername(userInput.text)
                }

            }

        }

    }

    Dialog {
        id: batchDialog

        title: "接收批次明细"
        anchors.centerIn: parent
        width: root.width - 24
        height: root.height - 80
        modal: true
        standardButtons: Dialog.Close

        contentItem: ColumnLayout {
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: controller.batchFiles

                delegate: ItemDelegate {
                    width: ListView.view.width
                    height: 66
                    onClicked: controller.openPath(modelData.path)

                    contentItem: ColumnLayout {
                        Label {
                            textFormat: Text.PlainText
                            text: modelData.source
                            Layout.fillWidth: true
                            elide: Text.ElideMiddle
                        }

                        Label {
                            textFormat: Text.PlainText
                            text: modelData.bytes === "-1" ? "文件夹" : modelData.bytes + " B"
                            color: "#888"
                        }

                    }

                }

                ScrollBar.vertical: ScrollBar {
                }

            }

            RowLayout {
                Button {
                    text: "上一页"
                    enabled: controller.batchPage > 0
                    onClicked: controller.changeBatchPage(controller.batchPage - 1)
                }

                Label {
                    textFormat: Text.PlainText
                    text: "第 " + (controller.batchPage + 1) + " 页"
                }

                Button {
                    text: "下一页"
                    enabled: controller.batchHasNext
                    onClicked: controller.changeBatchPage(controller.batchPage + 1)
                }

            }

        }

    }

    Dialog {
        id: addressDialog

        title: "本机地址"
        anchors.centerIn: parent
        width: root.width - 24
        height: Math.min(root.height - 24, 520)
        modal: true
        standardButtons: Dialog.Close

        contentItem: ColumnLayout {
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                Label {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: controller.addresses
                    color: "#666"
                    lineHeight: 1.5
                    wrapMode: Text.WrapAnywhere
                }

            }

            Button {
                text: "刷新地址"
                onClicked: controller.refresh()
            }

        }

    }

    Dialog {
        id: termsDialog

        objectName: "termsDialog"
        title: "欢迎使用 Dukto Next"
        anchors.centerIn: parent
        width: root.width - 32
        modal: true
        closePolicy: Popup.NoAutoClose

        // 日期：2026-11-05；正文按已知可用宽度换行，列的自然高度不回依赖Dialog高度，避免紧凑窗口绑定循环。
        contentItem: Column {
            width: termsDialog.availableWidth
            spacing: 12
            Label {
                textFormat: Text.PlainText
                text: "本项目参考 Dukto R6，并保留跨平台桌面与命令行入口。\n\nR6 兼容传输用于可信局域网；接收目录可在设置中修改。文件默认保留同名原文件。\n\n本程序不向原版旧站点发送匿名统计。"
                wrapMode: Text.WordWrap
                width: parent.width
                color: "#666"
                lineHeight: 1.5
            }

            Button {
                text: "开始使用"
                objectName: "acceptTermsButton"
                width: parent.width
                onClicked: {
                    controller.acceptTerms();
                    termsDialog.close();
                }
            }

        }

    }

    Connections {
        // 日期：2026-11-04；历史批次从磁盘按页打开，不在界面持有完整清单。
        function onBatchOpened() {
            batchDialog.open();
        }

        // 日期：2026-11-04；收到文本时使用只读页面展示，复制由用户显式操作。
        function onTextReceived(text) {
            textEditor.readOnly = true;
            textEditor.text = text;
            textDialog.open();
        }

        target: controller
    }

}

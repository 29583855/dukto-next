import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: page

    property var panel
    property color accent: "#268600"

    signal closeRequested()

    // 日期：2026-11-05；公开状态映射为中文，原协议值保持用于控制与恢复。
    function stateText(state) {
        const names = {
            "scanning": "扫描中",
            "queued": "排队等待",
            "retrying": "等待网络重试",
            "transferring": "传输中",
            "pausing": "正在暂停",
            "paused": "已暂停",
            "checking": "检查恢复数据",
            "verifying": "校验中",
            "committing": "保存最终结果",
            "completed": "已完成",
            "cancelling": "正在取消",
            "cancelled": "已取消",
            "failed": "失败",
            "interrupted": "已中断，可继续"
        };
        return names[state] || state || "尚无任务";
    }

    // 日期：2026-11-05；批次目标、并发、冲突与重试选项共用核心，恢复沿用任务中持久保存的策略。
    function remoteOptions() {
        return {
            "channels": channelCount.currentText,
            "conflict": conflictPolicy.currentIndex === 1 ? "fail" : "rename",
            "retries": retryCount.currentText,
            "deadlineSeconds": deadlineSeconds.text,
            "profile": profile.text,
            "share": share.text,
            "remotePath": remotePath.text,
            "output": output.text,
            "requestId": request.text,
            "taskId": taskId.text,
            "paths": resumePaths.text.length ? resumePaths.text.split("\n") : []
        };
    }

    // 日期：2026-11-04；本机共享与主体授权使用相同显式复选框，默认不开放。
    function localOptions() {
        return {
            "share": localShare.text,
            "path": localPath.text,
            "browse": allowBrowse.checked,
            "download": allowDownload.checked,
            "upload": allowUpload.checked,
            "client": clientId.text
        };
    }

    // 日期：2026-11-05；将已核对的共享授权转换为用户可读文字，不展示协议字段。
    function permissionSummary(grants) {
        let values = [];
        for (let index = 0; index < grants.length; ++index) {
            let grant = grants[index];
            let rights = [];
            if (grant.browse)
                rights.push("浏览");

            if (grant.download)
                rights.push("下载");

            if (grant.upload)
                rights.push("上传");

            values.push(grant.share + "：" + rights.join("、"));
        }
        return values.join("；");
    }

    // 日期：2026-11-05；权限随当前页及选中身份更新，授权修改后不能继续显示旧权限。
    function selectedClientSummary() {
        for (let index = 0; index < panel.clients.length; ++index) {
            let client = panel.clients[index];
            if (client.client === clientId.text)
                return (client.revoked ? "已撤销 · " : "有效 · ") + "修订 " + client.revision + " · " + permissionSummary(client.grants);

        }
        return "选择本页客户端查看其权限；授权修改使用上方共享和权限选项";
    }

    color: "white"

    ColumnLayout {
        anchors.fill: parent
        spacing: 6

        RowLayout {
            Layout.margins: 12

            Button {
                text: "‹ 返回"
                onClicked: page.closeRequested()
            }

            Label {
                text: "服务器"
                textFormat: Text.PlainText
                color: accent
                font.pixelSize: 27
                Layout.fillWidth: true
            }

            BusyIndicator {
                running: panel.busy || panel.controlBusy
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
            }

        }

        TabBar {
            id: sections

            objectName: "serverSections"
            Layout.fillWidth: true

            TabButton {
                text: "连接与文件"
            }

            TabButton {
                text: "任务"
            }

            TabButton {
                text: "本机共享"
            }

        }

        StackLayout {
            currentIndex: sections.currentIndex
            Layout.fillWidth: true
            Layout.fillHeight: true

            Flickable {
                objectName: "serverClientFlick"
                clip: true
                contentHeight: clientColumn.height + 24

                ColumnLayout {
                    id: clientColumn

                    x: 16
                    y: 8
                    width: parent.width - 32
                    spacing: 8

                    Label {
                        text: "已保存的服务器资料"
                        textFormat: Text.PlainText
                        color: accent
                    }

                    RowLayout {
                        TextField {
                            id: profile

                            objectName: "serverProfile"
                            text: "default"
                            placeholderText: "资料别名"
                            Layout.fillWidth: true
                            maximumLength: 64
                        }

                        Button {
                            text: "连接"
                            enabled: !panel.busy
                            onClicked: panel.execute("auth", page.remoteOptions())
                        }

                        Button {
                            objectName: "serverRotateCredential"
                            text: "轮换凭据"
                            enabled: !panel.busy && !panel.controlBusy
                            onClicked: panel.execute("rotate", page.remoteOptions())
                        }

                    }

                    CheckBox {
                        id: showPairing

                        text: "首次连接：展开配对设置"
                    }

                    GroupBox {
                        title: "首次连接 / 配对"
                        visible: showPairing.checked
                        Layout.fillWidth: true

                        ColumnLayout {
                            anchors.fill: parent

                            TextField {
                                id: target

                                objectName: "serverTarget"
                                placeholderText: "服务器 IP:端口（默认 4646）"
                                Layout.fillWidth: true
                                maximumLength: 4096
                            }

                            TextField {
                                id: fingerprint

                                objectName: "serverFingerprint"
                                placeholderText: "核对服务器 SHA-256 指纹"
                                Layout.fillWidth: true
                                maximumLength: 64
                            }

                            RowLayout {
                                TextField {
                                    id: credential

                                    objectName: "serverCredential"
                                    placeholderText: "配对文件路径"
                                    Layout.fillWidth: true
                                    maximumLength: 4096
                                }

                                Button {
                                    text: "选择"
                                    onClicked: {
                                        let path = panel.chooseCredential();
                                        if (path)
                                            credential.text = path;

                                    }
                                }

                            }

                            Button {
                                objectName: "serverPairButton"
                                text: "配对并保存资料"
                                enabled: !panel.busy
                                Layout.fillWidth: true
                                onClicked: panel.execute("pair", {
                                    "profile": profile.text,
                                    "target": target.text,
                                    "fingerprint": fingerprint.text,
                                    "credentialFile": credential.text
                                })
                            }

                        }

                    }

                    TextField {
                        id: share

                        objectName: "serverShare"
                        text: "docs"
                        placeholderText: "授权共享名称"
                        maximumLength: 64
                        Layout.fillWidth: true
                    }

                    TextField {
                        id: remotePath

                        objectName: "serverRemotePath"
                        placeholderText: "共享内相对路径；空表示共享根"
                        maximumLength: 4096
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Button {
                            text: "浏览"
                            objectName: "serverBrowseButton"
                            enabled: !panel.busy
                            onClicked: panel.execute("list", page.remoteOptions())
                        }

                        Button {
                            text: "下一页"
                            enabled: !panel.busy && panel.cursor.length > 0
                            onClicked: {
                                let values = page.remoteOptions();
                                values.cursor = panel.cursor;
                                panel.execute("list", values);
                            }
                        }

                        Button {
                            text: "上级"
                            enabled: remotePath.text.length > 0
                            onClicked: {
                                let parts = remotePath.text.split("/");
                                parts.pop();
                                remotePath.text = parts.join("/");
                            }
                        }

                    }

                    ListView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 150
                        clip: true
                        model: panel.listingKind === "listing" ? panel.entries : []

                        delegate: ItemDelegate {
                            width: ListView.view.width
                            text: (modelData.type === "directory" ? "▣ " : "") + modelData.name + (modelData.bytes ? " · " + modelData.bytes + " B" : "")
                            onClicked: {
                                remotePath.text = remotePath.text ? remotePath.text + "/" + modelData.name : modelData.name;
                            }

                            contentItem: Label {
                                text: parent.text
                                textFormat: Text.PlainText
                                elide: Text.ElideMiddle
                                verticalAlignment: Text.AlignVCenter
                            }

                        }

                        ScrollBar.vertical: ScrollBar {
                        }

                    }

                    RowLayout {
                        TextField {
                            id: output

                            objectName: "serverOutput"
                            placeholderText: "本地保存目录（须已存在）"
                            Layout.fillWidth: true
                            maximumLength: 4096
                        }

                        Button {
                            text: "选择"
                            onClicked: {
                                let path = panel.chooseDirectory();
                                if (path)
                                    output.text = path;

                            }
                        }

                    }

                    TextField {
                        id: request

                        objectName: "serverRequest"
                        placeholderText: "可选：原请求 UUID，用于相同内容重试"
                        Layout.fillWidth: true
                        maximumLength: 36
                    }

                    RowLayout {
                        Label {
                            text: "传输并发"
                            textFormat: Text.PlainText
                        }

                        ComboBox {
                            id: channelCount

                            objectName: "serverChannelCount"
                            model: ["1", "2", "4", "8", "16"]
                            enabled: !panel.busy
                            Layout.fillWidth: true
                        }

                    }

                    CheckBox {
                        id: showTransferPolicy

                        objectName: "serverShowTransferPolicy"
                        text: "展开冲突、重试和总时限"
                    }

                    GroupBox {
                        visible: showTransferPolicy.checked
                        title: "传输选项"
                        Layout.fillWidth: true

                        ColumnLayout {
                            anchors.fill: parent

                            Label {
                                text: "同名文件或目录"
                                textFormat: Text.PlainText
                            }

                            ComboBox {
                                id: conflictPolicy

                                objectName: "serverConflictPolicy"
                                model: ["保留双方（自动重命名）", "遇到冲突停止"]
                                enabled: !panel.busy
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "恢复始终沿用原任务策略；先前已完成的文件会保留。"
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }

                            RowLayout {
                                Label {
                                    text: "网络重试次数"
                                    textFormat: Text.PlainText
                                }

                                ComboBox {
                                    id: retryCount

                                    objectName: "serverRetryCount"
                                    model: ["0", "1", "2", "3"]
                                    enabled: !panel.busy
                                    Layout.fillWidth: true
                                }
                            }

                            Label {
                                text: "总时限（秒）"
                                textFormat: Text.PlainText
                            }

                            TextField {
                                id: deadlineSeconds

                                objectName: "serverDeadlineSeconds"
                                text: "86400"
                                placeholderText: "总时限（秒，1..604800）"
                                enabled: !panel.busy
                                maximumLength: 6
                                Layout.fillWidth: true
                            }

                            Label {
                                text: "默认手动恢复。总时限包含扫描、排队、传输和校验；中断后保留检查点。"
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                                color: "#777"
                            }
                        }
                    }

                    RowLayout {
                        Button {
                            text: "上传文件"
                            enabled: !panel.busy
                            onClicked: panel.chooseUpload(page.remoteOptions(), false)
                        }

                        Button {
                            text: "上传目录"
                            enabled: !panel.busy
                            onClicked: panel.chooseUpload(page.remoteOptions(), true)
                        }

                        Button {
                            text: "下载"
                            objectName: "serverDownloadButton"
                            enabled: !panel.busy && output.text.length > 0
                            onClicked: panel.execute("download", page.remoteOptions())
                        }

                    }

                    Label {
                        text: "上传目标为当前相对目录；下载当前路径。同名时保留双方。"
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                    }

                }

                ScrollBar.vertical: ScrollBar {
                }

            }

            Flickable {
                objectName: "serverTaskFlick"
                clip: true
                contentHeight: taskColumn.height + 24

                ColumnLayout {
                    id: taskColumn

                    x: 16
                    y: 8
                    width: parent.width - 32
                    spacing: 12

                    Label {
                        text: "查询与恢复"
                        color: accent
                        textFormat: Text.PlainText
                        font.pixelSize: 22
                    }

                    RowLayout {
                        Button {
                            objectName: "serverRecoverTasksButton"
                            text: "找回已有任务"
                            enabled: !panel.controlBusy
                            onClicked: panel.execute("tasks", {
                                "profile": profile.text,
                                "after": "0"
                            })
                        }

                        Button {
                            text: "下一页任务"
                            enabled: !panel.controlBusy && panel.tasksMore
                            onClicked: panel.execute("tasks", {
                                "profile": profile.text,
                                "after": panel.tasksAfter
                            })
                        }

                    }

                    ListView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 130
                        clip: true
                        model: panel.tasks

                        delegate: ItemDelegate {
                            width: ListView.view.width
                            height: 58
                            onClicked: taskId.text = modelData.taskId

                            contentItem: Label {
                                text: modelData.direction + " · " + modelData.share + " · " + page.stateText(modelData.state) + "\n" + modelData.taskId
                                textFormat: Text.PlainText
                                elide: Text.ElideMiddle
                                verticalAlignment: Text.AlignVCenter
                            }

                        }

                        ScrollBar.vertical: ScrollBar {
                        }

                    }

                    TextField {
                        id: taskId

                        objectName: "serverTaskId"
                        text: panel.task.taskId || ""
                        placeholderText: "任务 UUID"
                        maximumLength: 36
                        Layout.fillWidth: true
                    }

                    Label {
                        text: "服务器资料：" + profile.text
                        textFormat: Text.PlainText
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }

                    Label {
                        text: "状态：" + page.stateText(panel.task.state) + "\n请求：" + (panel.task.desired || "无") + "\n活动执行者：" + (panel.task.executionActive === undefined ? "请查询" : (panel.task.executionActive ? "是" : "否"))
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "serverQueueHint"
                        text: "正在等待可用传输名额；可在此暂停或取消。并发数会按当前可用资源调整。"
                        visible: panel.task.state === "queued"
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                    }

                    Label {
                        objectName: "serverTaskConflictPolicy"
                        text: "任务冲突策略：" + (panel.task.conflict === "fail" ? "遇到冲突停止" : "保留双方（自动重命名）")
                        visible: !!panel.task.taskId
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    ProgressBar {
                        objectName: "serverByteProgress"
                        Layout.fillWidth: true
                        from: 0
                        to: 1
                        // 日期：2026-11-05；零字节任务以最终提交确认显示完成，不能用总量为零推断成功。
                        value: panel.task.state === "completed" ? 1 : (Number(panel.task.total || 0) > 0 ? Math.min(1, Math.max(Number(panel.task.receivedBytes || 0), Number(panel.task.bytes || 0)) / Number(panel.task.total)) : 0)
                        indeterminate: panel.busy && panel.task.state !== "completed" && Number(panel.task.total || 0) === 0
                    }

                    Label {
                        text: "已接收：" + (panel.task.receivedBytes || panel.task.bytes || "0") + " / " + (panel.task.total || "0") + " B\n已校验落盘：" + (panel.task.bytes || "0") + " B；恢复：" + (panel.task.restoredBytes || "0") + " B"
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        Layout.fillWidth: true
                    }

                    Label {
                        text: panel.task.state === "transferring" && panel.task.bytesPerSecond !== undefined ? (Number(panel.task.bytesPerSecond) / 1.04858e+06).toFixed(2) + " MiB/s · 剩余传输时间：" + (panel.task.etaSeconds === null ? "估算中" : panel.task.etaSeconds + " 秒") + "（之后仍需校验和提交）" : "完成结果以最终校验和提交确认为准"
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                    }

                    Label {
                        text: "请求 UUID：" + (panel.task.requestId || "")
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        Layout.fillWidth: true
                        color: "#777"
                    }

                    RowLayout {
                        Button {
                            objectName: "serverQueryButton"
                            text: "查询"
                            enabled: !panel.controlBusy
                            onClicked: panel.execute("task", page.remoteOptions())
                        }

                        Button {
                            objectName: "serverPauseButton"
                            text: "暂停"
                            enabled: !panel.controlBusy
                            onClicked: panel.execute("pause", page.remoteOptions())
                        }

                        Button {
                            objectName: "serverCancelButton"
                            text: "取消任务"
                            enabled: !panel.controlBusy
                            onClicked: panel.execute("cancel", page.remoteOptions())
                        }

                    }

                    Label {
                        text: "继续上传提供原路径（每行一个）；继续下载使用“连接与文件”的原保存目录。"
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                    }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 100

                        TextArea {
                            id: resumePaths

                            placeholderText: "原上传文件/目录（每行一个）"
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.WrapAnywhere
                        }

                    }

                    Button {
                        objectName: "serverResumeButton"
                        text: "继续原任务"
                        enabled: !panel.busy && !panel.controlBusy
                        onClicked: panel.execute("resume", page.remoteOptions())
                    }

                    Button {
                        text: "断开当前连接"
                        enabled: panel.busy
                        onClicked: panel.disconnectTransfer()
                    }

                    Label {
                        text: "请求须查询到已暂停/已取消才算生效。断开保留恢复数据；取消为终态，目前保留临时数据待管理。"
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                        color: "#777"
                    }

                }

                ScrollBar.vertical: ScrollBar {
                }

            }

            Flickable {
                objectName: "serverLocalFlick"
                clip: true
                contentHeight: localColumn.height + 24

                ColumnLayout {
                    id: localColumn

                    x: 16
                    y: 8
                    width: parent.width - 32
                    spacing: 8

                    Label {
                        text: "本机作为服务器"
                        textFormat: Text.PlainText
                        color: accent
                        font.pixelSize: 22
                    }

                    TextField {
                        id: names

                        text: "127.0.0.1"
                        placeholderText: "证书对应的本机 IP/主机名，逗号分隔"
                        Layout.fillWidth: true
                        maximumLength: 4096
                    }

                    RowLayout {
                        Button {
                            text: "建立身份"
                            enabled: !panel.busy
                            onClicked: panel.execute("init", {
                                "names": names.text
                            })
                        }

                        Button {
                            text: "读取身份"
                            enabled: !panel.busy
                            onClicked: panel.execute("info", {
                            })
                        }

                    }

                    Label {
                        text: "服务器 UUID：" + (panel.identity.serverId || "尚未建立")
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        Layout.fillWidth: true
                    }

                    TextArea {
                        text: panel.identity.fingerprint || ""
                        readOnly: true
                        selectByMouse: true
                        textFormat: TextEdit.PlainText
                        wrapMode: TextEdit.WrapAnywhere
                        Layout.fillWidth: true
                        color: accent
                    }

                    RowLayout {
                        TextField {
                            id: bind

                            text: "0.0.0.0"
                            placeholderText: "监听地址"
                            Layout.fillWidth: true
                            maximumLength: 128
                        }

                        SpinBox {
                            id: port

                            from: 1
                            to: 65535
                            value: 4646
                            editable: true
                        }

                    }

                    Button {
                        text: panel.serving ? "停止本机服务" : "启动本机 TLS 服务"
                        Layout.fillWidth: true
                        onClicked: panel.setServing(!panel.serving, bind.text, port.value)
                    }

                    CheckBox {
                        id: showSessionPolicy

                        objectName: "serverSessionExpand"
                        text: "认证会话有效期设置"
                    }

                    GroupBox {
                        title: "本机认证会话"
                        visible: showSessionPolicy.checked
                        Layout.fillWidth: true

                        ColumnLayout {
                            anchors.fill: parent

                            SpinBox {
                                id: sessionSeconds

                                objectName: "serverSessionSeconds"
                                from: 1
                                to: 86400
                                value: panel.sessionSeconds
                                editable: true
                                Layout.fillWidth: true
                            }

                            RowLayout {
                                Button {
                                    objectName: "serverSessionRead"
                                    text: "读取"
                                    enabled: !panel.busy
                                    onClicked: panel.execute("session-show", {
                                    })
                                }

                                Button {
                                    objectName: "serverSessionSave"
                                    text: "保存"
                                    enabled: !panel.busy
                                    onClicked: panel.execute("session-set", {
                                        "sessionSeconds": String(sessionSeconds.value)
                                    })
                                }

                            }

                            Label {
                                text: "单位：秒，范围 1–86400，默认 24 小时。更改后新连接生效。到期后使用相同资料重新连接，继续原任务。"
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                                color: "#777"
                            }

                        }

                    }

                    TextField {
                        id: localShare

                        text: "docs"
                        placeholderText: "共享名称"
                        Layout.fillWidth: true
                        maximumLength: 64
                    }

                    RowLayout {
                        TextField {
                            id: localPath

                            placeholderText: "本机共享目录"
                            Layout.fillWidth: true
                            maximumLength: 4096
                        }

                        Button {
                            text: "选择"
                            onClicked: {
                                let path = panel.chooseDirectory();
                                if (path)
                                    localPath.text = path;

                            }
                        }

                    }

                    RowLayout {
                        CheckBox {
                            id: allowBrowse

                            text: "浏览"
                        }

                        CheckBox {
                            id: allowDownload

                            text: "下载"
                        }

                        CheckBox {
                            id: allowUpload

                            text: "上传"
                        }

                    }

                    RowLayout {
                        Button {
                            text: "保存共享"
                            enabled: !panel.busy
                            onClicked: panel.execute("share-add", page.localOptions())
                        }

                        Button {
                            text: "移除"
                            enabled: !panel.busy
                            onClicked: panel.execute("share-remove", page.localOptions())
                        }

                        Button {
                            text: "查看"
                            enabled: !panel.busy
                            onClicked: panel.execute("shares", {
                            })
                        }

                    }

                    ListView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 100
                        clip: true
                        model: panel.listingKind === "shares" ? panel.entries : []

                        delegate: ItemDelegate {
                            width: ListView.view.width
                            text: modelData.name + " · " + (modelData.root || "")

                            contentItem: Label {
                                text: parent.text
                                textFormat: Text.PlainText
                                elide: Text.ElideMiddle
                                verticalAlignment: Text.AlignVCenter
                            }

                        }

                        ScrollBar.vertical: ScrollBar {
                        }

                    }

                    Button {
                        text: "颁发本共享的配对文件"
                        enabled: !panel.busy
                        Layout.fillWidth: true
                        onClicked: panel.execute("pairing", page.localOptions())
                    }

                    Label {
                        text: "已配对客户端（包含已撤销）"
                        textFormat: Text.PlainText
                        color: accent
                    }

                    RowLayout {
                        Button {
                            objectName: "serverClientsRefresh"
                            text: "刷新客户端"
                            enabled: !panel.busy
                            onClicked: panel.execute("clients", {
                            })
                        }

                        Button {
                            objectName: "serverClientsNext"
                            text: "下一页"
                            enabled: !panel.busy && panel.clientsMore
                            onClicked: panel.execute("clients", {
                                "after": panel.clientsAfter
                            })
                        }

                    }

                    ListView {
                        objectName: "serverClientsList"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 150
                        clip: true
                        model: panel.clients

                        delegate: ItemDelegate {
                            objectName: "serverClientEntry"
                            width: ListView.view.width
                            text: (modelData.revoked ? "已撤销 · " : "有效 · ") + modelData.client
                            onClicked: clientId.text = modelData.client

                            contentItem: Label {
                                text: parent.text
                                textFormat: Text.PlainText
                                elide: Text.ElideMiddle
                                verticalAlignment: Text.AlignVCenter
                            }

                        }

                        ScrollBar.vertical: ScrollBar {
                        }

                    }

                    Label {
                        id: clientPermissions

                        objectName: "serverClientPermissions"
                        text: page.selectedClientSummary()
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        Layout.fillWidth: true
                        color: "#666"
                    }

                    TextField {
                        id: clientId

                        objectName: "serverClientId"
                        placeholderText: "客户端 UUID（从列表选择或输入）"
                        Layout.fillWidth: true
                        maximumLength: 36
                    }

                    RowLayout {
                        Button {
                            objectName: "serverClientGrant"
                            text: "更新客户端权限"
                            enabled: !panel.busy
                            onClicked: panel.execute("grant", page.localOptions())
                        }

                        Button {
                            objectName: "serverClientRevoke"
                            text: "撤销客户端"
                            enabled: !panel.busy
                            onClicked: panel.execute("revoke", page.localOptions())
                        }

                    }

                    Label {
                        text: "本机状态目录：" + panel.directory
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        Layout.fillWidth: true
                        color: "#888"
                    }

                }

                ScrollBar.vertical: ScrollBar {
                }

            }

        }

        Rectangle {
            height: 1
            Layout.fillWidth: true
            color: accent
            opacity: 0.5
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: 76
            Layout.margins: 10

            TextArea {
                text: panel.status
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                color: "#555"
            }

        }

    }

}

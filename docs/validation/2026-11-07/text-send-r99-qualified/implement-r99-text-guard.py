"""日期：2026-11-07；在UTF-8转换前核对原8MiB上限和共享预算，拒绝发送时保留编辑窗口。"""
from pathlib import Path


# 日期：2026-11-07；按已有换行精确替换唯一字节片段，不转换任何已有文件编码。
def replace(path, old, new):
    raw = path.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    old = old.replace('\n', newline).encode('utf-8')
    new = new.replace('\n', newline).encode('utf-8')
    assert raw.count(old) == 1, str(path)
    path.write_bytes(raw.replace(old, new))


# 日期：2026-11-07；只修改GUI发送入口，不改CLI、协议和正在执行长期测试的冻结输入。
def main():
    root = Path.cwd()
    path = root / 'src/app/controller.cpp'
    replace(path, '#include "controller.h"\n', '#include "controller.h"\n#include "core/buffercredit.h"\n')
    old = '''// 日期：2026-11-04；发送空文本有效，长度约束由共用核心执行。
void Controller::sendText(const QString &host, int port, const QString &text) {
    dukto::LegacyRequest request;
    if (!prepareRequest(request, host, port))
        return;
    request.textMode = true;
    request.text = text.toUtf8();
    start(request);
}
'''
    new = '''// 日期：2026-11-07；无分配计算Qt UTF-8字节数，孤立代理码元按Qt默认问号编码，超过原上限立即拒绝。
static qint64 outgoingTextBytes(const QString &text) {
    if (text.size() > dukto::MaxTextBytes)
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("文本超过 8 MiB 限制，请作为文件发送"), "scan");
    qint64 bytes = 0;
    for (int index = 0; index < text.size(); ++index) {
        const auto ch = text.at(index);
        if (ch.isHighSurrogate() && index + 1 < text.size() &&
            text.at(index + 1).isLowSurrogate()) {
            bytes += 4;
            ++index;
        } else if (ch.isSurrogate() || ch.unicode() < 0x80)
            ++bytes;
        else
            bytes += ch.unicode() < 0x800 ? 2 : 3;
        if (bytes > dukto::MaxTextBytes)
            throw dukto::Error(dukto::ExitCode::Config,
                               QStringLiteral("文本超过 8 MiB 限制，请作为文件发送"), "scan");
    }
    return bytes;
}

// 日期：2026-11-07；先检查字节上限并授信输入/转换临时量，再编码；拒绝时返回false让QML保留草稿。
bool Controller::sendText(const QString &host, int port, const QString &text) {
    dukto::LegacyRequest request;
    if (!prepareRequest(request, host, port))
        return false;
    try {
        const auto bytes = outgoingTextBytes(text);
        dukto::BufferCredit conversion(qint64(text.size()) * 2 + bytes + 64 * 1024, true);
        request.textMode = true;
        request.text = text.toUtf8();
        if (request.text.size() != bytes)
            throw dukto::Error(dukto::ExitCode::Runtime,
                               QStringLiteral("文本编码长度校验失败，未开始发送"), "scan");
        start(std::move(request));
        return sender_ != nullptr;
    } catch (const dukto::Error &error) {
        status_ = error.message;
        emit stateChanged();
        return false;
    }
}
'''
    replace(path, old, new)
    replace(path, '''// 日期：2026-11-04；剪贴板与文本编辑框走相同的协议和错误路径。
void Controller::sendClipboard(const QString &host, int port) {
    if (clipboardAvailable())
        sendText(host, port, QApplication::clipboard()->text());
}
''', '''// 日期：2026-11-07；显式发送只读取一次系统剪贴板，复用转换前字节检查；系统读取本身另行验收。
void Controller::sendClipboard(const QString &host, int port) {
    const auto text = QApplication::clipboard()->text();
    if (!text.isEmpty())
        sendText(host, port, text);
}
''')
    replace(root / 'src/app/controller.h',
            '// 日期：2026-11-04；验证文本长度后通过原版协议发送。\n    Q_INVOKABLE void sendText',
            '// 日期：2026-11-07；转换前核对UTF-8上限及临时授信，返回是否实际启动，失败保留编辑草稿。\n    Q_INVOKABLE bool sendText')
    path = root / 'ui/Main.qml'
    replace(path, '                                textEditor.text = "";\n                                textDialog.open();',
            '                                textEditor.text = "";\n                                textDialog.sendError = "";\n                                textDialog.open();')
    replace(path, '        objectName: "textDialog"\n', '        objectName: "textDialog"\n        property string sendError: ""\n')
    replace(path, '''            RowLayout {
                visible: textEditor.readOnly && controller.receivedTextPaged''', '''            Label {
                objectName: "sendTextError"
                Layout.fillWidth: true
                visible: !textEditor.readOnly && textDialog.sendError.length > 0
                text: textDialog.sendError
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                color: "#a62c2c"
            }

            RowLayout {
                visible: textEditor.readOnly && controller.receivedTextPaged''')
    replace(path, '''                        controller.sendText(root.targetHost, root.targetPort, textEditor.text);
                        textDialog.close();
                        sendDialog.close();''', '''                        // 日期：2026-11-07；仅实际启动后关闭，超限/授信/地址错误显示在编辑器内并允许原稿重试。
                        if (controller.sendText(root.targetHost, root.targetPort, textEditor.text)) {
                            textDialog.sendError = "";
                            textDialog.close();
                            sendDialog.close();
                        } else {
                            textDialog.sendError = controller.status;
                        }''')
    print('GUI text guard implemented; existing encoding and line endings retained')


if __name__ == '__main__':
    main()

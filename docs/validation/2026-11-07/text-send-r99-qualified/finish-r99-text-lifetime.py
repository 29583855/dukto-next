"""日期：2026-11-07；初轮结束后补齐临时额度的异常生命周期和编辑器关闭后的正文释放。"""
import runpy
from pathlib import Path


# 日期：2026-11-07；只在初轮取得真实终态后顺序修改，不能在其冻结输入期间写源码。
def main():
    root = Path.cwd()
    import json
    first = json.loads((root / 'docs/validation/2026-11-07/text-send-r99-windows/driver-result.json').read_text('utf-8'))
    assert first['completed'] and first['buildInputsUnchanged']
    replace = runpy.run_path('.cache/implement-r99-text-guard.py')['replace']
    path = root / 'src/app/controller.cpp'
    replace(path, '// 日期：2026-11-07；先检查字节上限并授信输入/转换临时量，再编码；拒绝时返回false让QML保留草稿。',
            '// 日期：2026-11-07；先核对上限和编码临时额度；令牌先于请求声明，异常反馈后也先释放正文再归还额度。')
    replace(path, '''bool Controller::sendText(const QString &host, int port, const QString &text) {
    dukto::LegacyRequest request;''', '''bool Controller::sendText(const QString &host, int port, const QString &text) {
    std::unique_ptr<dukto::BufferCredit> conversion;
    dukto::LegacyRequest request;''')
    replace(path, '        dukto::BufferCredit conversion(qint64(text.size()) * 2 + bytes + 64 * 1024, true);',
            '        conversion.reset(new dukto::BufferCredit(qint64(text.size()) * 3 + 64 * 1024, true));')
    path = root / 'ui/Main.qml'
    replace(path, '''        // 日期：2026-11-06；先移除QML正文，再归还控制器持有的显示授信，关闭后不缓存完整收到文本。
        onClosed: {
            if (textEditor.readOnly) {
                textEditor.text = "";
                controller.releaseReceivedText();
            }
        }''', '''        // 日期：2026-11-07；关闭后先清正文；只读页随后归还授信，成功发送和主动关闭也不缓存草稿。
        onClosed: {
            textEditor.text = "";
            if (textEditor.readOnly)
                controller.releaseReceivedText();
        }''')
    path = root / 'tests/ui_tests.cpp'
    replace(path, '''        QTRY_VERIFY(!sendDialog->property("visible").toBool());
        QTRY_VERIFY(!controller.busy());
    }
''', '''        QTRY_VERIFY(!sendDialog->property("visible").toBool());
        QTRY_VERIFY(!controller.busy());
        QTRY_COMPARE(editor->property("text").toString(), QString());
    }
''')
    print('Final GUI lifetime edits applied after first actual terminal')


if __name__ == '__main__':
    main()

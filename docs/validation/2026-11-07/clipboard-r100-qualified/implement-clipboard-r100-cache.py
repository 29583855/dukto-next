"""日期：2026-11-07；剪贴板可用性只在实际变化时刷新，传输进度查询只读取缓存布尔值。"""
from pathlib import Path
import json
import runpy
import subprocess


# 日期：2026-11-07；不缓存正文、不改显式发送的最新读取语义，原文件编码和换行保持。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    # 日期：2026-11-07；唯一锚点断言防止修改其他通知属性，新增私有刷新与独立信号。
    def header(text):
        replacements = {
            'Q_PROPERTY(bool clipboardAvailable READ clipboardAvailable NOTIFY stateChanged)':
                'Q_PROPERTY(bool clipboardAvailable READ clipboardAvailable NOTIFY clipboardAvailabilityChanged)',
            '// 日期：2026-11-04；初始化设置、历史数据库及旧版发现/接收入口。':
                '// 日期：2026-11-07；初始化独立设置/历史与发现接收入口，并读取剪贴板初始可用状态。',
            '// 日期：2026-11-04；剪贴板为空时禁用发送入口。':
                '// 日期：2026-11-07；返回缓存的空值状态，频繁进度查询不读取系统剪贴板正文。',
            '    void stateChanged();\n':
                '    void stateChanged();\n    // 日期：2026-11-07；正文是否为空改变时单独通知，不复用传输进度通知。\n    void clipboardAvailabilityChanged();\n',
            '  private:\n':
                '  private:\n    // 日期：2026-11-07；仅初始化或实际剪贴板变化时读取一次正文，只保留布尔状态。\n    void refreshClipboardAvailability();\n',
            '    bool capturePending_ = false;\n':
                '    bool capturePending_ = false;\n    bool clipboardAvailable_ = false;\n',
        }
        for old, new in replacements.items():
            assert text.count(old) == 1, old
            text = text.replace(old, new, 1)
        return text
    helper['update'](root / 'src/app/controller.h', header)
    # 日期：2026-11-07；连接实际变化通知并准备初值；普通getter保持无正文读取和无分配。
    def implementation(text):
        old = '    connect(QApplication::clipboard(), &QClipboard::dataChanged, this, &Controller::stateChanged);'
        assert text.count(old) == 1
        text = text.replace(old, '''    connect(QApplication::clipboard(), &QClipboard::dataChanged, this,
            &Controller::refreshClipboardAvailability);
    refreshClipboardAvailability();''', 1)
        text = text.replace('// 日期：2026-11-04；使用独立配置/数据库；首次运行准备默认下载目录，不重建用户保存后丢失的目录。',
                            '// 日期：2026-11-07；初始化独立设置、历史和接收服务，并缓存剪贴板初始可用状态。', 1)
        old = '''bool Controller::clipboardAvailable() const {
    return !QApplication::clipboard()->text().isEmpty();
}'''
        assert text.count(old) == 1
        return text.replace(old, '''bool Controller::clipboardAvailable() const {
    return clipboardAvailable_;
}

// 日期：2026-11-07；仅实际变化时读取一次正文；只保存布尔值，显式发送仍重新读取最新文本。
void Controller::refreshClipboardAvailability() {
    const bool available = !QApplication::clipboard()->text().isEmpty();
    if (available == clipboardAvailable_)
        return;
    clipboardAvailable_ = available;
    emit clipboardAvailabilityChanged();
}''', 1)
    helper['update'](root / 'src/app/controller.cpp', implementation)
    # 日期：2026-11-07；修改函数的定义注释与声明日期同步，未改功能的其他注释继续保持。
    path = root / 'src/app/controller.cpp'
    text = path.read_text('utf-8')
    position = text.index('bool Controller::clipboardAvailable() const')
    before = text[:position]
    print(before.splitlines()[-1])
    names = ('src/app/controller.cpp', 'src/app/controller.h', 'tests/ui_tests.cpp')
    subprocess.run([str(root / '.tools/python/Scripts/clang-format.exe'), '-i', *[str(root / name) for name in names]], check=True)
    for row in json.loads((root / '.cache/clipboard-r100-before/source-before.json').read_text('utf-8')):
        raw = (root / row['path']).read_bytes()
        assert raw.startswith(b'\xef\xbb\xbf') == row['utf8Bom'] and (b'\r\n' in raw) == row['crlf']
    print(json.dumps({'productionFilesUpdated': 2, 'regressionFiles': 1, 'originalEncodingPreserved': True}), flush=True)


if __name__ == '__main__':
    main()

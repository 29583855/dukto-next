"""日期：2026-11-07；绑定R100 Linux收验身份，保留R98原全部门槛并增加剪贴板QML核对。"""
from pathlib import Path


# 日期：2026-11-07；逐个固定替换必须唯一匹配，不修改历史收验工具的原编码和原件。
def main():
    source = Path('.cache/fetch-linux-preview-r98.py').read_bytes()
    newline = b'\r\n' if b'\r\n' in source else b'\n'
    mapping = {
        '固定R98源码': '固定R100源码',
        'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7': 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3',
        'exit-state-r98-linux-package-terminal': 'clipboard-r100-linux-package-terminal',
        'linux-preview-20261107-r98-exit-state': 'linux-preview-20261107-r100-clipboard',
        '.cache/r98-linux-package-dispatch.json': '.cache/r100-linux-package-dispatch.json',
        '42266702018': '42286121325',
        "package['applicationSourceFiles'] == 333": "package['applicationSourceFiles'] == 338",
        "'sourceFiles': 333": "'sourceFiles': 338",
    }
    for old, new in mapping.items():
        before = old.encode('utf-8')
        assert source.count(before) == 1, old
        source = source.replace(before, new.encode('utf-8'))
    before = b"    assert text.count('PASS   : FileExchangeTests::parallelDispositions(') == 16"
    assert source.count(before) == 1
    additional = '''
    # 日期：2026-11-07；包构建自己的原核心报告必须包含实际生产QML的新旧回归，拒绝仅继承其他运行结论。
    ui_log = (output / 'build/Testing/QtTest/ui-tests.log').read_text('utf-8')
    for method in ('clipboardAvailabilityDoesNotReadOnProgress', 'rejectedTextKeepsDraftThroughQml'):
        assert ui_log.splitlines().count('PASS   : UiTests::' + method + '()') == 1
    navigation = json.loads((output / 'build/main-window-navigation.json').read_text('utf-8'))
    assert navigation['passed'] and navigation['sourceCommit'] == COMMIT and navigation['binaryUnchanged']
'''.replace('\n', newline.decode()).encode('utf-8')
    source = source.replace(before, before + additional)
    target = Path('.cache/fetch-linux-preview-r100.py')
    assert not target.exists()
    target.write_bytes(source)
    compile(source, str(target), 'exec')
    print('R100 Linux collector prepared; original R98 verifier unchanged', flush=True)


if __name__ == '__main__':
    main()

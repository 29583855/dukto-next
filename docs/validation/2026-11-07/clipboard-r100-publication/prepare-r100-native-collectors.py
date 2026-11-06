"""日期：2026-11-07；为已发布的R100固定身份准备后续收验，不重复派发远端任务。"""
import ast
import json
from pathlib import Path


# 日期：2026-11-07；仅替换固定来源身份并增加实际剪贴板QML用例检查，原收验门槛完整保留。
def main():
    root = Path.cwd()
    ledger = json.loads((root / '.cache/r100-native-dispatch.json').read_text('utf-8'))
    assert ledger['sourceCommit'] == 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
    assert ledger['runId'] == 42282812778 and ledger['buildInputsVerified'] == 210
    replacements = (
        ('a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38', ledger['sourceCommit']),
        ('42276738981', str(ledger['runId'])),
        ('R99', 'R100'), ('r99', 'r100'),
        ('text-send-r100-native-terminal', 'clipboard-r100-native-terminal'),
        ('text-send-r100-macos-compiled', 'clipboard-r100-macos-compiled'),
        ('macos-compiled-20261107-r100-text-send', 'macos-compiled-20261107-r100-clipboard'),
    )
    for name in ('collect-r99-native-terminal.py', 'collect-r99-macos-compiled.py',
                 'dispatch-r99-preview-packages.py'):
        source = root / '.cache' / name
        text = source.read_bytes().decode('utf-8')
        for before, after in replacements:
            text = text.replace(before, after)
        if name == 'collect-r99-native-terminal.py':
            marker = "        text_rows.append({'runner': runner, 'encodingRows': 8, 'draftRecovery': True})"
            assert text.count(marker) == 1
            text = text.replace(marker, """        clipboard = [case for case in ui.findall('.//testcase')
                     if case.get('name') == 'clipboardAvailabilityDoesNotReadOnProgress']
        assert len(clipboard) == 1 and clipboard[0].get('result') == 'pass'
        ui_log = (core_dir / 'Testing/QtTest/ui-tests.log').read_text('utf-8')
        assert ui_log.splitlines().count('PASS   : UiTests::clipboardAvailabilityDoesNotReadOnProgress()') == 1
        text_rows.append({'runner': runner, 'encodingRows': 8, 'draftRecovery': True,
                          'clipboardAvailabilityThroughProductionQml': True})""")
        if name == 'dispatch-r99-preview-packages.py':
            marker = "    assert len(value['textSendChecks']) == 4 and all(row['encodingRows'] == 8 and row['draftRecovery'] for row in value['textSendChecks'])"
            assert text.count(marker) == 1
            text = text.replace(marker, marker + "\n    assert all(row['clipboardAvailabilityThroughProductionQml'] for row in value['textSendChecks'])")
        ast.parse(text)
        target = root / '.cache' / name.replace('r99', 'r100')
        assert not target.exists()
        target.write_bytes(text.encode('utf-8'))
    state_path = root / '.cache/execution-current.json'
    raw = state_path.read_bytes()
    state = json.loads(raw.decode('utf-8-sig'))
    state.update(currentRepositoryCommit=ledger['sourceCommit'],
                 currentSourceCommit=ledger['sourceCommit'],
                 currentProductionCommit=ledger['sourceCommit'],
                 currentTestCommit=ledger['sourceCommit'])
    state['r100ClipboardAvailability']['sourceCommit'] = ledger['sourceCommit']
    state['r100ClipboardAvailability']['nativeDispatch'] = ledger
    state['r100ClipboardAvailability']['nativeCIPending'] = True
    newline = '\r\n' if b'\r\n' in raw else '\n'
    encoded = (json.dumps(state, ensure_ascii=False, indent=2) + '\n').replace('\n', newline).encode('utf-8')
    if raw.startswith(b'\xef\xbb\xbf'):
        encoded = b'\xef\xbb\xbf' + encoded
    state_path.write_bytes(encoded)
    print(json.dumps({'sourceCommit': ledger['sourceCommit'], 'runId': ledger['runId'],
                      'collectorsPrepared': 3, 'noAdditionalDispatch': True}))


if __name__ == '__main__':
    main()

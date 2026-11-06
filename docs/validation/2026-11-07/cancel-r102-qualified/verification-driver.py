"""日期：2026-11-07；独立核验新慢端夹具的双Windows核心、原生和高DPI原报告。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；只接受实际通过用例及精确已知Qt消息，任何新警告、缺件或输入变化都中止。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    proof = helper['proof']
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    base = root / 'docs/validation/2026-11-07/cancel-r102-windows'
    driver = json.loads((base / 'driver-result.json').read_text('utf-8'))
    assert driver['passed'] and driver['buildInputsUnchanged']
    assert driver['changedBuildInputs'] == ['tests/ui_tests.cpp'] and len(driver['cases']) == 2
    inputs = json.loads((base / 'build-inputs.json').read_text('utf-8'))
    assert len(inputs) == 210
    changed = []
    for row in inputs:
        raw = (root / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        previous = subprocess.check_output(['git', 'show', '1f82d5d3b9ae36e77ee98da942c2fc5369310c7a:' + row['path']], cwd=checkout)
        if raw != previous:
            changed.append(row['path'])
            assert raw.startswith(b'\xef\xbb\xbf') == previous.startswith(b'\xef\xbb\xbf')
            assert (b'\r\n' in raw) == (b'\r\n' in previous)
            assert b'\n' not in raw.replace(b'\r\n', b'') if b'\r\n' in previous else b'\r' not in raw
    assert changed == ['tests/ui_tests.cpp']
    windows = []
    for label in ('ucrt', 'msvc'):
        folder = base / label
        row, = [row for row in driver['cases'] if row['toolchain'] == label]
        assert row['buildExitCode'] == row['ctestExitCode'] == row['nativeNavigationExitCode'] == 0
        assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$',
                         (folder / 'ctest.log').read_text('utf-8-sig'), re.M)
        reports = sorted((folder / 'QtTest').glob('*.xml'))
        assert len(reports) == 22
        for path in reports:
            parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
            suite = ET.fromstring(path.read_bytes(), parser=parser)
            assert suite.tag == 'testsuite' and suite.get('failures') == '0'
            assert not suite.findall('.//failure') and not suite.findall('.//error')
            assert all(case.get('result') == 'pass' for case in suite.findall('testcase'))
            comments = [item.text for item in suite.iter() if item.tag is ET.Comment]
            assert int(suite.get('errors')) == len(comments)
            if path.name == 'file-exchange-tests.xml':
                assert len(comments) == 64
                assert all('type="qinfo"' in text and 'message="terminal fixture ' in text for text in comments)
            elif path.name == 'avatars-tests.xml':
                # 日期：2026-11-07；既有头像警告允许未出现；出现时仍须精确匹配且至多一条。
                assert len(comments) <= 1 and all(text.strip() == (
                    'message="QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once." type="qwarn"')
                    for text in comments)
            else:
                assert not comments
        navigation = json.loads((folder / 'native-navigation.json').read_text('utf-8'))
        assert navigation['passed'] and navigation['binaryUnchanged'] and len(navigation['cases']) == 3
        assert navigation['cases'][0]['nativeSelectorGuard'] == {'exitCode': 2, 'passed': True}
        assert [scene['platform'] for scene in navigation['cases']] == ['windows', 'offscreen', 'offscreen']
        for scene in navigation['cases']:
            assert scene['passed'] and scene['verifiedCancellationRows'] == ['send', 'receive-header', 'receive-partial']
            lines = (folder / 'native-navigation' / scene['name'] / 'qt-test.log').read_text('utf-8-sig').splitlines()
            assert not any(line.startswith(('FAIL!', 'QWARN', 'QFATAL', 'SKIP', 'XPASS', 'XFAIL')) for line in lines)
            for phase in ('send', 'receive-header', 'receive-partial'):
                assert lines.count('PASS   : UiTests::cancelThenTransferAgainThroughQml(' + phase + ')') == 1
        windows.append({'toolchain': label, 'coreTargets': 23, 'originalQtReports': [proof(p) for p in reports],
                        'navigation': proof(folder / 'native-navigation.json'),
                        'nativeAndHighDpiCancellationRows': 9,
                        'sameControllerLaterBidirectionalContentVerified': True})
    audit_path = root / 'docs/validation/2026-11-07/cancel-r102-source-audit.json'
    audit = json.loads(audit_path.read_text('utf-8'))
    assert len(audit['files']) == 204 and not audit['findings'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    output = root / 'docs/validation/2026-11-07/cancel-r102-qualified'
    output.mkdir(exist_ok=False)
    value = {'date': '2026-11-07', 'observedUtc': datetime.now(timezone.utc).isoformat(),
             'basedOnSourceCommit': '1f82d5d3b9ae36e77ee98da942c2fc5369310c7a', 'buildInputs': inputs,
             'changedBuildInputs': changed, 'windows': windows, 'freshFull23TargetsRun': True,
             'cancellationAndEofBudgetMilliseconds': 5000, 'productionCoreChanged': False,
             'productCancellationBugFixClaimed': False, 'sourceAudit': proof(audit_path),
             'nativeMacLinuxR102Qualified': False, 'wholeF18Qualified': False,
             'passed': True, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'verified-receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'toolchains': 2, 'coreTargetsEach': 23, 'nativeCancellationRows': 18, 'passed': True}))


if __name__ == '__main__':
    main()

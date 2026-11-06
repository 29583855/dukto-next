"""日期：2026-11-07；独立核验Ubuntu旧/新慢端对照原件，不将未复现解释为根因已消除。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；实际进程终态、逐数据行、23核心及精确Git输入缺一不可，原门槛不变。
def main():
    root = Path.cwd()
    folder = root / 'docs/validation/2026-11-07/cancel-r102-glibc'
    collection = json.loads((folder / 'collection-result.json').read_text('utf-8'))
    driver = json.loads((folder / 'results/driver-result.json').read_text('utf-8'))
    assert collection['passed'] and collection['remoteExitCode'] == 0 and driver['passed'] and driver['binaryUnchanged']
    rows = json.loads((folder / 'results/exit-codes.json').read_text('utf-8'))
    assert len(rows) == 18 and all(row['exitCode'] == 0 for row in rows)
    assert len(driver['baselineCases']) == 3 and all(row['exitCode'] == 0 for row in driver['baselineCases'])
    assert driver['cancellationAndEofBudgetMilliseconds'] == 5000 and not driver['productionCoreChanged']
    assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$', (folder / 'results/fixed-ctest.log').read_text('utf-8'), re.M)
    xmls = sorted((folder / 'build/Testing/QtTest').glob('*.xml'))
    assert len(xmls) == 22
    for path in xmls:
        suite = ET.fromstring(path.read_bytes(), parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
        assert suite.get('failures') == '0' and not suite.findall('.//failure') and not suite.findall('.//error')
        assert all(case.get('result') == 'pass' for case in suite.findall('testcase'))
        comments = [item.text for item in suite.iter() if item.tag is ET.Comment]
        assert int(suite.get('errors')) == len(comments)
        if path.name == 'file-exchange-tests.xml':
            assert len(comments) == 64 and all('type="qinfo"' in item and 'message="terminal fixture ' in item for item in comments)
        elif path.name == 'avatars-tests.xml':
            assert len(comments) <= 1 and all(item.strip() == 'message="QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once." type="qwarn"' for item in comments)
        else:
            assert not comments
    for index in range(3):
        log = (folder / ('results/baseline-send-' + str(index) + '.txt')).read_text('utf-8').splitlines()
        assert log.count('PASS   : UiTests::cancelThenTransferAgainThroughQml(send)') == 1
    phases = ('send', 'receive-header', 'receive-partial')
    for index in range(10):
        path = folder / ('results/fixed-cancel-' + str(index) + '.xml')
        suite = ET.parse(path).getroot()
        assert suite.get('failures') == suite.get('errors') == '0'
        assert all(case.get('result') == 'pass' for case in suite.findall('testcase'))
        log = path.with_suffix('.txt').read_text('utf-8').splitlines()
        for phase in phases:
            assert log.count('PASS   : UiTests::cancelThenTransferAgainThroughQml(' + phase + ')') == 1
        assert not any(line.startswith(('FAIL!', 'QWARN', 'QFATAL', 'SKIP', 'XFAIL', 'XPASS')) for line in log)
    navigation = json.loads((folder / 'results/native-navigation.json').read_text('utf-8'))
    assert navigation['passed'] and navigation['binaryUnchanged'] and len(navigation['cases']) == 3
    assert navigation['cases'][0]['nativeSelectorGuard'] == {'exitCode': 2, 'passed': True}
    assert [row['platform'] for row in navigation['cases']] == ['xcb', 'offscreen', 'offscreen']
    for scene in navigation['cases']:
        assert scene['passed'] and scene['verifiedCancellationRows'] == list(phases)
    read = runpy.run_path('scripts/source_snapshot.py')['read_archive']
    baseline = root / '.cache/source-cancel-r102-baseline.tar.gz'
    fixed = root / '.cache/source-cancel-r102-fixed.tar.gz'
    before = read(baseline)[0]['files']
    manifest = read(fixed)[0]['files']
    assert sorted(name for name in manifest if manifest[name] != before[name]) == ['tests/ui_tests.cpp']
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == collection['baselineSnapshotSha256']
    assert hashlib.sha256(fixed.read_bytes()).hexdigest() == collection['fixedSnapshotSha256']
    inputs = json.loads((root / 'docs/ci-verification-20261107-r102.json').read_text('utf-8'))['buildInputs']
    assert len(inputs) == 210
    for row in inputs:
        raw = subprocess.check_output(['git', 'show', 'c1325b0b33ff4df116449c1e1c00d5b27a1a125c:' + row['path']], cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256'] == manifest[row['path']]['sha256']
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': True,
        'sourceCommit': 'c1325b0b33ff4df116449c1e1c00d5b27a1a125c', 'buildInputsVerified': 210,
        'originalCoreTargets': 23, 'originalQtReports': [proof(path) for path in xmls],
        'nativeNavigation': proof(folder / 'results/native-navigation.json'),
        'oldFixtureSendCasesPassed': 3, 'oldFailureReproduced': False,
        'fixedRepeatedCancellationRounds': 10, 'fixedRepeatedCancellationRows': 30,
        'nativeAndHighDpiCancellationRows': 9, 'cancellationAndEofBudgetMilliseconds': 5000,
        'binarySha256': driver['binarySha256'], 'binaryUnchanged': True,
        'productionCoreChanged': False, 'intermittentFailureRootCauseProved': False,
        'releaseQualified': False, 'deliveryComplete': False}
    target = folder / 'verified-receipt.json'
    assert not target.exists()
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), folder / 'verification-driver.py')
    print(json.dumps({'passed': True, 'coreTargets': 23, 'repeatedCancellationRows': 30, 'oldFailureReproduced': False}))


if __name__ == '__main__':
    main()

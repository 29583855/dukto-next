"""日期：2026-11-07；严格核验原QML缺陷、双Windows修正结果与全部维护源码审计。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；只核验实际相关四目标，十九个原完整回归二进制必须逐SHA一致，拒绝未知或跳过结果。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    original = root / 'docs/validation/2026-11-07/clipboard-r100-baseline'
    final = root / 'docs/validation/2026-11-07/clipboard-r100-windows'
    output = root / 'docs/validation/2026-11-07/clipboard-r100-qualified'
    output.mkdir(exist_ok=False)
    baseline = json.loads((original / 'driver-result.json').read_text('utf-8'))
    assert baseline['buildExitCode'] == 0 and baseline['testExitCode'] == 1
    old_log = (original / 'qt.log').read_text('utf-8')
    assert 'FAIL!  : UiTests::clipboardAvailabilityDoesNotReadOnProgress() Compared values are not the same' in old_log
    counts = re.search(r'Actual\s+\(\*reads\):\s*(\d+)\s+Expected\s+\(before\):\s*(\d+)', old_log)
    assert counts and int(counts[1]) - int(counts[2]) == 100
    assert '0 skipped' in old_log
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    for name in ('src/app/controller.cpp', 'src/app/controller.h'):
        frozen = (root / '.cache/clipboard-r100-before' / name).read_bytes()
        assert subprocess.check_output(['git', 'show', 'a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38:' + name], cwd=checkout) == frozen
        row, = [row for row in baseline['sourceFiles'] if row['path'] == name]
        assert hashlib.sha256(frozen).hexdigest() == row['sha256']
    driver = json.loads((final / 'driver-result.json').read_text('utf-8'))
    assert driver['passed'] and driver['buildInputsUnchanged'] and len(driver['cases']) == 2
    inputs = json.loads((final / 'build-inputs.json').read_text('utf-8'))
    assert len(inputs) == 210
    for row in inputs:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    encoding = []
    for row in json.loads((root / '.cache/clipboard-r100-before/source-before.json').read_text('utf-8')):
        raw = (root / row['path']).read_bytes()
        raw.decode('utf-8-sig')
        assert raw.startswith(b'\xef\xbb\xbf') == row['utf8Bom'] and (b'\r\n' in raw) == row['crlf']
        if row['crlf']:
            assert b'\n' not in raw.replace(b'\r\n', b'')
        encoding.append({'path': row['path'], 'bomPreserved': True, 'lineEndingPreserved': True})
    cases = []
    for label in ('ucrt', 'msvc'):
        row, = [item for item in driver['cases'] if item['toolchain'] == label]
        assert row['buildExitCode'] == row['ctestExitCode'] == 0 and len(row['unchangedCoreTestBinaries']) == 19
        text = (final / label / 'ctest.log').read_text('utf-8')
        assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 4$', text, re.M)
        reports = sorted((final / label / 'QtTest').glob('*.xml'))
        assert len(reports) == 4
        for path in reports:
            tree = ET.parse(path)
            assert not tree.findall('.//failure') and not tree.findall('.//error')
            assert all(case.get('result') == 'pass' for case in tree.findall('.//testcase'))
        text = (final / label / 'QtTest/ui-tests.log').read_text('utf-8')
        for method in ('clipboardAvailabilityDoesNotReadOnProgress', 'rejectedTextKeepsDraftThroughQml', 'dragClipboardAndTextThroughQml'):
            assert 'PASS   : UiTests::' + method + '()' in text
        assert not any(line.startswith(('FAIL!  :', 'XPASS  :', 'XFAIL  :', 'QFATAL :')) for line in text.splitlines())
        cases.append({'toolchain': label, 'guiTargets': 4, 'otherCoreTestBinariesUnchanged': 19,
                      'progressNotificationsWithoutBodyRequests': 100, 'emptyDisabled': True,
                      'latestBodySentAndVerified': True, 'explicitSendAddsOneBodyRequest': True,
                      'reports': [helper['proof'](path) for path in reports]})
    subprocess.run(['python', '-X', 'utf8', 'scripts/audit.py', '--report', str(output / 'source-audit.json')], check=True)
    audit = json.loads((output / 'source-audit.json').read_text('utf-8'))
    assert len(audit['files']) == 204 and not audit['findings'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'basedOnSourceCommit': 'a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38',
             'buildInputs': inputs, 'changedBuildInputs': driver['changedBuildInputs'], 'windows': cases,
             'originalProductFailure': helper['proof'](original / 'qt.log'),
             'originalBodyRequestsBefore': int(counts[2]), 'originalBodyRequestsAfter': int(counts[1]),
             'encoding': encoding, 'sourceAudit': helper['proof'](output / 'source-audit.json'),
             'passed': True, 'incrementalBuild': True, 'freshFull23TargetsRun': False,
             'fullEditorAndSystemClipboardBudgetQualified': False,
             'nativeMacLinuxR100Qualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'verified-receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    for name in ('prepare-clipboard-r100-baseline.py', 'implement-clipboard-r100-cache.py', 'verify-clipboard-r100-windows.py'):
        shutil.copyfile(root / '.cache' / name, output / name)
    for name in ('src/app/controller.cpp', 'src/app/controller.h'):
        target = output / 'original-inputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / '.cache/clipboard-r100-before' / name, target)
    print(json.dumps({'windowsToolchainsQualified': 2, 'relatedGuiTargetsEach': 4,
                      'unchangedCoreBinariesEach': 19, 'progressBodyRequestsPreventedEach': 100,
                      'allMaintenanceFiles': 204, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()

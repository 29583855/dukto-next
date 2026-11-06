"""日期：2026-11-07；逐原件核验双Windows兼容取消、恢复、原生/高DPI及原编码，保留所有初次失败。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；只授予原件覆盖的Windows子项，共用核心必须与公开R100逐字节相同。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    proof = helper['proof']
    output = root / 'docs/validation/2026-11-07/cancel-r101-qualified'
    output.mkdir(exist_ok=True)
    assert not (output / 'verified-receipt.json').exists()
    baseline = root / 'docs/validation/2026-11-07/cancel-r101-windows'
    initial = json.loads((baseline / 'driver-result.json').read_text('utf-8'))
    assert not initial['passed'] and initial['buildInputsUnchanged'] and len(initial['cases']) == 2
    for row in initial['cases']:
        assert row['buildExitCode'] == 0 and row['ctestExitCode'] == 8
        text = (baseline / row['toolchain'] / 'QtTest/ui-tests.log').read_text('utf-8-sig')
        assert "'(controller.progress() > 0)' returned FALSE" in text
    diagnosis = json.loads((baseline / 'diagnosis-correction.json').read_text('utf-8'))
    assert diagnosis['existingListenerReportsReceiveBeforeStartingWorker']
    assert not diagnosis['productCancellationBugConfirmed']
    for row in diagnosis['restoredCoreFiles']:
        raw = subprocess.check_output(['git', 'show', 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3:' + row['path']], cwd=checkout)
        assert raw == (root / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['restoredSha256']
    final = root / 'docs/validation/2026-11-07/cancel-r101-final-windows'
    driver = json.loads((final / 'driver-result.json').read_text('utf-8'))
    assert driver['passed'] and driver['buildInputsUnchanged'] and len(driver['cases']) == 2
    inputs = json.loads((final / 'build-inputs.json').read_text('utf-8'))
    assert len(inputs) == 210
    for row in inputs:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    encoding = []
    for row in json.loads((root / '.cache/cancel-r101-before/source-before.json').read_text('utf-8')):
        data = (root / row['path']).read_bytes()
        data.decode('utf-8-sig')
        assert data.startswith(b'\xef\xbb\xbf') == row['utf8Bom'] and (b'\r\n' in data) == row['crlf']
        if row['crlf']:
            assert b'\n' not in data.replace(b'\r\n', b'')
        encoding.append({'path': row['path'], 'bomPreserved': True, 'newlinesPreserved': True})
    cases = []
    for label in ('ucrt', 'msvc'):
        row, = [item for item in driver['cases'] if item['toolchain'] == label]
        assert row['buildExitCode'] == row['ctestExitCode'] == row['nativeNavigationExitCode'] == 0
        directory = final / label
        text = (directory / 'ctest.log').read_text('utf-8-sig')
        assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$', text, re.M)
        reports = sorted((directory / 'QtTest').glob('*.xml'))
        assert len(reports) == 22
        messages = []
        for path in reports:
            suite = ET.parse(path).getroot()
            assert suite.tag == 'testsuite' and suite.attrib['failures'] == '0'
            assert not suite.findall('.//failure') and not suite.findall('.//error')
            assert all(item.attrib['result'] == 'pass' for item in suite.findall('testcase'))
            # 日期：2026-11-07；Qt JUnit把已知qinfo/qwarn也计入errors，逐原注释限定类型/数量，不能吞未知失败。
            parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
            annotated = ET.fromstring(path.read_bytes(), parser=parser)
            comments = [element.text for element in annotated.iter() if element.tag is ET.Comment]
            assert int(suite.attrib['errors']) == len(comments)
            if path.name == 'file-exchange-tests.xml':
                assert len(comments) == 64
                assert all('type="qinfo"' in text and 'message="terminal fixture ' in text for text in comments)
                messages.append({'file': path.name, 'qtJunitErrorsCounter': 64,
                                 'actualMessageType': 'qinfo', 'terminalFixtureMessages': 64,
                                 'testFailuresOrErrorNodes': 0})
            elif path.name == 'avatars-tests.xml':
                assert len(comments) == 1
                assert comments[0].strip() == 'message="QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once." type="qwarn"'
                messages.append({'file': path.name, 'qtJunitErrorsCounter': 1,
                                 'actualMessageType': 'qwarn', 'knownAvatarReplyWarningCount': 1,
                                 'testFailuresOrErrorNodes': 0})
            else:
                assert not comments
        navigation_path = directory / 'native-navigation.json'
        navigation = json.loads(navigation_path.read_text('utf-8'))
        assert navigation['passed'] and navigation['binaryUnchanged'] and len(navigation['cases']) == 3
        assert [item['platform'] for item in navigation['cases']] == ['windows', 'offscreen', 'offscreen']
        assert navigation['cases'][0]['nativeSelectorGuard'] == {'exitCode': 2, 'passed': True}
        for scene in navigation['cases']:
            assert scene['passed'] and scene['verifiedCancellationRows'] == ['send', 'receive-header', 'receive-partial']
            qt_log = directory / 'native-navigation' / scene['name'] / 'qt-test.log'
            text = qt_log.read_text('utf-8-sig')
            for tag in scene['verifiedCancellationRows']:
                assert text.splitlines().count('PASS   : UiTests::cancelThenTransferAgainThroughQml(' + tag + ')') == 1
            assert not any(line.startswith(('FAIL!', 'XPASS', 'XFAIL', 'SKIP', 'QFATAL', 'QWARN')) for line in text.splitlines())
        cases.append({'toolchain': label, 'coreTargets': 23,
                      'xmlReports': [proof(path) for path in reports], 'ctest': proof(directory / 'ctest.log'),
                      'nativeAndHighDpiCancellationScenes': 3, 'cancellationRowsPerScene': 3,
                      'sameControllerLaterBidirectionalContentVerifiedPerRow': True,
                      'nativeSelectorRejectsClipboardSlotsBeforeExecution': True,
                      'explicitQtJunitMessageCounters': messages,
                      'navigation': proof(navigation_path)})
    audit_path = root / 'docs/validation/2026-11-07/cancel-r101-final-audit.json'
    audit = json.loads(audit_path.read_text('utf-8'))
    assert len(audit['files']) == 204 and not audit['findings'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    shutil.copyfile(audit_path, output / 'source-audit.json')
    (output / 'initial-verifier-failure.json').write_text(json.dumps({
        'date': '2026-11-07', 'exitCode': 1,
        'stage': 'Report interpretation after both Windows drivers completed successfully',
        'reason': 'Initial verifier treated Qt JUnit errors attribute as actual failure count; Qt counts qinfo/qwarn messages there',
        'correction': 'Require no failure/error nodes, all testcase results pass, and exact known message types/counts per report; native cancellation reports still require zero messages',
        'initialDriver': proof(output / 'initial-verification-driver.py'),
        'testsRepeatedByCorrection': False, 'unknownFailuresAccepted': False}, indent=2) + '\n', 'utf-8')
    value = {'date': '2026-11-07', 'observedUtc': datetime.now(timezone.utc).isoformat(),
             'basedOnSourceCommit': 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3',
             'buildInputs': inputs, 'changedBuildInputs': driver['changedBuildInputs'], 'windows': cases,
             'originalIncorrectAssertionFailure': proof(baseline / 'driver-result.json'),
             'diagnosisCorrection': proof(baseline / 'diagnosis-correction.json'),
             'originalTransferCoreUnchanged': True, 'productionCancellationBugFixClaimed': False,
             'originalR6AfterAbortCrashNotCopied': True, 'encoding': encoding,
             'sourceAudit': proof(output / 'source-audit.json'), 'passed': True,
             'freshFull23TargetsRun': True, 'cleanBuild': False,
             'nativeMacLinuxR101Qualified': False, 'wholeF18Qualified': False,
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'verified-receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    for name in ('prepare-cancel-r101-qml-regression.py', 'correct-cancel-r101-diagnosis.py',
                 'add-cancel-r101-native-navigation.py', 'verify-cancel-r101-windows.py'):
        shutil.copyfile(root / '.cache' / name, output / name)
    print(json.dumps({'toolchains': 2, 'coreTargetsEach': 23, 'cancellationScenesTotal': 6,
                      'cancellationRowsTotal': 18, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()

"""日期：2026-11-07；严格收验双Windows诊断、夹具修正及不变核心原报告。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；Qt消息逐类核对，不把聚合errors消息数当作失败，也不忽略真实失败节点。
def verify_xml(path):
    suite = ET.fromstring(path.read_bytes(), parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    assert suite.get('failures') == '0' and not suite.findall('.//failure') and not suite.findall('.//error')
    assert all(case.get('result') == 'pass' for case in suite.findall('testcase'))
    comments = [item.text for item in suite.iter() if item.tag is ET.Comment]
    assert int(suite.get('errors')) == len(comments)
    if path.name == 'file-exchange-tests.xml':
        assert len(comments) == 64 and all('type="qinfo"' in text and 'message="terminal fixture ' in text for text in comments)
    elif path.name == 'avatars-tests.xml':
        assert len(comments) <= 1 and all(text.strip() == 'message="QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once." type="qwarn"' for text in comments)
    else:
        assert not comments, (path, comments)


# 日期：2026-11-07；实际退出、修正前失败、二进制与输入身份逐一绑定，零标记不代表全部交付完成。
def main():
    root = Path.cwd()
    first = root / 'docs/validation/2026-11-07/diagnostics-r103-windows'
    second = root / 'docs/validation/2026-11-07/diagnostics-r103-recheck'
    original = json.loads((first / 'driver-result.json').read_text('utf-8'))
    recheck = json.loads((second / 'driver-result.json').read_text('utf-8'))
    assert not original['passed'] and original['buildInputsUnchanged']
    assert recheck['passed'] and recheck['buildInputsUnchanged'] and not recheck['freshFull23TargetsRerun']
    assert len(original['cases']) == len(recheck['cases']) == 2
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    windows = []
    for label, folder in [('ucrt', 'windows-ucrt'), ('msvc', 'windows/Release')]:
        a, = [row for row in original['cases'] if row['toolchain'] == label]
        b, = [row for row in recheck['cases'] if row['toolchain'] == label]
        assert a['ctestExitCode'] == 8 and a['buildExitCode'] == a['doctorExitCode'] == a['cliContractsExitCode'] == 0
        assert b['passed'] and b['ctestExitCode'] == b['buildExitCode'] == b['doctorExitCode'] == b['cli-contractsExitCode'] == b['doctorHumanExitCode'] == 0
        assert re.search(r'^96% tests passed, 1 tests failed out of 23$', (first / label / 'ctest.log').read_text('utf-8-sig'), re.M)
        initial_ui = ET.parse(first / label / 'QtTest/ui-tests.xml').getroot()
        bad = [case for case in initial_ui.findall('testcase') if case.get('result') != 'pass']
        assert len(bad) == 1 and bad[0].get('name') == 'localDiagnosticExport'
        xmls = sorted((first / label / 'QtTest').glob('*.xml'))
        assert len(xmls) == 22
        for path in xmls:
            if path.name != 'ui-tests.xml':
                verify_xml(path)
        assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 2$', (second / label / 'ctest.log').read_text('utf-8-sig'), re.M)
        for path in (second / label / 'QtTest').glob('*.xml'):
            verify_xml(path)
        ui = (second / label / 'QtTest/ui-tests.log').read_text('utf-8-sig').splitlines()
        assert ui.count('PASS   : UiTests::localDiagnosticExport()') == 1
        core = (first / label / 'QtTest/core-tests.log').read_text('utf-8-sig').splitlines()
        for name in ('diagnosticBoundedConfiguration', 'diagnosticPortAndDirectoryFailures', 'diagnosticAtomicExport'):
            assert core.count('PASS   : CoreTests::' + name + '()') == 1
        binaries = json.loads((root / 'docs/validation/2026-11-07/diagnostics-r103-correction/previous-test-binaries.json').read_text('utf-8'))[label]
        changed = sorted(name for name, digest in binaries.items() if digest != b['testBinarySha256'][name])
        assert changed == ['server-panel-tests.exe', 'ui-tests.exe'] and b['twentyOtherQtTestBinariesUnchanged']
        for name, digest in b['testBinarySha256'].items():
            assert hashlib.sha256((root / 'build' / folder / name).read_bytes()).hexdigest() == digest
        for name in ('doctor', 'cli-contracts'):
            report = json.loads((second / label / (name + '.json')).read_text('utf-8'))
            assert report['passed']
        doctor = json.loads((second / label / 'doctor.json').read_text('utf-8'))
        assert doctor['binaryUnchanged'] and len(doctor['checks']) == 12
        assert not doctor['entireR10Qualified'] and not doctor['nativeSaveDialogVerified']
        windows.append({'toolchain': label, 'initialFull23TargetsExecuted': True,
            'originalUIFixtureFailureRetained': True, 'recheckedQmlTargets': 2,
            'otherQtTestBinariesUnchanged': 20, 'doctor': proof(second / label / 'doctor.json'),
            'cliContracts': proof(second / label / 'cli-contracts.json'),
            'coreQtReports': [proof(path) for path in xmls if path.name not in ('ui-tests.xml', 'server-panel-tests.xml')],
            'recheckedQtReports': [proof(path) for path in (second / label / 'QtTest').glob('*.xml')]})
    inputs = json.loads((second / 'build-inputs.json').read_text('utf-8'))
    assert len(inputs) == 213
    for row in inputs:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    backup = root / '.cache/diagnostics-r103-originals'
    encoding = []
    for path in backup.rglob('*'):
        if not path.is_file():
            continue
        name = path.relative_to(backup)
        a, b = path.read_bytes(), (root / name).read_bytes()
        a.decode('utf-8-sig')
        b.decode('utf-8-sig')
        assert a.startswith(b'\xef\xbb\xbf') == b.startswith(b'\xef\xbb\xbf')
        assert (b'\r\n' in a) == (b'\r\n' in b)
        assert b'\n' not in b.replace(b'\r\n', b'') if b'\r\n' in a else b'\r' not in b
        encoding.append(name.as_posix())
    audit_path = root / 'docs/validation/2026-11-07/diagnostics-r103-source-audit.json'
    assert not audit_path.exists()
    subprocess.run(['python', '-X', 'utf8', 'scripts/audit.py', '--report', str(audit_path)], check=True)
    audit = json.loads(audit_path.read_text('utf-8'))
    assert len(audit['files']) == 207 and not audit['findings'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    output = root / 'docs/validation/2026-11-07/diagnostics-r103-qualified'
    output.mkdir(exist_ok=False)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': True,
        'basedOnPublishedCommit': '91a968b8637de5fa00ac3a2af6c4096299a651ca', 'buildInputs': inputs,
        'windows': windows, 'freshFull23TargetsRerunAfterCorrection': False,
        'encodingAndLineEndingsPreserved': encoding, 'sourceAudit': proof(audit_path),
        'explicitIniMaximumBytes': 65536, 'maximumJsonReportBytes': 65536,
        'guiAndCliShareProductionDiagnosticCore': True,
        'nativeSaveDialogVerified': False, 'macLinuxR103RuntimeVerified': False,
        'entireR10Qualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'verified-receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'windowsToolchains': 2, 'buildInputs': 213, 'sourceMarkers': 0, 'passed': True}))


if __name__ == '__main__':
    main()

"""日期：2026-11-07；独立收验R100四平台核心原件，完整协议运行结论仍等待真实终态。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
RUN = 42282812778


# 日期：2026-11-07；原23目标及精确Darwin预期失败保持原门槛，新增剪贴板方法必须实际通过且只有一条PASS。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/clipboard-r100-native-core'
    assert not (output / 'receipt.json').exists()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    focused = runpy.run_path('.cache/collect-r96-native-regression.py')
    verify_core = runpy.run_path('.cache/collect-r96-complete-native.py')['verify_core']
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    assert run['head_sha'] == COMMIT and len(jobs) == 4
    for job in jobs:
        for name in ('Compile', 'Core and GUI controller tests', 'Preserve core diagnostics before protocol suite'):
            step, = [row for row in job['steps'] if row['name'] == name]
            assert step['status'] == 'completed' and step['conclusion'] == 'success'
    runners = ('windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel')
    selected = [row for row in artifacts if row['name'].startswith('core-validation-')]
    assert {row['name'] for row in selected} == {'core-validation-' + runner for runner in runners}
    output.mkdir(exist_ok=True)
    records, cores, checks = [], [], []
    for item in selected:
        archive = output / (item['name'] + '.zip')
        raw = archive.read_bytes() if archive.exists() else request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        sha = hashlib.sha256(raw).hexdigest()
        assert not item['expired'] and item['digest'] == 'sha256:' + sha
        if not archive.exists():
            archive.write_bytes(raw)
        folder = output / item['name']
        if not folder.exists():
            helper['extract'](raw, folder)
        records.append({'id': item['id'], 'name': item['name'], 'sha256': sha})
        cores.append(verify_core(folder.relative_to(root), helper, focused))
        ui = ET.parse(folder / 'Testing/QtTest/ui-tests.xml')
        names = ('clipboardAvailabilityDoesNotReadOnProgress', 'rejectedTextKeepsDraftThroughQml',
                 'dragClipboardAndTextThroughQml')
        log = (folder / 'Testing/QtTest/ui-tests.log').read_text('utf-8').splitlines()
        for name in names:
            case, = [row for row in ui.findall('.//testcase') if row.get('name') == name]
            assert case.get('result') == 'pass'
            assert log.count('PASS   : UiTests::' + name + '()') == 1
        controller = (folder / 'Testing/QtTest/controller-tests.log').read_text('utf-8').splitlines()
        tags = ('empty', 'maximum-ascii', 'maximum-chinese', 'maximum-surrogate-pair',
                'isolated-surrogates', 'ascii-one-byte-over', 'chinese-one-byte-over',
                'large-input-before-conversion')
        actual = [line for line in controller if line.startswith('PASS   : ControllerTests::outgoingTextBounds(')]
        assert actual == ['PASS   : ControllerTests::outgoingTextBounds(' + tag + ')' for tag in tags]
        checks.append({'runner': item['name'], 'guiMethodsVerified': list(names),
                       'outgoingTextEncodingRowsVerified': 8})
    expected = sum(len(row['expectedFailures']) for row in cores)
    assert expected == 2
    manifest = json.loads((root / 'docs/ci-verification-20261107-r100.json').read_text('utf-8'))
    assert len(manifest['buildInputs']) == 210
    for row in manifest['buildInputs']:
        raw = subprocess.check_output(['git', 'show', COMMIT + ':' + row['path']],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
             'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'jobs': [{k: job[k] for k in ('id', 'name', 'status', 'conclusion', 'steps')} for job in jobs],
             'artifacts': records, 'cores': cores, 'clipboardAndTextChecks': checks,
             'coreTargetsEach': 23, 'originalQtReportsVerified': 88, 'buildInputsVerified': 210,
             'explicitDarwinExpectedFailureCount': expected,
             'fullNativeProtocolRegressionQualified': False,
             'fullEditorAndSystemClipboardBudgetQualified': False,
             'kernelExternalPortExclusivityQualified': False, 'releaseQualified': False,
             'deliveryComplete': False, 'passed': True}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    for name in ('collect-r96-complete-native.py', 'collect-r96-native-regression.py', 'collect-exact-native-r87.py'):
        shutil.copyfile(root / '.cache' / name, output / ('source-' + name))
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': COMMIT, 'runners': 4, 'coreTargetsEach': 23,
                      'qtReportsVerified': 88, 'clipboardAndDraftQmlVerified': True,
                      'explicitDarwinExpectedFailures': expected, 'fullProtocolQualified': False}), flush=True)


if __name__ == '__main__':
    main()

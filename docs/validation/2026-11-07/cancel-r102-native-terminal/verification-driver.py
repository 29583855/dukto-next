"""日期：2026-11-07；严格收验R102完整终态，核心、协议、原生负例及取消行分别核对。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET

COMMIT = 'c1325b0b33ff4df116449c1e1c00d5b27a1a125c'
RUN = 42304553041


# 日期：2026-11-07；必须真实终态及全部原附件齐全，失败先保存原观察，绝不放宽原测试门槛。
def main():
    root = Path.cwd()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    verify_core = runpy.run_path('.cache/collect-r96-complete-native.py')['verify_core']
    focused = runpy.run_path('.cache/collect-r96-native-regression.py')
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    assert run['head_sha'] == COMMIT and run['status'] == 'completed' and run['run_attempt'] == 1
    assert len(jobs) == 4 and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    runners = ('windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel')
    selected = [row for row in artifacts if row['name'].startswith(('core-validation-', 'validation-'))]
    assert {row['name'] for row in selected} == {prefix + runner for prefix in ('core-validation-', 'validation-') for runner in runners}
    output = root / 'docs/validation/2026-11-07/cancel-r102-native-terminal'
    output.mkdir(exist_ok=True)
    assert not (output / 'receipt.json').exists()
    records = []
    for item in selected:
        archive = output / (item['name'] + '.zip')
        old = root / 'docs/validation/2026-11-07/cancel-r102-native-core' / archive.name
        raw = archive.read_bytes() if archive.exists() else old.read_bytes() if old.exists() else request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert not item['expired'] and item['digest'] == 'sha256:' + digest
        if not archive.exists():
            archive.write_bytes(raw)
        folder = output / item['name']
        if not folder.exists():
            helper['extract'](raw, folder)
        records.append({'id': item['id'], 'name': item['name'], 'sha256': digest})
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
        'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'run_attempt', 'html_url')},
        'jobs': [{key: job[key] for key in ('id', 'name', 'status', 'conclusion', 'steps')} for job in jobs],
        'artifacts': records, 'allArtifactDigestsVerified': True, 'qualificationPending': True,
        'releaseQualified': False, 'deliveryComplete': False}
    path = output / 'terminal-artifact-observation.json'
    if not path.exists():
        path.write_text(json.dumps(observation, indent=2) + '\n', 'utf-8')
    assert run['conclusion'] == 'success' and all(job['conclusion'] == 'success' for job in jobs), 'Original terminal failure retained; no qualification'
    cores, extra, cancellation_rows = [], [], 0
    for runner in runners:
        core = output / ('core-validation-' + runner)
        cores.append(verify_core(core.relative_to(root), helper, focused))
        ui = ET.parse(core / 'Testing/QtTest/ui-tests.xml')
        log = (core / 'Testing/QtTest/ui-tests.log').read_text('utf-8').splitlines()
        for name in ('clipboardAvailabilityDoesNotReadOnProgress', 'rejectedTextKeepsDraftThroughQml', 'dragClipboardAndTextThroughQml', 'cancelThenTransferAgainThroughQml'):
            case, = [case for case in ui.findall('.//testcase') if case.get('name') == name]
            assert case.get('result') == 'pass'
        for phase in ('send', 'receive-header', 'receive-partial'):
            assert log.count('PASS   : UiTests::cancelThenTransferAgainThroughQml(' + phase + ')') == 1
            cancellation_rows += 1
        folder = output / ('validation-' + runner)
        navigation_path = folder / 'build/main-window-navigation.json'
        navigation = json.loads(navigation_path.read_text('utf-8'))
        assert navigation['passed'] and navigation['sourceCommit'] == COMMIT and navigation['binaryUnchanged']
        helper['verify_passed'](navigation)
        assert len(navigation['cases']) == 3 and navigation['cases'][0]['nativeSelectorGuard'] == {'exitCode': 2, 'passed': True}
        for scene in navigation['cases']:
            assert scene['passed'] and scene['verifiedCancellationRows'] == ['send', 'receive-header', 'receive-partial']
            cancellation_rows += 3
        paths = [navigation_path, folder / 'proxy-pacing.json']
        if runner.startswith('macos-'):
            paths += [folder / 'build/macos-native-render.json', folder / 'build/macos-native-process-recovery.json']
        if runner == 'ubuntu-22.04':
            paths += [folder / 'build/disk.json', folder / 'build/parallel-disk.json']
        for path in paths:
            value = json.loads(path.read_text('utf-8'))
            assert value['passed']
            helper['verify_passed'](value)
            extra.append(helper['proof'](path.relative_to(root)))
    assert cancellation_rows == 48 and sum(len(row['expectedFailures']) for row in cores) == 2
    suites = [helper['protocol'](path.relative_to(root), COMMIT) for path in output.rglob('protocol-suite.json')]
    assert len(suites) == 4 and sum(row['cases'] for row in suites) == 188
    manifest = json.loads((root / 'docs/ci-verification-20261107-r102.json').read_text('utf-8'))
    assert len(manifest['buildInputs']) == 210
    for row in manifest['buildInputs']:
        raw = subprocess.check_output(['git', 'show', COMMIT + ':' + row['path']], cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    receipt = dict(observation, qualificationPending=False, cores=cores, protocolSuites=suites,
        additionalBusinessReports=extra, verifiedCoreTargetsEach=23, verifiedProtocolReports=188,
        verifiedCancellationRows=48, nativeSelectorNegativeGuardsVerified=4,
        explicitDarwinExpectedFailures=2, originalR101FailureRetained=True,
        productCancellationBugFixClaimed=False, entireF18Qualified=False,
        allOriginalCoreAndProtocolReportsVerified=True)
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': COMMIT, 'coreTargetsEach': 23, 'protocolReports': 188, 'cancellationRows': 48, 'passed': True}))


if __name__ == '__main__':
    main()

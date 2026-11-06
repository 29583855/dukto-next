"""日期：2026-11-07；精确收验R100四平台原件，保留终态失败并逐条核对Darwin边界。"""
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


# 日期：2026-11-07；已有下载只按同摘要复用，报告不覆盖，任何未知失败或缺件均保留后停止。
def main():
    root = Path.cwd()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    previous = runpy.run_path('.cache/collect-r96-complete-native.py')
    focused = runpy.run_path('.cache/collect-r96-native-regression.py')
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    assert run['head_sha'] == COMMIT and run['status'] == 'completed'
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    assert len(jobs) == 4 and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    output = root / 'docs/validation/2026-11-07/clipboard-r100-native-terminal'
    output.mkdir(parents=True, exist_ok=True)
    assert not (output / 'receipt.json').exists()
    records = []
    for item in artifacts:
        if item['name'].startswith('macos-compiled-'):
            continue
        archive = output / (item['name'] + '.zip')
        raw = archive.read_bytes() if archive.exists() else request(
            base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest and not item['expired']
        if not archive.exists():
            archive.write_bytes(raw)
        folder = output / item['name']
        if not folder.exists():
            helper['extract'](raw, folder)
        records.append({'id': item['id'], 'name': item['name'], 'sha256': digest})
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
                   'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url', 'run_attempt')},
                   'jobs': [{k: job[k] for k in ('id', 'name', 'status', 'conclusion', 'steps')} for job in jobs],
                   'artifacts': records, 'allArtifactDigestsVerified': True,
                   'qualificationPending': True, 'releaseQualified': False, 'deliveryComplete': False}
    observation_path = output / 'terminal-artifact-observation.json'
    if not observation_path.exists():
        observation_path.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    assert run['conclusion'] == 'success' and all(job['conclusion'] == 'success' for job in jobs), \
        'Original terminal failure preserved; inspect without relaxing qualification'
    runners = ('windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel')
    assert {row['name'] for row in records} == {
        prefix + runner for prefix in ('core-validation-', 'validation-') for runner in runners}
    cores = []
    text_rows = []
    extra = []
    for runner in runners:
        core_dir = output / ('core-validation-' + runner)
        cores.append(previous['verify_core'](core_dir.relative_to(root), helper, focused))
        controller = ET.parse(core_dir / 'Testing/QtTest/controller-tests.xml')
        rows = [case for case in controller.findall('.//testcase') if case.get('name') == 'outgoingTextBounds']
        assert len(rows) == 1 and rows[0].get('result') == 'pass'
        log = (core_dir / 'Testing/QtTest/controller-tests.log').read_text('utf-8')
        tags = ('empty', 'maximum-ascii', 'maximum-chinese', 'maximum-surrogate-pair',
                'isolated-surrogates', 'ascii-one-byte-over', 'chinese-one-byte-over',
                'large-input-before-conversion')
        actual = [line for line in log.splitlines() if line.startswith('PASS   : ControllerTests::outgoingTextBounds(')]
        assert actual == ['PASS   : ControllerTests::outgoingTextBounds(' + tag + ')' for tag in tags]
        ui = ET.parse(core_dir / 'Testing/QtTest/ui-tests.xml')
        drafts = [case for case in ui.findall('.//testcase') if case.get('name') == 'rejectedTextKeepsDraftThroughQml']
        assert len(drafts) == 1 and drafts[0].get('result') == 'pass'
        clipboard = [case for case in ui.findall('.//testcase')
                     if case.get('name') == 'clipboardAvailabilityDoesNotReadOnProgress']
        assert len(clipboard) == 1 and clipboard[0].get('result') == 'pass'
        ui_log = (core_dir / 'Testing/QtTest/ui-tests.log').read_text('utf-8')
        assert ui_log.splitlines().count('PASS   : UiTests::clipboardAvailabilityDoesNotReadOnProgress()') == 1
        text_rows.append({'runner': runner, 'encodingRows': 8, 'draftRecovery': True,
                          'clipboardAvailabilityThroughProductionQml': True})
        folder = output / ('validation-' + runner)
        navigation = folder / 'build/main-window-navigation.json'
        value = json.loads(navigation.read_text('utf-8'))
        helper['verify_passed'](value)
        assert value['passed'] and value['sourceCommit'] == COMMIT and value['binaryUnchanged']
        paths = [navigation, folder / 'proxy-pacing.json']
        if runner.startswith('macos-'):
            paths += [folder / 'build/macos-native-render.json', folder / 'build/macos-native-process-recovery.json']
        if runner == 'ubuntu-22.04':
            paths += [folder / 'build/disk.json', folder / 'build/parallel-disk.json']
        for path in paths:
            value = json.loads(path.read_text('utf-8'))
            assert value['passed']
            helper['verify_passed'](value)
            extra.append(helper['proof'](path.relative_to(root)))
    suites = [helper['protocol'](path.relative_to(root), COMMIT) for path in output.rglob('protocol-suite.json')]
    assert len(suites) == 4 and sum(row['cases'] for row in suites) == 188
    expected = sum(len(row['expectedFailures']) for row in cores)
    assert expected == 2
    current = json.loads((root / 'docs/ci-verification-20261107-r100.json').read_text('utf-8'))
    assert len(current['buildInputs']) == 210
    for row in current['buildInputs']:
        raw = subprocess.check_output(['git', 'show', COMMIT + ':' + row['path']],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    receipt = dict(observation, qualificationPending=False, cores=cores, protocolSuites=suites,
                   textSendChecks=text_rows, additionalBusinessReports=extra,
                   allOriginalCoreAndProtocolReportsVerified=True, buildInputsVerified=210,
                   coreTargetsEach=23, protocolReports=188, explicitDarwinExpectedFailureCount=2,
                   allUnknownOrSkippedResultsRejected=True, kernelExternalPortExclusivityQualified=False)
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    for name in ('collect-r96-complete-native.py', 'collect-r96-native-regression.py', 'collect-exact-native-r87.py'):
        shutil.copyfile(root / '.cache' / name, output / ('source-' + name))
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': COMMIT, 'runners': 4, 'coreTargetsEach': 23,
                      'protocolReports': 188, 'explicitDarwinExpectedFailures': expected, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()

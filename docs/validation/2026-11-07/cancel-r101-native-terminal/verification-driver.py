"""日期：2026-11-07；保全R101真实终态失败，协议子集只能按独立原报告授予资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET

COMMIT = '1f82d5d3b9ae36e77ee98da942c2fc5369310c7a'
RUN = 42300792120


# 日期：2026-11-07；先保存官方摘要、原报告及全部失败步骤，再逐份核验协议；未知失败不改写成通过。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/cancel-r101-native-terminal'
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    assert run['head_sha'] == COMMIT and run['status'] == 'completed' and run['run_attempt'] == 1
    assert len(jobs) == 4 and all(job['status'] == 'completed' for job in jobs)
    assert run['conclusion'] == 'failure'
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    runners = ('windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel')
    selected = [item for item in artifacts if item['name'].startswith('validation-')]
    assert {item['name'] for item in selected} == {'validation-' + runner for runner in runners}
    output.mkdir(exist_ok=True)
    assert not (output / 'verified-subsets.json').exists()
    records, observations = [], []
    for item in selected:
        archive = output / (item['name'] + '.zip')
        raw = archive.read_bytes() if archive.exists() else request(
            base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert not item['expired'] and item['digest'] == 'sha256:' + digest
        if not archive.exists():
            archive.write_bytes(raw)
        folder = output / item['name']
        if not folder.exists():
            helper['extract'](raw, folder)
        records.append({'id': item['id'], 'name': item['name'], 'sha256': digest})
        failures = []
        for path in sorted((folder / 'build/Testing/QtTest').glob('*.xml')):
            suite = ET.parse(path).getroot()
            for case in suite.findall('.//testcase'):
                if case.get('result') not in ('pass', 'xfail'):
                    failures.append({'report': helper['proof'](path.relative_to(root)),
                                     'name': case.get('name'), 'result': case.get('result')})
        navigation_path = folder / 'build/main-window-navigation.json'
        navigation = json.loads(navigation_path.read_text('utf-8'))
        assert navigation['sourceCommit'] == COMMIT
        observations.append({'runner': item['name'], 'coreFailures': failures,
                             'navigationPassed': navigation['passed'],
                             'navigation': helper['proof'](navigation_path.relative_to(root))})
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
        'run': {k: run[k] for k in ('id', 'status', 'conclusion', 'html_url', 'run_attempt')},
        'jobs': [{k: job[k] for k in ('id', 'name', 'status', 'conclusion', 'steps')} for job in jobs],
        'artifacts': records, 'originalFailureRetained': True, 'allArtifactDigestsVerified': True,
        'observations': observations, 'fullNativeRegressionQualified': False,
        'releaseQualified': False, 'deliveryComplete': False}
    observed_path = output / 'terminal-artifact-observation.json'
    if not observed_path.exists():
        observed_path.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    suites = [helper['protocol'](path.relative_to(root), COMMIT) for path in output.rglob('protocol-suite.json')]
    assert len(suites) == 4 and sum(row['cases'] for row in suites) == 188
    extra, skipped = [], []
    for runner in runners:
        folder = output / ('validation-' + runner)
        paths = [folder / 'proxy-pacing.json']
        if runner.startswith('macos-'):
            paths += [folder / 'build/macos-native-render.json', folder / 'build/macos-native-process-recovery.json']
        if runner == 'ubuntu-22.04':
            # 日期：2026-11-07；工作流隐式success条件跳过的磁盘专项，明确未验证，不要求虚构报告。
            job, = [job for job in jobs if job['name'].startswith('native (' + runner + ',')]
            for filename, step_name in (('disk.json', 'Real disk exhaustion on isolated Linux tmpfs'),
                    ('parallel-disk.json', 'Real TLS transfer disk exhaustion and recovery')):
                step, = [step for step in job['steps'] if step['name'] == step_name]
                path = folder / 'build' / filename
                assert step['status'] == 'completed'
                if step['conclusion'] == 'skipped':
                    assert not path.exists()
                    skipped.append({'runner': runner, 'step': step_name, 'conclusion': 'skipped',
                                    'reportCreated': False, 'qualified': False})
                else:
                    assert step['conclusion'] == 'success'
                    paths.append(path)
        for path in paths:
            value = json.loads(path.read_text('utf-8'))
            assert value['passed']
            helper['verify_passed'](value)
            extra.append(helper['proof'](path.relative_to(root)))
    manifest = json.loads((root / 'docs/ci-verification-20261107-r101.json').read_text('utf-8'))
    assert len(manifest['buildInputs']) == 210
    for row in manifest['buildInputs']:
        raw = subprocess.check_output(['git', 'show', COMMIT + ':' + row['path']],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    value = dict(observation, protocolSuites=suites, independentlyVerifiedProtocolReports=188,
        allProtocolReportsAndHashesVerified=True, additionalBusinessReports=extra, skippedAdditionalReports=skipped,
        buildInputsVerified=210, qualifiedScope='Protocol reports and named extra business reports only; UI/core/navigation failures and skipped disk steps preserved',
        fullCoreAndNavigationQualified=False)
    (output / 'verified-subsets.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    shutil.copyfile(root / '.cache/collect-exact-native-r87.py', output / 'source-collect-exact-native-r87.py')
    print(json.dumps({'sourceCommit': COMMIT, 'originalWorkflowConclusion': 'failure',
                      'protocolReportsVerified': 188, 'wholeRegressionQualified': False}), flush=True)


if __name__ == '__main__':
    main()

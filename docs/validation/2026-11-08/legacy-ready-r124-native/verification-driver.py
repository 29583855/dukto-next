"""日期：2026-11-08；按四原生真实报告核对R6重复超时专项，旧版对照失败不覆盖。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASELINE = '206776b209c51fdd62661af6e90feb720bb6c1f1'


# 日期：2026-11-08；逐轮独立重验返回码、阶段、时间和正文，原件中的passed不足以替代断言。
def cases(report):
    assert report['roundsRequested'] == 3 and report['receiverTimeoutSeconds'] == 5
    assert report['pausedSeconds'] == 6 and len(report['cases']) == 12
    expected = {'buffered-valid': 0, 'buffered-invalid-text': 6,
                'silent-stall': 3, 'partial-stall': 3}
    assert {(case['round'], case['name']) for case in report['cases']} == {
        (index, name) for index in range(1, 4) for name in expected}
    for case in report['cases']:
        assert case['passed'] and not case['stderr'] and case['exitCode'] == expected[case['name']]
        if case['name'] == 'buffered-valid':
            assert case['contentVerified'] and case['lastEvent']['stage'] == 'received'
            assert case['lastEvent']['bytes'] == '21' and case['seconds'] >= 6
        elif case['name'] == 'buffered-invalid-text':
            assert case['lastEvent']['stage'] == 'receive' and case['lastEvent']['code'] == 6
            assert case['seconds'] >= 6
        else:
            assert case['lastEvent']['stage'] == 'transfer' and 4.5 <= case['seconds'] < 10
    assert report['passed']


# 日期：2026-11-08；精确Git树和实际检出规则双重核对，Mac对照绑定原提交、夹具绑定候选。
def identity(report, source, candidate, windows):
    helper = runpy.run_path(str(ROOT / '.cache/collect-r123-domain-native.py'))
    expected = helper['expected_inputs']
    tree = runpy.run_path(str(ROOT / '.cache/publish-r120-native-delivery.py'))['tree'](source)
    required = {name for name in tree if name == 'CMakeLists.txt' or any(name.startswith(prefix) for prefix in
                ['src/', 'ui/', 'resources/', 'tests/', 'scripts/', 'third-party/sqlite-runtime/', '.github/workflows/'])}
    assert set(report['sourceInputs']) == required
    assert report['sourceCommit'] == source
    assert report['sourceInputs'] == report['sourceInputsAfter'] == expected(source, list(report['sourceInputs']), windows)
    assert report['testInputs'] == report['testInputsAfter']
    fixtures = {'tests/' + name: sha for name, sha in report['testInputs'].items()}
    assert fixtures == expected(candidate, list(fixtures), windows)
    assert report['executableSha256'] == report['executableAfterSha256']
    return {'verifiedBuildInputs': len(required), 'verifiedFixtures': len(fixtures),
            'binarySha256': report['executableSha256'], 'sourceAndBinaryUnchanged': True}


# 日期：2026-11-08；仅收取终态原件，官方ZIP及日志留摘要，各平台独立授予这些12场景资格。
def main():
    runs = json.loads((ROOT / '.cache/r124-ci-runs.json').read_bytes())
    source = runs['sourceCommit']
    request = runpy.run_path(str(ROOT / '.cache/github-actions-r28.py'))['request']
    api = '/repos/29583855/dukto-next'
    path = api + '/actions/runs/' + str(runs['regressionRunId'])
    run = request(path)
    assert run['head_sha'] == source and run['run_attempt'] == 1
    jobs = request(path + '/jobs?per_page=100')['jobs']
    artifacts = request(path + '/artifacts?per_page=100')['artifacts']
    output = REPO / 'docs/validation/2026-11-08/legacy-ready-r124-native'
    output.mkdir(exist_ok=True)
    cache = ROOT / '.cache/legacy-ready-r124-native-artifacts'
    cache.mkdir(exist_ok=True)
    extract = runpy.run_path(str(ROOT / '.cache/collect-r123-full-native-core.py'))['extract']
    records = []
    for runner in ['windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel']:
        job, = [job for job in jobs if job['name'] == 'ready (' + runner + ')']
        folder = output / runner
        receipt = folder / 'receipt.json'
        if receipt.exists():
            value = json.loads(receipt.read_bytes())
            assert value['sourceCommit'] == source and value['jobStatus'] == 'completed'
            records.append(value)
            continue
        value = {'runner': runner, 'sourceCommit': source, 'jobId': job['id'],
                 'jobStatus': job['status'], 'jobConclusion': job['conclusion'], 'qualified': False,
                 'rootCauseProven': False, 'deliveryComplete': False, 'releaseQualified': False}
        if job['status'] != 'completed':
            records.append(value)
            continue
        folder.mkdir(exist_ok=True)
        log = folder / 'job.log'
        if not log.exists():
            log.write_bytes(request(api + '/actions/jobs/' + str(job['id']) + '/logs', binary=True))
        value['jobLogSha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
        items = [item for item in artifacts if item['name'] == 'legacy-ready-' + runner]
        if items:
            item, = items
            archive = cache / (str(item['id']) + '.zip')
            raw = archive.read_bytes() if archive.exists() else request(api + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
            checksum = hashlib.sha256(raw).hexdigest()
            assert item['digest'] == 'sha256:' + checksum and not item['expired']
            if not archive.exists():
                archive.write_bytes(raw)
            extract(raw, folder)
            value.update(artifactId=item['id'], artifactSha256=checksum)
        reports = list(folder.rglob('legacy-ready.json'))
        if job['conclusion'] == 'success':
            report, = reports
            actual = json.loads(report.read_bytes())
            value.update(identity(actual, source, source, runner == 'windows-2022'))
            cases(actual)
            value.update(qualified=True, casesPassed=12, originalIdleDeadlineSeconds=5, pausedSeconds=6)
            if runner.startswith('macos-'):
                old, = folder.rglob('baseline-ready.json')
                baseline = json.loads(old.read_bytes())
                value['baselineIdentity'] = identity(baseline, BASELINE, source, False)
                value['baselineAllCasesPassed'] = baseline['passed']
                value['baselinePassedCases'] = sum(case['passed'] for case in baseline['cases'])
                value['baselineFailedCases'] = [case for case in baseline['cases'] if not case['passed']]
                if baseline['passed']:
                    cases(baseline)
                value['failureReproducedByBaseline'] = not baseline['passed']
        else:
            value['originalFailureRetained'] = True
        receipt.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        records.append(value)
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'run': {key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
              'records': records, 'allFourNativeReadyCasesQualified': len(records) == 4 and all(row['qualified'] for row in records),
              'rootCauseProven': False, 'fullNativeProtocolQualified': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'runStatus': run['status'], 'runConclusion': run['conclusion'],
                      'verifiedJobs': sum(row['qualified'] for row in records),
                      'jobs': [{key: row.get(key) for key in ['runner', 'jobStatus', 'jobConclusion', 'qualified', 'baselineAllCasesPassed']} for row in records]}), flush=True)


if __name__ == '__main__':
    main()

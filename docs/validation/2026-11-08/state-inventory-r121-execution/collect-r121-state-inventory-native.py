"""日期：2026-11-08；增量核验R121原生状态专项的精确源码、程序身份和原始14/15行，不越授范围。"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-08；每个已终态job分别验官方附件及精确源码，失败原件保留、未终态不重启。
def main():
    selected = json.loads((ROOT / '.cache/r121-ci-runs.json').read_bytes())
    source, run_id = selected['sourceCommit'], selected['regressionRunId']
    request = runpy.run_path(str(ROOT / '.cache/github-actions-r28.py'))['request']
    helper = runpy.run_path(str(ROOT / '.cache/collect-r120-fixed-file-info-native.py'))
    shared = runpy.run_path(str(ROOT / '.cache/collect-r120-full-native-core.py'))
    api = '/repos/29583855/dukto-next'
    base = api + '/actions/runs/' + str(run_id)
    run = request(base)
    assert run['head_sha'] == source and run['run_attempt'] == 1
    jobs = request(base + '/jobs?per_page=100')['jobs']
    artifacts = request(base + '/artifacts?per_page=100')['artifacts']
    output = REPO / 'docs/validation/2026-11-08/state-inventory-r121-native'
    output.mkdir(parents=True, exist_ok=True)
    cache = ROOT / '.cache/state-inventory-r121-native-artifacts'
    cache.mkdir(exist_ok=True)
    expected = helper['input_hashes'](source)
    records = []
    for runner in ['windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel']:
        job, = [item for item in jobs if item['name'] == 'inventory (' + runner + ')']
        if job['status'] != 'completed':
            records.append({'runner': runner, 'status': job['status'], 'qualified': False})
            continue
        folder = output / runner
        folder.mkdir(exist_ok=True)
        target = folder / 'receipt.json'
        if target.exists():
            value = json.loads(target.read_bytes())
            assert value['jobId'] == job['id'] and value['sourceCommit'] == source
            records.append(value)
            continue
        artifact, = [item for item in artifacts if item['name'] == 'state-inventory-' + runner]
        assert not artifact['expired']
        path = cache / (str(artifact['id']) + '.zip')
        raw = path.read_bytes() if path.exists() else request(api + '/actions/artifacts/' + str(artifact['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert artifact['digest'] == 'sha256:' + digest
        if not path.exists():
            path.write_bytes(raw)
        shared['extract'](raw, folder)
        log = request(api + '/actions/jobs/' + str(job['id']) + '/logs', binary=True)
        (folder / 'job.log').write_bytes(log)
        value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
                 'runner': runner, 'jobId': job['id'], 'status': job['status'], 'conclusion': job['conclusion'],
                 'artifactId': artifact['id'], 'artifactSha256': digest, 'jobLogSha256': hashlib.sha256(log).hexdigest(),
                 'steps': job['steps'], 'qualified': False, 'completeCoreQualified': False,
                 'globalQuotaEnforced': False, 'deliveryComplete': False, 'releaseQualified': False}
        if job['conclusion'] == 'success':
            original = json.loads((folder / 'state-inventory-regression/receipt.json').read_bytes())
            assert original['sourceCommit'] == source and original['passed'] and original['ctestExitCode'] == 0
            assert original['binaryUnchanged'] and original['binaryBefore'] == original['binaryAfter']
            assert original['sourceInputsUnchanged'] and set(original['sourceInputs']) == set(expected)
            for name, actual in original['sourceInputs'].items():
                choices = expected[name]
                if runner != 'windows-2022':
                    actual_source = subprocess.check_output(['git', 'show', source + ':' + name], cwd=REPO)
                    choices = {hashlib.sha256(actual_source).hexdigest()}
                assert actual in choices, (runner, name)
            xml = folder / 'Testing/QtTest/state-storage-tests.xml'
            qt = shared['qt'](xml, runner)
            verifier_source = subprocess.check_output(['git', 'show', source + ':scripts/ci_state_inventory.py'], cwd=REPO)
            module = {'__name__': 'exact_committed_state_inventory_verifier'}
            exec(compile(verifier_source, source + ':scripts/ci_state_inventory.py', 'exec'), module)
            verifier = module['verify_xml']
            verifier.__globals__['os'] = type('Platform', (), {'name': 'nt' if runner == 'windows-2022' else 'posix'})
            exact = verifier(xml)
            assert original['rowsPassed'] == exact['rowsPassed'] and original['permissionRowsSkipped'] == exact['permissionRowsSkipped']
            assert original['newNativeIdentityAllocationAndLockMethodsPassed'] == 3
            assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 1$', (folder / 'state-inventory-regression/ctest.log').read_text('utf-8-sig'), re.M)
            value.update(qualified=True, exactSourceFilesVerified=len(expected), verifiedQtReport=qt,
                         binaryUnchanged=True, **exact)
        else:
            value['originalFailureRetained'] = True
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        records.append(value)
        print(json.dumps({'runner': runner, 'conclusion': job['conclusion'], 'qualified': value['qualified']}), flush=True)
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'run': {key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
              'records': records, 'allFourNativeStateInventoryQualified': len(records) == 4 and all(row['qualified'] for row in records),
              'completeCoreQualified': False, 'globalQuotaEnforced': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'runStatus': run['status'], 'runConclusion': run['conclusion'],
                      'verifiedJobs': sum(row['qualified'] for row in records)}), flush=True)


if __name__ == '__main__':
    main()

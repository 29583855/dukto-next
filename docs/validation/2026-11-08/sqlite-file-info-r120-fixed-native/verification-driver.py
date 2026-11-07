"""日期：2026-11-08；增量收验四原生的完整核心及真实文件专项，保留失败且按精确源码核对。"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-08；Git归档读取精确字节，Windows文本检出只接受确定的LF或CRLF转换，vendor始终原字节。
def input_hashes(commit):
    result = {}
    raw = subprocess.check_output(['git', 'archive', commit], cwd=REPO)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            if member.isfile() and (member.name == 'CMakeLists.txt' or member.name.startswith(
                    ('src/', 'tests/', 'scripts/', 'third-party/sqlite-runtime/', '.github/workflows/'))):
                data = archive.extractfile(member).read()
                hashes = {hashlib.sha256(data).hexdigest()}
                if not member.name.startswith('third-party/sqlite-runtime/'):
                    hashes.add(hashlib.sha256(data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')).hexdigest())
                result[member.name] = hashes
    return result


# 日期：2026-11-08；只有四个真实job的30完整核心与11条专项原件均通过，才授予对应范围资格。
def main():
    runs = json.loads((ROOT / '.cache/r120-fixed-ci-runs.json').read_bytes())
    source, run_id = runs['sourceCommit'], runs['regressionRunId']
    request = runpy.run_path(str(ROOT / '.cache/github-actions-r28.py'))['request']
    helper = runpy.run_path(str(ROOT / '.cache/collect-r119-native-core.py'))
    base = '/repos/29583855/dukto-next'
    path = base + '/actions/runs/' + str(run_id)
    run = request(path)
    assert run['head_sha'] == source and run['run_attempt'] == 1
    jobs = request(path + '/jobs?per_page=100')['jobs']
    artifacts = request(path + '/artifacts?per_page=100')['artifacts']
    output = REPO / 'docs/validation/2026-11-08/sqlite-file-info-r120-fixed-native'
    output.mkdir(parents=True, exist_ok=True)
    cache = ROOT / '.cache/sqlite-file-info-r120-fixed-native-artifacts'
    cache.mkdir(exist_ok=True)
    expected = input_hashes(source)
    records = []
    for runner in ['windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel']:
        job, = [job for job in jobs if job['name'] == 'native (' + runner + ')']
        if job['status'] != 'completed':
            records.append({'runner': runner, 'status': job['status'], 'qualified': False})
            continue
        folder = output / runner
        receipt_path = folder / 'receipt.json'
        if receipt_path.exists():
            record = json.loads(receipt_path.read_bytes())
            assert record['sourceCommit'] == source and record['jobId'] == job['id']
            records.append(record)
            continue
        folder.mkdir(exist_ok=True)
        artifact, = [item for item in artifacts if item['name'] == 'sqlite-file-info-' + runner]
        assert not artifact['expired']
        local = cache / (str(artifact['id']) + '.zip')
        raw = local.read_bytes() if local.exists() else request(base + '/actions/artifacts/' + str(artifact['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert artifact['digest'] == 'sha256:' + digest
        if not local.exists():
            local.write_bytes(raw)
        helper['extract'](raw, folder)
        log = request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True)
        (folder / 'job.log').write_bytes(log)
        record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'runner': runner,
                  'sourceCommit': source, 'jobId': job['id'], 'status': job['status'],
                  'conclusion': job['conclusion'], 'steps': job['steps'], 'artifactId': artifact['id'],
                  'artifactSha256': digest, 'jobLogSha256': hashlib.sha256(log).hexdigest(),
                  'qualified': False, 'globalQuotaEnforced': False,
                  'deliveryComplete': False, 'releaseQualified': False}
        original = folder / 'sqlite-file-info-regression/receipt.json'
        if job['conclusion'] == 'success':
            value = json.loads(original.read_bytes())
            assert value['sourceCommit'] == source and value['passed'] and value['ctestExitCode'] == 0
            assert value['binaryUnchanged'] and value['binaryBefore'] == value['binaryAfter']
            assert value['sourceInputsUnchanged'] and value['fileInfoTestMethods'] == 11
            assert value['fileInfoFailures'] == value['fileInfoSkipped'] == 0
            assert set(value['sourceInputs']) == set(expected)
            for name, actual in value['sourceInputs'].items():
                choices = expected[name]
                if runner != 'windows-2022':
                    raw_file = subprocess.check_output(['git', 'show', source + ':' + name], cwd=REPO)
                    choices = {hashlib.sha256(raw_file).hexdigest()}
                assert actual in choices, (runner, name)
            ctest = (folder / 'sqlite-file-info-regression/ctest.log').read_text('utf-8-sig')
            assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 30$', ctest, re.M)
            xmls = sorted((folder / 'Testing/QtTest').glob('*.xml'))
            assert len(xmls) == 29
            reports = [helper['qt'](xml, runner) for xml in xmls]
            target = folder / 'Testing/QtTest/sqlite-file-info-tests.xml'
            tests = ET.fromstring(target.read_bytes())
            cases = tests.findall('testcase')
            assert tests.get('errors') == tests.get('failures') == '0'
            assert len(cases) == 11 and all(case.get('result') == 'pass' for case in cases)
            assert 'Totals: 11 passed, 0 failed, 0 skipped' in target.with_suffix('.log').read_text('utf-8-sig')
            record.update(qualified=True, ctestTargetsPassed=30, qtXmlReportsVerified=29,
                          fileInfoRowsPassed=11, fileInfoSkipped=0, verifiedQtReports=reports,
                          exactSourceFilesVerified=len(expected), binaryUnchanged=True)
        else:
            record['originalFailureRetained'] = True
            record['failedSteps'] = [step['name'] for step in job['steps'] if step['conclusion'] == 'failure']
        receipt_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        records.append(record)
        print(json.dumps({'runner': runner, 'conclusion': job['conclusion'], 'qualified': record['qualified']}), flush=True)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'run': {key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
             'records': records, 'allFourNativeCoreAndFileInfoQualified': len(records) == 4 and all(row['qualified'] for row in records),
             'fullNativeProtocolQualified': False, 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'runStatus': run['status'], 'runConclusion': run['conclusion'],
                      'verifiedJobs': sum(row['qualified'] for row in records)}), flush=True)


if __name__ == '__main__':
    main()

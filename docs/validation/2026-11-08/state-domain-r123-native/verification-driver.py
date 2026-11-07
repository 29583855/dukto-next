"""日期：2026-11-08；逐原生平台收取R123持久账本底层原件，不以编译或其他平台替代专项资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-08；从精确Git树读取对应输入原字节，实际输入清单的每项均须匹配，不能转授其他提交。
def expected_inputs(source, names, windows=False):
    payload = ''.join(source + ':' + name + '\n' for name in names).encode('utf-8')
    raw = subprocess.check_output(['git', 'cat-file', '--batch'], input=payload, cwd=REPO)
    result = {}
    offset = 0
    for name in names:
        end = raw.index(b'\n', offset)
        fields = raw[offset:end].split()
        assert len(fields) == 3 and fields[1] == b'blob', name
        size = int(fields[2])
        start = end + 1
        data = raw[start:start + size]
        assert len(data) == size and raw[start + size:start + size + 1] == b'\n'
        if windows and not name.startswith('third-party/sqlite-runtime/'):
            # 日期：2026-11-08；Windows默认Git检出将原UTF-8/LF文本转为CRLF，固定依赖-text仍必须原字节。
            assert b'\0' not in data, name
            data.decode('utf-8-sig')
            if b'\r\n' not in data:
                data = data.replace(b'\n', b'\r\n')
        result[name] = hashlib.sha256(data).hexdigest()
        offset = start + size + 1
    assert offset == len(raw)
    return result


# 日期：2026-11-08；可增量收取已完成job，官方ZIP摘要、原XML、23行和全部执行输入分别核验。
def main():
    runs = json.loads((ROOT / '.cache/r123-ci-runs.json').read_bytes())
    source = runs['sourceCommit']
    request = runpy.run_path(str(ROOT / '.cache/github-actions-r28.py'))['request']
    base = '/repos/29583855/dukto-next'
    path = base + '/actions/runs/' + str(runs['regressionRunId'])
    run = request(path)
    assert run['head_sha'] == source and run['run_attempt'] == 1
    jobs = request(path + '/jobs?per_page=100')['jobs']
    artifacts = request(path + '/artifacts?per_page=100')['artifacts']
    output = REPO / 'docs/validation/2026-11-08/state-domain-r123-native'
    output.mkdir(exist_ok=True)
    records = []
    extract = runpy.run_path(str(ROOT / '.cache/collect-r120-full-native-core.py'))['extract']
    verify = runpy.run_path(str(ROOT / 'scripts/ci_state_domain.py'))['verify_xml']
    for runner in ['windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel']:
        job, = [job for job in jobs if job['name'] == 'budget (' + runner + ')']
        folder = output / runner
        receipt_path = folder / 'receipt.json'
        if receipt_path.exists():
            existing = json.loads(receipt_path.read_bytes())
            assert existing['sourceCommit'] == source and existing['jobStatus'] == 'completed'
            records.append(existing)
            continue
        record = {'runner': runner, 'sourceCommit': source, 'jobId': job['id'], 'jobStatus': job['status'],
                  'jobConclusion': job['conclusion'], 'qualified': False,
                  'globalQuotaEnforced': False, 'deliveryComplete': False, 'releaseQualified': False}
        if job['status'] != 'completed':
            records.append(record)
            continue
        item, = [item for item in artifacts if item['name'] == 'state-domain-' + runner]
        cache = ROOT / '.cache/state-domain-r123-native-artifacts'
        cache.mkdir(exist_ok=True)
        archive = cache / (str(item['id']) + '.zip')
        raw = archive.read_bytes() if archive.exists() else request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest and not item['expired']
        if not archive.exists():
            archive.write_bytes(raw)
        folder.mkdir(exist_ok=True)
        extract(raw, folder)
        log = folder / 'job.log'
        if not log.exists():
            log.write_bytes(request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True))
        record.update(artifactId=item['id'], artifactSha256=digest, jobLogSha256=hashlib.sha256(log.read_bytes()).hexdigest())
        matches = list(folder.rglob('state-domain-regression/receipt.json'))
        if job['conclusion'] != 'success' and not matches:
            record.update(originalFailureRetained=True, failedBeforeTestReceipt=True)
            receipt_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', 'utf-8')
            records.append(record)
            continue
        receipt, = matches
        tested = json.loads(receipt.read_bytes())
        assert tested['sourceCommit'] == source
        if job['conclusion'] == 'success':
            assert tested['passed'] and tested['testExitCode'] == 0 and tested['sourceInputsUnchanged'] and tested['binaryUnchanged']
            assert tested['binaryBefore'] == tested['binaryAfter']
            actual = tested['sourceInputs']
            assert len(actual) >= 260 and 'src/core/statedomain.cpp' in actual and 'tests/state_domain_tests.cpp' in actual
            names = runpy.run_path(str(ROOT / '.cache/publish-r120-native-delivery.py'))['tree'](source)
            required = {name for name in names if name == 'CMakeLists.txt' or any(name.startswith(prefix) for prefix in
                        ['src/', 'tests/', 'scripts/', 'third-party/sqlite-runtime/', '.github/workflows/'])}
            assert set(actual) == required
            canonical = expected_inputs(source, list(actual))
            expected = expected_inputs(source, list(actual), runner == 'windows-2022')
            assert actual == expected
            conversions = [{'path': name, 'gitBlobSha256': canonical[name], 'checkedOutSha256': actual[name]}
                           for name in actual if canonical[name] != actual[name]]
            record.update(canonicalGitBytesAllMatch=not conversions,
                          checkoutLineEndingPolicy='Git LF to CRLF for UTF-8 text; vendor -text unchanged' if conversions else 'exact Git bytes',
                          checkoutLineEndingConversions=conversions)
            result = verify(receipt.parent / 'state-domain-tests.xml')
            assert result['rowsPassed'] == tested['rowsPassed'] == 12
            assert not tested['globalQuotaEnforced'] and not tested['deliveryComplete'] and not tested['productionRootsIntegrated']
            record.update(qualified=True, verifiedInputs=len(actual), **result)
        else:
            record['originalFailureRetained'] = True
            record['reportedFailure'] = {key: tested.get(key) for key in ['testExitCode', 'passed', 'verificationError']}
        receipt_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        records.append(record)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'run': {key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
             'records': records, 'allFourNativeDomainFoundationQualified': len(records) == 4 and all(row['qualified'] for row in records),
             'globalQuotaEnforced': False, 'productionRootsIntegrated': False,
             'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'runStatus': run['status'], 'runConclusion': run['conclusion'],
                      'verifiedJobs': sum(row['qualified'] for row in records),
                      'jobs': [{key: row[key] for key in ['runner', 'jobStatus', 'jobConclusion', 'qualified']} for row in records]}), flush=True)


if __name__ == '__main__':
    main()

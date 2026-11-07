"""日期：2026-11-07；收验精确R117候选的两轮Windows专项，原失败与新通过使用不同目录。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
RUN = 42378902285


# 日期：2026-11-07；核对实际数据行和14个Qt方法，符号链接跳过只能来自明确的Windows原生权限缺口。
def verify_scan(folder):
    log = (folder / 'upload-scan-cleanup-tests.log').read_text('utf-8-sig')
    match = re.search(r'Totals: (\d+) passed, 0 failed, (\d+) skipped, 0 blacklisted', log)
    assert match, log[-2000:]
    passed, skipped = map(int, match.groups())
    assert passed + skipped == 29 and 0 <= skipped <= 2
    skips = [line for line in log.splitlines() if line.startswith('SKIP')]
    assert len(skips) == skipped
    for line in skips:
        assert 'Windows account cannot create a native symbolic link' in line
        assert any('::' + name + '(symbolic-link)' in line for name in ['unsafeObjects', 'unsafeJournalLinks'])
    for name in ['journalAccessBoundary()', 'unsafeJournalPermissions()', 'unsafeJournalLinks(hard-link)',
                 'retainedPreviewAndCleanup(hot-journal)', 'exhaustedCacheCredit()', 'realCli()']:
        assert 'PASS   : UploadScanCleanupTests::' + name in log, name
    tree = ET.fromstring((folder / 'upload-scan-cleanup-tests.xml').read_bytes())
    assert tree.get('failures') == '0' and not tree.findall('.//failure') and not tree.findall('.//error')
    methods = tree.findall('testcase')
    assert len(methods) == 14
    for method in methods:
        assert method.get('result') == 'pass' or (method.get('name') in ['unsafeObjects', 'unsafeJournalLinks'] and method.get('result') == 'skip')
    return {'rowsPassed': passed, 'rowsSkipped': skipped, 'junitMethods': len(methods), 'skips': skips}


# 日期：2026-11-07；使用官方附件摘要、固定提交及执行前后二进制身份验证新结果，非终态只报告状态。
def main():
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    extract = runpy.run_path('.cache/collect-r116-completed-native-jobs.py')['extract']
    dispatch = json.loads((ROOT / '.cache/r117-windows-native-dispatch.json').read_bytes())
    api = '/repos/29583855/dukto-next'
    path = api + '/actions/runs/' + str(RUN)
    run = request(path)
    assert run['head_sha'] == dispatch['sourceCommit'] and run['run_attempt'] == 1
    job, = request(path + '/jobs?per_page=100')['jobs']
    if job['status'] != 'completed':
        print(json.dumps({'status': job['status'], 'active': [step['name'] for step in job['steps'] if step['status'] == 'in_progress']}), flush=True)
        return
    output = REPO / 'docs/validation/2026-11-07/sqlite-journal-r117-windows-native'
    output.mkdir(exist_ok=True)
    item, = [row for row in request(path + '/artifacts?per_page=100')['artifacts'] if row['name'] == 'windows-upload-scan-diagnostic']
    cache = ROOT / '.cache' / ('r117-windows-native-' + str(item['id']) + '.zip')
    raw = cache.read_bytes() if cache.exists() else request(api + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
    digest = hashlib.sha256(raw).hexdigest()
    assert not item['expired'] and item['digest'] == 'sha256:' + digest
    if not cache.exists():
        cache.write_bytes(raw)
    extract(raw, output)
    log = output / 'job.log'
    if not log.exists():
        log.write_bytes(request(api + '/actions/jobs/' + str(job['id']) + '/logs', binary=True))
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': run['head_sha'],
             'run': {key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
             'artifactId': item['id'], 'artifactSha256': digest, 'jobId': job['id'],
             'jobLogSha256': hashlib.sha256(log.read_bytes()).hexdigest(), 'steps': job['steps'],
             'passed': False, 'deliveryComplete': False, 'releaseQualified': False}
    if job['conclusion'] == 'success':
        evidence = output / 'evidence'
        assert (evidence / 'source-commit.txt').read_text('utf-8-sig').strip() == dispatch['sourceCommit']
        assert (evidence / 'binaries-before.json').read_bytes() == (evidence / 'binaries-after.json').read_bytes()
        rounds = []
        for number in [1, 2]:
            folder = evidence / ('round-' + str(number))
            assert (folder / 'exit-code.txt').read_text().strip() == '0'
            assert '100% tests passed out of 1' in (folder / 'ctest.log').read_text('utf-8-sig')
            rounds.append(verify_scan(folder))
        index = json.loads((REPO / 'docs/ci-verification-20261107-r116.json').read_bytes())
        diagnostic = ROOT / '.cache/github-upload-scan-r116-diagnostic'
        compared = []
        for row in index['qualificationInputs']:
            name = row['path']
            if name.startswith('.github/'):
                continue
            actual = subprocess.check_output(['git', 'show', dispatch['sourceCommit'] + ':' + name], cwd=diagnostic)
            assert actual == (ROOT / name).read_bytes(), name
            compared.append(name)
        value.update(passed=True, rounds=rounds, binariesBeforeAfterUnchanged=True,
                     allApplicationAndTestInputsMatch=True, comparedApplicationAndTestInputCount=len(compared))
    (output / 'dispatch-receipt.json').write_bytes((ROOT / '.cache/r117-windows-native-dispatch.json').read_bytes())
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'conclusion': job['conclusion'], 'passed': value['passed'], 'rounds': value.get('rounds')}), flush=True)


if __name__ == '__main__':
    main()

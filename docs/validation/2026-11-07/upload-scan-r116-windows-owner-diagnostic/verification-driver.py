"""日期：2026-11-07；保留Windows两轮原诊断终态及真实异常，不将诊断失败计为产品通过。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy


# 日期：2026-11-07；单次只读既有运行，未终态不下载不授予资格，终态按官方摘要保存原件。
def main():
    root = Path.cwd()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    extract = runpy.run_path('.cache/collect-r114-completed-native-jobs.py')['extract']
    dispatch = json.loads((root / '.cache/r116-owner-diagnostic-dispatch.json').read_bytes())
    api = '/repos/29583855/dukto-next'
    path = api + '/actions/runs/42378231972'
    run = request(path)
    assert run['head_sha'] == dispatch['sourceCommit'] and run['run_attempt'] == 1
    jobs = request(path + '/jobs?per_page=100')['jobs']
    job, = jobs
    if job['status'] != 'completed':
        print(json.dumps({'runStatus': run['status'], 'active': [step['name'] for step in job['steps'] if step['status'] == 'in_progress']}), flush=True)
        return
    output = root / '.cache/github-29583855-dukto-next-r28/docs/validation/2026-11-07/upload-scan-r116-windows-owner-diagnostic'
    output.mkdir(exist_ok=True)
    artifacts = request(path + '/artifacts?per_page=100')['artifacts']
    item, = [item for item in artifacts if item['name'] == 'windows-upload-scan-diagnostic']
    cache = root / '.cache' / ('r116-windows-owner-diagnostic-' + str(item['id']) + '.zip')
    raw = cache.read_bytes() if cache.exists() else request(api + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
    digest = hashlib.sha256(raw).hexdigest()
    assert item['digest'] == 'sha256:' + digest and not item['expired']
    if not cache.exists():
        cache.write_bytes(raw)
    extract(raw, output)
    log = output / 'job.log'
    if not log.exists():
        log.write_bytes(request(api + '/actions/jobs/' + str(job['id']) + '/logs', binary=True))
    messages = []
    for ctest in sorted(output.rglob('ctest.log')):
        text = ctest.read_text('utf-8-sig')
        messages.extend(re.findall(r'^.*(?:scan diagnostic |journal-owner ).*$', text, re.M))
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': run['head_sha'],
             'productSourceCommit': dispatch['productSourceCommit'], 'allProductInputsUnchanged': True,
             'run': {key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
             'artifactId': item['id'], 'artifactSha256': digest, 'jobId': job['id'], 'steps': job['steps'],
             'jobLogSha256': hashlib.sha256(log.read_bytes()).hexdigest(), 'originalDiagnosticMessages': messages,
             'passed': job['conclusion'] == 'success', 'deliveryComplete': False, 'releaseQualified': False}
    (output / 'dispatch-receipt.json').write_bytes((root / '.cache/r116-owner-diagnostic-dispatch.json').read_bytes())
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'conclusion': job['conclusion'], 'diagnosticMessages': messages}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

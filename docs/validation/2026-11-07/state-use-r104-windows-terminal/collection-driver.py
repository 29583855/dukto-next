"""日期：2026-11-07；保存Windows原始失败附件及作业日志，不赋予完整回归通过资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil


# 日期：2026-11-07；核对既有作业及官方摘要，保存原件后仅输出实际失败项。
def main():
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    base = '/repos/29583855/dukto-next'
    source = '9c1e9419f7acb9bc3ddf2b8133eb330ead0c3fa6'
    run = request(base + '/actions/runs/42316601470')
    job = request(base + '/actions/jobs/128230608444')
    item = request(base + '/actions/artifacts/13555220671')
    assert run['head_sha'] == source and run['run_attempt'] == 1
    assert job['run_id'] == run['id'] and job['status'] == 'completed' and job['conclusion'] == 'failure'
    assert item['name'] == 'validation-windows-2022' and not item['expired']
    output = Path('docs/validation/2026-11-07/state-use-r104-windows-terminal')
    output.mkdir(exist_ok=False)
    raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
    digest = hashlib.sha256(raw).hexdigest()
    assert item['digest'] == 'sha256:' + digest
    (output / (item['name'] + '.zip')).write_bytes(raw)
    helper['extract'](raw, output / item['name'])
    log = request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True)
    (output / 'job.log').write_bytes(log)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'run_attempt', 'html_url')},
             'job': {key: job[key] for key in ('id', 'name', 'status', 'conclusion', 'steps')},
             'artifact': {key: item[key] for key in ('id', 'name', 'digest', 'expired')},
             'archiveSha256': digest, 'jobLogSha256': hashlib.sha256(log).hexdigest(),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'observation.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(__file__, output / 'collection-driver.py')
    suite = json.loads((output / item['name'] / 'build/protocol-suite.json').read_text('utf-8'))
    print(json.dumps({'sourceCommit': source, 'completed': suite['completed'], 'passed': suite['passed'],
                      'failures': [row for row in suite['cases'] if not row['passed']],
                      'archiveSha256': digest, 'jobLogSha256': value['jobLogSha256']}))


if __name__ == '__main__':
    main()

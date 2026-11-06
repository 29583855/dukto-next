"""日期：2026-11-07；保存R97双Mac编译前全文件基线校验失败，不能计为应用测试执行。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil


# 日期：2026-11-07；原终态、全部步骤与两份原日志独立保存，要求编译和测试均未执行。
def main():
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/42262546590')
    assert run['head_sha'] == '38f2384524bfdefa2ffefcc4c737224185a53266'
    assert run['status'] == 'completed' and run['conclusion'] == 'failure'
    jobs = request(base + '/actions/runs/42262546590/jobs?per_page=100')['jobs']
    assert len(jobs) == 2
    output = Path('docs/validation/2026-11-07/exit-state-r97-ci-guard-terminal')
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for job in jobs:
        assert job['conclusion'] == 'failure'
        failed = [step['name'] for step in job['steps'] if step['conclusion'] == 'failure']
        assert failed == ['Verify original failed assertions remain unchanged']
        for step in job['steps']:
            if step['name'] in ('Compile complete original application and tests', 'All 23 core targets'):
                assert step['conclusion'] == 'skipped'
        raw = request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True)
        path = output / (str(job['id']) + '.log')
        path.write_bytes(raw)
        records.append({'job': {key: job[key] for key in ('id', 'name', 'status', 'conclusion', 'steps')},
                        'originalLog': path.as_posix(), 'logSha256': hashlib.sha256(raw).hexdigest(),
                        'applicationCompiled': False, 'testsExecuted': False})
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': run['head_sha'],
             'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'jobs': records, 'applicationCompiled': False, 'testsExecuted': False,
             'reason': 'R94 whole-file guard rejects the reviewed R97 exit-fixture changes',
             'passed': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'runId': run['id'], 'originalConclusion': 'failure', 'jobs': 2,
                      'applicationCompiled': False, 'testsExecuted': False}), flush=True)


if __name__ == '__main__':
    main()

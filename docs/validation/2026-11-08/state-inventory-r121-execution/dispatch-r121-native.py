"""日期：2026-11-08；只派发已公开精确源码，回执先保存，不重复启动相同工作流。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy


# 日期：2026-11-08；分别启动真实状态专项、完整GUI/核心/协议及Mac依赖部署，授予范围分别收验。
def main():
    root = Path.cwd()
    source = json.loads((root / '.cache/r121-ci-source-publication.json').read_bytes())['sourceCommit']
    request = runpy.run_path(str(root / '.cache/github-actions-r28.py'))['request']
    base = '/repos/29583855/dukto-next'
    assert request(base + '/commits/main')['sha'] == source
    rows = []
    for workflow in ['state-inventory-regression.yml', 'build.yml', 'macos-package.yml']:
        path = root / ('.cache/r121-dispatch-' + workflow + '.json')
        if path.exists():
            row = json.loads(path.read_bytes())
            assert row['sourceCommit'] == source
        else:
            runs = request(base + '/actions/workflows/' + workflow + '/runs?per_page=100')['workflow_runs']
            exact = [run for run in runs if run['head_sha'] == source and run['event'] == 'workflow_dispatch']
            row = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
                   'workflow': workflow, 'matchingExistingRuns': [run['id'] for run in exact]}
            if not exact:
                request(base + '/actions/workflows/' + workflow + '/dispatches', method='POST', payload={'ref': 'main'})
                row['dispatched'] = True
            else:
                row['dispatched'] = False
            path.write_text(json.dumps(row, indent=2) + '\n', 'utf-8')
        runs = request(base + '/actions/workflows/' + workflow + '/runs?per_page=100')['workflow_runs']
        exact = [run for run in runs if run['head_sha'] == source and run['event'] == 'workflow_dispatch']
        row['observedRuns'] = [{key: run[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']} for run in exact]
        path.write_text(json.dumps(row, indent=2) + '\n', 'utf-8')
        rows.append(row)
    if all(len(row['observedRuns']) == 1 for row in rows):
        value = {'sourceCommit': source, 'regressionRunId': rows[0]['observedRuns'][0]['id'],
                 'nativeRunId': rows[1]['observedRuns'][0]['id'], 'packageRunId': rows[2]['observedRuns'][0]['id']}
        (root / '.cache/r121-ci-runs.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(rows), flush=True)


if __name__ == '__main__':
    main()

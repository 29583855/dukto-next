"""日期：2026-11-07；保全R101原生核心原件和真实失败，观察结果不授予通过资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil


# 日期：2026-11-07；只读现有运行，附件按不可变ID和官方摘要保存，未知失败原样披露。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/cancel-r101-native-observation'
    output.mkdir(exist_ok=True)
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    extract = runpy.run_path('.cache/collect-exact-native-r87.py')['extract']
    base = '/repos/29583855/dukto-next'
    number = 42300792120
    run = request(base + '/actions/runs/' + str(number))
    assert run['head_sha'] == '1f82d5d3b9ae36e77ee98da942c2fc5369310c7a'
    jobs = request(base + '/actions/runs/' + str(number) + '/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/' + str(number) + '/artifacts?per_page=100')['artifacts']
    rows = []
    for item in artifacts:
        if not item['name'].startswith('core-validation-'):
            continue
        archive = output / (str(item['id']) + '.zip')
        raw = archive.read_bytes() if archive.exists() else request(
            base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest and not item['expired']
        if not archive.exists():
            archive.write_bytes(raw)
        folder = output / item['name']
        if not folder.exists():
            extract(raw, folder)
        failures = []
        for path in sorted(folder.rglob('*.log')):
            for line in path.read_text('utf-8-sig', errors='replace').splitlines():
                if line.startswith(('FAIL!', 'QFATAL', 'XPASS')) or '***Failed' in line or '***Timeout' in line:
                    failures.append({'path': path.relative_to(output).as_posix(), 'line': line})
        rows.append({'id': item['id'], 'name': item['name'], 'sha256': digest, 'failureLines': failures})
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(),
             'sourceCommit': run['head_sha'], 'run': {k: run[k] for k in
                 ('id', 'status', 'conclusion', 'html_url', 'run_attempt')},
             'jobs': [{k: job[k] for k in ('id', 'name', 'status', 'conclusion', 'steps')} for job in jobs],
             'coreArtifacts': rows, 'qualificationGranted': False,
             'releaseQualified': False, 'deliveryComplete': False}
    target = output / ('observation-' + datetime.now(timezone.utc).strftime('%H%M%S') + '.json')
    assert not target.exists()
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'observation-driver.py')
    print(json.dumps({'observation': target.relative_to(root).as_posix(), 'coreArtifacts': rows}, ensure_ascii=False))


if __name__ == '__main__':
    main()

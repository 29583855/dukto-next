"""日期：2026-11-08；独立Ubuntu使用已冻结R127程序复验两份R128夹具，不改原安装源。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tarfile


# 日期：2026-11-08；测试安装在新目录，既有R127构建、源和长测资料均不修改。
def main():
    root = Path.cwd()
    prior = root / '.cache/r127-glibc'
    core = json.loads((root / '.cache/r127-glibc-recheck/receipt.json').read_bytes())
    assert core['passed'] and core['rowsPassed'] == 8 and core['allInstalledSourceInputsUnchanged']
    ssh = runpy.run_path(str(root / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    output = root / '.cache/r128-glibc-fixtures'
    output.mkdir(exist_ok=False)
    candidate = root / '.cache/r128-candidate/tests'
    inputs = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(candidate.glob('*.py'))}
    archive = output / 'test-inputs.tar.gz'
    with tarfile.open(archive, 'x:gz') as destination:
        for name in inputs:
            destination.add(candidate / name, arcname='tests/' + name)
    with archive.open('rb') as data:
        subprocess.run(ssh + ['set -C; cat > /home/dukto/r128-fixture-inputs.tar.gz'],
                       stdin=data, check=True, timeout=60)
    program = '''set -eu
mkdir /home/dukto/state-fixture-r128
cd /home/dukto/state-fixture-r128
tar xzf /home/dukto/r128-fixture-inputs.tar.gz
mkdir results
sha256sum /home/dukto/gui-state-r127/build/dukto-cli > results/before.sha256
set +e
python3 -X utf8 tests/credential_rotation_integration.py /home/dukto/gui-state-r127/build/dukto-cli --report results/credential_rotation.json > results/credential_rotation.log 2>&1
printf '%s\\n' "$?" > results/credential_rotation.exit
python3 -X utf8 tests/task_items_integration.py /home/dukto/gui-state-r127/build/dukto-cli --report results/task_items.json > results/task_items.log 2>&1
printf '%s\\n' "$?" > results/task_items.exit
sha256sum /home/dukto/gui-state-r127/build/dukto-cli > results/after.sha256
python3 - <<'PY'
import hashlib,json
from pathlib import Path
root=Path('/home/dukto/gui-state-r127')
manifest=json.loads((root/'.dukto-source-snapshot.json').read_bytes())['files']
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==row['sha256'] for name,row in manifest.items())
tests={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('tests').glob('*.py'))}
Path('results/inputs.json').write_text(json.dumps({'productionSnapshotUnchanged':True,'tests':tests})+'\\n')
PY
'''
    with (output / 'driver.log').open('xb') as log:
        driver = subprocess.run(ssh + ['sh -s'], input=program.encode('utf-8'), stdout=log,
                                stderr=subprocess.STDOUT, timeout=1500)
    result_archive = output / 'results.tar.gz'
    with result_archive.open('xb') as destination:
        subprocess.run(ssh + ['cd /home/dukto/state-fixture-r128 && tar czf - results'],
                       stdout=destination, check=True, timeout=90)
    runpy.run_path(str(root / '.cache/validate-r121-glibc-qualified.py'))['extract'](result_archive, output)
    result = output / 'results'
    observed = json.loads((result / 'inputs.json').read_bytes())
    assert observed['productionSnapshotUnchanged'] and observed['tests'] == inputs
    before = (result / 'before.sha256').read_bytes()
    assert before == (result / 'after.sha256').read_bytes()
    sha = before.decode().split()[0]
    assert sha in (prior / 'results/before.sha256').read_text('utf-8')
    verify = runpy.run_path(str(root / '.cache/r128-candidate/scripts/ci_state_fixture_regression.py'))['verify_report']
    rows = []
    for name, script in [('credential-rotation', 'credential_rotation'), ('task-items', 'task_items')]:
        code = int((result / (script + '.exit')).read_text('ascii'))
        row = {'name': name, 'exitCode': code, 'passed': False}
        report = result / (script + '.json')
        if report.is_file():
            verify(name, json.loads(report.read_bytes()), sha, inputs[script + '_integration.py'])
            row['passed'] = code == 0
        rows.append(row)
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'driverExitCode': driver.returncode,
               'productionSourceCommit': '6c6dc363c7bb755f7b5aae1f7627385c009a0ac2',
               'productionSnapshotUnchanged': True, 'testInputs': inputs,
               'binaryBefore': sha, 'binaryAfter': sha, 'records': rows,
               'passed': driver.returncode == 0 and all(row['passed'] for row in rows),
               'fullProtocolQualified': False, 'globalQuotaEnforced': False,
               'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    print(json.dumps(receipt), flush=True)
    raise SystemExit(0 if receipt['passed'] else 1)


if __name__ == '__main__':
    main()

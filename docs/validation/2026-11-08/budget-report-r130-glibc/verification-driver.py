"""日期：2026-11-08；独立Ubuntu新目录编译计量代码，验证POSIX特殊项和真实CLI。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-08；只安装新目录；工作目录与CTest一致，冻结安装源和295份维护输入。
def main():
    root = Path.cwd()
    output = root / '.cache/r130-glibc'
    output.mkdir(exist_ok=False)
    ssh = runpy.run_path(str(root / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    helper = runpy.run_path(str(root / 'scripts/source_snapshot.py'))
    snapshot = root / '.cache/r130-native-accounting-source.tar.gz'
    created = helper['create'](root, snapshot)
    (output / 'snapshot-receipt.json').write_text(json.dumps(created, indent=2) + '\n', 'utf-8')
    for local, remote in [(snapshot, '/home/dukto/source-budget-report-r130.tar.gz'),
                          (root / 'scripts/source_snapshot.py', '/home/dukto/install-budget-report-r130.py')]:
        with local.open('rb') as data:
            subprocess.run(ssh + ['set -C; cat > ' + remote], stdin=data, check=True, timeout=120)
    program = r'''set -eu
mkdir /home/dukto/budget-report-r130
cd /home/dukto/budget-report-r130
mkdir results
printf '%s  /home/dukto/source-budget-report-r130.tar.gz\n' SNAPSHOT_SHA | sha256sum -c -
python3 /home/dukto/install-budget-report-r130.py install /home/dukto/source-budget-report-r130.tar.gz --root /home/dukto/budget-report-r130 > results/source-install.json
cp .dukto-source-snapshot.json results/source-manifest.json
mkdir /tmp/runtime-budget-report-r130
chmod 700 /tmp/runtime-budget-report-r130
export XDG_RUNTIME_DIR=/tmp/runtime-budget-report-r130 QT_QPA_PLATFORM=offscreen
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DDUKTO_BUILD_GUI=OFF > results/configure.log 2>&1
cmake --build build --target dukto-cli state-budget-tests --parallel 2 > results/build.log 2>&1
cd build
mkdir -p Testing/QtTest
sha256sum dukto-cli state-budget-tests > ../results/before.sha256
set +e
./state-budget-tests reportExactAmountsAndHeadroom reportOverdrawnAndCategoryExhaustion -o ../results/state-budget-tests.log,txt -o ../results/state-budget-tests.xml,xml -o ../results/state-budget-tests-junit.xml,junitxml > ../results/test-driver.log 2>&1
code=$?
printf '%s\n' "$code" > ../results/test-exit.txt
sha256sum dukto-cli state-budget-tests > ../results/after.sha256
exit "$code"
'''.replace('SNAPSHOT_SHA', created['archiveSha256'])
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(ssh + ['sh -s'], input=program.encode('utf-8'), stdout=log,
                                stderr=subprocess.STDOUT, timeout=3600)
    archive = output / 'results.tar.gz'
    with archive.open('xb') as destination:
        subprocess.run(ssh + ['cd /home/dukto/budget-report-r130 && tar czf - results'],
                       stdout=destination, check=True, timeout=120)
    runpy.run_path(str(root / '.cache/validate-r121-glibc-qualified.py'))['extract'](archive, output)
    program = '''import hashlib,json,subprocess
from pathlib import Path
root=Path('/home/dukto/budget-report-r130')
manifest=json.loads((root/'.dukto-source-snapshot.json').read_bytes())['files']
actual={n:{'bytes':(root/n).stat().st_size,'sha256':hashlib.sha256((root/n).read_bytes()).hexdigest()} for n in manifest}
assert actual==manifest
assert '-std=c++14' in (root/'build/build.ninja').read_text()
print(json.dumps({'files':actual,'cpp14BuildFlagPresent':True,'compiler':subprocess.check_output(['c++','--version']).decode(),'qtVersion':subprocess.check_output(['qmake','-query','QT_VERSION']).decode().strip()}))
'''
    installed = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), capture_output=True, timeout=60)
    assert installed.returncode == 0, installed.stderr.decode('utf-8', 'replace')
    actual = json.loads(installed.stdout)
    manifest, _ = helper['read_archive'](snapshot)
    assert actual['files'] == manifest['files']
    (output / 'installed-source.json').write_bytes(installed.stdout)
    inputs = {row['path']: hashlib.sha256((root / row['path']).read_bytes()).hexdigest() for row in json.loads((root / 'docs/ci-verification-20261108-r129.json').read_bytes())['qualificationInputs']}
    assert len(inputs) == 295
    assert all(actual['files'][name]['sha256'] == sha for name, sha in inputs.items())
    assert (output / 'results/before.sha256').read_bytes() == (output / 'results/after.sha256').read_bytes()
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'driverExitCode': result.returncode,
             'snapshotSha256': created['archiveSha256'], 'allInstalledSourceInputsUnchanged': True,
             'actualSourceFileCount': len(actual['files']), 'qualificationInputsUnchanged': 295,
             'cpp14BuildFlagPresent': True, 'fullCoreQualified': False, 'binariesUnchanged': True,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False, 'passed': False}
    if result.returncode == 0:
        tree = ET.fromstring((output / 'results/state-budget-tests.xml').read_bytes())
        assert tree.tag == 'TestCase' and tree.get('name') == 'StateBudgetTests'
        methods = tree.findall('TestFunction')
        assert len(methods) == 4 and not tree.findall('.//Message')
        for method in methods:
            incidents = method.findall('Incident')
            assert len(incidents) == 1 and incidents[0].get('type') == 'pass'
        assert 'Totals: 4 passed, 0 failed, 0 skipped' in (output / 'results/state-budget-tests.log').read_text('utf-8-sig')
        value.update(passed=True, methodsPassed=4, warnings=0, skipped=0,
                     nativeLedgerReportBranchesExecuted=True)
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

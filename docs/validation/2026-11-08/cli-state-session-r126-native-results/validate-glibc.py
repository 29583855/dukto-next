"""日期：2026-11-08；独立Ubuntu新目录真实构建CLI和状态会话专项，保留13条原XML及全部输入。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path.cwd()


# 日期：2026-11-08；只写新建任务目录，源快照逐字节安装，不改已有长测环境或执行文件。
def main():
    ssh = runpy.run_path(str(ROOT / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    helper = runpy.run_path(str(ROOT / 'scripts/source_snapshot.py'))
    output = ROOT / '.cache/r126-glibc'
    output.mkdir(exist_ok=False)
    snapshot = ROOT / '.cache/r126-native-session-source.tar.gz'
    created = helper['create'](ROOT, snapshot)
    (output / 'snapshot-receipt.json').write_text(json.dumps(created, indent=2) + '\n', 'utf-8')
    sha = created['archiveSha256']
    for local, remote in [(snapshot, '/home/dukto/source-state-session-r126.tar.gz'),
                          (ROOT / 'scripts/source_snapshot.py', '/home/dukto/install-state-session-r126.py')]:
        with local.open('rb') as data:
            subprocess.run(ssh + ['set -C; cat > ' + remote], stdin=data, check=True, timeout=120)
    program = r"""set -eu
mkdir /home/dukto/state-session-r126
cd /home/dukto/state-session-r126
mkdir results
printf '%s  /home/dukto/source-state-session-r126.tar.gz\n' SNAPSHOT_SHA | sha256sum -c -
python3 /home/dukto/install-state-session-r126.py install /home/dukto/source-state-session-r126.tar.gz --root /home/dukto/state-session-r126 > results/source-install.json
cp .dukto-source-snapshot.json results/source-manifest.json
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DDUKTO_BUILD_GUI=OFF > results/configure.log 2>&1
cmake --build build --target dukto-cli state-session-tests --parallel 2 > results/build.log 2>&1
sha256sum build/dukto-cli build/state-session-tests > results/before.sha256
set +e
build/state-session-tests -o results/state-session-tests.log,txt -o results/state-session-tests.xml,xml -o results/state-session-tests-junit.xml,junitxml > results/test-driver.log 2>&1
code=$?
printf '%s\n' "$code" > results/test-exit.txt
sha256sum build/dukto-cli build/state-session-tests > results/after.sha256
cmp results/before.sha256 results/after.sha256 || code=99
exit "$code"
""".replace('SNAPSHOT_SHA', sha)
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(ssh + ['sh -s'], input=program.encode('utf-8'), stdout=log,
                                stderr=subprocess.STDOUT, timeout=3600)
    archive = output / 'results.tar.gz'
    with archive.open('xb') as destination:
        subprocess.run(ssh + ['cd /home/dukto/state-session-r126 && tar czf - results'],
                       stdout=destination, check=True, timeout=120)
    runpy.run_path(str(ROOT / '.cache/validate-r121-glibc-qualified.py'))['extract'](archive, output)
    program = r"""import hashlib,json,subprocess
from pathlib import Path
root=Path('/home/dukto/state-session-r126')
manifest=json.loads((root/'.dukto-source-snapshot.json').read_bytes())
actual={name:{'bytes':(root/name).stat().st_size,'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest()} for name in manifest['files']}
assert actual==manifest['files']
assert '-std=c++14' in (root/'build/build.ninja').read_text()
print(json.dumps({'files':actual,'cpp14BuildFlagPresent':True,'compiler':subprocess.check_output(['c++','--version']).decode(),'qtVersion':subprocess.check_output(['qmake','-query','QT_VERSION']).decode().strip()}))
"""
    installed = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), capture_output=True, timeout=60)
    assert installed.returncode == 0, installed.stderr.decode('utf-8', 'replace')
    actual = json.loads(installed.stdout)
    manifest, _ = helper['read_archive'](snapshot)
    assert actual['files'] == manifest['files']
    (output / 'installed-source.json').write_bytes(installed.stdout)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'driverExitCode': result.returncode,
             'snapshotSha256': sha, 'allInstalledSourceInputsUnchanged': True, 'cpp14BuildFlagPresent': True,
             'actualSourceFileCount': len(manifest['files']), 'fullCoreQualified': False,
             'cliLifecycleIntegrated': True, 'guiRootsIntegrated': False,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False, 'passed': False}
    if result.returncode == 0:
        assert (output / 'results/before.sha256').read_bytes() == (output / 'results/after.sha256').read_bytes()
        value.update(runpy.run_path(str(ROOT / 'scripts/ci_state_session.py'))['verify_xml'](output / 'results/state-session-tests.xml'))
        value['passed'] = True
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

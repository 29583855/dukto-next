"""日期：2026-11-08；独立Ubuntu目录从冻结快照编译真实CLI/观察程序，不干扰既有长期进程。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy
import subprocess
import tarfile

ROOT = Path.cwd()


# 日期：2026-11-08；仅提取普通有界报告，禁止链接/路径越界，原件在新目录保存。
def extract(archive, output):
    with tarfile.open(archive) as package:
        seen = set()
        for member in package:
            name = PurePosixPath(member.name)
            assert not name.is_absolute() and '..' not in name.parts and ':' not in member.name
            assert member.name not in seen and not member.issym() and not member.islnk()
            seen.add(member.name)
            if member.isdir():
                continue
            assert member.isfile() and member.size <= 32 * 1024**2
            target = output / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            assert not target.exists()
            target.write_bytes(package.extractfile(member).read())


# 日期：2026-11-08；独立目录/运行目录均禁止覆盖，构建后的程序摘要和输入验证分别保留。
def main():
    ssh = runpy.run_path(str(ROOT / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    output = ROOT / '.cache/r121-glibc-qualified'
    output.mkdir(exist_ok=False)
    snapshot = ROOT / '.cache/r121-native-state-source.tar.gz'
    sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with snapshot.open('rb') as data:
        subprocess.run(ssh + ['set -C; cat > /home/dukto/source-state-inventory-r121-qualified.tar.gz'], stdin=data, check=True, timeout=120)
    with (ROOT / 'scripts/source_snapshot.py').open('rb') as data:
        subprocess.run(ssh + ['set -C; cat > /home/dukto/install-state-inventory-r121-qualified.py'], stdin=data, check=True, timeout=30)
    program = r'''set -eu
mkdir /home/dukto/state-inventory-r121-qualified
cd /home/dukto/state-inventory-r121-qualified
mkdir results
printf '%s  /home/dukto/source-state-inventory-r121-qualified.tar.gz\n' SNAPSHOT_SHA | sha256sum -c -
python3 /home/dukto/install-state-inventory-r121-qualified.py install /home/dukto/source-state-inventory-r121-qualified.tar.gz --root /home/dukto/state-inventory-r121-qualified > results/source-install.json
cp .dukto-source-snapshot.json results/source-manifest.json
mkdir /tmp/runtime-state-inventory-r121-qualified
chmod 700 /tmp/runtime-state-inventory-r121-qualified
export XDG_RUNTIME_DIR=/tmp/runtime-state-inventory-r121-qualified QT_QPA_PLATFORM=offscreen
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DDUKTO_BUILD_GUI=OFF > results/configure.log 2>&1
cmake --build build --target dukto-cli state-storage-tests --parallel 2 > results/build.log 2>&1
sha256sum build/dukto-cli build/state-storage-tests > results/before.sha256
set +e
ctest --test-dir build -R '^state-storage-tests$' --output-on-failure --output-log results/ctest.log > results/ctest-driver.log 2>&1
code=$?
printf '%s\n' "$code" > results/ctest-exit.txt
sha256sum build/dukto-cli build/state-storage-tests > results/after.sha256
cmp results/before.sha256 results/after.sha256 || code=99
exit "$code"
'''.replace('SNAPSHOT_SHA', sha)
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(ssh + ['sh -s'], input=program.encode('utf-8'), stdout=log,
                                stderr=subprocess.STDOUT, timeout=3600)
    archive = output / 'results.tar.gz'
    with archive.open('xb') as destination:
        subprocess.run(ssh + ['cd /home/dukto/state-inventory-r121-qualified && tar czf - results build/Testing/QtTest'],
                       stdout=destination, check=True, timeout=120)
    extract(archive, output)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'driverExitCode': result.returncode,
             'snapshotSha256': sha, 'qualifiedByFrozenSnapshotInputs': True,
             'fullCoreQualified': False, 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        assert (output / 'results/before.sha256').read_bytes() == (output / 'results/after.sha256').read_bytes()
        verify = runpy.run_path(str(ROOT / 'scripts/ci_state_inventory.py'))['verify_xml']
        verify.__globals__['os'] = type('Platform', (), {'name': 'posix'})
        value.update(verify(output / 'build/Testing/QtTest/state-storage-tests.xml'))
        assert value['rowsPassed'] == 15 and value['permissionRowsSkipped'] == 0
        value['stateInventoryQualified'] = True
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()

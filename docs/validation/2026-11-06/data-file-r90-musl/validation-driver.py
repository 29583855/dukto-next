"""日期：2026-11-06；独立Alpine目录构建冻结源码，验证数据文件额度和POSIX路径元数据核验。"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path.cwd()
OUTPUT = ROOT / 'docs/validation/2026-11-06/data-file-r90-musl'
SNAPSHOT = ROOT / '.cache/source-data-file-r90.tar.gz'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'UserKnownHostsFile=.tools/linux-vm/known_hosts-v2', '-i', '.tools/linux-vm/id_ed25519',
       '-p', '22024', 'dukto@127.0.0.1']


# 日期：2026-11-06；仅提取本次普通日志/报告，拒绝绝对路径、父路径及全部链接。
def extract(path):
    with tarfile.open(path) as archive:
        for item in archive:
            name = PurePosixPath(item.name)
            assert not name.is_absolute() and '..' not in name.parts and ':' not in item.name
            assert not item.issym() and not item.islnk()
            if item.isfile():
                assert item.size <= 32 * 1024**2
                target = OUTPUT / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(item).read())
            else:
                assert item.isdir()


# 日期：2026-11-06；只创建新目录和新文件，不替换任何历史二进制或长测输入。
def main():
    OUTPUT.mkdir(exist_ok=False)
    with (OUTPUT / 'snapshot-create.json').open('x', encoding='utf-8') as log:
        subprocess.run(['python', '-X', 'utf8', 'scripts/source_snapshot.py', 'create', str(SNAPSHOT)],
                       stdout=log, check=True)
    sha = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    with SNAPSHOT.open('rb') as data:
        subprocess.run(SSH + ['set -C; cat > /home/dukto/source-data-file-r90.tar.gz'],
                       stdin=data, check=True, timeout=120)
    with (ROOT / 'scripts/source_snapshot.py').open('rb') as data:
        subprocess.run(SSH + ['set -C; cat > /home/dukto/source-install-data-file-r90.py'],
                       stdin=data, check=True, timeout=30)
    script = r'''set -eu
mkdir /home/dukto/data-file-r90
cd /home/dukto/data-file-r90
mkdir results
printf '%s  /home/dukto/source-data-file-r90.tar.gz\n' SNAPSHOT_SHA | sha256sum -c -
python3 /home/dukto/source-install-data-file-r90.py install /home/dukto/source-data-file-r90.tar.gz --root /home/dukto/data-file-r90 > results/source-install.json
cp .dukto-source-snapshot.json results/source-manifest.json
mkdir /tmp/runtime-dukto-data-file-r90
chmod 700 /tmp/runtime-dukto-data-file-r90
export QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/tmp/runtime-dukto-data-file-r90
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release > results/configure.log 2>&1
cmake --build build --parallel 2 > results/build.log 2>&1
sha256sum build/dukto-cli build/dukto-gui build/file-exchange-tests > results/binaries-before.sha256
status=0
set +e
run_check() {
    name="$1"
    shift
    "$@" > "results/$name.log" 2>&1
    code=$?
    printf '%s %s\n' "$name" "$code" >> results/exit-codes.txt
    printf '%s exit=%s\n' "$name" "$code"
    if test "$code" -ne 0; then status=1; fi
}
run_check ctest ctest --test-dir build --output-on-failure
run_check legacy python3 tests/legacy_integration.py build/dukto-cli --report results/legacy.json
run_check parallel-transfer python3 tests/parallel_transfer_integration.py build/dukto-cli --report results/parallel-transfer.json
run_check conflict-overwrite python3 tests/conflict_overwrite_integration.py build/dukto-cli --report results/conflict-overwrite.json
sha256sum build/dukto-cli build/dukto-gui build/file-exchange-tests > results/binaries-after.sha256
cmp results/binaries-before.sha256 results/binaries-after.sha256 || status=1
exit "$status"
'''.replace('SNAPSHOT_SHA', sha)
    with (OUTPUT / 'driver.log').open('xb') as log:
        code = subprocess.run(SSH + ['sh -s'], input=script.encode('utf-8'), stdout=log,
                              stderr=subprocess.STDOUT, timeout=14400).returncode
    archive = OUTPUT / 'results.tar.gz'
    with archive.open('xb') as log:
        subprocess.run(SSH + ['cd /home/dukto/data-file-r90 && tar czf - results build/Testing/QtTest'],
                       stdout=log, check=True, timeout=120)
    extract(archive)
    result = {'date': '2026-11-06', 'exitCode': code, 'sourceSnapshotSha256': sha,
              'remoteRoot': '/home/dukto/data-file-r90', 'originalReportsPreserved': True,
              'publicSkipEnabled': False, 'releaseQualified': False, 'deliveryComplete': False}
    (OUTPUT / 'driver-result.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

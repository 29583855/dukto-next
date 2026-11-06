"""日期：2026-11-06；独立Alpine目录构建R94冻结源码，验证全文分页/复制/历史和有界GUI内存。"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path.cwd()
OUTPUT = ROOT / 'docs/validation/2026-11-06/text-view-r94-musl'
SNAPSHOT = ROOT / '.cache/source-text-view-r94.tar.gz'
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
    assert SNAPSHOT.is_file()
    sha = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    with SNAPSHOT.open('rb') as data:
        subprocess.run(SSH + ['set -C; cat > /home/dukto/source-text-view-r94.tar.gz'],
                       stdin=data, check=True, timeout=120)
    with (ROOT / 'scripts/source_snapshot.py').open('rb') as data:
        subprocess.run(SSH + ['set -C; cat > /home/dukto/source-install-text-view-r94.py'],
                       stdin=data, check=True, timeout=30)
    script = r'''set -eu
mkdir /home/dukto/text-view-r94
cd /home/dukto/text-view-r94
mkdir results
printf '%s  /home/dukto/source-text-view-r94.tar.gz\n' SNAPSHOT_SHA | sha256sum -c -
python3 /home/dukto/source-install-text-view-r94.py install /home/dukto/source-text-view-r94.tar.gz --root /home/dukto/text-view-r94 > results/source-install.json
cp .dukto-source-snapshot.json results/source-manifest.json
mkdir /tmp/runtime-dukto-text-view-r94
chmod 700 /tmp/runtime-dukto-text-view-r94
export QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/tmp/runtime-dukto-text-view-r94
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release > results/configure.log 2>&1
cmake --build build --parallel 2 > results/build.log 2>&1
sha256sum build/dukto-cli build/dukto-gui build/core-tests > results/binaries-before.sha256
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
run_check text-preview python3 tests/text_preview_integration.py build/ui-tests --report results/text-preview.json
run_check legacy-text-credit python3 tests/legacy_text_credit_integration.py build/dukto-cli --report results/legacy-text-credit.json
run_check legacy python3 tests/legacy_integration.py build/dukto-cli --report results/legacy.json
sha256sum build/dukto-cli build/dukto-gui build/core-tests > results/binaries-after.sha256
cmp results/binaries-before.sha256 results/binaries-after.sha256 || status=1
exit "$status"
'''.replace('SNAPSHOT_SHA', sha)
    with (OUTPUT / 'driver.log').open('xb') as log:
        code = subprocess.run(SSH + ['sh -s'], input=script.encode('utf-8'), stdout=log,
                              stderr=subprocess.STDOUT, timeout=14400).returncode
    archive = OUTPUT / 'results.tar.gz'
    with archive.open('xb') as log:
        subprocess.run(SSH + ['cd /home/dukto/text-view-r94 && tar czf - results build/Testing/QtTest'],
                       stdout=log, check=True, timeout=120)
    extract(archive)
    result = {'date': '2026-11-06', 'exitCode': code, 'sourceSnapshotSha256': sha,
              'remoteRoot': '/home/dukto/text-view-r94', 'originalReportsPreserved': True,
              'publicSkipEnabled': True, 'releaseQualified': False, 'deliveryComplete': False}
    (OUTPUT / 'driver-result.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

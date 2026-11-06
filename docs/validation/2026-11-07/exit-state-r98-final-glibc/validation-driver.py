"""日期：2026-11-07；独立Ubuntu glibc目录构建R98最终冻结源码，验证完整核心、监听冲突、优雅重启和原并行退出。"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path.cwd()
OUTPUT = ROOT / 'docs/validation/2026-11-07/exit-state-r98-final-glibc'
SNAPSHOT = ROOT / '.cache/source-exit-state-r98-final.tar.gz'
SSH = ['C:/Windows/System32/OpenSSH/ssh.exe', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
       '-o', 'UserKnownHostsFile=.tools/linux-glibc-vm/known_hosts', '-i', '.tools/linux-vm/id_ed25519',
       '-p', '22026', 'dukto@127.0.0.1']


# 日期：2026-11-07；仅提取本次普通日志/报告，拒绝绝对路径、父路径及全部链接。
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


# 日期：2026-11-07；只创建新目录和新文件，不替换任何历史二进制或长测输入。
def main():
    OUTPUT.mkdir(exist_ok=False)
    assert SNAPSHOT.is_file()
    sha = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    with SNAPSHOT.open('rb') as data:
        subprocess.run(SSH + ['set -C; cat > /home/dukto/source-exit-state-r98-final.tar.gz'],
                       stdin=data, check=True, timeout=120)
    with (ROOT / 'scripts/source_snapshot.py').open('rb') as data:
        subprocess.run(SSH + ['set -C; cat > /home/dukto/source-install-exit-state-r98-final.py'],
                       stdin=data, check=True, timeout=30)
    script = r'''set -eu
mkdir /home/dukto/exit-state-r98-final
cd /home/dukto/exit-state-r98-final
mkdir results
printf '%s  /home/dukto/source-exit-state-r98-final.tar.gz\n' SNAPSHOT_SHA | sha256sum -c -
python3 /home/dukto/source-install-exit-state-r98-final.py install /home/dukto/source-exit-state-r98-final.tar.gz --root /home/dukto/exit-state-r98-final > results/source-install.json
cp .dukto-source-snapshot.json results/source-manifest.json
mkdir /tmp/runtime-dukto-exit-state-r98-final
chmod 700 /tmp/runtime-dukto-exit-state-r98-final
export QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/tmp/runtime-dukto-exit-state-r98-final
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release > results/configure.log 2>&1
cmake --build build --parallel 2 > results/build.log 2>&1
sha256sum build/dukto-cli build/dukto-gui build/core-tests build/file-exchange-tests > results/binaries-before.sha256
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
run_check listener build/core-tests exclusiveTcpBinding tcpAddressFamilies tcpGracefulRestart -o results/listener-qt.log,txt -o results/listener-qt.xml,junitxml
run_check exit-states build/file-exchange-tests childExitWait parallelDispositions -o results/exit-states-qt.log,txt -o results/exit-states-qt.xml,junitxml
sha256sum build/dukto-cli build/dukto-gui build/core-tests build/file-exchange-tests > results/binaries-after.sha256
cmp results/binaries-before.sha256 results/binaries-after.sha256 || status=1
exit "$status"
'''.replace('SNAPSHOT_SHA', sha)
    with (OUTPUT / 'driver.log').open('xb') as log:
        code = subprocess.run(SSH + ['sh -s'], input=script.encode('utf-8'), stdout=log,
                              stderr=subprocess.STDOUT, timeout=14400).returncode
    archive = OUTPUT / 'results.tar.gz'
    with archive.open('xb') as log:
        subprocess.run(SSH + ['cd /home/dukto/exit-state-r98-final && tar czf - results build/Testing/QtTest'],
                       stdout=log, check=True, timeout=120)
    extract(archive)
    result = {'date': '2026-11-07', 'exitCode': code, 'sourceSnapshotSha256': sha,
              'sourceCommit': 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7',
              'actualPlatform': 'Ubuntu glibc',
              'remoteRoot': '/home/dukto/exit-state-r98-final', 'originalReportsPreserved': True,
              'publicSkipEnabled': True, 'releaseQualified': False, 'deliveryComplete': False}
    (OUTPUT / 'driver-result.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

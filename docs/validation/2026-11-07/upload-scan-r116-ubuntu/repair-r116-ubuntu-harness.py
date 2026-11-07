"""日期：2026-11-07；保留独立验证工程首轮链接原件，补齐Qt元对象并以当前已修正测试复验。"""
from pathlib import Path
import base64
import json
import runpy
import subprocess

ROOT = Path.cwd()
OUT = ROOT / '.cache/upload-scan-r116-ubuntu'
REMOTE = '/home/dukto/upload-scan-r116-validation'


# 日期：2026-11-07；在同一隔离目录保留失败输入与日志，再仅补验证工程和测试，不修改核心产品源。
def main():
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    test = (ROOT / 'tests/upload_scan_cleanup_tests.cpp').read_bytes()
    program = '''from pathlib import Path
import base64,hashlib,json,shutil,subprocess
root=Path('/home/dukto/upload-scan-r116-validation')
processes=subprocess.check_output(['ps','-eo','args']).decode().splitlines()
assert not any(line.startswith(('cmake --build build','/usr/bin/cmake --build build')) for line in processes)
backup=root/'first-link-failure'
backup.mkdir(exist_ok=False)
for name in ['CMakeLists.txt','configure.log','build.log','frozen-objects-verified.json','missing-original-objects.json','tests/upload_scan_cleanup_tests.cpp']:
    path=root/name
    target=backup/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(path,target)
cmake=(root/'CMakeLists.txt').read_bytes()
assert b'    src/core/service.h\\n' not in cmake
cmake=cmake.replace(b'add_library(candidate STATIC\\n',b'add_library(candidate STATIC\\n    src/core/service.h\\n',1)
(root/'CMakeLists.txt').write_bytes(cmake)
test=base64.b64decode('TEST_BASE64')
(root/'tests/upload_scan_cleanup_tests.cpp').write_bytes(test)
print(json.dumps({'testSha256':hashlib.sha256(test).hexdigest(),'cmakeSha256':hashlib.sha256(cmake).hexdigest(),'priorFailurePreserved':True}))
'''.replace('TEST_BASE64', base64.b64encode(test).decode())
    result = subprocess.run(ssh + ['python3 -'], input=program.encode(), capture_output=True, timeout=30)
    (OUT / 'repair-harness.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    print(result.stdout.decode(), flush=True)
    script = '''set -eu
cd /home/dukto/upload-scan-r116-validation
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release > configure-verified.log 2>&1
nice -n 10 cmake --build build --parallel 2 > build-verified.log 2>&1
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-before.sha256
set +e
build/upload-scan-cleanup-tests -o qt.log,txt -o qt.xml,junitxml
test_result=$?
set -e
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-after.sha256
cmp binaries-before.sha256 binaries-after.sha256
printf '%s\\n' "$test_result" > test-exit-code.txt
exit "$test_result"
'''
    with (OUT / 'driver-verified.log').open('xb') as log:
        result = subprocess.run(ssh + ['sh -s'], input=script.encode(), stdout=log,
                                stderr=subprocess.STDOUT, timeout=600)
    for name in ['configure-verified.log', 'build-verified.log', 'qt.log', 'qt.xml',
                 'binaries-before.sha256', 'binaries-after.sha256', 'test-exit-code.txt', 'CMakeLists.txt']:
        fetched = subprocess.run(ssh + ['cat ' + REMOTE + '/' + name], capture_output=True, timeout=30)
        if fetched.returncode == 0:
            (OUT / name).write_bytes(fetched.stdout)
    print(json.dumps({'driverExitCode': result.returncode}), flush=True)
    assert result.returncode == 0


if __name__ == '__main__':
    main()

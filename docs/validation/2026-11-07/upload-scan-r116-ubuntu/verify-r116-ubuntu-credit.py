"""日期：2026-11-07；保留上一轮完整通过原件，独立Ubuntu增量编译真实资源失败修正。"""
import base64
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；只在前一构建结束后冻结新输入，保留真实失败/通过历史及编译前后程序摘要。
def main():
    root = Path.cwd()
    output = root / '.cache/upload-scan-r116-ubuntu'
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    names = ['src/core/uploadmanifest.cpp', 'tests/upload_scan_cleanup_tests.cpp']
    files = {name: base64.b64encode((root / name).read_bytes()).decode() for name in names}
    program = '''from pathlib import Path
import base64,hashlib,json,shutil
root=Path('/home/dukto/upload-scan-r116-validation')
backup=root/'before-credit-regression'
backup.mkdir(exist_ok=False)
for name in ['CMakeLists.txt','configure-verified.log','build-verified.log','qt.log','qt.xml','test-exit-code.txt','binaries-before.sha256','binaries-after.sha256','src/core/uploadmanifest.cpp','tests/upload_scan_cleanup_tests.cpp']:
    target=backup/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/name,target)
files=FILES
for name,data in files.items():
    (root/name).write_bytes(base64.b64decode(data))
inputs={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}
(root/'final-candidate-inputs.json').write_text(json.dumps(inputs,indent=2)+'\\n')
print(json.dumps(inputs))
'''.replace('FILES', repr(files))
    result = subprocess.run(ssh + ['python3 -'], input=program.encode(), capture_output=True, timeout=30)
    (output / 'final-input-upload.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0
    print(result.stdout.decode(), flush=True)
    script = '''set -eu
cd /home/dukto/upload-scan-r116-validation
nice -n 10 cmake --build build --parallel 2 > build-credit-fixed.log 2>&1
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-credit-before.sha256
set +e
build/upload-scan-cleanup-tests -o qt-credit-fixed.log,txt -o qt-credit-fixed.xml,junitxml
test_result=$?
set -e
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-credit-after.sha256
cmp binaries-credit-before.sha256 binaries-credit-after.sha256
printf '%s\\n' "$test_result" > test-credit-exit-code.txt
exit "$test_result"
'''
    with (output / 'driver-credit-fixed.log').open('xb') as log:
        result = subprocess.run(ssh + ['sh -s'], input=script.encode(), stdout=log,
                                stderr=subprocess.STDOUT, timeout=600)
    for name in ['build-credit-fixed.log', 'qt-credit-fixed.log', 'qt-credit-fixed.xml',
                 'binaries-credit-before.sha256', 'binaries-credit-after.sha256',
                 'test-credit-exit-code.txt', 'final-candidate-inputs.json']:
        fetched = subprocess.run(ssh + ['cat /home/dukto/upload-scan-r116-validation/' + name],
                                 capture_output=True, timeout=30)
        if fetched.returncode == 0:
            (output / name).write_bytes(fetched.stdout)
    print(json.dumps({'driverExitCode': result.returncode}), flush=True)
    assert result.returncode == 0
    expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    assert json.loads((output / 'final-candidate-inputs.json').read_bytes()) == expected


if __name__ == '__main__':
    main()

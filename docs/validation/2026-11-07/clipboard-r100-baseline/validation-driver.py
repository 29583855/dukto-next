"""日期：2026-11-07；在未改生产代码上执行隔离QML剪贴板回归，保留编译和预期产品失败原件。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；旧生产源码须逐字节不变，只有真正执行到正文读取断言才能证明原缺陷。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/clipboard-r100-baseline'
    output.mkdir(exist_ok=False)
    for name in ('src/app/controller.cpp', 'src/app/controller.h'):
        assert (root / name).read_bytes() == (root / '.cache/clipboard-r100-before' / name).read_bytes()
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']('msvc')
    with (output / 'build.log').open('xb') as log:
        build = subprocess.run([str(root / '.tools/python/Scripts/cmake.exe'), '--build', str(root / 'build/windows'),
                                '--config', 'Release', '--target', 'ui-tests', '--parallel', '2'],
                               env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    code = None
    if build.returncode == 0:
        with (output / 'process.log').open('xb') as log:
            process = subprocess.run([str(root / 'build/windows/Release/ui-tests.exe'),
                                      'clipboardAvailabilityDoesNotReadOnProgress',
                                      '-o', str(output / 'qt.log') + ',txt',
                                      '-o', str(output / 'qt.xml') + ',junitxml'],
                                     env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=120)
        code = process.returncode
    value = {'date': '2026-11-07', 'productionCommit': 'a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38',
             'buildExitCode': build.returncode, 'testExitCode': code,
             'sourceFiles': [{'path': name, 'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest()}
                             for name in ('src/app/controller.cpp', 'src/app/controller.h', 'tests/ui_tests.cpp')],
             'originalsPreserved': True}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    shutil.copyfile(root / '.cache/prepare-clipboard-r100-baseline.py', output / 'test-preparation-driver.py')
    shutil.copyfile(root / '.cache/clipboard-r100-before/source-before.json', output / 'production-source-before.json')
    print(json.dumps(value), flush=True)
    assert build.returncode == 0 and code == 1
    text = (output / 'qt.log').read_text('utf-8')
    assert 'FAIL!  : UiTests::clipboardAvailabilityDoesNotReadOnProgress() Compared values are not the same' in text
    assert 'Actual   (*reads)' in text and 'Expected (before)' in text
    print('Original repeated clipboard-body requests reproduced through production QML', flush=True)


if __name__ == '__main__':
    main()

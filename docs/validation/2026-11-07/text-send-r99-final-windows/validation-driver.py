"""日期：2026-11-07；最终GUI收尾重建四相关测试，逐摘要确认其余十九个完整回归二进制未变。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

GUI_TESTS = {'controller-tests', 'ui-tests', 'server-panel-tests', 'avatars-tests'}


# 日期：2026-11-07；文件内容逐字节取摘要，清单只保存公开测试与源码身份。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-07；初轮23目标全部成功后验证最终修改，真实终态与原件保持分立。
def main():
    root = Path.cwd()
    first = root / 'docs/validation/2026-11-07/text-send-r99-windows'
    driver = json.loads((first / 'driver-result.json').read_text('utf-8'))
    assert driver['passed'] and driver['buildInputsUnchanged']
    output = root / 'docs/validation/2026-11-07/text-send-r99-final-windows'
    output.mkdir(exist_ok=False)
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']
    original_inputs = json.loads((first / 'build-inputs.json').read_text('utf-8'))
    inputs = [{'path': row['path'], 'sha256': sha(root / row['path'])} for row in original_inputs]
    (output / 'build-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', 'utf-8')
    changed = {a['path'] for a, b in zip(inputs, original_inputs) if a != b}
    assert changed == {'src/app/controller.cpp', 'ui/Main.qml', 'tests/ui_tests.cpp'}, changed
    results = []
    for label, folder, cmake, ctest, extra in [
            ('ucrt', 'windows-ucrt', '.tools/msys64/ucrt64/bin/cmake.exe', '.tools/msys64/ucrt64/bin/ctest.exe', []),
            ('msvc', 'windows', '.tools/python/Scripts/cmake.exe', '.tools/python/Scripts/ctest.exe', ['-C', 'Release'])]:
        target = output / label
        target.mkdir()
        command = [str(root / ctest), '--test-dir', str(root / 'build' / folder), *extra]
        description = json.loads(subprocess.check_output(command + ['--show-only=json-v1'], env=environment(label)))
        binaries = {row['name']: Path(row['command'][0]) for row in description['tests']}
        assert len(binaries) == 23 and GUI_TESTS <= set(binaries)
        before = {name: sha(path) for name, path in binaries.items() if name not in GUI_TESTS}
        assert len(before) == 19
        with (target / 'build.log').open('xb') as log:
            build = subprocess.run([str(root / cmake), '--build', str(root / 'build' / folder),
                                    '--config', 'Release', '--parallel', '2'],
                                   env=environment(label), stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        after = {name: sha(binaries[name]) for name in before}
        assert before == after
        code = None
        if build.returncode == 0:
            with (target / 'ctest.log').open('xb') as log:
                process = subprocess.run(command + ['--output-on-failure', '-R',
                    '^(controller-tests|ui-tests|server-panel-tests|avatars-tests)$'],
                    env=environment(label), stdout=log, stderr=subprocess.STDOUT, timeout=600)
            code = process.returncode
            (target / 'QtTest').mkdir()
            for name in GUI_TESTS:
                for suffix in ('.xml', '.log'):
                    shutil.copyfile(root / 'build' / folder / 'Testing/QtTest' / (name + suffix),
                                    target / 'QtTest' / (name + suffix))
            shutil.copyfile(root / 'build' / folder / 'Testing/Temporary/LastTest.log', target / 'LastTest.log')
        result = {'toolchain': label, 'buildExitCode': build.returncode, 'ctestExitCode': code,
                  'unchangedCoreTestBinaries': before, 'finalGuiTargets': sorted(GUI_TESTS),
                  'passed': build.returncode == 0 and code == 0}
        results.append(result)
        print(json.dumps({key: result[key] for key in ('toolchain', 'passed', 'buildExitCode', 'ctestExitCode')}), flush=True)
    unchanged = all(sha(root / row['path']) == row['sha256'] for row in inputs)
    value = {'date': '2026-11-07', 'cases': results, 'buildInputsUnchanged': unchanged,
             'changedSinceFullRegression': sorted(changed),
             'passed': unchanged and all(row['passed'] for row in results),
             'cleanBuild': False, 'entireProtocolSuiteRun': False,
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

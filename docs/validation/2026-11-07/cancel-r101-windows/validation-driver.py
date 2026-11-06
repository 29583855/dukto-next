"""日期：2026-11-07；两Windows工具链完整构建，验证全部受影响GUI目标并绑定其余核心二进制。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；只在初轮已通过23目标且其余二进制逐SHA未变时，复用先前核心资格。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/cancel-r101-windows'
    output.mkdir(exist_ok=False)
    helper = runpy.run_path('.cache/validate-overwrite-r62.py')
    sha = runpy.run_path('.cache/validate-text-send-r99-final-windows.py')['sha']
    gui = {'controller-tests', 'ui-tests', 'server-panel-tests', 'avatars-tests'}
    original = json.loads((root / 'docs/ci-verification-20261107-r100.json').read_text('utf-8'))['buildInputs']
    inputs = [{'path': row['path'], 'sha256': sha(root / row['path'])} for row in original]
    changed = {a['path'] for a, b in zip(inputs, original) if a != b}
    assert changed == {'ui/Main.qml', 'tests/ui_tests.cpp'}
    (output / 'build-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', 'utf-8')
    results = []
    for label, folder, cmake, ctest, extra in [
            ('ucrt', 'windows-ucrt', '.tools/msys64/ucrt64/bin/cmake.exe', '.tools/msys64/ucrt64/bin/ctest.exe', []),
            ('msvc', 'windows', '.tools/python/Scripts/cmake.exe', '.tools/python/Scripts/ctest.exe', ['-C', 'Release'])]:
        environment = helper['environment'](label)
        target = output / label
        target.mkdir()
        command = [str(root / ctest), '--test-dir', str(root / 'build' / folder), *extra]
        description = json.loads(subprocess.check_output(command + ['--show-only=json-v1'], env=environment))
        binaries = {row['name']: Path(row['command'][0]) for row in description['tests']}
        assert len(binaries) == 23 and gui <= set(binaries)
        before = {name: sha(path) for name, path in binaries.items() if name not in gui}
        prior = json.loads((root / 'docs/validation/2026-11-07/clipboard-r100-windows/driver-result.json').read_text('utf-8'))
        previous, = [row for row in prior['cases'] if row['toolchain'] == label]
        assert previous['passed'] and before == previous['unchangedCoreTestBinaries'] and len(before) == 19
        with (target / 'build.log').open('xb') as log:
            build = subprocess.run([str(root / cmake), '--build', str(root / 'build' / folder),
                                    '--config', 'Release', '--parallel', '2'], env=environment,
                                   stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        after = {name: sha(binaries[name]) for name in before}
        assert before == after
        code = None
        if build.returncode == 0:
            with (target / 'ctest.log').open('xb') as log:
                process = subprocess.run(command + ['--output-on-failure', '-R',
                    '^(controller-tests|ui-tests|server-panel-tests|avatars-tests)$'], env=environment,
                    stdout=log, stderr=subprocess.STDOUT, timeout=600)
            code = process.returncode
            (target / 'QtTest').mkdir()
            for name in gui:
                for suffix in ('.xml', '.log'):
                    shutil.copyfile(root / 'build' / folder / 'Testing/QtTest' / (name + suffix),
                                    target / 'QtTest' / (name + suffix))
            shutil.copyfile(root / 'build' / folder / 'Testing/Temporary/LastTest.log', target / 'LastTest.log')
        result = {'toolchain': label, 'buildExitCode': build.returncode, 'ctestExitCode': code,
                  'guiTargets': sorted(gui), 'unchangedCoreTestBinaries': before,
                  'passed': build.returncode == 0 and code == 0}
        results.append(result)
        print(json.dumps({key: result[key] for key in ('toolchain', 'passed', 'buildExitCode', 'ctestExitCode')}), flush=True)
    unchanged = all(sha(root / row['path']) == row['sha256'] for row in inputs)
    value = {'date': '2026-11-07', 'cases': results, 'buildInputsUnchanged': unchanged,
             'changedBuildInputs': sorted(changed), 'cleanBuild': False, 'entireProtocolSuiteRun': False,
             'passed': unchanged and all(row['passed'] for row in results),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

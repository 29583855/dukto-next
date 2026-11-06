"""日期：2026-11-07；修正夹具后定向复验两个QML目标，未变核心程序与首轮原报告按SHA绑定。"""
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess
import sys


# 日期：2026-11-07；源输入前后冻结，失败原件保持；只复验修改导致重编译的QML和CLI。
def main():
    root = Path.cwd()
    first = root / 'docs/validation/2026-11-07/diagnostics-r103-windows'
    output = root / 'docs/validation/2026-11-07/diagnostics-r103-recheck'
    output.mkdir(exist_ok=False)
    before = json.loads((root / 'docs/validation/2026-11-07/diagnostics-r103-correction/previous-test-binaries.json').read_text('utf-8'))
    prior = json.loads((first / 'build-inputs.json').read_text('utf-8'))
    inputs = [{'path': row['path'], 'sha256': hashlib.sha256((root / row['path']).read_bytes()).hexdigest()} for row in prior]
    changed = sorted(a['path'] for a, b in zip(inputs, prior) if a != b)
    assert changed == ['scripts/ci_protocol.py', 'src/cli/main.cpp', 'tests/ui_tests.cpp', 'ui/Main.qml']
    (output / 'build-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', 'utf-8')
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']
    results = []
    for label, folder, cmake, ctest, extra in [
            ('ucrt', 'windows-ucrt', '.tools/msys64/ucrt64/bin/cmake.exe', '.tools/msys64/ucrt64/bin/ctest.exe', []),
            ('msvc', 'windows', '.tools/python/Scripts/cmake.exe', '.tools/python/Scripts/ctest.exe', ['-C', 'Release'])]:
        target = output / label
        target.mkdir()
        env = environment(label)
        row = {'toolchain': label}
        with (target / 'build.log').open('xb') as log:
            row['buildExitCode'] = subprocess.run([str(root / cmake), '--build', str(root / 'build' / folder), '--config', 'Release', '--parallel', '2'],
                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1800).returncode
        assert row['buildExitCode'] == 0
        binary = root / 'build' / folder
        if label == 'msvc':
            binary /= 'Release'
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in binary.glob('*-tests.exe')}
        different = sorted(name for name in after if before[label][name] != after[name])
        assert different == ['server-panel-tests.exe', 'ui-tests.exe'], different
        row['twentyOtherQtTestBinariesUnchanged'] = True
        row['changedQtTestBinaries'] = different
        row['testBinarySha256'] = after
        with (target / 'ctest.log').open('xb') as log:
            row['ctestExitCode'] = subprocess.run([str(root / ctest), '--test-dir', str(root / 'build' / folder), *extra,
                '--output-on-failure', '-R', '^(ui-tests|server-panel-tests)$'],
                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600).returncode
        (target / 'QtTest').mkdir()
        for name in ('ui-tests', 'server-panel-tests'):
            for extension in ('.xml', '.log'):
                shutil.copyfile(root / 'build' / folder / 'Testing/QtTest' / (name + extension), target / 'QtTest' / (name + extension))
        shutil.copyfile(root / 'build' / folder / 'Testing/Temporary/LastTest.log', target / 'LastTest.log')
        for name, script in [('doctor', 'doctor_integration'), ('cli-contracts', 'cli_contracts')]:
            with (target / (name + '.log')).open('xb') as log:
                row[name + 'ExitCode'] = subprocess.run([sys.executable, '-X', 'utf8', 'tests/' + script + '.py',
                    str(binary / 'dukto-cli.exe'), '--report', str(target / (name + '.json'))],
                    env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300).returncode
        human = subprocess.run([str(binary / 'dukto-cli.exe'), 'doctor'], env=env, capture_output=True, timeout=30)
        (target / 'doctor-human-output.txt').write_bytes(human.stdout)
        row['doctorHumanExitCode'] = human.returncode
        assert not human.stderr and b'dependencies [passed]' in human.stdout and b'configuration [passed]' in human.stdout
        row['passed'] = all(value == 0 for key, value in row.items() if key.endswith('ExitCode'))
        results.append(row)
        (output / 'progress.json').write_text(json.dumps(results, indent=2) + '\n', 'utf-8')
        print(json.dumps({key: value for key, value in row.items() if key != 'testBinarySha256'}), flush=True)
    unchanged = all(hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256'] for row in inputs)
    value = {'date': '2026-11-07', 'cases': results, 'buildInputsUnchanged': unchanged,
             'firstFailureRetained': True, 'freshFull23TargetsRerun': False,
             'passed': unchanged and all(row['passed'] for row in results), 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

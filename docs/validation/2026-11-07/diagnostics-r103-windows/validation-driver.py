"""日期：2026-11-07；冻结本轮输入后执行双Windows完整核心及真实CLI诊断专项。"""
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess
import sys


# 日期：2026-11-07；格式化保持原字节风格；测试运行期间固定所有构建与专项输入。
def main():
    root = Path.cwd()
    backup = root / '.cache/diagnostics-r103-originals'
    paths = [p.relative_to(backup) for p in backup.rglob('*') if p.suffix in ('.cpp', '.h')]
    paths += [Path('src/core/diagnostics.cpp'), Path('src/core/diagnostics.h')]
    formatter = str(root / '.tools/python/Scripts/clang-format.exe')
    for path in paths:
        raw = path.read_bytes()
        text = subprocess.check_output([formatter, str(path)]).decode('utf-8-sig').replace('\r\n', '\n')
        path.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') +
                         text.replace('\n', '\r\n' if b'\r\n' in raw else '\n').encode('utf-8'))
    subprocess.run([formatter, '--dry-run', '--Werror', *map(str, paths)], check=True)
    output = root / 'docs/validation/2026-11-07/diagnostics-r103-windows'
    output.mkdir(exist_ok=False)
    original = json.loads((root / 'docs/ci-verification-20261107-r102.json').read_text('utf-8'))['buildInputs']
    names = sorted({p['path'] for p in original} | {'src/core/diagnostics.cpp', 'src/core/diagnostics.h', 'tests/doctor_integration.py'})
    inputs = [{'path': p, 'sha256': hashlib.sha256((root / p).read_bytes()).hexdigest()} for p in names]
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
        command = [str(root / cmake), '--build', str(root / 'build' / folder), '--config', 'Release', '--parallel', '2']
        with (target / 'build.log').open('xb') as log:
            row['buildExitCode'] = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=2400).returncode
        if row['buildExitCode'] == 0:
            with (target / 'ctest.log').open('xb') as log:
                row['ctestExitCode'] = subprocess.run([str(root / ctest), '--test-dir', str(root / 'build' / folder), *extra, '--output-on-failure'],
                    env=env, stdout=log, stderr=subprocess.STDOUT, timeout=3600).returncode
            shutil.copytree(root / 'build' / folder / 'Testing/QtTest', target / 'QtTest')
            shutil.copyfile(root / 'build' / folder / 'Testing/Temporary/LastTest.log', target / 'LastTest.log')
            binary = root / 'build' / folder
            if label == 'msvc':
                binary /= 'Release'
            with (target / 'doctor.log').open('xb') as log:
                row['doctorExitCode'] = subprocess.run([sys.executable, '-X', 'utf8', 'tests/doctor_integration.py',
                    str(binary / 'dukto-cli.exe'), '--report', str(target / 'doctor.json')],
                    env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300).returncode
            with (target / 'cli-contracts.log').open('xb') as log:
                row['cliContractsExitCode'] = subprocess.run([sys.executable, '-X', 'utf8', 'tests/cli_contracts.py',
                    str(binary / 'dukto-cli.exe'), '--report', str(target / 'cli-contracts.json')],
                    env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300).returncode
        results.append(row)
        (output / 'progress.json').write_text(json.dumps(results, indent=2) + '\n', 'utf-8')
        print(json.dumps(row), flush=True)
    unchanged = all(hashlib.sha256((root / item['path']).read_bytes()).hexdigest() == item['sha256'] for item in inputs)
    value = {'date': '2026-11-07', 'cases': results, 'buildInputsUnchanged': unchanged,
             'passed': unchanged and all(len(row) == 5 and all(value == 0 for key, value in row.items() if key.endswith('ExitCode')) for row in results),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

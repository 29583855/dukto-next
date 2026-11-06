"""日期：2026-11-06；双Windows完整核心及真实R6/CLI回归，保留旧二进制和新原件。"""
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess
import sys

ROOT = Path.cwd()
OUT = ROOT / 'docs/validation/2026-11-06/discovery-r92-windows'
H = runpy.run_path('.cache/finalize-skip-items-r84.py')
ENV = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']


# 日期：2026-11-06；旧构建先复制到独立缓存，再完整编译；QtTest原报告逐份另存。
def validate(label):
    output = OUT / label
    output.mkdir()
    folder = ROOT / ('build/windows-ucrt' if label == 'ucrt' else 'build/windows')
    binary_dir = folder if label == 'ucrt' else folder / 'Release'
    saved = ROOT / '.cache/windows-before-r92' / label
    saved.mkdir(parents=True, exist_ok=False)
    old = []
    for name in ('dukto-cli.exe', 'dukto-gui.exe', 'core-tests.exe'):
        shutil.copyfile(binary_dir / name, saved / name)
        old.append({'name': name, 'sha256': hashlib.sha256((saved / name).read_bytes()).hexdigest()})
    tools = ROOT / ('.tools/msys64/ucrt64/bin' if label == 'ucrt' else '.tools/python/Scripts')
    env = ENV(label)
    build_config = [] if label == 'ucrt' else ['--config', 'Release']
    with (output / 'build.log').open('xb') as log:
        code = subprocess.run([str(tools / 'cmake.exe'), '--build', str(folder), *build_config,
                               '--parallel', '2'], env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    assert code == 0, label + ' build failed'
    ctest_config = [] if label == 'ucrt' else ['-C', 'Release']
    cases = []
    with (output / 'ctest.log').open('xb') as log:
        code = subprocess.run([str(tools / 'ctest.exe'), '--test-dir', str(folder), *ctest_config,
                               '--output-on-failure'], env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    shutil.copytree(folder / 'Testing/QtTest', output / 'QtTest')
    cases.append({'name': 'full-core', 'exitCode': code, 'passed': code == 0})
    for name, script in (('legacy', 'legacy_integration'), ('cli', 'cli_contracts')):
        report = output / (name + '.json')
        with (output / (name + '.log')).open('xb') as log:
            code = subprocess.run([sys.executable, '-X', 'utf8', 'tests/' + script + '.py',
                                   str(binary_dir / 'dukto-cli.exe'), '--report', str(report)],
                                  env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240).returncode
        value = json.loads(report.read_text('utf-8')) if report.exists() else None
        passed = value and (all(row.get('passed') is True for row in value)
                            if isinstance(value, list) else value.get('passed') is True)
        cases.append({'name': name, 'exitCode': code, 'passed': code == 0 and bool(passed),
                      'report': H['proof'](report) if value else None})
    row = {'toolchain': label, 'oldBinariesPreserved': old,
           'binary': H['proof'](binary_dir / 'dukto-cli.exe'), 'cases': cases,
           'passed': all(case['passed'] for case in cases)}
    (output / 'receipt.json').write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'toolchain': label, 'passed': row['passed'], 'cases': cases}), flush=True)
    return row


# 日期：2026-11-06；两套核心串行避免UDP测试相互干扰，输入摘要在测试前后必须一致。
def main():
    OUT.mkdir(exist_ok=False)
    inputs = [H['proof'](ROOT / name) for name in ('src/core/discovery.cpp', 'tests/core_tests.cpp')]
    rows = [validate(label) for label in ('ucrt', 'msvc')]
    assert inputs == [H['proof'](ROOT / row['path']) for row in inputs]
    value = {'date': '2026-11-06', 'inputs': inputs, 'testsAndTimeoutsUnchanged': True,
             'toolchains': rows, 'passed': all(row['passed'] for row in rows), 'deliveryComplete': False}
    (OUT / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    assert value['passed']


if __name__ == '__main__':
    main()

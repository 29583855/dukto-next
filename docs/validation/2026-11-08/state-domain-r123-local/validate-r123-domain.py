"""日期：2026-11-08；保留原始Qt XML并验证CI收验器，绑定完整输入和实际执行文件。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-08；已完成核心回归后以同一测试程序补原始XML，验证CI收验规则而不重编译。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    tag = parser.parse_args().toolchain
    root = Path.cwd()
    output = root / ('.cache/r123-focused-' + tag)
    output.mkdir(exist_ok=False)
    previous = json.loads((root / 'docs/ci-verification-20261108-r122.json').read_bytes())
    names = {row['path'] for row in previous['qualificationInputs']} | {
        'src/core/statedomain.h', 'src/core/statedomain.cpp', 'tests/state_domain_tests.cpp',
        'scripts/ci_state_domain.py', '.github/workflows/state-domain-regression.yml'}
    inputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(names)}
    binary = root / ('build/windows/Release' if tag == 'msvc' else 'build/windows-ucrt') / 'state-domain-tests.exe'
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    environment = os.environ.copy()
    bins = ['.tools/Qt/5.15.2/msvc2019_64/bin', '.tools/openssl/Library/bin'] if tag == 'msvc' else ['.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(str(root / name) for name in bins) + os.pathsep + environment['PATH']
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run([str(binary), '-o', str(output / 'state-domain-tests.xml') + ',xml',
                                 '-o', str(output / 'state-domain-tests.log') + ',txt'],
                                stdout=log, stderr=subprocess.STDOUT, env=environment, timeout=180)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'exitCode': result.returncode,
             'inputs': inputs, 'binaryBefore': before, 'binaryAfter': hashlib.sha256(binary.read_bytes()).hexdigest(),
             'inputsAfter': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs},
             'passed': False, 'globalQuotaEnforced': False, 'productionRootsIntegrated': False,
             'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        value.update(runpy.run_path(str(root / 'scripts/ci_state_domain.py'))['verify_xml'](output / 'state-domain-tests.xml'))
        value['passed'] = value['inputs'] == value['inputsAfter'] and value['binaryBefore'] == value['binaryAfter']
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value.get(key) for key in ['exitCode', 'rowsPassed', 'passed']}))
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

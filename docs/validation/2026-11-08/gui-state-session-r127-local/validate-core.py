"""日期：2026-11-08；构建真实GUI/CLI会话接入并保留全部核心结果，输出目录独立于R126。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


# 日期：2026-11-08；冻结全部291输入，测试结束核对程序和输入；原日志及失败不覆盖。
def main():
    root = Path.cwd()
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    parser.add_argument('--attempt', default='first')
    args = parser.parse_args()
    tag = args.toolchain
    output = root / '.cache' / ('r127-' + args.attempt + '-' + tag)
    output.mkdir(exist_ok=False)
    names = [row['path'] for row in json.loads((root / 'docs/ci-verification-20261108-r126.json').read_bytes())['qualificationInputs']]
    inputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    build = root / ('build/windows' if tag == 'msvc' else 'build/windows-ucrt')
    environment = os.environ.copy()
    bins = [root / '.tools/Qt/5.15.2/msvc2019_64/bin', root / '.tools/openssl/Library/bin'] if tag == 'msvc' else [root / '.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(map(str, bins)) + os.pathsep + environment['PATH']
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
              'toolchain': tag, 'globalQuotaEnforced': False, 'allProductionRootsIntegrated': False,
              'deliveryComplete': False, 'releaseQualified': False}
    with (output / 'build.log').open('xb') as log:
        code = subprocess.run([str(root / '.tools/python/Scripts/cmake.exe'), '--build', str(build),
                               '--config', 'Release', '--parallel', '3'], env=environment,
                              stdout=log, stderr=subprocess.STDOUT).returncode
    result['buildExitCode'] = code
    if code == 0:
        program = build / ('Release' if tag == 'msvc' else '')
        names = [path.name for path in program.glob('*.exe') if path.name.endswith('-tests.exe') or path.name in ['dukto-cli.exe', 'dukto-gui.exe']]
        before = {name: hashlib.sha256((program / name).read_bytes()).hexdigest() for name in names}
        with (output / 'ctest-driver.log').open('xb') as log:
            code = subprocess.run([str(root / '.tools/python/Scripts/ctest.exe'), '--test-dir', str(build),
                                   '-C', 'Release', '--output-on-failure', '--output-log', str(output / 'ctest.log')],
                                  env=environment, stdout=log, stderr=subprocess.STDOUT).returncode
        result['ctestExitCode'] = code
        result['binariesBefore'] = before
        result['binariesAfter'] = {name: hashlib.sha256((program / name).read_bytes()).hexdigest() for name in before}
        shutil.copytree(build / 'Testing', output / 'Testing')
    result['inputsAfter'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs}
    result['passed'] = result.get('ctestExitCode') == 0 and inputs == result['inputsAfter'] and result.get('binariesBefore') == result.get('binariesAfter')
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps({'toolchain': tag, 'buildExitCode': result['buildExitCode'],
                      'ctestExitCode': result.get('ctestExitCode'), 'passed': result['passed']}), flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()

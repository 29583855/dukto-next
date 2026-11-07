"""日期：2026-11-08；构建真实CLI和状态会话专项，保留失败、原XML及精确输入/程序摘要。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-08；独立输出目录避免覆盖先前失败；使用各工具链的实际Qt/TLS运行时。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    parser.add_argument('--attempt', default='initial')
    args = parser.parse_args()
    root = Path.cwd()
    output = root / ('.cache/r126-' + args.attempt + '-' + args.toolchain)
    output.mkdir(exist_ok=False)
    names = {row['path'] for row in json.loads((root / 'docs/ci-verification-20261108-r125.json').read_bytes())['qualificationInputs']}
    names |= {'src/core/statesession.h', 'src/core/statesession.cpp', 'tests/state_session_tests.cpp'}
    inputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(names)}
    environment = os.environ.copy()
    paths = ['.tools/Qt/5.15.2/msvc2019_64/bin', '.tools/openssl/Library/bin'] if args.toolchain == 'msvc' else ['.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(str(root / name) for name in paths) + os.pathsep + environment['PATH']
    build = root / ('build/windows' if args.toolchain == 'msvc' else 'build/windows-ucrt')
    program = build / ('Release' if args.toolchain == 'msvc' else '')
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'inputs': inputs,
              'toolchain': args.toolchain, 'passed': False, 'productionQuotaEnforced': False,
              'guiRootsIntegrated': False, 'deliveryComplete': False, 'releaseQualified': False}
    with (output / 'build.log').open('xb') as log:
        process = subprocess.run([str(root / '.tools/python/Scripts/cmake.exe'), '--build', str(build),
                                  '--config', 'Release', '--target', 'state-session-tests', '--parallel', '3'],
                                 env=environment, stdout=log, stderr=subprocess.STDOUT)
    result['buildExitCode'] = process.returncode
    if process.returncode == 0:
        binaries = {name: hashlib.sha256((program / name).read_bytes()).hexdigest()
                    for name in ['dukto-cli.exe', 'state-session-tests.exe']}
        result['binariesBefore'] = binaries
        with (output / 'driver.log').open('xb') as log:
            process = subprocess.run([str(program / 'state-session-tests.exe'),
                                      '-o', str(output / 'state-session-tests.xml') + ',xml',
                                      '-o', str(output / 'state-session-tests.log') + ',txt',
                                      '-o', str(output / 'state-session-tests-junit.xml') + ',junitxml'],
                                     env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        result['testExitCode'] = process.returncode
        result['binariesAfter'] = {name: hashlib.sha256((program / name).read_bytes()).hexdigest() for name in binaries}
        result['passed'] = process.returncode == 0 and result['binariesBefore'] == result['binariesAfter']
    result['inputsAfter'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs}
    result['passed'] = result['passed'] and inputs == result['inputsAfter']
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: result.get(key) for key in ['toolchain', 'buildExitCode', 'testExitCode', 'passed']}), flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()

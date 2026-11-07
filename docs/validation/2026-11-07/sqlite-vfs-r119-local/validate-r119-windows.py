"""日期：2026-11-07；按原源码构建双Windows工具链并保留全部29核心原件，失败不改写成通过。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path.cwd()
NAMES = ['CMakeLists.txt', *[path.as_posix() for path in sorted((ROOT / 'src').rglob('*'))
                              if path.suffix in ['.cpp', '.h']],
         'tests/sqlite_vfs_tests.cpp', 'scripts/source_snapshot.py', 'scripts/package_windows.py',
         *[path.as_posix() for path in sorted((ROOT / 'third-party/sqlite-runtime').rglob('*'))
           if path.is_file()]]


# 日期：2026-11-07；构建与测试各自保存原日志及退出码，测试时固定对应工具链Qt/TLS及offscreen。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    tag = parser.parse_args().toolchain
    build = ROOT / 'build' / ('windows' if tag == 'msvc' else 'windows-ucrt')
    output = ROOT / '.cache' / ('r119-' + tag)
    output.mkdir(exist_ok=False)
    inputs = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in NAMES}
    environment = os.environ.copy()
    bins = [ROOT / '.tools/Qt/5.15.2/msvc2019_64/bin', ROOT / '.tools/openssl/Library/bin'] if tag == 'msvc' else [ROOT / '.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(map(str, bins)) + os.pathsep + environment['PATH']
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'inputs': inputs, 'toolchain': tag,
              'deliveryComplete': False, 'releaseQualified': False}
    with (output / 'build.log').open('wb') as log:
        code = subprocess.run([str(ROOT / '.tools/python/Scripts/cmake.exe'), '--build', str(build),
                               '--config', 'Release', '--parallel', '3'], env=environment, stdout=log,
                              stderr=subprocess.STDOUT).returncode
    result['buildExitCode'] = code
    if code == 0:
        program = build / ('Release' if tag == 'msvc' else '')
        before = {name: hashlib.sha256((program / name).read_bytes()).hexdigest()
                  for name in ['dukto-cli.exe', 'dukto-gui.exe', 'sqlite-vfs-tests.exe']}
        with (output / 'ctest-driver.log').open('wb') as log:
            code = subprocess.run([str(ROOT / '.tools/python/Scripts/ctest.exe'), '--test-dir', str(build),
                                   '-C', 'Release', '--output-on-failure', '--output-log', str(output / 'ctest.log')],
                                  env=environment, stdout=log, stderr=subprocess.STDOUT).returncode
        result['ctestExitCode'] = code
        result['binariesBefore'] = before
        result['binariesAfter'] = {name: hashlib.sha256((program / name).read_bytes()).hexdigest() for name in before}
        shutil.copytree(build / 'Testing', output / 'Testing')
    result['inputsAfter'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in NAMES}
    result['passed'] = result.get('ctestExitCode') == 0 and inputs == result['inputsAfter'] and result.get('binariesBefore') == result.get('binariesAfter')
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps({'toolchain': tag, 'buildExit': result['buildExitCode'], 'ctestExit': result.get('ctestExitCode'), 'passed': result['passed']}), flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()

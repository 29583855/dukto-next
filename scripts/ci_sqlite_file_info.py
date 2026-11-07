"""日期：2026-11-08；记录精确输入及真实程序身份，执行完整核心并保存原始Qt报告。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET


# 日期：2026-11-08；固定缓冲计算摘要，不因程序或依赖大小增长而增加内存。
def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


# 日期：2026-11-08；只授予实际执行的完整核心及原生文件专项资格，不代替协议/部署/总配额。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--configuration', default='Release')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    build = args.build.resolve()
    output = build / 'sqlite-file-info-regression'
    output.mkdir(exist_ok=False)
    suffix = '.exe' if os.name == 'nt' else ''
    program = build / args.configuration if os.name == 'nt' else build
    gui = program / ('dukto-gui.exe' if os.name == 'nt' else 'dukto-gui')
    if sys.platform == 'darwin':
        gui = build / 'dukto-gui.app/Contents/MacOS/dukto-gui'
    binaries = [program / ('dukto-cli' + suffix), gui,
                program / ('sqlite-file-info-tests' + suffix), program / ('sqlite-vfs-tests' + suffix)]
    inputs = [root / 'CMakeLists.txt']
    for folder in ['src', 'tests', 'scripts', 'third-party/sqlite-runtime', '.github/workflows']:
        inputs.extend(path for path in (root / folder).rglob('*')
                      if path.is_file() and '__pycache__' not in path.parts)
    source_before = {path.relative_to(root).as_posix(): digest(path) for path in sorted(inputs)}
    before = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    with (output / 'ctest-driver.log').open('wb') as log:
        result = subprocess.run(['ctest', '--test-dir', str(build), '-C', args.configuration,
                                 '--output-on-failure', '--output-log', str(output / 'ctest.log')],
                                stdout=log, stderr=subprocess.STDOUT)
    after = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    source_after = {path.relative_to(root).as_posix(): digest(path) for path in sorted(inputs)}
    report = build / 'Testing/QtTest/sqlite-file-info-tests.xml'
    tests = ET.parse(report).getroot() if report.exists() else None
    methods = list(tests.iter('testcase')) if tests is not None else []
    failures = list(tests.iter('failure')) + list(tests.iter('error')) if tests is not None else []
    skips = list(tests.iter('skipped')) if tests is not None else []
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source_commit,
             'system': platform.platform(), 'architecture': platform.machine(),
             'ctestExitCode': result.returncode, 'binaryBefore': before, 'binaryAfter': after,
             'sourceInputs': source_before, 'binaryUnchanged': before == after,
             'sourceInputsUnchanged': source_before == source_after,
             'fileInfoTestMethods': len(methods), 'fileInfoFailures': len(failures),
             'fileInfoSkipped': len(skips), 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False}
    value['passed'] = (result.returncode == 0 and before == after and source_before == source_after
                       and tests is not None and tests.tag == 'testsuite'
                       and tests.get('failures') == '0' and tests.get('errors') == '0'
                       and len(methods) == 11 and all(item.get('result') == 'pass' for item in methods)
                       and not failures and not skips)
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value[key] for key in ['sourceCommit', 'architecture', 'ctestExitCode',
                                                'fileInfoTestMethods', 'passed']}), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

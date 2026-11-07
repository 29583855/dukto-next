"""日期：2026-11-08；真实CLI核对受保护根/旧凭据与缺失记录夹具，不替代完整协议验收。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


# 日期：2026-11-08；分块计算真实执行程序和输入摘要，避免随文件大小增加内存。
def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


# 日期：2026-11-08；独立核对原业务断言和新增目录控制断言，不因测试返回零就授予资格。
def verify_report(name, value, binary_sha, script_sha):
    assert value['passed'] and value['executableSha256'] == binary_sha
    if name == 'credential-rotation':
        assert value['testScriptSha256'] == script_sha
        assert 'copied native root binding refused without changing marker, profile or server credential' in value['checks']
        assert 'old connections and fresh locally bound old-credential connections denied' in value['checks']
        assert len(value['checks']) == 13 and len(value['liveCases']) == 2
        assert {row['direction'] for row in value['liveCases']} == {'upload', 'download'}
        for row in value['liveCases']:
            assert row['channels'] == 4 and row['secondsToStop'] < 15
            assert row['restoredBytes'] >= row['checkpoint'] > 0
            assert row['sameTaskResumed'] and row['originalPreserved']
            assert row['serverStoppedState'] == 'interrupted' and row['errorCode'] in (3, 4)
    else:
        assert value['scriptSha256'] == script_sha
        assert value['missingLocalReceiptControlsOnly'] and value['missingLocalReceiptFixedMarkerCharge'] == 256
        for key in ['foreignOwnerRefused', 'revokedRefused', 'restartStable', 'missingLocalReceiptExplicit']:
            assert value[key]
        assert len(value['cases']) == 4 and len(value['partial']) == 2


# 日期：2026-11-08；两项独立执行保留各自失败和原始日志；源码、程序前后相同才授予本专项资格。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    build = args.build.resolve()
    output = build / 'state-fixture-regression'
    output.mkdir(exist_ok=False)
    binary = build / 'Release/dukto-cli.exe' if os.name == 'nt' else build / 'dukto-cli'
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    before = digest(binary)

    # 日期：2026-11-08；源清单同时核对新增/删除，排除解释器自动缓存。
    def sources():
        paths = [root / 'CMakeLists.txt']
        for folder in ['src', 'ui', 'resources', 'tests', 'scripts', 'third-party/sqlite-runtime', '.github/workflows']:
            paths.extend(path for path in (root / folder).rglob('*')
                         if path.is_file() and '__pycache__' not in path.parts)
        return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}

    inputs = sources()
    rows = []
    for name, script in [('credential-rotation', 'credential_rotation_integration'),
                         ('task-items', 'task_items_integration')]:
        report = output / (name + '.json')
        script_path = root / 'tests' / (script + '.py')
        row = {'name': name, 'passed': False}
        try:
            with (output / (name + '.log')).open('xb') as log:
                result = subprocess.run([sys.executable, '-X', 'utf8', str(script_path), str(binary),
                                         '--report', str(report)], cwd=root, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=600)
            row['exitCode'] = result.returncode
            if report.is_file():
                row['reportSha256'] = digest(report)
                verify_report(name, json.loads(report.read_bytes()), before, digest(script_path))
                row['passed'] = result.returncode == 0
        except (AssertionError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
            row['verificationErrorType'] = type(error).__name__
        rows.append(row)
        print(json.dumps(row), flush=True)
    after = digest(binary)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'system': platform.platform(), 'architecture': platform.machine(),
             'binaryBefore': before, 'binaryAfter': after, 'binaryUnchanged': before == after,
             'sourceInputs': inputs, 'sourceInputsUnchanged': inputs == sources(), 'records': rows,
             'fullProtocolQualified': False, 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False}
    value['passed'] = all(row['passed'] for row in rows) and value['binaryUnchanged'] and value['sourceInputsUnchanged']
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

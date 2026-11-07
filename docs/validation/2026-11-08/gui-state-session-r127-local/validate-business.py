"""日期：2026-11-08；冻结GUI接入程序后核对真实进程恢复与显式资料诊断。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-08；只使用本构建真实GUI探针和CLI，不模拟网络、重启或私有根资格。
def main():
    root = Path.cwd()
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    tag = parser.parse_args().toolchain
    output = root / '.cache' / ('r127-business-' + tag)
    output.mkdir(exist_ok=False)
    full = json.loads((root / '.cache' / ('r127-first-' + tag) / 'receipt.json').read_bytes())
    assert full['passed']
    inputs = full['inputs']
    assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha for name, sha in inputs.items())
    program = root / ('build/windows/Release' if tag == 'msvc' else 'build/windows-ucrt')
    binaries = {name: hashlib.sha256((program / name).read_bytes()).hexdigest()
                for name in ['dukto-cli.exe', 'server-panel-process-probe.exe']}
    assert full['binariesBefore']['dukto-cli.exe'] == binaries['dukto-cli.exe']
    environment = os.environ.copy()
    bins = [root / '.tools/Qt/5.15.2/msvc2019_64/bin', root / '.tools/openssl/Library/bin'] if tag == 'msvc' else [root / '.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(map(str, bins)) + os.pathsep + environment['PATH']
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    rows = []
    for name in ['doctor', 'gui_process_recovery']:
        report = output / (name + '.json')
        command = [str(root / '.tools/python/Scripts/python.exe'), '-X', 'utf8',
                   str(root / 'tests' / (name + '_integration.py')), str(program / 'dukto-cli.exe')]
        if name == 'gui_process_recovery':
            command.append(str(program / 'server-panel-process-probe.exe'))
        command += ['--report', str(report)]
        with (output / (name + '.log')).open('xb') as log:
            actual = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        row = {'name': name, 'exitCode': actual.returncode, 'passed': False}
        if report.exists():
            value = json.loads(report.read_bytes())
            row['passed'] = actual.returncode == 0 and value['passed']
        rows.append(row)
        if not row['passed']:
            break
    after = {name: hashlib.sha256((program / name).read_bytes()).hexdigest() for name in binaries}
    unchanged = all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha for name, sha in inputs.items())
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'toolchain': tag,
              'binaryBefore': binaries, 'binaryAfter': after, 'sourceInputsUnchanged': unchanged,
              'sourceInputCount': len(inputs), 'rows': rows,
              'passed': len(rows) == 2 and all(row['passed'] for row in rows) and binaries == after and unchanged,
              'globalQuotaEnforced': False, 'allProductionRootsIntegrated': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()

"""日期：2026-11-08；对冻结R126程序执行真实服务与多通道双向传输，不修改产品门槛。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-08；程序与全部资格输入前后核对，业务失败保留原日志并停止授予资格。
def main():
    root = Path.cwd()
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    tag = parser.parse_args().toolchain
    output = root / '.cache' / ('r126-cli-business-' + tag)
    output.mkdir(exist_ok=False)
    inputs = {row['path']: row['sha256'] for row in json.loads((root / 'docs/ci-verification-20261108-r126.json').read_bytes())['qualificationInputs']}
    executable = root / ('build/windows/Release/dukto-cli.exe' if tag == 'msvc' else 'build/windows-ucrt/dukto-cli.exe')
    before = hashlib.sha256(executable.read_bytes()).hexdigest()
    assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha for name, sha in inputs.items())
    previous = json.loads((root / '.cache' / ('r126-first-' + tag) / 'receipt.json').read_bytes())
    assert previous['binariesBefore']['dukto-cli.exe'] == before
    environment = os.environ.copy()
    bins = [root / '.tools/Qt/5.15.2/msvc2019_64/bin', root / '.tools/openssl/Library/bin'] if tag == 'msvc' else [root / '.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(map(str, bins)) + os.pathsep + environment['PATH']
    rows = []
    for name in ['service', 'parallel_transfer']:
        report = output / (name + '.json')
        command = [str(root / '.tools/python/Scripts/python.exe'), '-X', 'utf8', str(root / 'tests' / (name + '_integration.py')), str(executable), '--report', str(report)]
        with (output / (name + '.log')).open('xb') as log:
            result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        row = {'name': name, 'exitCode': result.returncode, 'passed': False}
        if report.exists():
            value = json.loads(report.read_bytes())
            row['passed'] = result.returncode == 0 and value['passed']
            row['reportSha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
        rows.append(row)
        if not row['passed']:
            break
    after = hashlib.sha256(executable.read_bytes()).hexdigest()
    unchanged = all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha for name, sha in inputs.items())
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'toolchain': tag,
               'binaryBefore': before, 'binaryAfter': after, 'sourceInputCount': len(inputs),
               'sourceInputsUnchanged': unchanged, 'rows': rows,
               'passed': len(rows) == 2 and all(row['passed'] for row in rows) and before == after and unchanged,
               'globalQuotaEnforced': False, 'guiRootsIntegrated': False,
               'fullProtocolQualified': False, 'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    print(json.dumps(receipt), flush=True)
    raise SystemExit(0 if receipt['passed'] else 1)


if __name__ == '__main__':
    main()

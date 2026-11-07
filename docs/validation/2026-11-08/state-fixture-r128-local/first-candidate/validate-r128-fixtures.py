"""日期：2026-11-08；使用冻结R127生产程序验证两份修正夹具，原源码和旧失败保持。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-08；两个业务分别保留真实退出码及报告，候选夹具与产品输入身份分开记录。
def main():
    root = Path.cwd()
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    tag = parser.parse_args().toolchain
    output = root / '.cache' / ('r128-candidate-' + tag)
    output.mkdir(exist_ok=False)
    program = root / ('build/windows/Release/dukto-cli.exe' if tag == 'msvc' else 'build/windows-ucrt/dukto-cli.exe')
    before = hashlib.sha256(program.read_bytes()).hexdigest()
    core = json.loads((root / '.cache' / ('r127-first-' + tag) / 'receipt.json').read_bytes())
    assert core['passed'] and core['binariesBefore']['dukto-cli.exe'] == before
    assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha for name, sha in core['inputs'].items())
    candidate = root / '.cache/r128-candidate'
    fixtures = {name: hashlib.sha256((candidate / name).read_bytes()).hexdigest() for name in
                ['tests/credential_rotation_integration.py', 'tests/task_items_integration.py']}
    environment = os.environ.copy()
    bins = [root / '.tools/Qt/5.15.2/msvc2019_64/bin', root / '.tools/openssl/Library/bin'] if tag == 'msvc' else [root / '.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(map(str, bins)) + os.pathsep + environment['PATH']
    records = []
    for name in ['credential_rotation', 'task_items']:
        report = output / (name + '.json')
        with (output / (name + '.log')).open('xb') as log:
            result = subprocess.run([str(root / '.tools/python/Scripts/python.exe'), '-X', 'utf8',
                                     str(candidate / 'tests' / (name + '_integration.py')), str(program),
                                     '--report', str(report)], env=environment, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=600)
        row = {'name': name, 'exitCode': result.returncode, 'passed': False}
        if report.exists():
            value = json.loads(report.read_bytes())
            assert value['executableSha256'] == before
            if name == 'task_items':
                assert value['missingLocalReceiptControlsOnly'] and value['missingLocalReceiptFixedMarkerCharge'] == 256
            else:
                assert 'copied native root binding refused without changing marker, profile or server credential' in value['checks']
            row.update(passed=result.returncode == 0 and value['passed'], reportSha256=hashlib.sha256(report.read_bytes()).hexdigest())
        records.append(row)
    after = hashlib.sha256(program.read_bytes()).hexdigest()
    unchanged = all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha for name, sha in core['inputs'].items())
    assert all(hashlib.sha256((candidate / name).read_bytes()).hexdigest() == sha for name, sha in fixtures.items())
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'toolchain': tag,
             'productionSourceCommit': '6c6dc363c7bb755f7b5aae1f7627385c009a0ac2',
             'originalSourceInputCount': len(core['inputs']), 'originalSourceInputsUnchanged': unchanged,
             'candidateFixtures': fixtures, 'binaryBefore': before, 'binaryAfter': after, 'records': records,
             'passed': all(row['passed'] for row in records) and before == after and unchanged,
             'fullProtocolQualified': False, 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

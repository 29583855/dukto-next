"""日期：2026-11-06；在Windows执行与旧Intel包相同覆盖恢复条件，保持原始参数和时限并保存全部原件。"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys


# 日期：2026-11-06；此复查不能证明Mac根因或替代Mac资格，输入与冻结R94必须一致。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-06/checkpoint-r94-windows-reproduction'
    output.mkdir(exist_ok=False)
    source = json.loads((root / 'docs/ci-verification-20261106-r94.json').read_text('utf-8'))
    assert source['productionCommit'] == 'dec40621cce2d223e46b343e0d3d345a67b80523'
    for row in source['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    binary = root / 'build/windows/Release/dukto-cli.exe'
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    command = [sys.executable, '-X', 'utf8', '-u', 'tests/transfer_recovery_integration.py', str(binary),
               '--threads', '4', '--resume-threads', '8', '--files', '4', '--payload-mib', '8',
               '--checkpoint-percent', '50', '--on-conflict', 'overwrite',
               '--report', str(output / 'overwrite-recovery.json')]
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']('msvc')
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
    after = hashlib.sha256(binary.read_bytes()).hexdigest()
    value = {'sourceCommit': source['productionCommit'], 'platform': 'Windows MSVC',
             'command': command, 'exitCode': result.returncode, 'binarySha256': before,
             'binaryUnchanged': before == after, 'originalGatesUnchanged': True,
             'macOSRootCauseProven': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(value, ensure_ascii=False), flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())

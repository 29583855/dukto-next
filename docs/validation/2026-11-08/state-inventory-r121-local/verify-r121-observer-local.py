"""日期：2026-11-08；对新增CI判读器取得一次真实观察程序前后身份与全部专项原件。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-08；候选工作区按全部268输入冻结，不把根仓库旧HEAD当作尚未公开的新源提交。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    tag = parser.parse_args().toolchain
    root = Path.cwd()
    old = json.loads((root / '.cache/r120-execution-publication.json').read_bytes())['qualificationInputs']
    names = sorted({row['path'] for row in old} | {'scripts/ci_state_inventory.py', '.github/workflows/state-inventory-regression.yml'})
    inputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    binary_dir = root / 'build' / ('windows/Release' if tag == 'msvc' else 'windows-ucrt')
    binaries = ['state-storage-tests.exe', 'dukto-cli.exe']
    before = {name: hashlib.sha256((binary_dir / name).read_bytes()).hexdigest() for name in binaries}
    environment = os.environ.copy()
    bins = ['.tools/Qt/5.15.2/msvc2019_64/bin', '.tools/openssl/Library/bin'] if tag == 'msvc' else ['.tools/msys64/ucrt64/bin']
    environment['PATH'] = os.pathsep.join(str(root / name) for name in bins) + os.pathsep + environment['PATH']
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    output = root / '.cache' / ('r121-observer-' + tag)
    output.mkdir(exist_ok=False)
    with (output / 'driver.log').open('wb') as log:
        result = subprocess.run([str(binary_dir / binaries[0]), '-o', str(output / 'state-storage-tests.log') + ',txt',
                                 '-o', str(output / 'state-storage-tests.xml') + ',junitxml'],
                                env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    after = {name: hashlib.sha256((binary_dir / name).read_bytes()).hexdigest() for name in binaries}
    inputs_after = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': None,
             'qualificationByFrozenWorkspaceInputs': True, 'toolchain': tag,
             'sourceSnapshotSha256': hashlib.sha256((root / '.cache/r121-native-state-source.tar.gz').read_bytes()).hexdigest(),
             'inputs': inputs, 'inputsAfter': inputs_after, 'binaryBefore': before, 'binaryAfter': after,
             'exitCode': result.returncode, 'passed': False, 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        helper = runpy.run_path(str(root / 'scripts/ci_state_inventory.py'))['verify_xml']
        value.update(helper(output / 'state-storage-tests.xml'))
        value['passed'] = inputs == inputs_after and before == after
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'toolchain': tag, 'passed': value['passed'], 'rowsPassed': value.get('rowsPassed'),
                      'permissionRowsSkipped': value.get('permissionRowsSkipped')}), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

"""日期：2026-11-07；收验独立Ubuntu真实终态，失败保留且不给完整任务测试资格。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess

SOURCE = 'e220461bdd0a409b10f483a3aaa321db927975c3'


# 日期：2026-11-07；终态、原报告、冻结源码/二进制及C++14均独立核对，不用子集覆盖失败。
def main():
    root = Path.cwd()
    folder = root / 'docs/validation/2026-11-07/secure-ready-r107-glibc'
    collected = json.loads((folder / 'collection-result.json').read_text('utf-8'))
    assert collected['collectionExitCode'] == 0 and collected['remoteExitCode'] in (0, 1)
    result = json.loads((folder / 'results/driver-result.json').read_text('utf-8'))
    assert result['passed'] == (collected['remoteExitCode'] == 0)
    assert result['binaryUnchanged'] and not result['independentFullCoreSuiteRun']
    assert [row['name'] for row in result['cases']] == ['configure', 'build', 'secure-channel', 'task-items', 'transfer16']
    steps = {row['name']: row['exitCode'] for row in result['cases']}
    assert steps['configure'] == steps['build'] == steps['secure-channel'] == 0
    tls = json.loads((folder / 'results/secure-channel.json').read_text('utf-8'))
    assert tls['passed'] and len(tls['cases']) == 31
    for name, code in [('bufferedBurst', 0), ('bufferedBurstAfterDisconnect', 0), ('bufferedBurstCancellation', 7)]:
        assert tls['cases'][name]['passed'] and tls['cases'][name]['exitCode'] == code
    for name in ('task-items', 'transfer16'):
        path = folder / ('results/' + name + '.json')
        if steps[name] == 0:
            value = json.loads(path.read_text('utf-8'))
            assert value['passed']
            if name == 'task-items':
                assert len(value['cases']) == 4 and value['missingLocalReceiptExplicit'] and value['restartStable']
        elif path.exists():
            assert not json.loads(path.read_text('utf-8'))['passed']
    manifest = json.loads((root / 'docs/ci-verification-20261107-r107.json').read_text('utf-8'))
    inputs = manifest['buildInputs']
    assert len(inputs) == 213
    for row in inputs:
        raw = subprocess.check_output(['git', 'show', SOURCE + ':' + row['path']], cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    program = '''from pathlib import Path
import hashlib,json,subprocess
root=Path('/home/dukto/secure-ready-r107')
expected=json.loads(%s)
for row in expected:
    assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256']
binary={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in ('dukto-cli','secure-channel-probe')}
assert '-std=c++14' in (root/'build/build.ninja').read_text(encoding='utf-8')
print(json.dumps({'buildInputsVerified':len(expected),'binarySha256':binary,'cxx14Verified':True,
 'qtVersion':subprocess.check_output(['qmake','-query','QT_VERSION'],text=True).strip(),
 'compiler':subprocess.check_output(['g++','--version'],text=True).splitlines()[0]}))
''' % repr(json.dumps(inputs))
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    observed = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), capture_output=True, timeout=60)
    assert observed.returncode == 0, 'remote input verification failed; output not printed'
    exact = json.loads(observed.stdout)
    assert exact['binarySha256'] == result['binarySha256'] and exact['buildInputsVerified'] == 213
    assert exact['qtVersion'].startswith('5.15.')
    (folder / 'input-and-toolchain-verification.json').write_text(json.dumps(exact, indent=2) + '\n', 'utf-8')
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': SOURCE,
               'driverActuallyExited': True, 'driverExitCode': collected['remoteExitCode'],
               'inputVerification': proof(folder / 'input-and-toolchain-verification.json'),
               'secureChannelCasesVerified': 31, 'tlsBoundarySubsetPassed': True,
               'fullOriginalTaskItemsPassed': steps['task-items'] == 0,
               'taskItemsDeadlineIncreased': False, 'independentFullCoreSuiteRun': False,
               'throughputImprovementProven': False, 'originalUbuntuTimeoutCauseEstablished': False,
               'allRequestedIndependentTestsPassed': result['passed'],
               'originalFailuresRetained': True, 'releaseQualified': False, 'deliveryComplete': False}
    (folder / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    shutil.copyfile(__file__, folder / 'verification-driver.py')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()

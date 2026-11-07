"""日期：2026-11-07；核对夹具唯一改动、双Windows真实结果及独立Ubuntu失败，不合并资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

PARENT = '0e1cf818ec6aea9f842cc6759b9bcd16387d7431'


# 日期：2026-11-07；只给双Windows定向复验授予通过资格，未执行的核心和未通过的Ubuntu仍保留原状态。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    previous = json.loads((root / 'docs/ci-verification-20261107-r104.json').read_text('utf-8'))['buildInputs']
    inputs, changed = [], []
    for row in previous:
        path = root / row['path']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        inputs.append({'path': row['path'], 'sha256': digest})
        if digest != row['sha256']:
            changed.append(row['path'])
        raw = subprocess.check_output(['git', 'show', 'HEAD:' + row['path']], cwd=checkout)
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    assert changed == ['tests/task_items_integration.py'] and len(inputs) == 213
    name = changed[0]
    before = (root / '.cache/task-maintenance-r105-before' / name).read_bytes()
    after = (root / name).read_bytes()
    assert hashlib.sha256(before).hexdigest() == next(row['sha256'] for row in previous if row['path'] == name)
    assert before.startswith(b'\xef\xbb\xbf') == after.startswith(b'\xef\xbb\xbf')
    assert b'\r' not in before and b'\r' not in after
    after.decode('utf-8')
    assert b'original.rmdir()' in before and b'original.rmdir()' not in after
    assert b'stat.S_ISREG(guard.st_mode) and guard.st_nlink == 1 and guard.st_size == 0' in after
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    proof = helper['proof']
    folder = root / 'docs/validation/2026-11-07/task-items-r105-windows'
    driver = json.loads((folder / 'driver-result.json').read_text('utf-8'))
    digest = hashlib.sha256(after).hexdigest()
    assert driver['passed'] and driver['scriptSha256'] == digest and not driver['productionCodeChangedForFixtureCorrection']
    rows = []
    for label, directory in [('ucrt', 'windows-ucrt'), ('msvc', 'windows/Release')]:
        row, = [row for row in driver['cases'] if row['toolchain'] == label]
        assert row['exitCode'] == 0 and row['passed'] and row['binaryUnchanged']
        binary = root / 'build' / directory / 'dukto-cli.exe'
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == row['binarySha256']
        path = folder / label / 'task-items.json'
        result = json.loads(path.read_text('utf-8'))
        assert result['passed'] and result['scriptSha256'] == digest
        assert result['executableSha256'] == row['binarySha256']
        assert len(result['cases']) == 4 and len(result['partial']) == 2
        assert {(case['direction'], case['channels']) for case in result['cases']} == {
            (direction, channels) for direction in ('upload', 'download') for channels in (4, 16)}
        assert all(case['entries'] == 204 and case['pages'] == 3 and case['renamedTargetsVerified']
                   and case['readOnlyTaskRevision'] and case['contentReverificationNotClaimed'] for case in result['cases'])
        for key in ('foreignOwnerRefused', 'revokedRefused', 'restartStable', 'missingLocalReceiptExplicit'):
            assert result[key]
        rows.append(dict(row, report=proof(path)))
    ubuntu = root / 'docs/validation/2026-11-07/task-items-r105-glibc'
    failure = json.loads((ubuntu / 'driver-result.json').read_text('utf-8'))
    assert failure['exitCode'] == 1 and not failure['passed'] and failure['binaryUnchanged']
    assert failure['scriptSha256'] == digest and not (ubuntu / 'task-items.json').exists()
    assert b'timed out after 90 seconds' in (ubuntu / 'task-items.log').read_bytes()
    audit_path = root / 'docs/validation/2026-11-07/task-items-r105-source-audit.json'
    audit = json.loads(audit_path.read_text('utf-8'))
    assert len(audit['files']) == 207 and not audit['findings'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    original = root / 'docs/validation/2026-11-07/state-use-r104-ubuntu-terminal/subset-verification.json'
    subset = json.loads(original.read_text('utf-8'))
    assert subset['verificationPassedWithinExplicitSubset'] and len(subset['verifiedPassedProtocolReports']) == 46
    output = root / 'docs/validation/2026-11-07/task-items-r105-qualified'
    output.mkdir(exist_ok=False)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'basedOnPublishedCommit': PARENT,
             'buildInputs': inputs, 'changedBuildInputs': changed, 'productionCodeChanged': False,
             'windowsTargetedFixtureRecheckPassed': True, 'windows': rows,
             'encodingBomAndNewlinesPreserved': True, 'sourceAudit': proof(audit_path),
             'originalUbuntuTerminalFailureSubset': proof(original),
             'independentUbuntuTimeoutRetained': proof(ubuntu / 'collection-failure.json'),
             'independentUbuntuFixtureRecheckPassed': False, 'newNativeCIPending': True,
             'freshFullCoreRunClaimed': False, 'entireR04Qualified': False,
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'windowsToolchainsPassed': 2, 'changedBuildInputs': changed, 'independentUbuntuQualified': False}))


if __name__ == '__main__':
    main()

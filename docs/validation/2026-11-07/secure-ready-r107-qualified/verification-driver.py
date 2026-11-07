"""日期：2026-11-07；独立核对Windows原件、源码身份和新增TLS边界，不推定提速或全交付。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import runpy
import shutil
import subprocess


# 日期：2026-11-07；报告、实际退出、二进制和213源码输入须一致才生成验证回执。
def main():
    root = Path.cwd()
    base = root / 'docs/validation/2026-11-07'
    target = base / 'secure-ready-r107-windows'
    result = json.loads((target / 'driver-result.json').read_text('utf-8'))
    assert result['passed'] and result['buildInputsUnchanged'] and len(result['cases']) == 2
    inputs = json.loads((target / 'build-inputs.json').read_text('utf-8'))
    assert len(inputs) == 213
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    proof = helper['proof']
    verify_xml = runpy.run_path('.cache/verify-diagnostics-r103.py')['verify_xml']
    rows = []
    for label in ('ucrt', 'msvc'):
        row, = [row for row in result['cases'] if row['toolchain'] == label]
        assert row['passed'] and row['binaryUnchanged']
        assert [step['name'] for step in row['cases']] == ['build', 'ctest', 'secure-channel', 'task-items', 'transfer16']
        assert all(step['exitCode'] == 0 for step in row['cases'])
        folder = target / label
        assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$', (folder / 'ctest.log').read_text('utf-8-sig'), re.M)
        files = sorted((folder / 'QtTest').glob('*.xml'))
        assert len(files) == 22
        for path in files:
            verify_xml(path)
        tls = json.loads((folder / 'secure-channel.json').read_text('utf-8'))
        assert tls['passed'] and len(tls['cases']) == 31
        for name, code in [('bufferedBurst', 0), ('bufferedBurstAfterDisconnect', 0), ('bufferedBurstCancellation', 7)]:
            assert tls['cases'][name]['passed'] and tls['cases'][name]['exitCode'] == code
        for name in ('task-items', 'transfer16'):
            assert json.loads((folder / (name + '.json')).read_text('utf-8'))['passed']
        items = json.loads((folder / 'task-items.json').read_text('utf-8'))
        assert len(items['cases']) == 4 and items['missingLocalReceiptExplicit'] and items['restartStable']
        binary = root / ('build/windows-ucrt' if label == 'ucrt' else 'build/windows/Release')
        for name, digest in row['binarySha256'].items():
            assert hashlib.sha256((binary / name).read_bytes()).hexdigest() == digest
        rows.append({'toolchain': label, 'coreTargets': 23, 'qtXmlReports': 22, 'tlsCases': 31,
                     'secureChannel': proof(folder / 'secure-channel.json'),
                     'taskItems': proof(folder / 'task-items.json'), 'transfer16': proof(folder / 'transfer16.json'),
                     'binarySha256': row['binarySha256']})
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    changed = []
    for item in inputs:
        raw = (root / item['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
        before = subprocess.check_output(['git', 'show', 'HEAD:' + item['path']], cwd=checkout)
        if before != raw:
            changed.append(item['path'])
            assert before.startswith(b'\xef\xbb\xbf') == raw.startswith(b'\xef\xbb\xbf')
            assert (b'\r\n' in before) == (b'\r\n' in raw)
            raw.decode('utf-8-sig')
    assert set(changed) == {'src/core/securechannel.cpp', 'tests/secure_channel_probe.cpp', 'tests/secure_channel_integration.py'}
    prior_audit = json.loads((base / 'task-items-r105-source-audit.json').read_text('utf-8'))
    findings, files = [], []
    for item in prior_audit['files']:
        path = root / item['path']
        files.append(dict(path=item['path'], sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        for number, line in enumerate(path.read_text('utf-8-sig').splitlines(), 1):
            if re.search(r'\b(TODO|FIXME|HACK|XXX|stub|placeholder)\b|not implemented|简化实现|待实现', line, re.I):
                findings.append({'path': item['path'], 'line': number})
    assert len(files) == 207 and not findings
    formatting = subprocess.run([str(root / '.tools/python/Scripts/clang-format.exe'), '--dry-run', '--Werror', *[name for name in changed if name.endswith('.cpp')]], capture_output=True)
    assert formatting.returncode == 0 and not formatting.stdout and not formatting.stderr
    cmake = (root / 'CMakeLists.txt').read_text('utf-8')
    assert 'set(CMAKE_CXX_STANDARD 14)' in cmake and 'set(CMAKE_CXX_STANDARD_REQUIRED ON)' in cmake and 'set(CMAKE_CXX_EXTENSIONS OFF)' in cmake
    output = base / 'secure-ready-r107-qualified'
    output.mkdir(exist_ok=False)
    audit = {'files': files, 'findings': findings, 'formattingExitCode': formatting.returncode, 'cxx14Configuration': True, 'encodingAndNewlinesPreserved': True}
    (output / 'source-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'basedOnPublishedCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip(),
               'buildInputs': inputs, 'changedBuildInputs': changed, 'windows': rows, 'sourceAudit': proof(output / 'source-audit.json'),
               'readyFastPathImplemented': True, 'timeoutsCancellationAndPeerFailureChecksPreserved': True,
               'throughputImprovementProven': False, 'originalUbuntuTimeoutCauseEstablished': False,
               'allPlatformR107RuntimeVerified': False, 'fullSafeGcImplemented': False, 'globalDiskQuotaImplemented': False,
               'passed': True, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(__file__, output / 'verification-driver.py')
    print(json.dumps({'passed': True, 'windowsToolchains': 2, 'coreTargetsEach': 23, 'tlsCasesEach': 31, 'changedBuildInputs': changed, 'throughputImprovementProven': False}))


if __name__ == '__main__':
    main()

"""日期：2026-11-07；严格保存R95独立Ubuntu原退出超时，成功专项不覆盖完整回归失败。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET


# 日期：2026-11-07；207构建输入、327冻结源码、二进制和每份原XML逐件核对，失败保持失败。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-06/listener-r95-final-glibc'
    commit = '5dd243fbad36da36568943513deed95ee124ba2d'
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    selected = runpy.run_path('.cache/verify-r95-local-terminals.py')['listener']
    driver = json.loads((output / 'driver-result.json').read_text('utf-8'))
    assert driver['exitCode'] == 1 and driver['sourceCommit'] == commit
    frozen = json.loads((root / 'docs/ci-verification-20261106-r95.json').read_text('utf-8'))
    manifest = json.loads((output / 'results/source-manifest.json').read_text('utf-8'))['files']
    assert len(frozen['buildInputs']) == 207 and len(manifest) == 327
    archive_path = root / '.cache/source-listener-r95-final.tar.gz'
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == driver['sourceSnapshotSha256']
    with tarfile.open(archive_path) as archive:
        for row in frozen['buildInputs']:
            raw = subprocess.check_output(['git', 'show', commit + ':' + row['path']],
                                          cwd=root / '.cache/github-29583855-dukto-next-r28')
            assert raw == archive.extractfile(row['path']).read()
            assert hashlib.sha256(raw).hexdigest() == row['sha256'] == manifest[row['path']]['sha256']
    assert '[186/186]' in (output / 'results/build.log').read_text('utf-8')
    assert (output / 'results/binaries-before.sha256').read_bytes() == (output / 'results/binaries-after.sha256').read_bytes()
    assert (output / 'results/exit-codes.txt').read_text('utf-8').splitlines() == ['ctest 8', 'listener 0', 'parallel-exit 0']
    assert '96% tests passed, 1 tests failed out of 23' in (output / 'results/ctest.log').read_text('utf-8')
    xmls = sorted((output / 'build/Testing/QtTest').glob('*.xml'))
    assert len(xmls) == 22
    failures = []
    for path in xmls:
        for case in ET.parse(path).findall('.//testcase'):
            details = case.findall('failure') + case.findall('error')
            if details:
                failures.append({'report': helper['proof'](path), 'method': case.get('name'),
                                 'details': [node.attrib for node in details]})
            else:
                assert case.get('result') == 'pass', (path, case.attrib)
    assert len(failures) == 1 and failures[0]['method'] == 'parallelDispositions'
    assert failures[0]['details'] == [{'tag': 'download-16-2',
                                      'message': "'server.waitForFinished(10000)' returned FALSE. ()",
                                      'result': 'fail'}]
    selected(output / 'results/listener-qt.log')
    for name in ('listener-qt', 'parallel-exit-qt'):
        tree = ET.parse(output / ('results/' + name + '.xml'))
        assert not tree.findall('.//failure') and not tree.findall('.//error')
        assert all(row.get('result') == 'pass' for row in tree.findall('.//testcase'))
    value = {'sourceCommit': commit, 'actualPlatform': 'Ubuntu 24.04 glibc in independent VM',
             'snapshotFiles': 327, 'buildInputsVerified': 207, 'allInputsMatchExactGitCommit': True,
             'buildSteps': 186, 'completeBuildPassed': True, 'coreTargets': 23, 'coreTargetsPassed': 22,
             'coreFailures': failures, 'originalFailureTimeoutMs': 10000,
             'selectedOriginalListenerAnd4LaneExitPassed': True, 'binariesUnchanged': True,
             'allQtOriginalReports': [helper['proof'](p) for p in xmls],
             'sourceSnapshotSha256': driver['sourceSnapshotSha256'],
             'rootCauseProven': False, 'entireProtocolSuiteRun': False, 'passed': False,
             'releaseQualified': False, 'deliveryComplete': False}
    receipt = output / 'verified-failure-receipt.json'
    assert not receipt.exists() and not (output / 'verified-receipt.json').exists()
    receipt.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/validate-listener-r95-final-glibc.py', output / 'validation-driver.py')
    shutil.copyfile(Path(__file__), output / 'failure-verification-driver.py')
    print(json.dumps({'fullRegressionPassed': False, 'passedTargets': 22, 'totalTargets': 23,
                      'originalFailedRow': 'parallelDispositions:download-16-2',
                      'snapshotInputsVerified': 207, 'originalTimeoutMs': 10000}), flush=True)


if __name__ == '__main__':
    main()

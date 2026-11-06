"""日期：2026-11-07；收验当前独立Ubuntu干净构建，失败仍保存原件而不降低成功规则。"""
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET


# 日期：2026-11-07；源快照、远端源清单和Git对象全集一致后，分别收验完整23核心与原监听/退出专项。
def main():
    root = Path.cwd()
    folder = root / 'docs/validation/2026-11-07/exit-state-r98-final-glibc'
    commit = 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
    driver = json.loads((folder / 'driver-result.json').read_text('utf-8'))
    assert driver['sourceCommit'] == commit and driver['actualPlatform'] == 'Ubuntu glibc'
    frozen = json.loads((root / '.cache/r98-linux-snapshot-verified.json').read_text('utf-8'))
    assert frozen['sourceCommit'] == commit and frozen['files'] == 333 and frozen['buildInputsVerified'] == 210
    assert frozen['archiveSha256'] == driver['sourceSnapshotSha256']
    snapshot = root / '.cache/source-exit-state-r98-final.tar.gz'
    with snapshot.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == frozen['archiveSha256']
    manifest = json.loads((folder / 'results/source-manifest.json').read_text('utf-8'))['files']
    listing = subprocess.check_output(['git', 'ls-tree', '-r', '-z', commit],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
    blobs = {}
    for entry in listing.split(b'\0'):
        if entry:
            header, name = entry.split(b'\t', 1)
            blobs[name.decode('utf-8')] = header.split()[2].decode()
    count = 0
    with tarfile.open(snapshot) as archive:
        for item in archive:
            if item.name == '.dukto-source-snapshot.json':
                continue
            assert item.isfile() and item.name in manifest
            raw = archive.extractfile(item).read()
            assert manifest[item.name] == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blobs[item.name]
            count += 1
    assert len(manifest) == count == 333
    xmls = sorted((folder / 'build/Testing/QtTest').glob('*.xml'))
    failures = []
    for path in xmls:
        for case in ET.parse(path).findall('.//testcase'):
            if case.get('result') != 'pass':
                failures.append({'report': path.name, 'method': case.get('name'),
                                 'result': case.get('result'), 'details': [row.attrib for row in case]})
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    value = {'sourceCommit': commit, 'sourceFilesVerified': 333, 'buildInputsVerified': 210,
             'sourceSnapshotSha256': frozen['archiveSha256'], 'allSourcesMatchExactGitBlobs': True,
             'driverExitCode': driver['exitCode'], 'originalQtReportCount': len(xmls),
             'originalUnexpectedQtResults': failures, 'cleanBuild': True,
             'entireProtocolSuiteRun': False, 'releaseQualified': False, 'deliveryComplete': False}
    if driver['exitCode'] == 0:
        assert not failures and len(xmls) == 22
        assert '[186/186]' in (folder / 'results/build.log').read_text('utf-8')
        value['core'] = runpy.run_path('.cache/verify-r95-local-terminals.py')['core'](
            folder, folder / 'results/ctest.log', folder / 'build/Testing/QtTest')
        assert (folder / 'results/exit-codes.txt').read_text('utf-8').splitlines() == ['ctest 0', 'listener 0', 'exit-states 0']
        assert (folder / 'results/binaries-before.sha256').read_bytes() == (folder / 'results/binaries-after.sha256').read_bytes()
        for name in ('listener-qt', 'exit-states-qt'):
            tree = ET.parse(folder / 'results' / (name + '.xml'))
            assert not tree.findall('.//failure') and not tree.findall('.//error')
            assert all(case.get('result') == 'pass' for case in tree.findall('.//testcase'))
        runpy.run_path('.cache/verify-r95-local-terminals.py')['listener'](folder / 'results/listener-qt.log')
        text = (folder / 'results/exit-states-qt.log').read_text('utf-8')
        for row in ('already-finished', 'already-finished-error', 'running-finishes', 'real-deadline'):
            assert 'PASS   : FileExchangeTests::childExitWait(' + row + ')' in text
        assert text.count('PASS   : FileExchangeTests::parallelDispositions(') == 16
        value.update(coreTargets=23, newExitStateRows=4, originalParallelRows=16,
                     binariesUnchanged=True, passed=True)
        name = 'verified-receipt.json'
    else:
        value.update(passed=False, originalFailurePreserved=True)
        name = 'verified-failure-receipt.json'
    value['sourceManifest'] = helper['proof'](folder / 'results/source-manifest.json')
    path = folder / name
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/validate-exit-state-r98-final-glibc.py', folder / 'validation-driver.py')
    shutil.copyfile(root / '.cache/r98-linux-snapshot-verified.json', folder / 'snapshot-source-proof.json')
    shutil.copyfile(Path(__file__), folder / 'verification-driver.py')
    print(json.dumps({'sourceCommit': commit, 'cleanBuild': True, 'passed': value['passed'],
                      'receipt': path.relative_to(root).as_posix()}), flush=True)


if __name__ == '__main__':
    main()

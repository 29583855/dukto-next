"""日期：2026-11-06；严格收验最终公开R94在独立Ubuntu的冻结干净构建与全文分页业务。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET


# 日期：2026-11-06；运行仍未结束时拒绝收验，逐字节核对快照、206输入、Git对象与原始测试。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-06/text-view-r94-final-glibc'
    driver = json.loads((output / 'driver-result.json').read_text('utf-8'))
    commit = 'dec40621cce2d223e46b343e0d3d345a67b80523'
    expected_sha = '7f6116a05f181b93f0ccac754a2de54a60c2e567d6835d70c6a290732ffe9d5e'
    snapshot = root / '.cache/source-text-view-r94-final.tar.gz'
    assert driver['exitCode'] == 0 and driver['sourceCommit'] == commit
    assert driver['actualPlatform'] == 'Ubuntu glibc' and driver['sourceSnapshotSha256'] == expected_sha
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == expected_sha
    frozen = json.loads((root / 'docs/ci-verification-20261106-r94.json').read_text('utf-8'))
    assert frozen['productionCommit'] == commit and len(frozen['buildInputs']) == 206
    manifest = json.loads((output / 'results/source-manifest.json').read_text('utf-8'))['files']
    assert len(manifest) == 319
    listing = subprocess.check_output(['git', 'ls-tree', '-r', '-z', commit],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
    blobs = {}
    for entry in listing.split(b'\0'):
        if entry:
            header, encoded = entry.split(b'\t', 1)
            blobs[encoded.decode('utf-8')] = header.split()[2].decode()
    with tarfile.open(snapshot) as archive:
        for row in frozen['buildInputs']:
            member = archive.getmember(row['path'])
            assert member.isfile() and not member.issym() and not member.islnk()
            raw = archive.extractfile(member).read()
            assert hashlib.sha256(raw).hexdigest() == row['sha256'] == manifest[row['path']]['sha256']
            assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blobs[row['path']]
    assert '[186/186]' in (output / 'results/build.log').read_text('utf-8')
    assert '100% tests passed, 0 tests failed out of 23' in (output / 'results/ctest.log').read_text('utf-8')
    assert (output / 'results/binaries-before.sha256').read_bytes() == (output / 'results/binaries-after.sha256').read_bytes()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    xmls = sorted((output / 'build/Testing/QtTest').glob('*.xml'))
    assert len(xmls) == 22
    for path in xmls:
        tree = ET.parse(path)
        assert not tree.findall('.//failure') and not tree.findall('.//error')
        assert all(row.get('result') == 'pass' for row in tree.findall('.//testcase'))
    business = []
    for name in ('text-preview', 'legacy-text-credit', 'legacy', 'cli'):
        path = output / 'results' / (name + '.json')
        value = json.loads(path.read_text('utf-8'))
        runpy.run_path('.cache/collect-exact-native-r87.py')['verify_passed'](value)
        business.append(helper['proof'](path))
    preview = json.loads((output / 'results/text-preview.json').read_text('utf-8'))
    assert preview['passed'] and preview['completed'] and len(preview['cases']) == 4
    for row in preview['cases']:
        assert row['guiEvidence']['clipboardFullTextVerified'] and row['guiEvidence']['historyReopenVerified']
        assert row['guiEvidence']['firstPageBlocks'] <= 513
        assert row['peak'] and row['peak']['rss'] < 512 * 1024**2 and row['peak']['private'] < 512 * 1024**2
    text = json.loads((output / 'results/legacy-text-credit.json').read_text('utf-8'))['cases'][0]
    assert text['bytes'] == 8 * 1024**2 and text['jsonBytes'] > 48 * 1024**2 and text['completeTextVerified']
    assert text['memorySamplingRequired'] and text['memoryQualified'] and all(text['peaks'].get(role) for role in ('sender', 'receiver'))
    value = {'date': '2026-11-06', 'sourceCommit': commit, 'actualPlatform': 'Ubuntu glibc',
             'sourceSnapshotSha256': expected_sha, 'sourceFiles': 319, 'buildInputsVerified': 206,
             'allBuildInputsMatchExactGitCommit': True, 'cleanBuildSteps': 186, 'coreTargets': 23,
             'qtTestReports': [helper['proof'](path) for path in xmls], 'selectedReports': business,
             'binariesUnchanged': True, 'passed': True, 'entireNativeProtocolSuiteRun': False,
             'newTextPagingScreenshotsReviewed': False, 'releaseQualified': False, 'deliveryComplete': False}
    path = output / 'verified-receipt.json'
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/validate-text-view-r94-final-glibc.py', output / 'validation-driver.py')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': commit, 'coreTargets': 23, 'selectedReports': 4, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()

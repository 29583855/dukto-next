"""日期：2026-11-06；核验独立Ubuntu R93冻结源码、23核心和三份业务，目录旧命名musl不改变实际glibc平台。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
OUT = ROOT / 'docs/validation/2026-11-06/legacy-text-r93-glibc-musl'
H = runpy.run_path('.cache/finalize-skip-items-r84.py')


# 日期：2026-11-06；只对冻结快照和R93 Git blob核对，不使用当前已修改的R94工作区源码。
def main():
    driver = json.loads((OUT / 'driver-result.json').read_text('utf-8'))
    assert driver['exitCode'] == 0 and driver['remoteRoot'] == '/home/dukto/legacy-text-r93-glibc'
    snapshot = ROOT / '.cache/source-legacy-text-r93.tar.gz'
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == driver['sourceSnapshotSha256']
    r93 = json.loads((ROOT / 'docs/ci-verification-20261106-r93.json').read_text('utf-8'))
    sha = r93['productionCommit']
    assert sha == 'b615d8a0e820bcf9de05d0dce546e930b27ad748'
    listing = subprocess.check_output(['git', 'ls-tree', '-r', '-z', sha], cwd=ROOT / '.cache/github-29583855-dukto-next-r28')
    blobs = {}
    for entry in listing.split(b'\0'):
        if entry:
            metadata, name = entry.split(b'\t', 1)
            blobs[name.decode('utf-8')] = metadata.split()[2].decode()
    manifest = json.loads((OUT / 'results/source-manifest.json').read_text('utf-8'))['files']
    assert len(r93['buildInputs']) == 203
    with tarfile.open(snapshot) as archive:
        for row in r93['buildInputs']:
            member = archive.getmember(row['path'])
            assert member.isfile() and not member.issym() and not member.islnk()
            data = archive.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest() == row['sha256'] == manifest[row['path']]['sha256']
            assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == blobs[row['path']]
    assert '[185/185]' in (OUT / 'results/build.log').read_text('utf-8')
    assert '100% tests passed, 0 tests failed out of 23' in (OUT / 'results/ctest.log').read_text('utf-8')
    xmls = sorted((OUT / 'build/Testing/QtTest').glob('*.xml'))
    assert len(xmls) == 22
    for path in xmls:
        tree = ET.parse(path)
        assert not tree.findall('.//failure') and not tree.findall('.//error')
        assert all(case.get('result') == 'pass' for case in tree.findall('.//testcase'))
    assert (OUT / 'results/binaries-before.sha256').read_bytes() == (OUT / 'results/binaries-after.sha256').read_bytes()
    reports = []
    for name in ('legacy-text-credit', 'legacy', 'cli'):
        path = OUT / 'results' / (name + '.json')
        value = json.loads(path.read_text('utf-8'))
        runpy.run_path('.cache/collect-exact-native-r87.py')['verify_passed'](value)
        reports.append(H['proof'](path))
    maximum = json.loads((OUT / 'results/legacy-text-credit.json').read_text('utf-8'))['cases'][0]
    assert maximum['bytes'] == 8 * 1024**2 and maximum['jsonBytes'] > 48 * 1024**2 and maximum['completeTextVerified']
    assert all(maximum['peaks'].get(role) for role in ('receiver', 'sender'))
    value = {'date': datetime.now(timezone.utc).isoformat(), 'sourceCommit': sha, 'actualPlatform': 'Ubuntu glibc',
             'directoryNameContainsHistoricalMuslTypo': True, 'sourceSnapshotSha256': driver['sourceSnapshotSha256'],
             'allBuildInputsMatchExactGitCommit': True, 'buildInputsVerified': 203, 'cleanBuildSteps': 185,
             'coreTargets': 23, 'qtTestReports': [H['proof'](p) for p in xmls], 'selectedReports': reports,
             'binariesUnchanged': True, 'maximumText': maximum, 'passed': True,
             'entireNativeProtocolSuiteRun': False, 'releaseQualified': False, 'deliveryComplete': False}
    path = OUT / 'verified-receipt.json'
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(ROOT / '.cache/validate-legacy-text-r93-glibc.py', OUT / 'validation-driver.py')
    shutil.copyfile(Path(__file__), OUT / 'verification-driver.py')
    print(json.dumps({'sourceCommit': sha, 'buildInputs': 203, 'coreTargets': 23, 'protocolReports': 3,
                      'actualPlatform': 'Ubuntu glibc', 'passed': True}))


if __name__ == '__main__':
    main()

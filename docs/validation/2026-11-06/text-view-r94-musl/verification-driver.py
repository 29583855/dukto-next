"""日期：2026-11-06；仅收验R94早期Alpine快照，不把缺少最终监听适配器的结果授予公开R94。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET


# 日期：2026-11-06；核对原冻结输入、安装清单、真实日志和全部业务，明确与最终Git输入的差异。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-06/text-view-r94-musl'
    driver = json.loads((output / 'driver-result.json').read_text('utf-8'))
    snapshot = root / '.cache/source-text-view-r94.tar.gz'
    expected = '9384a4b61c6400de37843fce023887efdd141fc2f345ef4f82f13b7d06826cd8'
    assert driver['exitCode'] == 0 and hashlib.sha256(snapshot.read_bytes()).hexdigest() == expected
    frozen_path = root / '.cache/r94-original-inputs-before-listener.json'
    frozen = json.loads(frozen_path.read_text('utf-8'))['files']
    manifest = json.loads((output / 'results/source-manifest.json').read_text('utf-8'))['files']
    assert len(frozen) == 204 and len(manifest) == 315
    commit = 'dec40621cce2d223e46b343e0d3d345a67b80523'
    differences = []
    with tarfile.open(snapshot) as archive:
        for row in frozen:
            member = archive.getmember(row['path'])
            assert member.isfile() and not member.issym() and not member.islnk()
            raw = archive.extractfile(member).read()
            assert hashlib.sha256(raw).hexdigest() == row['sha256'] == manifest[row['path']]['sha256']
            final = subprocess.check_output(['git', 'show', commit + ':' + row['path']],
                                            cwd=root / '.cache/github-29583855-dukto-next-r28')
            if raw != final:
                differences.append(row['path'])
    assert len(differences) == 9
    assert '[185/185]' in (output / 'results/build.log').read_text('utf-8')
    assert '100% tests passed, 0 tests failed out of 23' in (output / 'results/ctest.log').read_text('utf-8')
    assert (output / 'results/binaries-before.sha256').read_bytes() == (output / 'results/binaries-after.sha256').read_bytes()
    reports = []
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    for path in sorted((output / 'build/Testing/QtTest').glob('*.xml')):
        tree = ET.parse(path)
        assert not tree.findall('.//failure') and not tree.findall('.//error')
        assert all(row.get('result') == 'pass' for row in tree.findall('.//testcase'))
        reports.append(helper['proof'](path))
    assert len(reports) == 22
    business = []
    for name in ('text-preview', 'legacy-text-credit', 'legacy'):
        path = output / 'results' / (name + '.json')
        value = json.loads(path.read_text('utf-8'))
        runpy.run_path('.cache/collect-exact-native-r87.py')['verify_passed'](value)
        business.append(helper['proof'](path))
    preview = json.loads((output / 'results/text-preview.json').read_text('utf-8'))
    assert preview['passed'] and preview['completed'] and len(preview['cases']) == 4
    for case in preview['cases']:
        assert case['peak'] and case['peak']['rss'] < 512 * 1024**2 and case['peak']['private'] < 512 * 1024**2
        assert case['guiEvidence']['clipboardFullTextVerified'] and case['guiEvidence']['historyReopenVerified']
    value = {'date': '2026-11-06', 'actualPlatform': 'Alpine musl',
             'sourceSnapshotSha256': expected, 'snapshotFiles': 315, 'buildInputsVerified': 204,
             'frozenBuildInputsVerified': True, 'cleanBuildSteps': 185, 'coreTargets': 23,
             'qtTestReports': reports, 'selectedReports': business, 'binariesUnchanged': True,
             'finalPublicCommitCompared': commit, 'differentBuildInputsFromFinalCommit': differences,
             'missingFinalBuildInputs': ['src/core/tcplistener.cpp', 'src/core/tcplistener.h'],
             'finalPublicR94Qualified': False, 'containsFinalListenerAdapter': False,
             'earlySnapshotSelectedTestsPassed': True, 'entireProtocolSuiteRun': False,
             'releaseQualified': False, 'deliveryComplete': False}
    path = output / 'verified-receipt.json'
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(frozen_path, output / 'frozen-build-inputs.json')
    shutil.copyfile(root / '.cache/validate-text-view-r94-musl.py', output / 'validation-driver.py')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'earlySnapshotPassed': True, 'buildInputs': 204, 'coreTargets': 23,
                      'selectedReports': 3, 'finalPublicR94Qualified': False}), flush=True)


if __name__ == '__main__':
    main()

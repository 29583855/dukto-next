"""日期：2026-11-06；收验R92冻结Alpine干净构建，逐输入比对精确Git而非当前R93工作区。"""
from pathlib import Path
import hashlib
import json
import runpy
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-06；源码、所有原XML及退出码均通过后生成独立回执，原失败不改写。
def main():
    root = Path.cwd()
    out = root / 'docs/validation/2026-11-06/discovery-r92-musl'
    h = runpy.run_path('.cache/finalize-skip-items-r84.py')
    driver = json.loads((out / 'driver-result.json').read_text('utf-8'))
    assert driver['exitCode'] == 0
    inputs = json.loads((root / '.cache/r92-exact-inputs.json').read_text('utf-8'))
    sha = inputs['sourceCommit']
    manifest = json.loads((out / 'results/source-manifest.json').read_text('utf-8'))
    for row in inputs['files']:
        data = subprocess.check_output(['git', 'show', sha + ':' + row['path']],
                                       cwd=root / '.cache/github-29583855-dukto-next-r28')
        digest = hashlib.sha256(data).hexdigest()
        assert digest == row['sha256'] == manifest['files'][row['path']]['sha256'], row['path']
    assert len(inputs['files']) == 202
    assert (out / 'results/binaries-before.sha256').read_bytes() == (out / 'results/binaries-after.sha256').read_bytes()
    exits = (out / 'results/exit-codes.txt').read_text('utf-8').splitlines()
    assert exits == ['ctest 0'] + ['discovery-' + str(i) + ' 0' for i in range(1, 11)] + ['legacy 0'], exits
    assert '100% tests passed, 0 tests failed out of 23' in (out / 'results/ctest.log').read_text('utf-8')
    xmls = sorted((out / 'build/Testing/QtTest').glob('*.xml')) + sorted((out / 'results').glob('discovery-*.xml'))
    assert len(xmls) == 32, len(xmls)
    for path in xmls:
        tree = ET.parse(path)
        assert not tree.findall('.//failure') and not tree.findall('.//error')
        assert all(case.get('result') == 'pass' for case in tree.findall('.//testcase'))
    legacy = json.loads((out / 'results/legacy.json').read_text('utf-8'))
    assert len(legacy) == 5 and all(row['passed'] for row in legacy)
    target = out / 'verified-receipt.json'
    assert not target.exists()
    value = {'sourceCommit': sha, 'buildInputsEachByteVerified': 202,
             'sourceManifest': h['proof'](out / 'results/source-manifest.json'),
             'snapshotSha256': driver['sourceSnapshotSha256'], 'driver': h['proof'](out / 'driver-result.json'),
             'ctest': h['proof'](out / 'results/ctest.log'), 'coreTargets': 23,
             'discoveryOriginalMethodRepeatsPassed': 10, 'xmls': [h['proof'](path) for path in xmls],
             'legacy': h['proof'](out / 'results/legacy.json'), 'legacyFixtureCases': 5,
             'binariesUnchangedThroughValidation': True, 'passed': True,
             'doesNotQualifyR93': True, 'releaseQualified': False, 'deliveryComplete': False}
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'sourceCommit': sha, 'buildInputs': 202, 'coreTargets': 23,
                      'discoveryRepeats': 10, 'legacyCases': 5, 'passed': True}))


if __name__ == '__main__':
    main()

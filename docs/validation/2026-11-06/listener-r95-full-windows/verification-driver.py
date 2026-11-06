"""日期：2026-11-06；严格收验R95独立Ubuntu或双Windows的完整构建和原始核心结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-06；同时检查JUnit聚合方法及逐数据行日志，避免把方法数误当实际执行行数。
def listener(log):
    text = log.read_text('utf-8')
    assert text.count('PASS   : CoreTests::exclusiveTcpBinding(') == 8
    assert text.count('PASS   : CoreTests::tcpGracefulRestart(') == 3
    assert 'PASS   : CoreTests::tcpAddressFamilies()' in text


# 日期：2026-11-06；23目标和至少22Qt原报告必须全部存在且无失败，日志原件始终保持原字节。
def core(folder, ctest, xml_folder):
    log = ctest.read_text('utf-8')
    assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$', log, re.M)
    xmls = sorted(xml_folder.glob('*.xml'))
    assert len(xmls) == 22
    for path in xmls:
        tree = ET.parse(path)
        assert not tree.findall('.//failure') and not tree.findall('.//error')
        assert all(row.get('result') == 'pass' for row in tree.findall('.//testcase'))
    listener(xml_folder / 'core-tests.log')
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    return {'coreTargets': 23, 'ctest': proof(ctest), 'qtReports': [proof(path) for path in xmls]}


# 日期：2026-11-06；仅在驱动成功终态后写入一次回执，全部207输入先核对精确公开Git对象。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('platform', choices=('windows', 'glibc'))
    args = parser.parse_args()
    root = Path.cwd()
    commit = '5dd243fbad36da36568943513deed95ee124ba2d'
    frozen = json.loads((root / 'docs/ci-verification-20261106-r95.json').read_text('utf-8'))
    assert len(frozen['buildInputs']) == 207
    for row in frozen['buildInputs']:
        raw = subprocess.check_output(['git', 'show', commit + ':' + row['path']],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert (root / row['path']).read_bytes() == raw
    folder = root / ('docs/validation/2026-11-06/listener-r95-full-windows' if args.platform == 'windows'
                     else 'docs/validation/2026-11-06/listener-r95-final-glibc')
    driver = json.loads((folder / 'driver-result.json').read_text('utf-8'))
    assert driver['sourceCommit'] == commit
    value = {'sourceCommit': commit, 'platform': args.platform, 'buildInputsVerified': 207,
             'allInputsMatchExactGitCommit': True, 'entireProtocolSuiteRun': False,
             'releaseQualified': False, 'deliveryComplete': False}
    if args.platform == 'windows':
        assert driver['completed'] and driver['passed'] and driver['buildInputsUnchanged'] == 207
        assert [row['toolchain'] for row in driver['cases']] == ['ucrt', 'msvc']
        assert all(row['buildExitCode'] == row['ctestExitCode'] == 0 for row in driver['cases'])
        value['toolchains'] = [dict(core(folder / label, folder / label / 'ctest.log', folder / label / 'QtTest'),
                                    toolchain=label) for label in ('ucrt', 'msvc')]
        validation_driver = '.cache/validate-listener-r95-full-windows.py'
    else:
        assert driver['exitCode'] == 0 and driver['actualPlatform'] == 'Ubuntu glibc'
        snapshot = json.loads((root / '.cache/r95-linux-snapshot-verified.json').read_text('utf-8'))
        assert snapshot['sourceCommit'] == commit and snapshot['sourceFiles'] == 327 and snapshot['buildInputs'] == 207
        assert snapshot['sourceSnapshotSha256'] == driver['sourceSnapshotSha256']
        assert hashlib.sha256((root / '.cache/source-listener-r95-final.tar.gz').read_bytes()).hexdigest() == driver['sourceSnapshotSha256']
        manifest = json.loads((folder / 'results/source-manifest.json').read_text('utf-8'))['files']
        assert len(manifest) == 327
        for row in frozen['buildInputs']:
            assert manifest[row['path']]['sha256'] == row['sha256']
        assert '[186/186]' in (folder / 'results/build.log').read_text('utf-8')
        assert (folder / 'results/binaries-before.sha256').read_bytes() == (folder / 'results/binaries-after.sha256').read_bytes()
        assert (folder / 'results/exit-codes.txt').read_text('utf-8').splitlines() == ['ctest 0', 'listener 0', 'parallel-exit 0']
        listener(folder / 'results/listener-qt.log')
        for name in ('listener-qt', 'parallel-exit-qt'):
            tree = ET.parse(folder / 'results' / (name + '.xml'))
            assert not tree.findall('.//failure') and not tree.findall('.//error')
            assert all(row.get('result') == 'pass' for row in tree.findall('.//testcase'))
        value.update(core(folder, folder / 'results/ctest.log', folder / 'build/Testing/QtTest'))
        value.update(snapshot=snapshot, selectedOriginalListenerAndExitPassed=True, binariesUnchanged=True)
        validation_driver = '.cache/validate-listener-r95-final-glibc.py'
    path = folder / 'verified-receipt.json'
    assert not path.exists()
    value['passed'] = True
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / validation_driver, folder / 'validation-driver.py')
    shutil.copyfile(Path(__file__), folder / 'verification-driver.py')
    print(json.dumps({'platform': args.platform, 'passed': True, 'receipt': str(path)}), flush=True)


if __name__ == '__main__':
    main()

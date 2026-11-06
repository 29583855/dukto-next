"""日期：2026-11-07；收取独立moc重编译的Linux退出夹具专项，保留首次旧moc失败。"""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET


# 日期：2026-11-07；只收自有日志/源码并绑定精确Git测试字节，明确这不是干净完整Linux构建。
def main():
    commit = '38f2384524bfdefa2ffefcc4c737224185a53266'
    ssh = runpy.run_path('.cache/validate-listener-r95-final-glibc.py')['SSH']
    remote = subprocess.run(ssh + ['cd /home/dukto/exit-state-r97-targeted-moc && '
                                  'tar czf - report.json qt.log qt.xml stdout.log build.log file_exchange_tests.cpp file_exchange_tests.moc'],
                            capture_output=True, check=True, timeout=30)
    output = Path('docs/validation/2026-11-07/exit-state-r97-glibc-targeted')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'originals.tar.gz').write_bytes(remote.stdout)
    with tarfile.open(fileobj=io.BytesIO(remote.stdout)) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert member.isfile() and member.size <= 4 * 1024**2
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            assert path.suffix in ('.json', '.log', '.xml', '.cpp', '.moc')
            (output / path).write_bytes(archive.extractfile(member).read())
    report = json.loads((output / 'report.json').read_text('utf-8'))
    assert report['passed'] and report['originalFilesUnchanged'] and report['originalWaitMs'] == 10000
    assert report['newStateDataRows'] == 4 and report['originalParallelDataRows'] == 16
    source = subprocess.check_output(['git', 'show', commit + ':tests/file_exchange_tests.cpp'],
                                     cwd='.cache/github-29583855-dukto-next-r28')
    assert source == (output / 'file_exchange_tests.cpp').read_bytes() == Path('tests/file_exchange_tests.cpp').read_bytes()
    assert report['testSourceSha256'] == hashlib.sha256(source).hexdigest()
    subprocess.run(['git', 'diff', '--quiet', report['productionCoreCommit'], commit, '--', 'src'],
                   cwd='.cache/github-29583855-dukto-next-r28', check=True)
    tree = ET.parse(output / 'qt.xml')
    assert not tree.findall('.//failure') and not tree.findall('.//error')
    assert all(case.get('result') == 'pass' for case in tree.findall('.//testcase'))
    log = (output / 'qt.log').read_text('utf-8')
    assert log.count('PASS   : FileExchangeTests::childExitWait(') == 4
    assert log.count('PASS   : FileExchangeTests::parallelDispositions(') == 16
    value = {'sourceCommit': commit, 'testSourceSha256': report['testSourceSha256'],
             'testSourceMatchesExactGitCommit': True, 'productionSourceUnchangedFromCoreBuild': True,
             'originalCoreCommit': report['productionCoreCommit'], 'originalFilesUnchanged': True,
             'originalWaitMs': 10000, 'newStateDataRows': 4, 'originalParallelDataRows': 16,
             'ownMocGenerated': True, 'passed': True,
             'scope': report['scope'], 'archiveSha256': hashlib.sha256(remote.stdout).hexdigest(),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    for name in ('validate-r97-glibc-test-remote.py', 'r97-glibc-targeted-moc-driver.log'):
        shutil.copyfile(Path('.cache') / name, output / name)
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': commit, 'newStateDataRows': 4, 'originalParallelDataRows': 16,
                      'ownMocGenerated': True, 'targetedPassed': True, 'cleanFullBuild': False}), flush=True)


if __name__ == '__main__':
    main()

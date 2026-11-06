"""日期：2026-11-07；收验独立Qt退出状态诊断，显式区分自然运行与100ms事件泵刺激。"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET


# 日期：2026-11-07；精确导出诊断原件，已收件归档可恢复解析，不覆盖原二进制及旧失败。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('normal', 'forced'))
    args = parser.parse_args()
    forced = args.kind == 'forced'
    tag = 'listener-r95-exit-state-' + ('forced' if forced else 'diagnostic')
    output = (Path('docs/validation/2026-11-07') / tag.replace('listener-r95-', 'listener-r95-glibc-')).resolve()
    assert not (output / 'receipt.json').exists()
    archive_path = output / 'originals.tar.gz'
    if archive_path.exists():
        raw = archive_path.read_bytes()
    else:
        ssh = runpy.run_path('.cache/validate-listener-r95-final-glibc.py')['SSH']
        remote = subprocess.run(ssh + ['cd /home/dukto/' + tag +
                                      ' && tar czf - report.json probe.log probe.xml probe.stdout.log compile.log file_exchange_tests.cpp'],
                                capture_output=True, check=True, timeout=30)
        output.mkdir(parents=True, exist_ok=False)
        raw = remote.stdout
        archive_path.write_bytes(raw)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            assert member.isfile() and member.size <= 4 * 1024**2
            target = output / path
            assert target.suffix in ('.json', '.log', '.xml', '.cpp')
            contents = archive.extractfile(member).read()
            if target.exists():
                assert target.read_bytes() == contents
            else:
                target.write_bytes(contents)
    report = json.loads((output / 'report.json').read_text('utf-8'))
    assert report['originalBinaryAndCoreUnchanged'] and report['originalWaitMs'] == 10000
    assert report['originalFailureConditionUnchanged'] and not report['productionFixProven']
    original = json.loads(Path('docs/validation/2026-11-07/listener-r95-glibc-group-exit-diagnostic/receipt.json').read_text('utf-8'))
    assert report['originalFiles']['/home/dukto/listener-r95-final/build/file-exchange-tests'] == original['originalBinarySha256']
    assert hashlib.sha256((output / 'file_exchange_tests.cpp').read_bytes()).hexdigest() == report['diagnosticSourceSha256']
    log = (output / 'probe.log').read_text('utf-8')
    before = re.findall(r'parallelDispositions\(([^)]+)\) exit-state-before state QProcess::(\w+) pid (\d+)', log)
    after = re.findall(r'parallelDispositions\(([^)]+)\) exit-state-after state QProcess::(\w+) result (\w+) elapsedMs (\d+) exitStatus QProcess::(\w+) exitCode (\d+)', log)
    assert len(before) == len(after) == (1 if forced else 16)
    failures = ET.parse(output / 'probe.xml').findall('.//failure')
    if forced:
        assert report['exitStateStimulusInjected'] and report['delayBeforeOriginalWaitMs'] == 100
        assert report['exitCode'] == 1 and len(failures) == 1
        assert before == [('download-4-1', 'NotRunning', '0')]
        assert after[0][0:3] == ('download-4-1', 'NotRunning', 'false')
        assert int(after[0][3]) < 10 and after[0][4:] == ('NormalExit', '0')
    else:
        assert report['exitCode'] == 0 and not failures
        assert all(row[1] == 'Running' for row in before)
        assert all(row[1:3] == ('NotRunning', 'true') and row[4:] == ('NormalExit', '0') for row in after)
    value = {'sourceCommit': report['sourceCommit'], 'originalBinaryAndCoreUnchanged': True,
             'mode': args.kind, 'rows': len(after), 'originalWaitMs': 10000,
             'exitStateStimulusInjected': forced, 'delayBeforeWaitMs': 100 if forced else 0,
             'statesBefore': before, 'statesAfter': after,
             'alreadyFinishedReturnsFalseWithNormalExitReproduced': forced,
             'originalFailuresDefinitiveCauseProven': False, 'productionFixProven': False,
             'archiveSha256': hashlib.sha256(raw).hexdigest(),
             'releaseQualified': False, 'deliveryComplete': False}
    driver = 'diagnose-r95-glibc-exit-state-' + ('forced-remote.py' if forced else 'remote.py')
    driver_log = 'r95-glibc-exit-state-' + ('forced-driver.log' if forced else 'diagnostic-driver.log')
    shutil.copyfile(Path('.cache') / driver, output / driver)
    shutil.copyfile(Path('.cache') / driver_log, output / driver_log)
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({'mode': args.kind, 'rows': len(after),
                      'alreadyFinishedFalseReproduced': forced, 'allSpecifiedObservationsVerified': True}), flush=True)


if __name__ == '__main__':
    main()

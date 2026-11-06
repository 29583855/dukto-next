"""日期：2026-11-07；保存原二进制整组处置顺序诊断，不覆盖原退出超时失败。"""
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


# 日期：2026-11-07；只接收自有普通日志；摘要步骤失败后按原归档恢复，拒绝改写已收件字节。
def main():
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    ssh = runpy.run_path('.cache/validate-listener-r95-final-glibc.py')['SSH']
    output = Path('docs/validation/2026-11-07/listener-r95-glibc-group-exit-diagnostic').resolve()
    assert not (output / 'receipt.json').exists()
    archive_path = output / 'originals.tar.gz'
    if archive_path.exists():
        raw = archive_path.read_bytes()
    else:
        remote = subprocess.run(ssh + ['cd /home/dukto/listener-r95-group-exit-diagnostic && tar czf - .'],
                                capture_output=True, check=True, timeout=30)
        output.mkdir(parents=True, exist_ok=False)
        raw = remote.stdout
        archive_path.write_bytes(raw)
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            if member.isdir():
                continue
            assert member.isfile() and member.size <= 4 * 1024**2
            target = output / path
            assert target.suffix in ('.log', '.xml', '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            contents = archive.extractfile(member).read()
            if target.exists():
                assert target.read_bytes() == contents
            else:
                target.write_bytes(contents)
    original = json.loads(Path('docs/validation/2026-11-07/listener-r95-glibc-exit-diagnostic/receipt.json').read_text('utf-8'))
    report = json.loads((output / 'report.json').read_text('utf-8'))
    assert report['completed'] and report['binaryUnchanged'] and len(report['cases']) == 1
    assert report['originalBinarySha256'] == original['originalBinarySha256']
    assert report['originalExitWaitMs'] == 10000 and report['expectedDataRows'] == 16
    text = (output / 'attempt-1.log').read_text('utf-8')
    rows = re.findall(r'^(PASS   |FAIL!  )\s*:\s*FileExchangeTests::parallelDispositions\(([^)]+)\)', text, re.M)
    expected = {direction + '-' + str(lanes) + '-' + str(scenario)
                for direction in ('upload', 'download') for lanes in (4, 16) for scenario in range(4)}
    assert len(rows) == 16 and {row[1] for row in rows} == expected
    xml = ET.parse(output / 'attempt-1.xml')
    failures = xml.findall('.//failure') + xml.findall('.//error')
    passed = not failures and all(kind == 'PASS   ' for kind, _ in rows)
    assert passed == report['cases'][0]['passed']
    for name in ('diagnose-r95-glibc-group-exit-remote.py', 'r95-glibc-group-exit-diagnostic-driver.log'):
        shutil.copyfile(Path('.cache') / name, output / name)
    value = {'sourceCommit': report['sourceCommit'], 'originalBinarySha256': report['originalBinarySha256'],
             'originalBinaryUnchanged': True, 'originalExitWaitMs': 10000,
             'dataRows': 16, 'groupPassed': passed,
             'failedRows': [name for kind, name in rows if kind != 'PASS   '],
             'slowServiceSamples': report['cases'][0]['samples'],
             'observerMayPerturbTiming': True, 'originalFullRegressionStillFailed': True,
             'rootCauseProven': False, 'report': helper['proof'](output / 'report.json'),
             'archiveSha256': hashlib.sha256(raw).hexdigest(),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()

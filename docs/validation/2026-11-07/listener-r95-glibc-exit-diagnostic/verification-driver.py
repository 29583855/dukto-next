"""日期：2026-11-07；收件原二进制三次退出诊断，不用未复现覆盖原22/23失败。"""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import tarfile


# 日期：2026-11-07；只从自有诊断目录接收有限普通日志，拒绝路径逃逸、链接及历史目录覆盖。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    ssh = runpy.run_path('.cache/validate-listener-r95-final-glibc.py')['SSH']
    remote = subprocess.run(ssh + ['cd /home/dukto/listener-r95-exit-diagnostic && tar czf - .'],
                            capture_output=True, check=True, timeout=30)
    output = root / 'docs/validation/2026-11-07/listener-r95-glibc-exit-diagnostic'
    output.mkdir(parents=True, exist_ok=False)
    (output / 'originals.tar.gz').write_bytes(remote.stdout)
    with tarfile.open(fileobj=io.BytesIO(remote.stdout)) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            if member.isdir():
                continue
            assert member.isfile() and member.size <= 4 * 1024**2
            target = output / path
            assert target.suffix in ('.log', '.xml', '.json')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    result = json.loads((output / 'report.json').read_text('utf-8'))
    assert result['completed'] and result['binaryUnchanged'] and len(result['cases']) == 3
    assert all(row['passed'] and not row['samples'] and not row['failures'] for row in result['cases'])
    for name in ('.cache/diagnose-r95-glibc-exit-remote.py', '.cache/r95-glibc-gdb-install.log',
                 '.cache/r95-glibc-exit-diagnostic-driver.log'):
        shutil.copyfile(root / name, output / Path(name).name)
    value = {'sourceCommit': result['sourceCommit'], 'originalBinarySha256': result['originalBinarySha256'],
             'binaryUnchanged': True, 'attempts': 3, 'originalExitWaitMs': 10000,
             'originalFailureReproduced': False, 'slowServiceSampleCaptured': False,
             'originalFullRegressionStillFailed': True, 'rootCauseProven': False,
             'report': helper['proof'](output / 'report.json'),
             'archiveSha256': hashlib.sha256(remote.stdout).hexdigest(),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'attempts': 3, 'originalFailureReproduced': False,
                      'rootCauseProven': False, 'originalFullRegressionStillFailed': True}), flush=True)


if __name__ == '__main__':
    main()

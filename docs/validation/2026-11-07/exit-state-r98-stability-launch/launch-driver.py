"""日期：2026-11-07；冻结R98包和测试输入，先100轮再执行当前生产源码的Windows24小时长测。"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = Path.cwd()
FROZEN = ROOT / '.cache/current-windows-r98-long'
REPORT = ROOT / 'docs/validation/2026-11-07/current-windows-r98-long'
ARCHIVE = ROOT / 'dist/windows-preview-20261107-r98-exit-state/DuktoNext-windows-x64-preview.zip'
EXPECTED = '99f007bb1daf11a87750ecbb0435b5f0ccc617ce3baf9566efb77c72add77a82'


# 日期：2026-11-07；只提取测试自有已核验包的有界普通文件，全部输入固定在独立目录。
def freeze():
    assert not FROZEN.exists() and not REPORT.exists()
    runtime = json.loads((ROOT / 'docs/validation/2026-11-07/exit-state-r98-windows-package/runtime.json').read_text('utf-8'))
    assert runtime['passed'] and runtime['archiveSha256'] == EXPECTED
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() == EXPECTED
    FROZEN.mkdir()
    REPORT.mkdir()
    with zipfile.ZipFile(ARCHIVE) as package:
        seen = set()
        prefix = 'DuktoNext-windows-x64-preview/'
        for member in package.infolist():
            assert member.filename.startswith(prefix) and member.filename not in seen
            seen.add(member.filename)
            relative = PurePosixPath(member.filename[len(prefix):])
            assert not relative.is_absolute() and '..' not in relative.parts and ':' not in member.filename
            assert not stat.S_ISLNK(member.external_attr >> 16) and member.file_size < 64 * 1024**2
            if member.is_dir():
                continue
            target = FROZEN / 'runtime' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(member))
    tests = FROZEN / 'tests'
    tests.mkdir()
    checkout = ROOT / '.cache/windows-r98-package-source'
    for source in (checkout / 'tests').glob('*.py'):
        shutil.copyfile(source, tests / source.name)
    inventory = {p.relative_to(FROZEN).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in FROZEN.rglob('*') if p.is_file()}
    receipt = {'date': '2026-11-07', 'sourceCommit': 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7',
        'productionCommit': '88f33b2c83f2950307c362fb64c693f7e9e5929d',
        'archiveSha256': EXPECTED, 'files': inventory, 'requestedSeconds': 86400,
        'requestedChannels': 16, 'smokeRounds': 100, 'oldLongTestsChanged': False,
        'qualificationScope': 'current fixed Windows production kernel; bounded-task long test only',
        'passed': False}
    (REPORT / 'launch.json').write_text(json.dumps(receipt, indent=2) + chr(10), 'utf-8')
    return receipt


# 日期：2026-11-07；测试可生成独立pycache，原始输入不可变化；运行只使用冻结依赖及系统PATH。
def main():
    receipt = freeze()
    environment = {key: value for key, value in os.environ.items()
        if key.upper() in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'SYSTEMDRIVE', 'NUMBER_OF_PROCESSORS')}
    environment.update(PATH=str(FROZEN / 'runtime') + os.pathsep + str(Path(os.environ['SystemRoot']) / 'System32'),
        QT_PLUGIN_PATH=str(FROZEN / 'runtime'), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    cases = [('sampling', 'process_sampling_integration.py', []),
        ('smoke100', 'parallel_soak_portable_integration.py',
            [str(FROZEN / 'runtime/dukto-cli.exe'), '--rounds', '100', '--threads', '16', '--payload-mib', '1']),
        ('summary24h', 'parallel_soak_portable_integration.py',
            [str(FROZEN / 'runtime/dukto-cli.exe'), '--duration', '86400', '--interval', '300',
             '--threads', '16', '--payload-mib', '8'])]
    results = []
    for name, script, arguments in cases:
        with (REPORT / (name + '.log')).open('xb') as output:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-u', str(FROZEN / 'tests' / script),
                *arguments, '--report', str(REPORT / (name + '.json'))],
                env=environment, stdout=output, stderr=subprocess.STDOUT, timeout=93000)
        results.append({'name': name, 'exitCode': result.returncode})
        print(json.dumps(results[-1]), flush=True)
        if result.returncode:
            break
    unchanged = all(hashlib.sha256((FROZEN / name).read_bytes()).hexdigest() == sha
                    for name, sha in receipt['files'].items())
    value = {'date': '2026-11-07', 'cases': results, 'frozenInputsUnchanged': unchanged,
        'passed': unchanged and len(results) == 3 and all(r['exitCode'] == 0 for r in results),
        'qualificationScope': receipt['qualificationScope'], 'releaseQualified': False}
    (REPORT / 'driver-result.json').write_text(json.dumps(value, indent=2) + chr(10), 'utf-8')
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()

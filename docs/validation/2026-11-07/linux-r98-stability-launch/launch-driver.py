"""日期：2026-11-07；冻结独立Ubuntu已验CLI和测试，先20轮再运行真实24小时双向传输。"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import tarfile

ROOT = Path.cwd()
OUTPUT = ROOT / 'docs/validation/2026-11-07/current-linux-r98-long'
REMOTE = '/home/dukto/current-linux-r98-long'
COMMIT = 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
BINARY = '816b549fd5c34be611e9e1f669e54ab8a2c224ace1206cc3b314adcceb9d2412'

REMOTE_RUNNER = '''"""日期：2026-11-07；冻结输入的完整20轮和86400秒原长测，不降低资源及摘要断言。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


# 日期：2026-11-07；实际子进程退出后记录结果，所有被冻结文件和系统动态依赖必须保持原摘要。
def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    launch = json.loads((root / 'results/launch.json').read_text('utf-8'))
    environment = os.environ.copy()
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    cases = [('sampling', 'process_sampling_integration.py', []),
             ('smoke20', 'parallel_soak_portable_integration.py',
              [str(root / 'dukto-cli'), '--rounds', '20', '--threads', '16', '--payload-mib', '1']),
             ('summary24h', 'parallel_soak_portable_integration.py',
              [str(root / 'dukto-cli'), '--duration', '86400', '--interval', '300',
               '--threads', '16', '--payload-mib', '8'])]
    results = []
    for name, script, arguments in cases:
        with (root / 'results' / (name + '.log')).open('xb') as log:
            code = subprocess.run([sys.executable, '-X', 'utf8', '-u', str(root / 'tests' / script),
                                   *arguments, '--report', str(root / 'results' / (name + '.json'))],
                                  env=environment, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=93000).returncode
        results.append({'name': name, 'exitCode': code})
        print(json.dumps(results[-1]), flush=True)
        if code:
            break
    inventory = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                 for name in launch['frozenFiles']}
    dependencies = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                    for name in launch['runtimeDependencies']}
    unchanged = inventory == launch['frozenFiles'] and dependencies == launch['runtimeDependencies']
    value = {'date': '2026-11-07', 'finishedUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
             'sourceCommit': launch['sourceCommit'], 'cases': results,
             'frozenInputsAndDependenciesUnchanged': unchanged,
             'passed': unchanged and len(results) == 3 and all(item['exitCode'] == 0 for item in results),
             'qualificationScope': launch['qualificationScope'],
             'releaseQualified': False, 'deliveryComplete': False}
    (root / 'results/driver-result.json').write_text(json.dumps(value, indent=2) + '\\n', 'utf-8')
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
'''


# 日期：2026-11-07；只收集新测试目录的普通报告，拒绝链接、越界路径和过大条目。
def extract(archive):
    with tarfile.open(archive) as source:
        for member in source:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            assert not member.issym() and not member.islnk()
            if member.isdir():
                continue
            assert member.isfile() and member.size < 32 * 1024**2
            target = OUTPUT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(member).read())


# 日期：2026-11-07；准备和运行分开留存，重复目录一律拒绝，既有Windows及Linux长测输入不变。
def main():
    prior = ROOT / 'docs/validation/2026-11-07/exit-state-r98-final-glibc'
    qualification = json.loads((prior / 'verified-receipt.json').read_text('utf-8'))
    assert qualification['passed'] and qualification['cleanBuild'] and qualification['sourceCommit'] == COMMIT
    assert qualification['coreTargets'] == 23
    manifest_path = prior / 'results/source-manifest.json'
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == qualification['sourceManifest']['sha256']
    manifest = json.loads(manifest_path.read_text('utf-8'))['files']
    tests = {name: row['sha256'] for name, row in manifest.items()
             if PurePosixPath(name).parent == PurePosixPath('tests') and name.endswith('.py')}
    assert len(tests) >= 40
    config = {'remoteRoot': REMOTE, 'sourceCommit': COMMIT, 'binarySha256': BINARY,
              'tests': tests, 'runner': REMOTE_RUNNER,
              'independentCleanBuildEvidenceSha256': hashlib.sha256((prior / 'verified-receipt.json').read_bytes()).hexdigest()}
    prepare = '''import hashlib, json, os, platform, psutil, re, shutil, subprocess, sys, time
from pathlib import Path
config = CONFIG_VALUE
root = Path(config['remoteRoot'])
assert not root.exists()
original = Path('/home/dukto/exit-state-r98-final')
assert hashlib.sha256((original / 'build/dukto-cli').read_bytes()).hexdigest() == config['binarySha256']
root.mkdir()
(root / 'tests').mkdir()
(root / 'results').mkdir()
for name, expected in config['tests'].items():
    source = original / name
    assert hashlib.sha256(source.read_bytes()).hexdigest() == expected
    shutil.copy2(source, root / name)
shutil.copy2(original / 'build/dukto-cli', root / 'dukto-cli')
(root / 'runner.py').write_text(config['runner'], 'utf-8')
listing = subprocess.check_output(['ldd', str(root / 'dukto-cli')]).decode('utf-8')
assert 'not found' not in listing
(root / 'results/ldd-before.txt').write_text(listing, 'utf-8')
dependencies = {}
for line in listing.splitlines():
    paths = re.findall(r'(/[^ ]+)', line)
    for name in paths:
        path = Path(name)
        if path.is_file():
            dependencies[name] = hashlib.sha256(path.read_bytes()).hexdigest()
assert len(dependencies) >= 10
files = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
         for path in root.rglob('*') if path.is_file() and path.parent.name != 'results'}
launch = {'date': '2026-11-07', 'startedUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
          'sourceCommit': config['sourceCommit'], 'binarySha256': config['binarySha256'],
          'remoteRoot': str(root), 'frozenFiles': files, 'runtimeDependencies': dependencies,
          'platform': platform.platform(), 'python': sys.version, 'psutil': psutil.__version__,
          'independentCleanBuildEvidenceSha256': config['independentCleanBuildEvidenceSha256'],
          'requestedSeconds': 86400, 'requestedChannels': 16, 'smokeRounds': 20,
          'qualificationScope': 'frozen R98 Ubuntu CLI, complete original bounded-task duplex soak; no arbitrary growth or GC qualification',
          'terminalPending': True, 'passed': False, 'releaseQualified': False, 'deliveryComplete': False}
(root / 'results/launch.json').write_text(json.dumps(launch, indent=2) + '\\n', 'utf-8')
print(json.dumps(launch))
'''.replace('CONFIG_VALUE', repr(config))
    OUTPUT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__), OUTPUT / 'validation-driver.py')
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    prepared = subprocess.run(ssh + ['python3 -'], input=prepare.encode('utf-8'), capture_output=True, timeout=60)
    (OUTPUT / 'prepare-stderr.log').write_bytes(prepared.stderr)
    assert prepared.returncode == 0, prepared.stderr.decode('utf-8')
    launch = json.loads(prepared.stdout)
    assert launch['binarySha256'] == BINARY and launch['sourceCommit'] == COMMIT
    (OUTPUT / 'launch.json').write_bytes(prepared.stdout)
    print(json.dumps({'frozenFiles': len(launch['frozenFiles']), 'sourceCommit': COMMIT,
                      'binarySha256': BINARY, 'requestedSeconds': 86400}), flush=True)
    with (OUTPUT / 'driver.log').open('xb') as log:
        code = subprocess.run(ssh + ['python3 -u /home/dukto/current-linux-r98-long/runner.py'],
                              stdout=log, stderr=subprocess.STDOUT, timeout=94000).returncode
    archive = OUTPUT / 'results.tar.gz'
    with archive.open('xb') as log:
        subprocess.run(ssh + ['cd /home/dukto/current-linux-r98-long && tar czf - results'],
                       stdout=log, check=True, timeout=120)
    extract(archive)
    result = json.loads((OUTPUT / 'results/driver-result.json').read_text('utf-8'))
    assert code == 0 and result['passed']
    print(json.dumps({'sourceCommit': COMMIT, 'driverExitCode': code, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()

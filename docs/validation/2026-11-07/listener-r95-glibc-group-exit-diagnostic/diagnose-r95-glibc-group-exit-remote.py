"""日期：2026-11-07；原R95二进制按原16组并行处置顺序诊断退出，保留原十秒断言。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

import psutil

ROOT = Path('/home/dukto/listener-r95-final')
OUTPUT = Path('/home/dukto/listener-r95-group-exit-diagnostic')
BINARY = ROOT / 'build/file-exchange-tests'


# 日期：2026-11-07；只读取本驱动创建的服务进程及有限线程，不打印配置、令牌或环境内容。
def snapshot(child, path):
    rows = []
    for task in sorted(Path('/proc/' + str(child.pid) + '/task').iterdir())[:64]:
        item = {'tid': int(task.name)}
        for name in ('comm', 'wchan', 'syscall'):
            try:
                item[name] = (task / name).read_text().strip()[:1024]
            except (FileNotFoundError, PermissionError) as error:
                item[name] = type(error).__name__
        rows.append(item)
    path.write_text(json.dumps({'pid': child.pid, 'threads': rows}, indent=2) + '\n', 'utf-8')


# 日期：2026-11-07；新诊断目录保留每次原日志和观测干扰声明，观察结果不能替代无采样回归。
def main():
    OUTPUT.mkdir(exist_ok=False)
    before = hashlib.sha256(BINARY.read_bytes()).hexdigest()
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    cases = []
    for attempt in range(1, 2):
        prefix = OUTPUT / ('attempt-' + str(attempt))
        captures = []
        observed = {}
        started = time.monotonic()
        with prefix.with_suffix('.stdout.log').open('xb') as log:
            process = subprocess.Popen([str(BINARY), 'parallelDispositions',
                                        '-o', str(prefix.with_suffix('.log')) + ',txt',
                                        '-o', str(prefix.with_suffix('.xml')) + ',junitxml'],
                                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            while process.poll() is None:
                if time.monotonic() - started > 1200:
                    for child in psutil.Process(process.pid).children(recursive=True):
                        child.kill()
                    process.kill()
                    process.wait()
                    break
                try:
                    children = psutil.Process(process.pid).children(recursive=True)
                except psutil.NoSuchProcess:
                    children = []
                for child in children:
                    try:
                        args = child.cmdline()
                        if '--parallel-disposition-server' not in args:
                            continue
                        state = Path(args[args.index('--parallel-disposition-server') + 1])
                        if not (state / 'parallel-result.json').exists():
                            continue
                        first, sampled = observed.setdefault(child.pid, (time.monotonic(), False))
                        if sampled or time.monotonic() - first < 2:
                            continue
                        observed[child.pid] = (first, True)
                        snapshot(child, OUTPUT / (prefix.name + '-server-' + str(child.pid) + '.json'))
                        sample_path = OUTPUT / (prefix.name + '-server-' + str(child.pid) + '.gdb.log')
                        with sample_path.open('xb') as sample_log:
                            sampler = subprocess.Popen(['sudo', '-n', 'gdb', '--batch', '--quiet',
                                                        '-iex', 'set auto-load off', '-ex', 'set pagination off',
                                                        '-ex', 'set print frame-arguments none',
                                                        '-ex', 'thread apply all bt 20', '-ex', 'detach',
                                                        '-p', str(child.pid)], stdout=sample_log,
                                                       stderr=subprocess.STDOUT)
                        captures.append((sample_path, sampler))
                    except (psutil.NoSuchProcess, psutil.AccessDenied, FileNotFoundError):
                        continue
                time.sleep(0.05)
        samples = []
        for path, sampler in captures:
            try:
                code = sampler.wait(timeout=30)
            except subprocess.TimeoutExpired:
                sampler.kill()
                code = sampler.wait()
            samples.append({'path': path.name, 'exitCode': code})
        xml = prefix.with_suffix('.xml')
        failures = []
        if xml.exists():
            failures = [node.attrib for node in ET.parse(xml).findall('.//failure')]
        cases.append({'attempt': attempt, 'exitCode': process.returncode, 'failures': failures,
                      'samples': samples, 'seconds': round(time.monotonic() - started, 3),
                      'passed': process.returncode == 0 and not failures})
        assert hashlib.sha256(BINARY.read_bytes()).hexdigest() == before
        value = {'sourceCommit': '5dd243fbad36da36568943513deed95ee124ba2d',
                 'originalBinarySha256': before, 'binaryUnchanged': True,
                 'originalExitWaitMs': 10000, 'cases': cases, 'completed': len(cases) == 1, 'method': 'parallelDispositions', 'expectedDataRows': 16,
                 'observerMayPerturbTiming': True, 'rootCauseProven': False,
                 'releaseQualified': False, 'deliveryComplete': False}
        (OUTPUT / 'report.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
        print(json.dumps(cases[-1]), flush=True)


if __name__ == '__main__':
    main()

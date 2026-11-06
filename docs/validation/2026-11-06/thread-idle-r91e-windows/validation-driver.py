"""日期：2026-11-06；验证系统线程池有界回收与真实应用线程增长拒绝，原失败不覆盖。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

ROOT = Path.cwd()
OUTPUT = ROOT / 'docs/validation/2026-11-06/thread-idle-r91a-windows'


# 日期：2026-11-06；所有结果关联实际输入字节，测试门槛断言保持原样。
def proof(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


# 日期：2026-11-06；新建真实Python子进程保持16个应用线程，新增入口不得得到系统池宽限。
def reject_application_threads(helper):
    import psutil
    script = ('import sys,threading\n'
              'done=threading.Event()\n'
              'print("ready",flush=True)\nsys.stdin.readline()\n'
              'workers=[threading.Thread(target=done.wait) for _ in range(16)]\n'
              'for worker in workers: worker.start()\n'
              'print("active",flush=True)\nsys.stdin.readline()\n'
              'done.set()\nfor worker in workers: worker.join()\n')
    child = subprocess.Popen([sys.executable, '-u', '-c', script], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'ready'
        before = helper['idle_sample'](child)
        child.stdin.write('start\n')
        child.stdin.flush()
        assert child.stdout.readline().strip() == 'active'
        started = time.monotonic()
        current = helper['idle_sample'](child, before)
        elapsed = time.monotonic() - started
        assert before['nativeThreads']['complete'] and current['nativeThreads']['complete']
        assert current['threads'] >= before['threads'] + 12
        assert not helper['same_system_pool'](before, current)
        assert 'systemPoolSettling' not in current and elapsed < 3
        return {'passed': True, 'baseline': before, 'active': current, 'seconds': round(elapsed, 3),
                'nativeThreadGateStillRejects': current['threads'] > before['threads'] + 1}
    finally:
        child.stdin.write('exit\n')
        child.stdin.flush()
        try:
            _, error = child.communicate(timeout=10)
            assert child.returncode == 0 and not error
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


# 日期：2026-11-06；用相同R90生产二进制运行正式并发专项，保留原数值门槛和新旧空闲样本。
def validate(label):
    directory = OUTPUT / label
    directory.mkdir()
    binary = ROOT / ('build/windows-ucrt/dukto-cli.exe' if label == 'ucrt' else 'build/windows/Release/dukto-cli.exe')
    report = directory / 'parallel-isolation.json'
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment'](label)
    started = time.monotonic()
    with (directory / 'parallel-isolation.log').open('xb') as log:
        code = subprocess.run([sys.executable, '-X', 'utf8', 'tests/parallel_isolation_integration.py', str(binary),
                               '--report', str(report)], env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=240).returncode
    value = json.loads(report.read_text('utf-8')) if report.exists() else None
    passed = code == 0 and value and value['passed']
    result = {'toolchain': label, 'binary': proof(binary), 'exitCode': code, 'passed': bool(passed),
              'seconds': round(time.monotonic() - started, 3), 'report': proof(report) if value else None}
    if value:
        samples = value['idleSamplesAfterWarmup']
        result.update(keptSamples=len(samples), settledWindowsSamples=sum('beforeSettling' in row for row in samples),
                      sampledThreads=[row['threads'] for row in samples],
                      rawThreadPeak=max(row.get('beforeSettling', row)['threads'] for row in samples))
    print(json.dumps(result), flush=True)
    return result


# 日期：2026-11-06；快照编码/断言与精确旧二进制身份；本轮只改变采样夹具，不声明旧运行通过。
def main():
    global OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='thread-idle-r91c-windows')
    arguments = parser.parse_args()
    assert arguments.label.replace('-', '').isalnum()
    OUTPUT = ROOT / 'docs/validation/2026-11-06' / arguments.label
    OUTPUT.mkdir(exist_ok=False)
    sys.path.insert(0, str(ROOT / 'tests'))
    helper = runpy.run_path('tests/idle_resources.py')
    original = (ROOT / '.cache/thread-idle-r91-baseline/tests/parallel_isolation_integration.py').read_bytes()
    current = (ROOT / 'tests/parallel_isolation_integration.py').read_bytes()
    assert not original.startswith(b'\xef\xbb\xbf') and not current.startswith(b'\xef\xbb\xbf')
    original.decode('utf-8')
    current.decode('utf-8')
    assert b'\r' not in original and b'\r' not in current
    guards = [line.strip() for line in original.decode('utf-8').splitlines() if 'assert max(item[' in line or 'assert samples[-1][' in line]
    assert len(guards) == 3 and all(line in current.decode('utf-8') for line in guards)
    inputs = [proof(ROOT / name) for name in ('tests/idle_resources.py', 'tests/parallel_isolation_integration.py')]
    refusal = reject_application_threads(helper)
    (OUTPUT / 'application-thread-refusal.json').write_text(json.dumps(refusal, indent=2) + '\n', 'utf-8')
    print(json.dumps({'applicationThreadsRefused': refusal['passed'], 'seconds': refusal['seconds']}), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(validate, ('ucrt', 'msvc')))
    assert inputs == [proof(ROOT / row['path']) for row in inputs]
    value = {'date': '2026-11-06', 'productionCommit': 'effd3115e95e696077a13038f3bb0616362eac5d',
             'inputs': inputs, 'numericGuardsUnchanged': guards, 'windowsSystemPoolSettlingLimitSeconds': 60,
             'applicationThreadRefusal': proof(OUTPUT / 'application-thread-refusal.json'),
             'firstR90FailureRetained': True, 'originalTestChanged': True, 'toolchains': results,
             'passed': all(row['passed'] for row in results), 'deliveryComplete': False}
    (OUTPUT / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    assert value['passed']


if __name__ == '__main__':
    main()

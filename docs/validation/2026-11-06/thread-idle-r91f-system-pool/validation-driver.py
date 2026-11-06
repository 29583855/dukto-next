"""日期：2026-11-06；真实Windows私有线程池增长/关闭验证有界回收分支，不伪造资源样本。"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time


# 日期：2026-11-06；私有系统线程池保持一名基线worker，再增加到六名，两秒后原生关闭归还。
def main():
    output = Path('docs/validation/2026-11-06/thread-idle-r91f-system-pool')
    output.mkdir(exist_ok=False)
    helper = runpy.run_path('tests/idle_resources.py')
    script = r'''
import ctypes as C
from ctypes import wintypes as W
import sys
import time
K = C.WinDLL('kernel32', use_last_error=True)
K.CreateThreadpool.argtypes = [C.c_void_p]
K.CreateThreadpool.restype = C.c_void_p
K.SetThreadpoolThreadMinimum.argtypes = [C.c_void_p, W.DWORD]
K.SetThreadpoolThreadMinimum.restype = W.BOOL
K.SetThreadpoolThreadMaximum.argtypes = [C.c_void_p, W.DWORD]
K.CloseThreadpool.argtypes = [C.c_void_p]
callback_type = C.WINFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_void_p)
K.CreateThreadpoolTimer.argtypes = [callback_type, C.c_void_p, C.c_void_p]
K.CreateThreadpoolTimer.restype = C.c_void_p
K.SetThreadpoolTimer.argtypes = [C.c_void_p, C.c_void_p, W.DWORD, W.DWORD]
K.WaitForThreadpoolTimerCallbacks.argtypes = [C.c_void_p, W.BOOL]
K.CloseThreadpoolTimer.argtypes = [C.c_void_p]
pool = K.CreateThreadpool(None)
assert pool
K.SetThreadpoolThreadMaximum(pool, 6)
assert K.SetThreadpoolThreadMinimum(pool, 1)
time.sleep(0.2)
print('ready', flush=True)
sys.stdin.readline()
assert K.SetThreadpoolThreadMinimum(pool, 6)
# 日期：2026-11-06；定时回调运行在系统默认池，无额外Python应用线程参与回收。
def retire(instance, context, timer):
    assert K.SetThreadpoolThreadMinimum(pool, 0)
    K.CloseThreadpool(pool)
callback = callback_type(retire)
timer = K.CreateThreadpoolTimer(callback, None, None)
assert timer
due = C.c_longlong(-20_000_000)
K.SetThreadpoolTimer(timer, C.byref(due), 0, 0)
print('active', flush=True)
sys.stdin.readline()
K.WaitForThreadpoolTimerCallbacks(timer, False)
K.CloseThreadpoolTimer(timer)
'''
    (output / 'native-pool-child.py').write_text(script, 'utf-8')
    process = subprocess.Popen([sys.executable, '-u', '-c', script], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        baseline = helper['idle_sample'](process)
        process.stdin.write('grow\n')
        process.stdin.flush()
        assert process.stdout.readline().strip() == 'active'
        started = time.monotonic()
        current = helper['idle_sample'](process, baseline)
        elapsed = time.monotonic() - started
        result = {'baseline': baseline, 'afterSettling': current, 'seconds': round(elapsed, 3), 'passed': False,
                  'helperSha256': hashlib.sha256(Path('tests/idle_resources.py').read_bytes()).hexdigest()}
        (output / 'observations.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
        assert 'beforeSettling' in current and current['systemPoolSettling']
        assert current['beforeSettling']['threads'] > baseline['threads'] + 1
        assert current['threads'] <= baseline['threads'] + 1
        assert current['settlingLimitSeconds'] == 60 and elapsed < 20
        result['passed'] = True
        (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
        print(json.dumps({'passed': True, 'baseline': baseline['threads'],
                          'raw': current['beforeSettling']['threads'], 'final': current['threads'],
                          'seconds': round(elapsed, 3)}), flush=True)
    finally:
        process.stdin.write('exit\n')
        process.stdin.flush()
        try:
            _, error = process.communicate(timeout=10)
            assert process.returncode == 0 and not error, error
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()

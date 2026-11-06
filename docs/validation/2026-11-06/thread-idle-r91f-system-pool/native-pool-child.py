
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

"""日期：2026-11-06；记录真实空闲资源，Windows系统线程池回收单独保留有界观察。"""
import ctypes as C
from ctypes import wintypes as W
import os
import time

import psutil


class Module(C.Structure):
    _fields_ = [('size', W.DWORD), ('moduleId', W.DWORD), ('processId', W.DWORD),
                ('globalUsage', W.DWORD), ('processUsage', W.DWORD), ('base', C.c_void_p),
                ('bytes', W.DWORD), ('module', W.HMODULE), ('name', W.WCHAR * 256),
                ('path', W.WCHAR * 260)]


# 日期：2026-11-06；只查询调用者创建的测试进程，不解析堆或输出模块绝对路径，失败保留为未知。
def thread_starts(process):
    if os.name != 'nt':
        return None
    kernel = C.WinDLL('kernel32', use_last_error=True)
    native = C.WinDLL('ntdll')
    kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
    kernel.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(Module)]
    kernel.Module32NextW.argtypes = [W.HANDLE, C.POINTER(Module)]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenThread.restype = W.HANDLE
    kernel.GetProcessIdOfThread.argtypes = [W.HANDLE]
    kernel.GetProcessIdOfThread.restype = W.DWORD
    native.NtQueryInformationThread.argtypes = [W.HANDLE, W.ULONG, W.LPVOID, W.ULONG, W.LPVOID]
    native.NtQueryInformationThread.restype = W.LONG
    snapshot = kernel.CreateToolhelp32Snapshot(0x18, process.pid)
    if snapshot == C.c_void_p(-1).value:
        return {'complete': False, 'error': C.get_last_error(), 'rows': []}
    modules = []
    try:
        entry = Module()
        entry.size = C.sizeof(entry)
        active = kernel.Module32FirstW(snapshot, C.byref(entry))
        while active:
            modules.append((entry.base, entry.bytes, entry.name.lower()))
            active = kernel.Module32NextW(snapshot, C.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    rows = []
    for thread in process.threads():
        row = {'id': thread.id}
        handle = kernel.OpenThread(0x40 | 0x800, False, thread.id)
        if not handle:
            row['queryError'] = C.get_last_error()
        else:
            try:
                if kernel.GetProcessIdOfThread(handle) != process.pid:
                    row['queryError'] = 'thread-owner-changed'
                    rows.append(row)
                    continue
                address = C.c_void_p()
                status = native.NtQueryInformationThread(handle, 9, C.byref(address), C.sizeof(address), None)
                mapped = [(base, name) for base, size, name in modules
                          if address.value and base <= address.value < base + size]
                if status == 0 and len(mapped) == 1:
                    base, name = mapped[0]
                    row.update(module=name, offset=hex(address.value - base))
                else:
                    row['queryStatus'] = status
            finally:
                kernel.CloseHandle(handle)
        rows.append(row)
    return {'complete': bool(rows) and all('module' in row for row in rows), 'rows': rows}


# 日期：2026-11-06；只有新增入口全部等于本进程基线已有ntdll入口时才允许观察回收，未知/应用入口不等待。
def same_system_pool(baseline, current):
    before, after = baseline.get('nativeThreads'), current.get('nativeThreads')
    if not before or not after or not before['complete'] or not after['complete']:
        return False
    if len(before['rows']) != baseline['threads'] or len(after['rows']) != current['threads']:
        return False
    known = {row['id']: (row['module'], row['offset']) for row in before['rows']}
    entries = {(row['module'], row['offset']) for row in before['rows'] if row['module'] == 'ntdll.dll'}
    added = [row for row in after['rows'] if known.get(row['id']) != (row['module'], row['offset'])]
    return bool(added) and all((row['module'], row['offset']) in entries for row in added)


# 日期：2026-11-06；数值门槛维持基线+1，仅Windows同入口系统线程池增长最多观察60秒，所有原样本留档。
def idle_sample(process, baseline=None):
    item = psutil.Process(process.pid)
    time.sleep(0.3)

    # 日期：2026-11-06；数值与相邻入口快照分开记录，快照竞态/查询失败不得触发宽限。
    def measure():
        value = {'rss': item.memory_info().rss, 'threads': item.num_threads(),
                 'handlesOrFds': item.num_handles() if os.name == 'nt' else item.num_fds()}
        if os.name == 'nt':
            value['nativeThreads'] = thread_starts(item)
        return value

    first = current = measure()
    observations = []
    started = time.monotonic()
    if baseline and os.name == 'nt':
        limit = baseline['threads'] + 1
        while (current['threads'] > limit and same_system_pool(baseline, current)
               and time.monotonic() - started < 60):
            observations.append(dict(current, elapsedSeconds=round(time.monotonic() - started, 3)))
            time.sleep(min(5, max(0, 60 - (time.monotonic() - started))))
            current = measure()
    if observations:
        return dict(current, beforeSettling=first, systemPoolSettling=observations,
                    settlingSeconds=round(time.monotonic() - started, 3), settlingLimitSeconds=60)
    return current

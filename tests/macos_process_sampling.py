"""日期：2026-11-05；用 macOS 公共 libproc 接口采样，避免要求已签名进程的 Mach 调试权限。"""

import ctypes
import errno

import psutil


class RUsageV2(ctypes.Structure):
    """日期：2026-11-05；字段顺序对应 Darwin sys/resource.h 的 rusage_info_v2。"""

    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in (
            "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins",
            "wired_size", "resident_size", "phys_footprint", "proc_start_abstime", "proc_exit_abstime",
            "child_user_time", "child_system_time", "child_pkg_idle_wkups", "child_interrupt_wkups",
            "child_pageins", "child_elapsed_abstime", "diskio_bytesread", "diskio_byteswritten",
        )
    ]


# 日期：2026-11-05；加载系统库并声明参数宽度，只在真实 Darwin 分支按需调用。
def library():
    native = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    native.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    native.proc_pid_rusage.restype = ctypes.c_int
    native.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    native.proc_pidinfo.restype = ctypes.c_int
    return native


# 日期：2026-11-05；活动进程的权限或接口错误不能以零值替代，退出仍由外层有界确认。
def failure(pid):
    code = ctypes.get_errno()
    if code == errno.ESRCH:
        raise psutil.NoSuchProcess(pid)
    if code in (errno.EPERM, errno.EACCES):
        raise psutil.AccessDenied(pid)
    raise OSError(code, "macOS libproc sampling failed", str(pid))


# 日期：2026-11-05；使用 RSS 和原生 physical footprint，后者明确区别于其他系统的 USS。
def memory_metrics(target):
    usage = RUsageV2()
    if library().proc_pid_rusage(target.pid, 2, ctypes.byref(usage)) != 0:
        failure(target.pid)
    return {"rss": usage.resident_size, "private": usage.phys_footprint,
            "threads": target.num_threads(), "handles": target.num_fds()}


# 日期：2026-11-05；原生线程 ID 使用 PROC_PIDLISTTHREADS，缓冲最多 65536 项并拒绝截断清单。
def thread_inventory(target):
    capacity = min(65536, max(32, target.num_threads() + 16))
    native = library()
    while True:
        values = (ctypes.c_uint64 * capacity)()
        size = ctypes.sizeof(values)
        received = native.proc_pidinfo(target.pid, 6, 0, values, size)
        if received <= 0:
            failure(target.pid)
        if received > size or received % ctypes.sizeof(ctypes.c_uint64):
            raise RuntimeError("invalid native macOS thread inventory size")
        if received < size:
            return [{"id": int(values[index])} for index in range(received // 8)]
        if capacity == 65536:
            raise RuntimeError("native macOS thread inventory exceeds sampling bound")
        capacity = min(65536, capacity * 2)

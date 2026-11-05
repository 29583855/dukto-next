"""日期：2026-11-05；有界处理短命子进程退出采样竞争，活动进程权限错误仍必须失败。"""

import os
import platform
import sys
import subprocess

import psutil

from soak_transfer import metrics as portable_metrics


# 日期：2026-11-05；Darwin 的私有内存指标采用系统 physical footprint，其余平台保持既有指标。
def metrics(target):
    if sys.platform == "darwin":
        from macos_process_sampling import memory_metrics
        return memory_metrics(target)
    return portable_metrics(target)


# 日期：2026-11-05；Linux 在进程退出的短窗口可能先拒绝 fd 采样，最多等 100ms 确认真实退出。
def sample(process, peak):
    try:
        current = metrics(psutil.Process(process.pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired as timeout:
            raise error from timeout
        return
    for key, value in current.items():
        peak[key] = max(peak.get(key, 0), value)
    assert current["rss"] < 512 * 1024**2 and current["private"] < 512 * 1024**2, current


# 日期：2026-11-05；Windows 保留模块归属检查，macOS 通过 psutil 线程清单，Linux 才使用 procfs。
def thread_inventory(process, windows_inventory):
    if os.name == "nt":
        return windows_inventory(process)
    target = psutil.Process(process.pid)
    if sys.platform == "darwin":
        from macos_process_sampling import thread_inventory as native_inventory
        return native_inventory(target)
    threads = target.threads()
    from pathlib import Path
    return [{"id": item.id, "name": Path(f"/proc/{process.pid}/task/{item.id}/comm").read_text().strip()}
            for item in threads]

"""日期：2026-11-04；流式验证超过 4 GiB 的真实 CLI 传输及双端资源峰值。"""

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time

import psutil


# 日期：2026-11-04；固定片段计算摘要，不将整个大文件读入内存。
def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(256 * 1024):
            value.update(block)
    return value.hexdigest()


# 日期：2026-11-04；从有界事件日志读取监听状态，等待有总截止时间。
def await_listener(process, log):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        lines = log.read_text(encoding="utf-8").splitlines()
        if lines and json.loads(lines[0]).get("event") == "listening":
            return
        if process.poll() is not None:
            raise RuntimeError(lines)
        time.sleep(0.05)
    raise TimeoutError("receiver did not listen")


# 日期：2026-11-04；以 50ms 间隔观测两个真实进程，不把采样序列无界保存在内存。
def sample(process, peak):
    try:
        target = psutil.Process(process.pid)
        memory = target.memory_info()
        peak["rss"] = max(peak.get("rss", 0), memory.rss)
        private = memory.private if os.name == "nt" else target.memory_full_info().uss
        peak["private"] = max(peak.get("private", 0), private)
        peak["threads"] = max(peak.get("threads", 0), target.num_threads())
        handles = target.num_handles() if os.name == "nt" else target.num_fds()
        peak["handles"] = max(peak.get("handles", 0), handles)
        peak["samples"] = peak.get("samples", 0) + 1
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied:
        # 日期：2026-11-04；Linux 退出期间 /proc 权限可能先变化；仍活动的进程拒绝采样必须报错。
        if process.poll() is None:
            try:
                if psutil.Process(process.pid).status() != psutil.STATUS_ZOMBIE:
                    raise
            except psutil.NoSuchProcess:
                pass


# 日期：2026-11-04；建立含跨 2/4 GiB 边界标记的大文件，验证退出、尺寸、摘要与缓冲峰值。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--size", type=int, default=4 * 1024**3 + 131)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    cache = Path(__file__).resolve().parent.parent / ".cache"
    cache.mkdir(exist_ok=True)
    if shutil.disk_usage(cache).free < args.size * 2 + 1024**3:
        raise RuntimeError("insufficient space for both transfer copies and reserve")
    processes = []
    with tempfile.TemporaryDirectory(prefix="large-", dir=cache) as temporary:
        root = Path(temporary)
        source = root / "large.bin"
        with source.open("wb") as stream:
            stream.truncate(args.size)
            for offset in {0, 2 * 1024**3 - 7, 4 * 1024**3 - 9, args.size - 16}:
                if 0 <= offset <= args.size - 16:
                    stream.seek(offset)
                    stream.write(b"dukto-boundary!\n")
        expected = digest(source)
        output = root / "received"
        output.mkdir()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = str(reservation.getsockname()[1])
        receive_log = root / "receive.jsonl"
        send_log = root / "send.jsonl"
        peaks = {"sender": {}, "receiver": {}}
        with receive_log.open("wb") as rx, send_log.open("wb") as tx, (root / "error.log").open("wb") as err:
            try:
                receiver = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", port,
                                             "--output", str(output), "--once", "--json", "--state-directory", str(root / "state")], stdout=rx, stderr=err)
                processes.append(receiver)
                await_listener(receiver, receive_log)
                started = time.monotonic()
                sender = subprocess.Popen([executable, "send", "--to", "127.0.0.1", "--port", port,
                                           "--path", str(source), "--json"], stdout=tx, stderr=err)
                processes.append(sender)
                deadline = started + 600
                while any(process.poll() is None for process in processes):
                    if time.monotonic() > deadline:
                        raise TimeoutError("large transfer exceeded 600 seconds")
                    sample(sender, peaks["sender"])
                    sample(receiver, peaks["receiver"])
                    time.sleep(0.05)
                elapsed = time.monotonic() - started
                assert [process.returncode for process in processes] == [0, 0]
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
        destination = output / source.name
        assert destination.stat().st_size == args.size
        assert digest(destination) == expected
        assert not list(output.glob("*.part"))
        assert not (root / "error.log").read_bytes()
        for peak in peaks.values():
            assert peak["rss"] < 512 * 1024**2, peak
        report = {"date": "2026-11-04", "passed": True, "bytes": str(args.size), "sha256": expected,
                  "seconds": round(elapsed, 3), "MiBps": round(args.size / elapsed / 1024**2, 2),
                  "peaks": peaks, "sampleIntervalMs": 50,
                  "platform": platform.platform(), "physicalMemoryBytes": psutil.virtual_memory().total,
                  "privateMetric": "PrivateUsage" if os.name == "nt" else "USS",
                  "sourceAllocationBytes": getattr(source.stat(), "st_blocks", 0) * 512 if os.name == "posix" else None,
                  "scope": "two native CLI processes over loopback; all declared bytes read and sent; not a LAN or long-term claim",
                  "senderResult": json.loads(send_log.read_text(encoding="utf-8").splitlines()[-1]),
                  "receiverResult": json.loads(receive_log.read_text(encoding="utf-8").splitlines()[-1])}
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

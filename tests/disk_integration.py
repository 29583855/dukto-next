"""日期：2026-11-04；仅在独立小型挂载点制造真实 ENOSPC，禁止填满普通用户磁盘。"""

import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

from legacy_integration import finish, free_port, frame
from limited_filesystem import exhaust


# 日期：2026-11-04；接收明细放在另一个临时目录，真实数据盘满不能连带破坏测试控制记录。
def receive(executable, output, state, port):
    process = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", str(port),
                                "--output", str(output), "--state-directory", str(state),
                                "--once", "--timeout", "5", "--json"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8")
    assert json.loads(process.stdout.readline())["event"] == "listening"
    return process


# 日期：2026-11-04；声明超过整个受限盘的文件，不发送正文，接收方必须在创建临时文件前拒绝。
def preflight_rejection(executable, output, state, capacity):
    port = free_port()
    process = receive(executable, output, state, port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
            size = capacity + 1
            sender.sendall(struct.pack("<qq", 1, size) + b"too-large.bin\0" + struct.pack("<q", size))
            events = finish(process, 5)
        result = events[-1]
        assert result["stage"] == "space", result
        assert not list(output.glob("*.part")) and not (output / "too-large.bin").exists()
        return {"passed": True, "receiverExitCode": 5, "stage": "space", "noTemporaryCreated": True}
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


# 日期：2026-11-04；先写入部分文件，再让独立写入者耗尽同一受限文件系统，验证中途磁盘满。
def run(executable, mount, expected_capacity=None):
    filesystem = os.statvfs(mount)
    capacity = filesystem.f_blocks * filesystem.f_frsize
    # 日期：2026-11-05；Linux默认4–64MiB保持；APFS显式绑定实际容量且上限512MiB，仍须独立挂载点。
    maximum = 64 * 1024**2 if expected_capacity is None else 512 * 1024**2
    if not os.path.ismount(mount) or not 4 * 1024**2 <= capacity <= maximum:
        raise RuntimeError("test requires a dedicated mounted filesystem within the explicit capacity bound")
    if expected_capacity is not None:
        assert capacity == expected_capacity, (capacity, expected_capacity)
    with tempfile.TemporaryDirectory(prefix="dukto-enospc-", dir=mount) as temporary, \
            tempfile.TemporaryDirectory(prefix="dukto-enospc-state-") as metadata:
        output = Path(temporary)
        state = Path(metadata)
        original = output / "preserved.bin"
        original.write_bytes(b"original must survive")
        preflight = preflight_rejection(executable, output, state, capacity)
        port = free_port()
        process = receive(executable, output, state, port)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=8) as sender:
                # 日期：2026-11-05；APFS可为小文件预留完整extent；较大声明确保还有未分配正文。
                size = capacity // 2 if capacity > 64 * 1024**2 else min(2 * 1024**2, capacity // 2)
                sender.sendall(struct.pack("<qq", 1, size) + b"preserved.bin\0" +
                               struct.pack("<q", size) + b"x" * (256 * 1024))
                deadline = time.monotonic() + 5
                while not any(path.stat().st_size >= 256 * 1024 for path in output.glob("*.part")):
                    if time.monotonic() > deadline:
                        raise AssertionError("receiver did not write the first fragment")
                    time.sleep(0.02)
                # 日期：2026-11-05；只耗尽自有小卷；APFS快速预留物理空间，不能先触发原5秒无进展期限。
                exhausted = exhaust(output / "filler", capacity)
                try:
                    remaining = size - 256 * 1024
                    while remaining:
                        count = min(256 * 1024, remaining)
                        sender.sendall(b"x" * count)
                        remaining -= count
                except (BrokenPipeError, ConnectionResetError):
                    pass
            events = finish(process, 5)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        result = events[-1]
        assert result["stage"] == "write", result
        assert not list(output.glob("*.part"))
        assert original.read_bytes() == b"original must survive"
        assert not (output / "preserved (2).bin").exists()
        (output / "filler").unlink()
        port = free_port()
        process = receive(executable, output, state, port)
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
                sender.sendall(frame([("after-disk-full.txt", b"space recovered")]))
            finish(process, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        assert (output / "after-disk-full.txt").read_bytes() == b"space recovered"
        return {"passed": True, "filesystemBytes": capacity, "kernelError": "ENOSPC",
                "preflight": preflight,
                "receiverExitCode": 5, "originalPreserved": True, "temporaryCleaned": True,
                "nextReceivePassed": True, "failureResult": result, "exhaustion": exhausted}


# 日期：2026-11-04；挂载由测试环境预先准备；脚本不自行挂载、提权或填充用户普通磁盘。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--limited-directory", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--filesystem-bytes", type=int)
    args = parser.parse_args()
    report = run(str(Path(args.executable).resolve()), Path(args.limited_directory).resolve(),
                 args.filesystem_bytes)
    report["date"] = "2026-11-04"
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

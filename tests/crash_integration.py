"""日期：2026-11-04；强制终止真实接收进程，验证活动所有权和重启后的结果未知语义。"""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import tempfile
import time

from legacy_integration import finish, free_port, frame, receiver


# 日期：2026-11-04；查询实际 CLI，JSON 状态与进程退出码必须同时正确。
def receipt(executable, state, task):
    result = subprocess.run([executable, "receipts", "show", "--task", task,
                             "--state-directory", str(state), "--json"],
                            capture_output=True, encoding="utf-8", timeout=8)
    assert result.returncode == 0 and not result.stderr, (result.stdout, result.stderr)
    return json.loads(result.stdout)


# 日期：2026-11-04；只等待确定的磁盘状态，超时立即失败，不能将未开始的传输当崩溃样本。
def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("expected disk state did not appear before timeout")


# 日期：2026-11-04；先观察存活任务，再强制结束进程；已提交副本及原文件均不能被破坏。
def crash_during_receive(executable, root):
    output = root / "received"
    output.mkdir()
    original = output / "preserved.bin"
    original.write_bytes(b"original content")
    payload = b"first complete file"
    completed = output / "preserved (2).bin"
    port = free_port()
    process = receiver(executable, output, port)
    state = output / ".state"
    with closing(socket.create_connection(("127.0.0.1", port), timeout=5)) as sender:
        try:
            pending_size = 32 * 1024**2
            sender.sendall(struct.pack("<qq", 2, len(payload) + pending_size) +
                           b"preserved.bin\0" + struct.pack("<q", len(payload)) + payload +
                           b"partial.bin\0" + struct.pack("<q", pending_size) + b"p" * (256 * 1024))
            wait_for(lambda: completed.exists() and any(
                item.stat().st_size > 0 for item in output.glob(".dukto-*.part")))
            with closing(sqlite3.connect(state / "history/receipts.sqlite")) as database:
                task = database.execute("SELECT id FROM tasks WHERE state='receiving'").fetchone()[0]
            assert receipt(executable, state, task)["state"] == "receiving"
            process.kill()
            process.communicate(timeout=5)
            assert process.returncode != 0
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    recovered = receipt(executable, state, task)
    assert recovered["state"] == "interrupted", recovered
    assert "未知" in recovered["message"]
    assert completed.read_bytes() == payload
    assert original.read_bytes() == b"original content"
    assert not (output / "partial.bin").exists()
    remnants = list(output.glob(".dukto-*.part"))
    assert len(remnants) == 1 and remnants[0].stat().st_size > 0
    assert not list(state.glob("*.lock"))
    assert not list((state / "history/receipts.sqlite.locks").glob("*.lock"))

    port = free_port()
    restarted = receiver(executable, output, port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
            sender.sendall(frame([("after-restart.bin", b"restarted successfully")]))
        finish(restarted, 0)
    finally:
        if restarted.poll() is None:
            restarted.kill()
            restarted.communicate(timeout=5)
    assert (output / "after-restart.bin").read_bytes() == b"restarted successfully"
    assert receipt(executable, state, task)["state"] == "interrupted"
    return {"passed": True, "liveOwnerPreserved": True, "afterCrashState": "interrupted",
            "completedCopySha256": hashlib.sha256(completed.read_bytes()).hexdigest(),
            "originalPreserved": True, "nextReceivePassed": True,
            "uncommittedTemporaryFilesRetained": len(remnants), "automaticResume": False,
            "limitation": "R6 cannot resume; interrupted files require inspection; cleanup is not yet automatic"}


# 日期：2026-11-04；测试数据完全隔离，残留样本随专用临时目录清理，不扫描用户接收目录。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="dukto-crash-") as temporary:
        report = crash_during_receive(str(Path(args.executable).resolve()), Path(temporary))
    report["date"] = "2026-11-04"
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

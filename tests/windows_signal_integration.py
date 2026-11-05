"""日期：2026-11-04；隐藏的独立 Windows 控制台接收真实 CTRL_C_EVENT，不向用户终端发送事件。"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time

from legacy_integration import finish, free_port


# 日期：2026-11-04；专用短生命周期助手只附加到本测试创建的控制台，忽略自身 Ctrl+C 后发送事件。
def signal_owned_console(pid):
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.AttachConsole.argtypes = [wintypes.DWORD]
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
    kernel.GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.GenerateConsoleCtrlEvent.restype = wintypes.BOOL
    kernel.FreeConsole()
    if not kernel.AttachConsole(pid):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel.SetConsoleCtrlHandler(None, True):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.GenerateConsoleCtrlEvent(0, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.1)
    finally:
        kernel.FreeConsole()


# 日期：2026-11-04；只创建隐藏的新控制台，进程和 stdout/stderr 均归本测试所有。
def launch(executable, arguments, stdin=None):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return subprocess.Popen([executable, *arguments], stdin=stdin, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NEW_CONSOLE,
                            startupinfo=startup)


# 日期：2026-11-04；等待显式接收状态后才产生取消，避免把信号送给尚未安装处理器的启动阶段。
def cancel(process):
    started = time.monotonic()
    subprocess.run([sys.executable, __file__, "--signal-pid", str(process.pid)],
                   check=True, capture_output=True, timeout=5,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    process.wait(timeout=5)
    events = finish(process, 7)
    result = events[-1]
    assert result["event"] == "error" and result["code"] == 7, result
    return {"passed": True, "exitCode": 7, "stage": result["stage"],
            "seconds": round(time.monotonic() - started, 3), "event": "CTRL_C_EVENT"}


# 日期：2026-11-04；活动/空闲接收与保持打开的管道分别测试，失败也必须结束自建进程。
def run(executable, root):
    results = []
    for active in [False, True]:
        output = root / ("active" if active else "idle")
        output.mkdir()
        port = free_port()
        process = launch(executable, ["receive", "--bind", "127.0.0.1", "--port", str(port),
                                     "--output", str(output), "--state-directory", str(root / "state"),
                                     "--json"])
        sender = None
        try:
            assert json.loads(process.stdout.readline())["event"] == "listening"
            if active:
                sender = socket.create_connection(("127.0.0.1", port), timeout=5)
                sender.sendall(struct.pack("<qq", 1, 1024**2) + b"cancelled.bin\0" +
                               struct.pack("<q", 1024**2) + b"p" * (256 * 1024))
                deadline = time.monotonic() + 5
                while not any(p.stat().st_size > 0 for p in output.glob(".dukto-*.part")):
                    if time.monotonic() > deadline:
                        raise AssertionError("receiver did not start before Ctrl+C")
                    time.sleep(0.02)
            result = cancel(process)
            assert not list(output.iterdir())
            result.update(activeReceive=active, temporaryCleaned=True)
            results.append(result)
        finally:
            if sender:
                sender.close()
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    process = launch(executable, ["send-text", "--to", "127.0.0.1", "--file", "-", "--json"],
                     stdin=subprocess.PIPE)
    try:
        time.sleep(0.5)
        assert process.poll() is None
        result = cancel(process)
        assert result["stage"] == "stdin", result
        results.append(result)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        process.stdin.close()
    return {"date": "2026-11-04", "passed": True, "checks": results,
            "scope": "real Windows console control events; hidden test-owned console; no physical keyboard automation"}


# 日期：2026-11-04；信号助手模式不创建其他任务，也不操作用户当前控制台。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", nargs="?")
    parser.add_argument("--report")
    parser.add_argument("--signal-pid", type=int)
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("this test requires Windows")
    if args.signal_pid:
        signal_owned_console(args.signal_pid)
        return
    if not args.executable or not args.report:
        parser.error("executable and --report are required")
    with tempfile.TemporaryDirectory(prefix="dukto-console-signal-") as temporary:
        report = run(str(Path(args.executable).resolve()), Path(temporary))
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_bytes(text.encode("utf-8"))
    print(text)


if __name__ == "__main__":
    main()

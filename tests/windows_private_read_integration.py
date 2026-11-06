"""日期：2026-11-06；公开CLI读取共享配置在DELETE句柄瞬时/持续占用下有界等待，原配置保持。"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from service_integration import run
from transfer_integration import digest


# 日期：2026-11-06；独立进程只持有测试配置DELETE访问，stdin通知后释放，不修改或删除目标。
def hold_delete(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x00010000, 7, None, 3, 0x00200000, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        print("locked", flush=True)
        sys.stdin.readline()
    finally:
        assert kernel.CloseHandle(handle)


# 日期：2026-11-06；使用真实CLI子进程，不替代私有状态读实现，永久占用保持原错误与明确期限。
def one_case(executable, root, state, config, persistent, index):
    before = digest(config)
    holder = subprocess.Popen([sys.executable, "-X", "utf8", __file__, "--hold-delete", str(config)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              encoding="utf-8")
    operation = None
    try:
        assert holder.stdout.readline().strip() == "locked"
        started = time.monotonic()
        operation = subprocess.Popen([executable, "serve", "share", "list", "--state-directory", str(state),
                                      "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     encoding="utf-8")
        if not persistent:
            time.sleep(0.1)
            assert operation.poll() is None, "CLI completed before occupied configuration released"
            holder.stdin.write("release\n")
            holder.stdin.flush()
            assert holder.wait(5) == 0 and not holder.stderr.read()
        stdout, stderr = operation.communicate(timeout=5)
        seconds = time.monotonic() - started
        assert not stderr and seconds < 3, (seconds, stderr)
        value = json.loads(stdout)
        if persistent:
            assert operation.returncode == 5 and value["stage"] == "read-busy", (operation.returncode, value)
            assert "32" in value["message"] and "已尝试" in value["message"]
            assert seconds >= 0.45
            holder.stdin.write("release\n")
            holder.stdin.flush()
            assert holder.wait(5) == 0 and not holder.stderr.read()
        else:
            assert operation.returncode == 0 and value["event"] == "shares" and len(value["shares"]) == 1
        assert digest(config) == before
        after, _ = run(executable, state, ["serve", "share", "list"])
        assert len(after["shares"]) == 1
        assert not list(config.parent.glob("*.part")) and not list(config.parent.glob(".dukto-*.part"))
        return {"persistent": persistent, "index": index, "seconds": round(seconds, 6),
                "exitCode": operation.returncode, "stage": value.get("stage"),
                "configurationUnchanged": True, "readAfterReleasePassed": True, "passed": True}
    finally:
        for process in (operation, holder):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


# 日期：2026-11-06；首次报告只写实际结果，不使用重试覆盖失败；测试只操作自有回环服务状态。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assert os.name == "nt" and not args.report.exists()
    binary = Path(args.executable).resolve()
    with tempfile.TemporaryDirectory(prefix="dukto-private-read-") as temporary:
        root = Path(temporary).resolve()
        executable = root / "dukto-cli.exe"
        shutil.copyfile(binary, executable)
        state, shared = root / "server", root / "shared"
        shared.mkdir()
        run(str(executable), state, ["serve", "init", "--server-name", "127.0.0.1"])
        run(str(executable), state, ["serve", "share", "add", "--share", "data", "--path", str(shared),
                                     "--allow-browse", "--allow-download"])
        config = state / "service/shares.json"
        cases = [one_case(str(executable), root, state, config, persistent, index)
                 for index, persistent in enumerate((False, True, False, False, False, False))]
    args.report.write_text(json.dumps({"date": "2026-11-06", "passed": True,
        "executableSha256": digest(binary), "testScriptSha256": digest(Path(__file__)),
        "retryBudgetMilliseconds": 500, "retryAttemptsMaximum": 21, "cases": cases,
        "r85RootCauseProven": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--hold-delete":
        hold_delete(Path(sys.argv[2]))
    else:
        main()

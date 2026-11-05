"""日期：2026-11-06；真实TLS上传/下载在外部读句柄占用下有界等待，永久占用后同任务恢复。"""

import argparse
from contextlib import closing
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

from conflict_fail_integration import start
from disposition_transfer_integration import verify_journal
from service_integration import free_port, run
from transfer_integration import digest, transfer
from transfer_recovery_integration import TransferProcess
from transfer_retry_integration import finish


# 日期：2026-11-06；独立进程只持有测试文件的读句柄，收到父进程输入后释放，模拟外部阅读器的短暂占用。
def hold_read(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        print("locked", flush=True)
        sys.stdin.readline()
    finally:
        assert kernel.CloseHandle(handle)


# 日期：2026-11-06；只观察自有接收日志，不能用已发送字节判断发布时点；轮询不修改应用生产状态。
def wait_committing(database, operation):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if database.exists():
            with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True, timeout=0.1)) as connection:
                try:
                    row = connection.execute("SELECT state FROM files WHERE id=1").fetchone()
                except sqlite3.OperationalError:
                    row = None
            if row and row[0] == "committing":
                return time.monotonic()
        assert operation.process.poll() is None, "transfer terminated before committing"
        time.sleep(0.002)
    raise AssertionError("receive commit observation deadline")


# 日期：2026-11-06；配对和数据均为本测试回环服务，锁释放前原文件保持完整，失败后不重建请求身份。
def one_case(executable, root, server, client, shared, sample, channels, direction, persistent):
    key = f"{direction}-{channels}-{'persistent' if persistent else 'transient'}"
    remote = shared / key
    remote.mkdir()
    destination = remote if direction == "upload" else root / key
    destination.mkdir(exist_ok=True)
    target = destination / sample.name
    target.write_bytes(b"original-user-content")
    original_sha = digest(target)
    if direction == "download":
        (remote / sample.name).write_bytes(sample.read_bytes())
    arguments = (["upload", "--share", "data", "--remote-path", key, "--path", str(sample)] if direction == "upload"
                 else ["download", "--share", "data", "--remote-path", key + "/" + sample.name, "--output", str(destination)])
    arguments += ["--on-conflict", "overwrite", "--threads", str(channels), "--request-id", str(uuid.uuid4())]
    holder = subprocess.Popen([sys.executable, "-X", "utf8", __file__, "--hold-read", str(target)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              encoding="utf-8")
    assert holder.stdout.readline().strip() == "locked"
    operation = None
    try:
        operation = TransferProcess(executable, client, arguments)
        task = operation.task()
        state = server / "service" if direction == "upload" else client / "transfers"
        commit_time = wait_committing(state / f"receive-{task}.sqlite", operation)
        # 日期：2026-11-06；确认进入committing后再保持100ms，保证覆盖已受真实外部句柄阻挡。
        time.sleep(0.1)
        assert digest(target) == original_sha
        if persistent:
            events = finish(operation, 5, 30)
            assert events[-1]["stage"] == "commit-busy" and "已尝试" in events[-1]["message"]
            assert time.monotonic() - commit_time < 5
            failed, _ = run(executable, client, ["task", "--task", task])
            assert failed["state"] == "interrupted" and failed["error"] == 0
            assert digest(target) == original_sha
            # 日期：2026-11-06；批次失败前尚未发布文件，双端处置不可提前写copied。
            for directory, prefix in [(server / "service", "disposition"),
                                      (client / "transfers", "upload-disposition" if direction == "upload" else "disposition")]:
                with closing(sqlite3.connect(f"{(directory / (prefix + '-' + task + '.sqlite')).as_uri()}?mode=ro", uri=True)) as ledger:
                    assert ledger.execute("SELECT COUNT(*) FROM items").fetchone() == (0,)
        holder.stdin.write("release\n")
        holder.stdin.flush()
        holder.stdin.close()
        assert holder.wait(timeout=3) == 0 and not holder.stderr.read()
        if persistent:
            resume = ["resume", "--task", task, "--threads", str(channels),
                      "--path" if direction == "upload" else "--output", str(sample if direction == "upload" else destination)]
            result = transfer(executable, client, resume)
        else:
            events = finish(operation, 0, 30)
            result = events[-1]
        assert result["taskId"] == task and digest(target) == digest(sample)
        manifest = server / "service" / f"manifest-{task}.sqlite"
        remote_result = verify_journal(server / "service", manifest.name, task, destination, "overwrite")
        local_result = verify_journal(client / "transfers", manifest if direction == "upload" else f"download-{task}.sqlite",
                                      task, destination, "overwrite", sender=direction == "upload")
        assert local_result["records"] == remote_result["records"]
        return {"direction": direction, "channels": channels, "persistent": persistent,
                "sameTask": True, "originalPreservedUntilPublication": True, "bothFinalJournalsVerified": True,
                "failureBeforeRelease": 5 if persistent else None, "sha256": digest(target)}
    finally:
        if operation and operation.process.poll() is None:
            operation.process.kill()
            operation.process.wait(timeout=5)
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


# 日期：2026-11-06；保持原30秒就绪与完成限制，不自动重跑失败；结果只记录公开摘要和二进制身份。
def main():
    assert os.name == "nt"
    if len(sys.argv) == 3 and sys.argv[1] == "--hold-read":
        hold_read(Path(sys.argv[2]))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report = Path(args.report)
    assert not report.exists()
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-overwrite-busy-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        sample = root / "sample.bin"
        with sample.open("wb") as output:
            for index in range(33):
                output.write(bytes([index]) * (256 * 1024))
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        port = free_port()
        service = start(executable, server, port)
        try:
            run(executable, client, ["pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                                     "--credential-file", offer["credentialFile"]])
            for channels in (1, 4, 16):
                for direction in ("upload", "download"):
                    for persistent in (False, True):
                        cases.append(one_case(executable, root, server, client, shared, sample, channels, direction, persistent))
        finally:
            service.kill()
            service.wait(timeout=10)
            service.output_drain.finish()
            assert not service.stderr.read()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"date": "2026-11-06", "passed": True, "cases": cases,
                                 "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
                                 "historicalFailureOwnerIdentified": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

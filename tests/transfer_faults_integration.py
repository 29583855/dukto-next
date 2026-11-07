"""日期：2026-11-05；公共多通道链路中途改变源内容、撤权和改配根，验证不发布错误文件。"""

import argparse
from collections import deque
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time

from service_integration import free_port, run
from transfer_integration import digest
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_checkpoint


# 日期：2026-11-05；读取测试自有数据库的最终证据，权限被撤销后不能用客户端绕过授权查询任务。
def stopped_task(state, task):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with closing(sqlite3.connect(f"{(state / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as database:
            row = database.execute("SELECT state,error,processed,total FROM tasks WHERE id=?", (task,)).fetchone()
        if row and row[0] in ("failed", "interrupted"):
            return {"state": row[0], "error": row[1], "confirmed": row[2], "total": row[3]}
        time.sleep(0.05)
    raise AssertionError(row)


# 日期：2026-11-05；真实子进程失败必须保留非零错误事件，不能把连接退出当作成功或静默简化。
def failure(operation):
    code = operation.process.wait(30)
    operation.reader.join(3)
    events = []
    while not operation.events.empty():
        value = operation.events.get_nowait()
        if value:
            events.append(value)
    assert code != 0 and not operation.process.stderr.read(), (code, events)
    assert events and events[-1]["event"] == "error", events
    assert not any(value["event"] == "transfer-completed" for value in events), events
    return events[-1]


# 日期：2026-11-07；配置原子替换可触发精确路径/对象拒绝，仍要求任务未完成；其他完整性错误不能混入撤权预期。
def validate_fault_refusal(error, fault, stopped, platform_name=os.name):
    signature = tuple(error.get(key) for key in ("event", "eventVersion", "code", "stage", "message"))
    path_refusal = (
        platform_name == "posix"
        and fault in ("revoke", "root-reconfigure")
        and type(error.get("eventVersion")) is int
        and type(error.get("code")) is int
        and signature in (
            ("error", 1, 6, "read", "源文件路径在读取期间已被替换"),
            ("error", 1, 6, "read", "读取期间源文件已变化"),
        )
    )
    if path_refusal:
        assert stopped["state"] in ("failed", "interrupted"), stopped
        assert 0 <= stopped["confirmed"] < stopped["total"], stopped
    else:
        assert error["code"] in ((3, 6) if fault == "same-size-mtime-source-change" else (3, 4)), error
    return path_refusal


# 日期：2026-11-05；持续排空测试服务的标准输出，仅保留最后 32 条事件用于故障诊断，避免管道背压阻塞服务。
def drain_service(stream, recent):
    for line in stream:
        recent.append(line.rstrip())


# 日期：2026-11-05；每个用例独立主体、源和接收目录，仅复用测试自有监听服务及固定缓冲样本。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--on-conflict", choices=("rename", "overwrite"), default="rename")
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    executable_sha = digest(Path(executable))
    script_sha = digest(Path(__file__))
    results = []
    with tempfile.TemporaryDirectory(prefix="dukto-transfer-faults-") as temporary:
        root = Path(temporary).resolve()
        if os.name == "nt":
            local = root / "dukto-cli.exe"
            shutil.copyfile(executable, local)
            executable = str(local)
        state, shared, replacement = root / "server", root / "shared", root / "replacement"
        shared.mkdir()
        replacement.mkdir()
        sample = root / "sample.bin"
        with sample.open("wb") as output:
            for index in range(256):
                output.write(bytes([index]) * (256 * 1024))
            output.write(b"frozen-tail")
        expected = digest(sample)
        identity, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        permissions = ["--share", "data", "--allow-browse", "--allow-upload", "--allow-download"]
        port = free_port()
        server_error = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        recent = deque(maxlen=32)
        server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state),
                                   "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                  stdout=subprocess.PIPE, stderr=server_error, encoding="utf-8")
        proxy = SlowProxy(port)
        active = None
        reader = None
        try:
            assert json.loads(server.stdout.readline())["event"] == "service-listening"
            reader = threading.Thread(target=drain_service, args=(server.stdout, recent), daemon=True)
            reader.start()
            for fault in ("same-size-mtime-source-change", "revoke", "root-reconfigure"):
                for direction in ("upload", "download"):
                    key = fault + "-" + direction
                    source_directory = root / (key + "-source") if direction == "upload" else shared / key
                    source_directory.mkdir()
                    source = source_directory / "source.bin"
                    shutil.copyfile(sample, source)
                    target = shared / key if direction == "upload" else root / (key + "-target")
                    target.mkdir(exist_ok=True)
                    original = target / source.name
                    original.write_bytes(b"preserve existing user file")
                    original_sha = digest(original)
                    run(executable, state, ["serve", "share", "add", "--path", str(shared), *permissions])
                    offer, _ = run(executable, state, ["serve", "pairing", *permissions])
                    client = root / (key + "-client")
                    paired, _ = run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                        "--fingerprint", identity["fingerprint"], "--credential-file", offer["credentialFile"]])
                    arguments = [direction, "--share", "data", "--threads", "4", "--on-conflict", args.on_conflict]
                    arguments += (["--path", str(source), "--remote-path", key] if direction == "upload" else
                                  ["--remote-path", key + "/source.bin", "--output", str(target)])
                    active = TransferProcess(executable, client, arguments)
                    task = active.task()
                    received_state = state / "service" if direction == "upload" else client / "transfers"
                    checkpoint = wait_checkpoint(received_state, task)
                    assert active.process.poll() is None
                    started = time.monotonic()
                    if fault == "same-size-mtime-source-change":
                        info = source.stat()
                        with source.open("r+b") as changed:
                            changed.seek(60 * 1024 * 1024)
                            changed.write(b"CHANGED-CONTENT")
                            changed.flush()
                            os.fsync(changed.fileno())
                        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
                        assert source.stat().st_size == info.st_size and source.stat().st_mtime_ns == info.st_mtime_ns
                        assert digest(source) != expected
                    elif fault == "revoke":
                        run(executable, state, ["serve", "revoke", "--client", paired["client"]])
                    else:
                        run(executable, state, ["serve", "share", "add", "--path", str(replacement), *permissions])
                    error = failure(active)
                    active = None
                    stopped = stopped_task(state, task)
                    seconds = round(time.monotonic() - started, 3)
                    path_refusal = validate_fault_refusal(error, fault, stopped)
                    # 日期：2026-11-05；尾部源变化须等该块实际发送和摘要核对；授权撤销仍保留独立 15 秒门槛。
                    deadline_seconds = 30 if fault == "same-size-mtime-source-change" else 15
                    assert seconds < deadline_seconds, {"fault": fault, "direction": direction,
                                                        "seconds": seconds, "deadline": deadline_seconds}
                    assert digest(original) == original_sha
                    assert [path.name for path in target.iterdir() if not path.name.startswith(".")] == [source.name]
                    assert list(replacement.iterdir()) == []
                    run(executable, client, ["task", "--task", task], 4 if fault != "same-size-mtime-source-change" else 0)
                    results.append({"direction": direction, "fault": fault, "taskId": task,
                                    "checkpoint": checkpoint, "secondsAfterFault": seconds,
                                    "deadlineSeconds": deadline_seconds,
                                    "clientError": error, "serverTask": stopped,
                                    "pathIntegrityRefusalAccepted": path_refusal,
                                    "originalPreserved": True, "noPublishedCopy": True})
                    print(f"{direction}/{fault}: passed ({seconds}s)", flush=True)
        finally:
            if active and active.process.poll() is None:
                active.process.kill()
                active.process.wait(10)
            proxy.close()
            server.kill()
            server.wait(timeout=15)
            if reader is not None:
                reader.join(3)
            server.stdout.close()
            server_error.seek(0)
            error = server_error.read()
            server_error.close()
            assert not error, (error, list(recent))
    Path(args.report).write_text(json.dumps({"date": "2026-11-05", "passed": True,
        "executableSha256": executable_sha, "testScriptSha256": script_sha, "conflictPolicy": args.on_conflict,
        "sourceChangeDeadlineSeconds": 30, "authorizationDeadlineSeconds": 15,
        "sampleSha256": expected, "cases": results,
        "scope": "selected mid-transfer content/authorization/root faults; partial data retained, no disk-full or final-ack-loss claim"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

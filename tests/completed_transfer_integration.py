"""日期：2026-11-06；真实TLS重复请求重验当前服务文件，历史完成状态与原证据保持不变。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import uuid

from conflict_fail_integration import start
from disposition_transfer_integration import verify_journal
from service_integration import free_port, run
from transfer_integration import digest, transfer


# 日期：2026-11-06；拒绝必须来自真实进程、无完成事件，保持原90秒上限且保留明确错误阶段。
def refused(executable, client, operation):
    result = subprocess.run([executable, *operation, "--state-directory", str(client), "--json"],
                            capture_output=True, encoding="utf-8", timeout=90)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode in (4, 5, 6) and not result.stderr, (result.returncode, events, result.stderr)
    assert events and events[-1]["event"] == "error", events
    assert not any(event.get("event") == "transfer-completed" for event in events), events
    return {"code": result.returncode, "stage": events[-1]["stage"]}


# 日期：2026-11-06；只读查询终态和修订号，不由成功输出推测服务端历史是否被重写。
def task_row(server, task):
    with closing(sqlite3.connect(f"{(server / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        row = db.execute("SELECT state,revision,processed,error FROM tasks WHERE id=?", (task,)).fetchone()
    assert row and row[0] == "completed" and row[3] == 0
    return row


# 日期：2026-11-06；跨页Unicode/空项/大文件及三策略分别走1/4/16通道，两方向独立验证。
def case(executable, root, server, client, shared, channels, conflict, direction):
    key = f"history-{direction}-{channels}-{conflict}"
    source = root / (key + "-source")
    (source / "资料/空目录").mkdir(parents=True)
    (source / "资料/空文件").touch()
    for index in range(101):
        (source / f"file-{index:03}.bin").write_bytes(bytes([index + 1]) * (index + 1))
    payload = source / "资料/payload.bin"
    payload.write_bytes(bytes(range(251)) * 33429 + b"tail")
    expected_sha = digest(payload)
    destination = shared / key if direction == "upload" else root / key
    destination.mkdir()
    if conflict != "fail":
        shutil.copytree(source, destination / source.name)
        (destination / source.name / "资料/payload.bin").write_bytes(b"original-user-data")
    if direction == "upload":
        args = ["upload", "--share", "data", "--remote-path", key, "--path", str(source)]
    else:
        shutil.copytree(source, shared / source.name)
        args = ["download", "--share", "data", "--remote-path", source.name, "--output", str(destination)]
    operation = [*args, "--threads", str(channels), "--on-conflict", conflict,
                 "--request-id", str(uuid.uuid4())]
    completed = transfer(executable, client, operation)
    task = completed["taskId"]
    state = server / "service"
    manifest = state / f"manifest-{task}.sqlite"
    ledger = state / f"disposition-{task}.sqlite"
    receiver = state / f"receive-{task}.sqlite"
    history = task_row(server, task)
    evidence = [manifest, ledger] + ([receiver] if direction == "upload" else [])
    hashes = {path.name: digest(path) for path in evidence}
    with closing(sqlite3.connect(f"{ledger.as_uri()}?mode=ro", uri=True)) as db:
        records = [json.loads(value) for value, in db.execute("SELECT spec FROM items ORDER BY id")]
    payload_record, = [item for item in records if item["entry"]["path"].endswith("/资料/payload.bin")]
    directory_record, = [item for item in records if item["entry"]["path"].endswith("/资料/空目录")]
    current = destination / payload_record["path"] if direction == "upload" else shared / source.name / "资料/payload.bin"
    directory = destination / directory_record["path"] if direction == "upload" else shared / source.name / "资料/空目录"
    assert digest(current) == expected_sha
    assert transfer(executable, client, operation)["taskId"] == task
    assert hashes == {path.name: digest(path) for path in evidence}
    assert task_row(server, task) == history
    failures = []
    # 日期：2026-11-06；同长度原地损坏后恢复原对象，防止只比大小而接受已变化正文。
    with current.open("r+b") as output:
        original = output.read(1)
        output.seek(0)
        output.write(bytes([original[0] ^ 0xff]))
    try:
        failures.append({"attack": "same-length-corruption", **refused(executable, client, operation)})
    finally:
        with current.open("r+b") as output:
            output.write(original)
    assert digest(current) == expected_sha
    # 日期：2026-11-06；移走文件及空目录后不能凭旧完成态成功，恢复使用同一原生对象。
    for name, path in (("missing-file", current), ("missing-directory", directory)):
        hidden = path.with_name(path.name + ".hidden")
        path.rename(hidden)
        try:
            failures.append({"attack": name, **refused(executable, client, operation)})
            assert not path.exists()
        finally:
            hidden.rename(path)
    if direction == "upload":
        hidden = current.with_name(current.name + ".original")
        current.rename(hidden)
        shutil.copyfile(hidden, current)
        try:
            assert digest(current) == expected_sha
            failures.append({"attack": "same-content-foreign-object", **refused(executable, client, operation)})
        finally:
            current.unlink()
            hidden.rename(current)
    # 日期：2026-11-06；缺少处置/接收证据不能新建空库，恢复后才能再次得到原任务成功。
    for path in [ledger] + ([receiver] if direction == "upload" else []):
        hidden = path.with_suffix(".hidden")
        path.rename(hidden)
        try:
            failures.append({"attack": "missing-" + path.name.split("-")[0],
                             **refused(executable, client, operation)})
            assert not path.exists()
        finally:
            hidden.rename(path)
    assert task_row(server, task) == history
    assert hashes == {path.name: digest(path) for path in evidence}
    assert transfer(executable, client, operation)["taskId"] == task
    assert task_row(server, task) == history
    assert digest(current) == expected_sha
    if conflict == "rename":
        assert (destination / source.name / "资料/payload.bin").read_bytes() == b"original-user-data"
    return {"direction": direction, "channels": channels, "conflict": conflict, "taskId": task,
            "entries": len(records), "attacks": failures, "currentContentVerified": True,
            "historyUnchanged": True, "evidenceByteHashesUnchanged": True, "restoredRetryPassed": True}


# 日期：2026-11-06；服务仅监听回环，关闭后确认输出无错误，所有原报告独立保存。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report = Path(args.report)
    assert not report.exists()
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-completed-history-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        service = start(executable, server, free_port())
        try:
            # 日期：2026-11-06；从进程启动参数读取本测试实际分配端口，不猜测系统端口。
            port = service.args[service.args.index("--port") + 1]
            run(executable, client, ["pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                                     "--credential-file", offer["credentialFile"]])
            for channels, conflict in ((1, "rename"), (4, "fail"), (16, "overwrite")):
                for direction in ("upload", "download"):
                    cases.append(case(executable, root, server, client, shared, channels, conflict, direction))
        finally:
            service.kill()
            service.wait(timeout=10)
            service.output_drain.finish()
            assert not service.stderr.read()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"date": "2026-11-06", "passed": True, "cases": cases,
                                 "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
                                 "scope": "current server content on repeated transfer; immutable historical task evidence"},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

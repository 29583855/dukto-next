"""日期：2026-11-06；真实CLI/TLS核验完成处置接线、双向多通道、恢复幂等和失败前缀。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid

from conflict_fail_integration import start
from service_integration import free_port, run
from transfer_integration import digest, transfer


# 日期：2026-11-06；只读测试自有数据库，独立核对冻结清单、真实目标及连续完成前缀。
def verify_journal(state, manifest_name, task, destination, conflict, complete=True):
    ledger = state / f"disposition-{task}.sqlite"
    assert ledger.is_file(), ledger
    with closing(sqlite3.connect(f"{(state / manifest_name).as_uri()}?mode=ro", uri=True)) as database:
        entries = database.execute("SELECT id,relative,directory,bytes,sha FROM entries ORDER BY id").fetchall()
        metadata, = database.execute("SELECT value FROM metadata").fetchone()
        metadata = json.loads(metadata)
    with closing(sqlite3.connect(f"{ledger.as_uri()}?mode=ro", uri=True)) as database:
        assert database.execute("PRAGMA user_version").fetchone() == (1,)
        bindings = database.execute("SELECT spec FROM binding").fetchall()
        assert len(bindings) == 1
        binding = json.loads(bindings[0][0])
        assert binding["taskId"] == task and binding["conflict"] == conflict
        assert all(binding["manifest"][key] == metadata[key] for key in ("sha256", "entries", "bytes", "blocks"))
        rows = database.execute("SELECT id,source,spec FROM items ORDER BY id").fetchall()
    assert len(rows) <= len(entries) and (not complete or len(rows) == len(entries))
    records = []
    for row, entry in zip(rows, entries):
        identifier, source, spec = row
        file, relative, directory, size, sha = entry
        assert identifier == file == len(records) + 1 and source == relative
        value = json.loads(spec)
        assert set(value) == {"version", "entry", "path", "disposition"}
        assert value["version"] == 1 and value["disposition"] == "copied"
        assert value["entry"] == {"id": str(file), "path": relative,
                                  "type": "directory" if directory else "file",
                                  "bytes": str(size), "sha256": sha.hex()}
        target = destination / value["path"]
        assert not Path(value["path"]).is_absolute() and ".." not in Path(value["path"]).parts
        assert target.is_dir() if directory else target.is_file()
        if not directory:
            assert target.stat().st_size == size and digest(target) == sha.hex()
        records.append(value)
    return {"recordedEntries": len(rows), "totalEntries": len(entries),
            "complete": len(rows) == len(entries), "records": records,
            "journalSha256": digest(ledger)}


# 日期：2026-11-06；三种公开策略和1/4/16通道都执行真实重名传输；跨窗口、空项和Unicode同时覆盖。
def completed_case(executable, root, server, client, shared, channels, direction, conflict):
    key = f"{direction}-{channels}-{conflict}"
    source = root / f"source-{key}"
    (source / "资料/空目录").mkdir(parents=True)
    (source / "资料/空文件").touch()
    for index in range(35):
        (source / f"file-{index:02}.bin").write_bytes(bytes([index + 1]) * (index * 137 + 1))
    (source / "资料/large.bin").write_bytes(bytes(range(251)) * 33429 + b"tail")
    if direction == "download":
        shutil.copytree(source, shared / source.name)
    destination = shared / key if direction == "upload" else root / key
    destination.mkdir()
    arguments = (["upload", "--share", "data", "--path", str(source), "--remote-path", key]
                 if direction == "upload" else
                 ["download", "--share", "data", "--remote-path", source.name, "--output", str(destination)])
    if conflict in ("rename", "overwrite"):
        shutil.copytree(source, destination / source.name)
        (destination / source.name / "资料/large.bin").write_bytes(b"existing-user-data")
    operation = [*arguments, "--threads", str(channels), "--on-conflict", conflict,
                 "--request-id", str(uuid.uuid4())]
    result = transfer(executable, client, operation)
    task = result["taskId"]
    remote = verify_journal(server / "service", f"manifest-{task}.sqlite", task, destination, conflict)
    assert remote["recordedEntries"] > 32
    if direction == "download":
        local = verify_journal(client / "transfers", f"download-{task}.sqlite", task, destination, conflict)
        assert local["records"] == remote["records"]
    else:
        local = None
    if conflict == "rename":
        assert remote["records"][0]["path"] != remote["records"][0]["entry"]["path"]
        assert (destination / source.name / "资料/large.bin").read_bytes() == b"existing-user-data"
    repeated = transfer(executable, client, operation)
    assert repeated["taskId"] == task
    assert verify_journal(server / "service", f"manifest-{task}.sqlite", task, destination, conflict) == remote
    if local:
        assert verify_journal(client / "transfers", f"download-{task}.sqlite", task, destination, conflict) == local
    # 日期：2026-11-06；只有一例篡改本测试私有日志；完整任务重试必须拒绝旧处置不一致，原数据保持可恢复。
    tamper_checked = direction == "download" and channels == 4 and conflict == "rename"
    if tamper_checked:
        ledger = client / "transfers" / f"disposition-{task}.sqlite"
        with closing(sqlite3.connect(ledger)) as database:
            original, = database.execute("SELECT spec FROM items WHERE id=1").fetchone()
            changed = json.loads(original)
            changed["disposition"] = "skipped"
            database.execute("UPDATE items SET spec=? WHERE id=1", (json.dumps(changed).encode(),))
            database.commit()
        failure = transfer(executable, client, operation, 6)
        assert failure["stage"] == "disposition"
        with closing(sqlite3.connect(ledger)) as database:
            database.execute("UPDATE items SET spec=? WHERE id=1", (original,))
            database.commit()
        assert transfer(executable, client, operation)["taskId"] == task
        assert verify_journal(client / "transfers", f"download-{task}.sqlite", task, destination, conflict)["records"] == local["records"]
    return {"taskId": task, "direction": direction, "channels": channels, "conflict": conflict,
            "entries": remote["recordedEntries"], "actualTargetsVerified": True,
            "retryDidNotDuplicateRecords": True, "bothDownloadJournalsMatch": local is not None,
            "corruptCompletedDownloadRefused": tamper_checked}


# 日期：2026-11-06；正文前冲突不能写copied；单通道上传先完成再冲突必须保留真实前缀。
def failed_case(executable, root, server, client, shared, channels, direction):
    key = f"partial-{direction}-{channels}"
    source = root / (key + "-source")
    source.mkdir()
    first, second = source / "a-first.bin", source / "z-conflict.bin"
    first.write_bytes(b"completed-first-item")
    second.write_bytes(b"second-item")
    destination = shared / key if direction == "upload" else root / key
    destination.mkdir()
    (destination / second.name).write_bytes(b"original-user-data")
    if direction == "upload":
        operation = ["upload", "--share", "data", "--path", str(first), "--path", str(second), "--remote-path", key]
    else:
        shutil.copytree(source, shared / source.name)
        operation = ["download", "--share", "data", "--remote-path", source.name + "/" + second.name,
                     "--output", str(destination)]
    request = str(uuid.uuid4())
    error = transfer(executable, client, [*operation, "--threads", str(channels), "--on-conflict", "fail",
                                         "--request-id", request], 4)
    assert error["stage"] == "conflict"
    tasks, _ = run(executable, client, ["tasks"])
    task, = [task["taskId"] for task in tasks["tasks"] if task["requestId"] == request]
    remote = verify_journal(server / "service", f"manifest-{task}.sqlite", task, destination, "fail", False)
    assert not remote["complete"]
    if direction == "upload" and channels == 1:
        assert remote["recordedEntries"] == 1 and (destination / first.name).read_bytes() == first.read_bytes()
    else:
        assert remote["recordedEntries"] == 0
    if direction == "download":
        local = verify_journal(client / "transfers", f"download-{task}.sqlite", task, destination, "fail", False)
        assert local["records"] == remote["records"]
    assert (destination / second.name).read_bytes() == b"original-user-data"
    return {"direction": direction, "channels": channels, "taskId": task,
            "recordedEntries": remote["recordedEntries"], "totalEntries": remote["totalEntries"],
            "unexecutedNotRecordedAsCopied": True, "originalConflictPreserved": True}


# 日期：2026-11-06；服务和样本均归本测试所有；只输出摘要，不保存凭据或私有绝对路径。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report = Path(args.report)
    assert not report.exists()
    completed, failed = [], []
    with tempfile.TemporaryDirectory(prefix="dukto-disposition-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        port = free_port()
        process = start(executable, server, port)
        try:
            run(executable, client, ["pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                                     "--credential-file", offer["credentialFile"]])
            for channels in (1, 4, 16):
                for direction in ("upload", "download"):
                    for conflict in ("rename", "fail", "overwrite"):
                        completed.append(completed_case(executable, root, server, client, shared, channels, direction, conflict))
                    failed.append(failed_case(executable, root, server, client, shared, channels, direction))
        finally:
            process.kill()
            process.wait(timeout=10)
            process.output_drain.finish()
            assert not process.stderr.read()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"date": "2026-11-06", "passed": True, "completed": completed, "partial": failed,
                                 "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
                                 "scope": "copied journal integration; public skip and wire disposition summary not enabled"},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

"""日期：2026-11-06；真实上传重试按有界接收证据恢复本机日志，拒绝缺项、改清单及伪造目标。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid

from conflict_fail_integration import start
from disposition_transfer_integration import verify_journal
from service_integration import free_port, run
from transfer_integration import digest, transfer


# 日期：2026-11-06；仅截断本测试自有日志的完成后缀，模拟接收确认到达前或持久保存前退出。
def truncate(ledger, after):
    with closing(sqlite3.connect(ledger)) as database:
        database.execute("DELETE FROM items WHERE id>?", (after,))
        database.commit()


# 日期：2026-11-06；只读统计真实持久项，不能用批次完成状态代替缺失的逐项记录。
def count_rows(ledger):
    with closing(sqlite3.connect(f"{ledger.as_uri()}?mode=ro", uri=True)) as database:
        return database.execute("SELECT COUNT(*) FROM items").fetchone()[0]


# 日期：2026-11-06；创建跨三页、含空目录及Unicode的真实样本；三种策略分别使用1/4/16通道。
def recovery_case(executable, root, server, client, shared, channels, conflict):
    key = f"receipt-{conflict}-{channels}"
    source = root / key
    (source / "资料 空目录").mkdir(parents=True)
    for index in range(204):
        (source / f"file-{index:03}.bin").write_bytes(bytes([index + 1]) * (index + 1))
    destination = shared / key
    destination.mkdir()
    if conflict != "fail":
        shutil.copytree(source, destination / source.name)
        (destination / source.name / "file-203.bin").write_bytes(b"existing-user-data")
    request = str(uuid.uuid4())
    operation = ["upload", "--share", "data", "--remote-path", key, "--path", str(source),
                 "--threads", str(channels), "--on-conflict", conflict, "--request-id", request]
    result = transfer(executable, client, operation)
    task = result["taskId"]
    state = client / "transfers"
    ledger = state / f"upload-disposition-{task}.sqlite"
    frozen = [state / f"upload-source-{request}{suffix}" for suffix in (".json", ".sqlite")]
    assert all(path.is_file() for path in frozen)
    frozen_hashes = {path.name: digest(path) for path in frozen}
    manifest = server / "service" / f"manifest-{task}.sqlite"
    receiver = server / "service" / f"receive-{task}.sqlite"
    copied = state / f"test-manifest-{task}.sqlite"
    shutil.copyfile(manifest, copied)
    expected = verify_journal(state, copied.name, task, destination, conflict, sender=True)
    assert expected["recordedEntries"] > 200
    remote = verify_journal(server / "service", manifest.name, task, destination, conflict)
    assert remote["records"] == expected["records"]
    truncate(ledger, 73)
    assert count_rows(ledger) == 73
    assert transfer(executable, client, operation)["taskId"] == task
    repaired = verify_journal(state, copied.name, task, destination, conflict, sender=True)
    assert repaired["records"] == expected["records"]
    # 日期：2026-11-06；历史版本完全没有发送日志，同样必须从真实接收证据重建全部条目。
    ledger.unlink()
    assert transfer(executable, client, operation)["taskId"] == task
    rebuilt = verify_journal(state, copied.name, task, destination, conflict, sender=True)
    assert rebuilt["records"] == expected["records"]
    binding = json.loads((state / f"upload-request-{request}.json").read_bytes())
    assert binding["server"] and binding["client"] and binding["conflict"] == conflict
    assert binding["manifest"]["entries"] == str(expected["totalEntries"])
    # 日期：2026-11-06；重复请求不得改源清单或目标，即使远端早已完成；原目标不受影响。
    changed = source / "file-203.bin"
    original = changed.read_bytes()
    changed.write_bytes(original + b"changed-source")
    error = transfer(executable, client, operation, 6)
    assert error["stage"] == "completion"
    changed.write_bytes(original)
    assert transfer(executable, client, operation)["taskId"] == task
    assert verify_journal(state, copied.name, task, destination, conflict, sender=True)["records"] == expected["records"]
    # 日期：2026-11-06；重试使用原冻结集合，扫描后新增文件须新建请求，不能混入已完成批次。
    added = source / "new-after-freeze.bin"
    added.write_bytes(b"not part of the original upload")
    assert transfer(executable, client, operation)["taskId"] == task
    assert not any(destination.rglob(added.name))
    added.unlink()
    # 日期：2026-11-06；改源根、缺失记录/数据库及本机源映射篡改都必须只读拒绝，再恢复原件。
    frozen_attacks = []
    for path in frozen:
        hidden = path.with_suffix(path.suffix + ".saved")
        path.rename(hidden)
        try:
            remaining = {item.name: digest(item) for item in frozen if item.exists()}
            error = transfer(executable, client, operation, 6)
            assert error["stage"] == "manifest" and not path.exists(), error
            assert remaining == {item.name: digest(item) for item in frozen if item.exists()}
            frozen_attacks.append({"attack": "missing-" + path.suffix, "refused": True})
        finally:
            hidden.rename(path)
    original_database = frozen[1].read_bytes()
    try:
        with closing(sqlite3.connect(frozen[1])) as database:
            database.execute("UPDATE entries SET source=? WHERE id=1", (str(root / "foreign-source"),))
            database.commit()
        tampered_hash = digest(frozen[1])
        error = transfer(executable, client, operation, 6)
        assert error["stage"] == "manifest" and digest(frozen[1]) == tampered_hash, error
        frozen_attacks.append({"attack": "local-source-mapping", "refused": True})
    finally:
        frozen[1].write_bytes(original_database)
    alternate = root / (key + "-alternate")
    shutil.copytree(source, alternate)
    changed_paths = list(operation)
    changed_paths[changed_paths.index("--path") + 1] = str(alternate)
    error = transfer(executable, client, changed_paths, 6)
    assert error["stage"] == "manifest", error
    frozen_attacks.append({"attack": "different-source-root", "refused": True})
    assert transfer(executable, client, operation)["taskId"] == task
    assert frozen_hashes == {path.name: digest(path) for path in frozen}
    attacks = []
    if conflict == "rename":
        manifest_backup, receiver_backup = root / "manifest-backup.sqlite", root / "receiver-backup.sqlite"
        shutil.copyfile(manifest, manifest_backup)
        shutil.copyfile(receiver, receiver_backup)
        # 日期：2026-11-06；Unicode空目录排在文件之后；必须实际选取文件ID，不能把末目录当文件注入。
        with closing(sqlite3.connect(manifest)) as entries:
            last, = entries.execute("SELECT MAX(id) FROM entries WHERE directory=0").fetchone()
        for attack in ("missing-receive-journal", "missing-entry", "not-copied", "changed-source", "foreign-parent"):
            truncate(ledger, 73)
            hidden = receiver.with_suffix(".hidden")
            try:
                if attack == "missing-receive-journal":
                    receiver.rename(hidden)
                else:
                    with closing(sqlite3.connect(receiver)) as database:
                        if attack == "missing-entry":
                            database.execute("DELETE FROM files WHERE id=?", (last,))
                        elif attack == "not-copied":
                            database.execute("UPDATE files SET state='planned',confirmed=0 WHERE id=?", (last,))
                        else:
                            spec, = database.execute("SELECT spec FROM files WHERE id=?", (last,)).fetchone()
                            spec = json.loads(spec)
                            if attack == "changed-source":
                                spec["entry"]["path"] = source.name + "/foreign.bin"
                                with closing(sqlite3.connect(manifest)) as entries:
                                    entries.execute("UPDATE entries SET relative=? WHERE id=?", (spec["entry"]["path"], last))
                                    entries.commit()
                            else:
                                spec["path"] = "foreign-parent/foreign.bin"
                                database.execute("UPDATE files SET target=? WHERE id=?", (spec["path"], last))
                            database.execute("UPDATE files SET spec=? WHERE id=?", (json.dumps(spec).encode(), last))
                        database.commit()
                error = transfer(executable, client, operation, 6)
                assert error["stage"] in ("items", "disposition", "manifest", "completion"), error
                assert count_rows(ledger) < last
                attacks.append({"attack": attack, "refused": True, "recordedEntries": count_rows(ledger)})
            finally:
                if hidden.exists():
                    hidden.rename(receiver)
                shutil.copyfile(manifest_backup, manifest)
                shutil.copyfile(receiver_backup, receiver)
            assert transfer(executable, client, operation)["taskId"] == task
            assert verify_journal(state, copied.name, task, destination, conflict, sender=True)["records"] == expected["records"]
    if conflict == "rename":
        assert (destination / source.name / "file-203.bin").read_bytes() == b"existing-user-data"
    return {"taskId": task, "conflict": conflict, "channels": channels, "entries": expected["totalEntries"],
            "partialAndMissingLedgerRecovered": True, "receiverAndSenderRecordsMatch": True,
            "requestRebindingRefused": True, "malformedEvidence": attacks,
            "frozenManifestPreservedAcrossProcesses": True, "newFilesDoNotChangeFrozenRequest": True,
            "frozenManifestAttacks": frozen_attacks}


# 日期：2026-11-06；所有服务仅监听自有回环端口，原报告不含凭据；任一恢复或拒绝错误都使专项失败。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report = Path(args.report)
    assert not report.exists()
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-upload-receipt-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        port = free_port()
        service = start(executable, server, port)
        try:
            run(executable, client, ["pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                                     "--credential-file", offer["credentialFile"]])
            for channels, conflict in ((1, "rename"), (4, "fail"), (16, "overwrite")):
                cases.append(recovery_case(executable, root, server, client, shared, channels, conflict))
        finally:
            service.kill()
            service.wait(timeout=10)
            service.output_drain.finish()
            assert not service.stderr.read()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"date": "2026-11-06", "passed": True, "cases": cases,
                                 "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
                                 "scope": "historical receiver acknowledgements; not current remote content verification"},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

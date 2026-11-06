"""日期：2026-11-06；公开CLI双向skip，独立核对正文、处置根、分页、计量、协商和历史恢复。"""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import uuid

from conflict_fail_integration import start
from credential_rotation_integration import IndependentSession
from disposition_summary_integration import Relay, read_frame, write_frame
from service_integration import free_port, run
from transfer_integration import digest, transfer

CAPABILITIES = ["conflict-skip-v1", "byte-progress-v1", "disposition-summary-v1",
                "disposition-progress-v1"]


# 日期：2026-11-06；只读测试私有SQLite，绝不通过生产解析器计算预期结果。
def rows(path, statement, parameters=()):
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        return db.execute(statement, parameters).fetchall()


# 日期：2026-11-06；验证现有文件的原生身份、时间、长度及真实正文均未被应用改写。
def native_snapshot(path):
    info = path.stat()
    return info.st_ino, info.st_mtime_ns, info.st_size, digest(path)


# 日期：2026-11-06；直接散列原始处置字节并核对每项清单、类型、跳过根及实际复制目标。
def verify(executable, server, client, result, direction, destination, expected_discarded=0):
    task = result["taskId"]
    remote = server / "service"
    manifest = rows(remote / f"manifest-{task}.sqlite",
                    "SELECT id,relative,directory,bytes,sha FROM entries ORDER BY id")
    ledger = remote / f"disposition-{task}.sqlite"
    binding, = rows(ledger, "SELECT spec FROM binding")
    records = rows(ledger, "SELECT spec FROM items ORDER BY id")
    assert len(records) == len(manifest) and result["dispositionConfirmed"] is True
    local_ledger = client / "transfers" / f"{'upload-disposition' if direction == 'upload' else 'disposition'}-{task}.sqlite"
    assert rows(local_ledger, "SELECT spec FROM binding") == [binding]
    assert rows(local_ledger, "SELECT spec FROM items ORDER BY id") == records
    h = hashlib.sha256()
    for raw, in [binding, *records]:
        h.update(struct.pack(">I", len(raw)))
        h.update(raw)
    counts = {key: 0 for key in ("copiedFiles", "copiedDirectories", "skippedFiles",
                                "skippedDirectories", "copiedBytes", "skippedBytes")}
    items = {}
    for (raw,), (identifier, relative, directory, size, sha) in zip(records, manifest):
        item = json.loads(raw)
        assert item["entry"] == {"id": str(identifier), "path": relative,
                                  "type": "directory" if directory else "file",
                                  "bytes": str(size), "sha256": sha.hex()}
        assert item["version"] == 1 and item["path"] == relative
        disposition = item["disposition"]
        assert disposition in ("copied", "skipped")
        counts[disposition + ("Directories" if directory else "Files")] += 1
        counts[disposition + "Bytes"] += size
        if disposition == "copied":
            assert "skippedRoot" not in item
            target = destination / relative
            assert target.is_dir() if directory else target.is_file()
            if not directory:
                assert target.stat().st_size == size and digest(target) == sha.hex()
        else:
            root = int(item["skippedRoot"])
            ancestor = item if root == identifier else items[root]
            assert 0 < root <= identifier and ancestor["disposition"] == "skipped"
            assert ancestor["skippedRoot"] == str(root)
            assert root == identifier or (ancestor["entry"]["type"] == "directory" and
                                          relative.startswith(ancestor["path"] + "/"))
        items[identifier] = item
    total = sum(row[3] for row in manifest)
    summary = result["dispositionSummary"]
    assert summary["sha256"] == h.hexdigest() and summary["conflict"] == "skip"
    assert summary["complete"] is True and summary["totalEntries"] == str(len(manifest))
    assert summary["processedEntries"] == str(len(manifest)) and summary["unexecutedEntries"] == "0"
    assert summary["copiedEntries"] == str(counts["copiedFiles"] + counts["copiedDirectories"])
    assert summary["skippedEntries"] == str(counts["skippedFiles"] + counts["skippedDirectories"])
    assert summary["totalBytes"] == str(total)
    assert all(summary[key] == result[key] == str(value) for key, value in counts.items())
    assert result["accountingVersion"] == 1 and result["bytes"] == result["handledBytes"] == str(total)
    assert result["discardedBytes"] == str(expected_discarded)
    assert result["receivedBytes"] == result["confirmedBytes"] == str(counts["copiedBytes"] + expected_discarded)
    spec, accounting, processed = rows(remote / "tasks.sqlite", "SELECT spec,accounting,processed FROM tasks WHERE id=?", (task,))[0]
    assert json.loads(spec)["version"] == 3 and json.loads(spec)["progress"] == "disposition-v1"
    accounting = json.loads(accounting)
    assert processed == total and accounting["bytes"] == result["receivedBytes"]
    assert accounting["confirmed"] == result["confirmedBytes"]
    assert all(accounting[key] == result[key] for key in [*counts, "discardedBytes"])
    after = 0
    while after < len(manifest):
        page, _ = run(executable, client, ["task-items", "--task", task, "--after", str(after)])
        assert page["available"] and not page["currentContentVerified"]
        for item in page["entries"]:
            after += 1
            record = items[after]
            assert item["id"] == str(after) and item["target"] == record["path"]
            assert item["disposition"] == record["disposition"]
            assert item["confirmedBytes"] == ("0" if record["disposition"] == "skipped" else record["entry"]["bytes"])
            assert item.get("skippedRoot") == record.get("skippedRoot")
        assert page["after"] == str(after) and page["more"] == (after < len(manifest))
    return {"entries": len(manifest), **counts, "sha256": h.hexdigest()}


# 日期：2026-11-06；跨三页目录被整体跳过；同时复制全新目录、空文件及超过8MiB的真实正文。
def upload_case(executable, root, server, client, shared, channels):
    source = root / f"sources-{channels}"
    skipped = source / "同名目录"
    copied = source / "新目录"
    (skipped / "空目录").mkdir(parents=True)
    (copied / "空目录").mkdir(parents=True)
    for index in range(204):
        (skipped / f"file-{index:03}.bin").write_bytes(bytes([index + 1]) * (index + 1))
    (skipped / "空文件").touch()
    (copied / "大文件.bin").write_bytes(bytes(range(251)) * 33429 + b"tail")
    (copied / "空文件").touch()
    old_file, empty = source / "同名文件.bin", source / "新空文件"
    old_file.write_bytes(b"unneeded-source")
    empty.touch()
    destination = shared / f"upload-{channels}"
    (destination / skipped.name).mkdir(parents=True)
    preserved = [destination / skipped.name / "只保留原目录.txt", destination / old_file.name]
    for path in preserved:
        path.write_bytes(b"original-user-data")
    snapshots = [native_snapshot(path) for path in preserved]
    operation = ["upload", "--share", "data", "--remote-path", destination.name,
                 "--threads", str(channels), "--on-conflict", "skip", "--request-id", str(uuid.uuid4())]
    for path in (skipped, copied, old_file, empty):
        operation += ["--path", str(path)]
    result = transfer(executable, client, operation)
    checked = verify(executable, server, client, result, "upload", destination)
    assert checked["entries"] > 200 and checked["copiedBytes"] > 8 * 1024 * 1024
    assert checked["skippedFiles"] == 206 and checked["skippedDirectories"] == 2
    assert [native_snapshot(path) for path in preserved] == snapshots
    assert sorted(path.name for path in (destination / skipped.name).iterdir()) == ["只保留原目录.txt"]
    # 日期：2026-11-06；删除仅跳过的源；独立重启CLI及接收分页恢复均不得重新扫描或访问这些源。
    shutil.rmtree(skipped)
    old_file.unlink()
    ledger = client / "transfers" / f"upload-disposition-{result['taskId']}.sqlite"
    with closing(sqlite3.connect(ledger)) as db:
        db.execute("DELETE FROM items WHERE id>73")
        db.commit()
    assert transfer(executable, client, operation)["taskId"] == result["taskId"]
    assert verify(executable, server, client, result, "upload", destination) == checked
    changed = copied / "大文件.bin"
    original = changed.read_bytes()
    changed.write_bytes(b"x" + original[1:])
    transfer(executable, client, operation, 6)
    changed.write_bytes(original)
    assert transfer(executable, client, operation)["taskId"] == result["taskId"]
    assert [native_snapshot(path) for path in preserved] == snapshots
    return {"direction": "upload", "channels": channels, **checked,
            "deletedSkippedSourceAndTruncatedReceiptRecovered": True, "changedCopiedSourceRefused": True}


# 日期：2026-11-06；下载已有目录整棵跳过、全新目录真实复制；历史跳过源/目标删除均不改写原证据。
def download_case(executable, root, server, client, shared, channels, skip):
    key = f"download-{channels}-{'skip' if skip else 'copy'}"
    source = shared / key
    (source / "空目录").mkdir(parents=True)
    for index in range(204):
        (source / f"资料-{index:03}.bin").write_bytes(bytes([index + 1]) * (index + 1))
    (source / "空文件").touch()
    destination = root / (key + "-output")
    destination.mkdir()
    preserved = destination / key / "原目录.txt"
    if skip:
        preserved.parent.mkdir()
        preserved.write_bytes(b"keep-native-target")
        snapshot = native_snapshot(preserved)
    operation = ["download", "--share", "data", "--remote-path", key, "--output", str(destination),
                 "--threads", str(channels), "--on-conflict", "skip", "--request-id", str(uuid.uuid4())]
    result = transfer(executable, client, operation)
    checked = verify(executable, server, client, result, "download", destination)
    assert checked["entries"] == 207
    if skip:
        assert checked["copiedFiles"] == checked["copiedDirectories"] == checked["copiedBytes"] == 0
        assert native_snapshot(preserved) == snapshot
        assert list(preserved.parent.iterdir()) == [preserved]
        shutil.rmtree(source)
        shutil.rmtree(preserved.parent)
        journals = [server / "service" / f"{prefix}-{result['taskId']}.sqlite" for prefix in ("manifest", "disposition")]
        journals += [client / "transfers" / f"{prefix}-{result['taskId']}.sqlite" for prefix in ("download", "receive", "disposition")]
        hashes = [digest(path) for path in journals]
        assert transfer(executable, client, operation)["taskId"] == result["taskId"]
        assert [digest(path) for path in journals] == hashes and list(destination.iterdir()) == []
    else:
        assert checked["skippedFiles"] == checked["skippedDirectories"] == 0
        changed = source / "资料-203.bin"
        changed.unlink()
        failure = transfer(executable, client, operation, 5)
        assert failure["stage"] == "path"
    return {"direction": "download", "channels": channels, "allSkipped": skip, **checked,
            "historyAfterSourceAndTargetDeletion": skip, "missingCopiedSourceRefused": not skip}


class SkipSession(IndependentSession):
    # 日期：2026-11-06；独立客户机按单个能力删除，认证及证书核对仍走真实服务。
    def __init__(self, port, profile, capabilities):
        self.capabilities = capabilities
        super().__init__(port, profile)

    # 日期：2026-11-06；Hello不允许由创建字段自动补全能力。
    def request(self, kind, value):
        if kind == 1:
            value = {**value, "capabilities": self.capabilities}
        return super().request(kind, value)


# 日期：2026-11-06；缺少每项Hello或创建依赖都在建任务前拒绝，任务库逐字节保持不变。
def negotiations(port, profile, server):
    cases = []
    for direction in ("upload", "download"):
        for hidden in CAPABILITIES + ["byteProgress", "dispositionSummary", "dispositionProgress"]:
            capabilities = [cap for cap in CAPABILITIES if cap != hidden]
            session = SkipSession(port, profile, capabilities)
            try:
                create = {"requestId": str(uuid.uuid4()), "share": "data", "path": "missing",
                          "conflict": "skip", "byteProgress": True, "dispositionSummary": True,
                          "dispositionProgress": True}
                if direction == "upload":
                    create["manifest"] = {"sha256": "00" * 32}
                create.pop(hidden, None)
                before = digest(server / "service/tasks.sqlite")
                kind, result = session.request(32 if direction == "upload" else 33, create)
                assert kind == 7 and result["code"] == 2
                assert digest(server / "service/tasks.sqlite") == before
                cases.append({"direction": direction, "missing": hidden, "beforeCreateRefused": True})
            finally:
                session.close()
    return cases


class SkipRelay(Relay):
    # 日期：2026-11-06；只在自有TLS中继隐藏一项能力或制造真实迟到同名目标，正文仍完整转发。
    def __init__(self, *args, target=None):
        self.created = 0
        self.target_path = target
        super().__init__(*args)

    # 日期：2026-11-06；每次最多保存一帧；迟到冲突发生在准备确认之后、首段正文落盘之前。
    def forward(self, source, destination, side):
        frame = read_frame(source)
        if frame is None:
            return False
        header, payload = frame
        kind = header[3]
        if kind in (32, 33):
            self.created += 1
        if kind == 2 and self.attack in CAPABILITIES:
            value = json.loads(payload)
            value["capabilities"].remove(self.attack)
            payload = json.dumps(value, separators=(",", ":")).encode()
            self.hit += 1
        if kind == 40 and self.attack == "late-target" and not self.hit:
            assert not self.target_path.exists()
            self.target_path.write_bytes(b"external-late-original")
            self.hit += 1
        write_frame(destination, header, payload)
        return True


# 日期：2026-11-06；真实CLI遇不完整服务能力不得降级或发送创建；单通道最终跳过核对丢弃量。
def relay_cases(executable, root, server, client, shared, identity, profile, port):
    cases = []
    profile_path = client / "clients/profile-default.json"
    original_profile = profile_path.read_bytes()
    for direction in ("upload", "download"):
        for attack in [*CAPABILITIES, "late-target"]:
            key = f"{direction}-{attack}.bin"
            source = (root if direction == "upload" else shared) / key
            source.write_bytes(bytes(range(251)) * 33429 + b"tail")
            destination = shared if direction == "upload" else root / (key + "-output")
            destination.mkdir(exist_ok=True)
            target = destination / key
            operation = [direction, "--share", "data", "--threads", "1", "--on-conflict", "skip",
                         "--request-id", str(uuid.uuid4())]
            operation += (["--path", str(source)] if direction == "upload" else
                          ["--remote-path", key, "--output", str(destination)])
            relay = SkipRelay(root, identity, port, profile["fingerprint"], server / "service/tasks.sqlite",
                              attack, "summary", target=target)
            try:
                profile_path.write_text(json.dumps({**profile, "port": str(relay.port)}), "utf-8")
                result = transfer(executable, client, operation, 0 if attack == "late-target" else 2)
            finally:
                profile_path.write_bytes(original_profile)
                relay.close()
            assert relay.hit == 1
            if attack == "late-target":
                assert target.read_bytes() == b"external-late-original"
                checked = verify(executable, server, client, result, direction, destination, source.stat().st_size)
                assert checked["copiedBytes"] == 0 and checked["skippedFiles"] == 1
                assert not list(destination.glob(".dukto*"))
            else:
                assert relay.created == 0 and result["stage"] == "conflict" and not target.exists()
            cases.append({"direction": direction, "attack": attack, "creates": relay.created,
                          "refusedBeforeCreate": attack != "late-target", "nativeTargetPreserved": attack == "late-target"})
    return cases


# 日期：2026-11-06；仅测试自有服务/临时目录，报告保存公开结果，不输出认证秘密。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    assert not args.report.exists()
    with tempfile.TemporaryDirectory(prefix="dukto-public-skip-") as temporary:
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
            profile = json.loads((client / "clients/profile-default.json").read_bytes())
            identity = json.loads((server / "service/identity.json").read_bytes())
            cases = []
            for channels in (1, 4, 16):
                cases.append(upload_case(executable, root, server, client, shared, channels))
                for skip in (True, False):
                    cases.append(download_case(executable, root, server, client, shared, channels, skip))
            rejected = negotiations(port, profile, server)
            relayed = relay_cases(executable, root, server, client, shared, identity, profile, port)
            assert service.poll() is None
        finally:
            service.terminate()
            service.wait(timeout=10)
            service.output_drain.finish()
            assert not service.stderr.read()
    report = {"date": "2026-11-06", "passed": True, "publicSkipEnabled": True,
              "cases": cases, "negotiationRefusals": rejected, "relayCases": relayed,
              "scope": "real CLI, loopback TLS, bounded windows/pages and durable histories; physical LAN, soak and formal delivery remain separate"}
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"passed": True, "cases": len(cases), "negotiationRefusals": len(rejected), "relayCases": len(relayed)}))


if __name__ == "__main__":
    main()

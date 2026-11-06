"""日期：2026-11-06；独立TLS客户机验证服务端必需计量协商、持久化和历史一致性。"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import time
import uuid

from conflict_fail_integration import start
from credential_rotation_integration import IndependentSession
from disposition_summary_integration import verify_summary
from service_integration import free_port, run
from transfer_integration import digest, transfer

COUNTERS = ["copiedBytes", "skippedBytes", "discardedBytes", "copiedFiles",
            "copiedDirectories", "skippedFiles", "skippedDirectories"]


class PeerFailure(Exception):
    # 日期：2026-11-06；仅保存公开失败字段，协议错误须由真实服务返回而非测试断言推测。
    def __init__(self, value):
        super().__init__(value)
        self.value = value


class PeerClosed(ConnectionError):
    """日期：2026-11-06；仅在下一完整帧之前断开，实际拒绝仍须核对服务错误事件、任务状态与原计量。"""


class AccountingSession(IndependentSession):
    # 日期：2026-11-06；使用独立编码器，真实指纹校验和认证保持，普通客户端不参与本扩展测试。
    def __init__(self, port, profile, negotiated=True):
        self.negotiated = negotiated
        self.snapshots = []
        self.boundary_close = None
        super().__init__(port, profile)
        self.socket.settimeout(20)

    # 日期：2026-11-06；仅在本连接Hello声明所选能力，创建字段不能自动添加协商能力。
    def request(self, kind, value):
        if kind == 1:
            value = {**value, "capabilities": ["disposition-summary-v1"] +
                     (["disposition-progress-v1"] if self.negotiated else [])}
        return super().request(kind, value)

    # 日期：2026-11-06；固定32字节大端帧头，二进制正文不经过生产库或JSON编码器。
    def send(self, kind, value):
        payload = value if isinstance(value, bytes) else json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.socket.sendall(struct.pack(">8sHHHHQII", b"DKTNEXT1", 1, 0, kind, 0,
                                        self.correlation, len(payload), 0) + payload)

    # 日期：2026-11-06；恶意进度会使安全通道主动中止；帧间RST/EPIPE仅为候选，截断帧和超时仍失败，不能按任意断开判通过。
    def frame_bytes(self, length, boundary=False):
        result = bytearray()
        while len(result) < length:
            try:
                part = self.socket.recv(length - len(result))
            except (ConnectionResetError, BrokenPipeError) as error:
                if boundary and not result:
                    self.boundary_close = type(error).__name__
                    raise PeerClosed("closed before next frame") from error
                raise AssertionError("truncated frame") from error
            if boundary and not result and not part:
                self.boundary_close = "eof"
                raise PeerClosed("closed before next frame")
            assert part, "truncated frame"
            result.extend(part)
        return bytes(result)

    # 日期：2026-11-06；进度帧独立核对全部十三字段、规范数字和单调性，不吞掉错误或错误序号。
    def receive(self, expected=None):
        while True:
            header = struct.unpack(">8sHHHHQII", self.frame_bytes(32, True))
            assert header[:3] == (b"DKTNEXT1", 1, 0) and header[4] == header[7] == 0
            assert header[5] == self.correlation and 2 <= header[6] <= 262184
            raw = self.frame_bytes(header[6])
            kind = header[3]
            value = raw if kind == 40 else json.loads(raw)
            if kind == 46 and value == {"state": "busy"}:
                continue
            if (kind == 46 and set(value) == {"taskId", "state"}
                    and value["taskId"] == self.task and value["state"] in ("scanning", "queued")):
                continue
            if kind == 50:
                assert set(value) == {"taskId", "manifest", "total", "bytes", "confirmed", "restored", *COUNTERS}
                assert value["taskId"] == self.task and value["manifest"] == self.summary["sha256"]
                assert value["total"] == self.summary["bytes"]
                fields = ["bytes", "confirmed", "restored", *COUNTERS]
                assert all(isinstance(value[k], str) and value[k].isascii() and value[k].isdecimal()
                           and str(int(value[k])) == value[k] for k in fields)
                assert 0 <= int(value["restored"]) <= int(value["confirmed"]) <= int(value["bytes"]) <= int(value["total"])
                if self.snapshots:
                    assert all(int(value[k]) >= int(self.snapshots[-1][k]) for k in fields)
                assert all(value[k] == "0" for k in ["skippedBytes", "discardedBytes", "skippedFiles", "skippedDirectories"])
                self.snapshots.append(value)
                continue
            if kind == 7:
                raise PeerFailure(value)
            assert expected is None or kind == expected, (kind, value)
            return kind, value

    # 日期：2026-11-06；新请求只递增一次序号；清单、正文与最终确认均保持同一传输相关号。
    def begin(self, direction, fields):
        self.correlation += 1
        self.send(32 if direction == "upload" else 33, fields)
        _, task = self.receive(34)
        self.task = task["taskId"]
        return task


# 日期：2026-11-06；只从自有旧模式真实传输读取冻结清单，用于独立对端，不重新实现生产摘要算法。
def frozen_manifest(path):
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        summary = json.loads(db.execute("SELECT value FROM metadata").fetchone()[0])
        entries = [{"id": str(i), "path": name, "type": "directory" if directory else "file",
                    "bytes": str(size), "sha256": sha.hex()}
                   for i, name, directory, size, sha in db.execute("SELECT id,relative,directory,bytes,sha FROM entries ORDER BY id")]
        blocks = {}
        for file, block, size, sha in db.execute("SELECT file,block,bytes,sha FROM blocks ORDER BY file,block"):
            blocks.setdefault(str(file), []).append({"block": str(block), "bytes": str(size), "sha256": sha.hex()})
    return summary, entries, blocks


# 日期：2026-11-06；分页和确认独立发送，106条样本实际跨越100项边界。
def send_manifest(session, entries, blocks):
    pages = [("summary", session.summary)]
    for at in range(0, len(entries), 100):
        group = entries[at:at + 100]
        pages.append(("entries", group))
        for item in group:
            rows = blocks.get(item["id"], [])
            if rows:
                pages.append(("blocks", {"file": item["id"], "rows": rows}))
    pages.append(("seal", session.summary))
    for index, (kind, value) in enumerate(pages):
        session.send(35, {"taskId": session.task, "index": str(index), "kind": kind, "value": value})
        assert session.receive(36)[1] == {"taskId": session.task, "index": str(index)}


# 日期：2026-11-06；下载端逐页核对冻结内容和顺序，不以收到任意清单作为成功。
def receive_manifest(session, entries, blocks):
    seen = []
    seen_blocks = {}
    for index in range(1000):
        _, page = session.receive(35)
        assert page["taskId"] == session.task and page["index"] == str(index)
        kind, value = page["kind"], page["value"]
        if kind in ("summary", "seal"):
            assert value == session.summary
        elif kind == "entries":
            seen.extend(value)
        elif kind == "blocks":
            seen_blocks.setdefault(value["file"], []).extend(value["rows"])
        else:
            raise AssertionError(kind)
        session.send(36, {"taskId": session.task, "index": str(index)})
        if kind == "seal":
            assert seen == entries and seen_blocks == blocks
            return
    raise AssertionError("manifest did not seal")


# 日期：2026-11-06；真实发送跨两个8MiB块、空项和中文路径，逐块等待同步确认。
def send_tree(session, source, entries, blocks):
    for entry in entries:
        identity = {"taskId": session.task, "manifest": session.summary["sha256"], "file": entry["id"]}
        if entry["type"] == "directory":
            session.send(38, {**identity, "kind": "directory"})
            _, result = session.receive(39)
            assert result.keys() == {"taskId", "manifest", "file", "kind", "path"}
            continue
        session.send(38, identity)
        _, result = session.receive(39)
        assert result == {**identity, "block": "0", "bytes": "0"}
        with (source.parent / entry["path"]).open("rb") as data:
            for row in blocks.get(entry["id"], []):
                offset = 0
                while offset < int(row["bytes"]):
                    part = data.read(min(256 * 1024, int(row["bytes"]) - offset))
                    assert part
                    session.send(40, struct.pack(">16sQQII", uuid.UUID(session.task).bytes,
                                                int(entry["id"]), int(row["block"]), offset, len(part)) + part)
                    offset += len(part)
                done = {**identity, "block": row["block"]}
                session.send(41, done)
                assert session.receive(42)[1] == done
        session.send(43, identity)
        _, result = session.receive(44)
        assert result.keys() == {"taskId", "manifest", "file", "path"}


# 日期：2026-11-06；下载样本实际写入同步并独立核对块/全文SHA，按真实处置发送扩展进度。
def receive_tree(session, destination, entries, blocks):
    received = confirmed = copied = files = directories = 0

    # 日期：2026-11-06；只发送固定十三字段，实际同步和最终条目处置分别计量。
    def progress():
        session.send(50, {"taskId": session.task, "manifest": session.summary["sha256"],
            "total": session.summary["bytes"], "bytes": str(received), "confirmed": str(confirmed),
            "restored": "0", "copiedBytes": str(copied), "copiedFiles": str(files),
            "copiedDirectories": str(directories), "skippedBytes": "0", "discardedBytes": "0",
            "skippedFiles": "0", "skippedDirectories": "0"})

    for entry in entries:
        identity = {"taskId": session.task, "manifest": session.summary["sha256"], "file": entry["id"]}
        _, attach = session.receive(38)
        target = destination / entry["path"]
        if entry["type"] == "directory":
            assert attach == {**identity, "kind": "directory"}
            target.mkdir()
            directories += 1
            progress()
            session.send(39, {**attach, "path": entry["path"]})
            continue
        assert attach == identity
        session.send(39, {**identity, "block": "0", "bytes": "0"})
        with target.open("xb") as output:
            for row in blocks.get(entry["id"], []):
                offset = 0
                block_hash = hashlib.sha256()
                while offset < int(row["bytes"]):
                    _, raw = session.receive(40)
                    task, file, block, start, size = struct.unpack(">16sQQII", raw[:40])
                    assert task == uuid.UUID(session.task).bytes and file == int(entry["id"])
                    assert block == int(row["block"]) and start == offset and size == len(raw) - 40
                    output.write(raw[40:])
                    block_hash.update(raw[40:])
                    offset += size
                    received += size
                assert block_hash.hexdigest() == row["sha256"]
                output.flush()
                os.fsync(output.fileno())
                confirmed = received
                done = {**identity, "block": row["block"]}
                assert session.receive(41)[1] == done
                progress()
                session.send(42, done)
        assert session.receive(43)[1] == identity
        assert digest(target) == entry["sha256"]
        copied += int(entry["bytes"])
        files += 1
        progress()
        session.send(44, {**identity, "path": entry["path"]})


# 日期：2026-11-06；查看原生SQLite持久契约和固定快照，任务汇总不能由成功事件代替。
def check_persisted(server, task, entries, summary):
    with closing(sqlite3.connect(f"{(server / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        state, processed, spec, accounting = db.execute(
            "SELECT state,processed,spec,accounting FROM tasks WHERE id=?", (task,)).fetchone()
    spec, accounting = json.loads(spec), json.loads(accounting)
    assert state == "completed" and processed == int(summary["bytes"])
    assert spec["version"] == 3 and spec["progress"] == "disposition-v1"
    assert set(accounting) == {"bytes", "confirmed", "restored", *COUNTERS}
    assert accounting["bytes"] == accounting["confirmed"] == accounting["copiedBytes"] == summary["bytes"]
    assert int(accounting["copiedFiles"]) == sum(e["type"] == "file" for e in entries)
    assert int(accounting["copiedDirectories"]) == sum(e["type"] == "directory" for e in entries)
    assert all(accounting[key] == "0" for key in ["restored", "skippedBytes", "discardedBytes", "skippedFiles", "skippedDirectories"])
    return accounting


# 日期：2026-11-06；真正下载/上传后重连同请求，完成历史必须维持原任务及完整计量。
def case(port, profile, server, shared, root, source, summary, entries, blocks, direction, policy):
    key = direction + "-" + policy
    destination = shared / key if direction == "upload" else root / key
    destination.mkdir()
    fields = {"requestId": str(uuid.uuid4()), "share": "data", "path": key if direction == "upload" else source.name,
              "byteProgress": True, "dispositionSummary": True, "dispositionProgress": True}
    if direction == "upload":
        fields["manifest"] = summary
        if policy in ("rename", "overwrite"):
            shutil.copytree(source, destination / source.name)
            (destination / source.name / "资料/payload.bin").write_bytes(b"original-user-data")
    if policy != "rename":
        fields["conflict"] = policy
    session = AccountingSession(port, profile)
    session.summary = summary
    try:
        initial = session.begin(direction, fields)
        assert initial["accountingVersion"] == 1
        if direction == "upload":
            send_manifest(session, entries, blocks)
        ready = session.receive(34)[1]
        assert ready["state"] == "transferring" and ready["manifestInfo"] == summary
        if direction == "upload":
            send_tree(session, source, entries, blocks)
            assert session.snapshots and session.snapshots[-1]["copiedBytes"] == summary["bytes"]
        else:
            receive_manifest(session, entries, blocks)
            receive_tree(session, destination, entries, blocks)
        _, disposition = session.receive(52)
        session.send(53, disposition)
        result = session.receive(46)[1]
        assert result["state"] == "completed" and result["accountingVersion"] == 1
        verify_summary(result, server / "service" / f"disposition-{session.task}.sqlite")
        task = session.task
    finally:
        session.close()
    accounting = check_persisted(server, task, entries, summary)
    again = AccountingSession(port, profile)
    again.summary = summary
    try:
        initial = again.begin(direction, fields)
        assert initial["taskId"] == task and initial["state"] == "scanning" and not initial["needManifest"]
        result = again.receive(46)[1]
        assert result["taskId"] == task and result["state"] == "completed" and result["confirmationRequired"]
        disposition = again.receive(52)[1]
        again.send(53, disposition)
        assert again.receive(46)[1]["taskId"] == task
    finally:
        again.close()
    assert check_persisted(server, task, entries, summary) == accounting
    downgrade = AccountingSession(port, profile)
    try:
        kind, rejected = downgrade.request(32 if direction == "upload" else 33,
                                           {k: v for k, v in fields.items() if k != "dispositionProgress"})
        assert kind == 7 and rejected["code"] == 6
    finally:
        downgrade.close()
    database = server / "service/tasks.sqlite"
    with closing(sqlite3.connect(database)) as db:
        original = db.execute("SELECT accounting FROM tasks WHERE id=?", (task,)).fetchone()[0]
        changed = json.loads(original)
        changed["copiedFiles"] = str(int(changed["copiedFiles"]) - 1)
        changed["copiedDirectories"] = str(int(changed["copiedDirectories"]) + 1)
        db.execute("UPDATE tasks SET accounting=? WHERE id=?",
                   (json.dumps(changed, separators=(",", ":")).encode("utf-8"), task))
        db.commit()
    ledger = server / "service" / f"disposition-{task}.sqlite"
    before = digest(database), digest(ledger)
    before_bytes = database.read_bytes()
    damaged = AccountingSession(port, profile)
    damaged.summary = summary
    try:
        damaged.begin(direction, fields)
        try:
            damaged.receive(46)
        except PeerFailure as error:
            assert error.value["code"] == 6 and error.value["stage"] == "completion"
        else:
            raise AssertionError("mismatched persistent accounting accepted")
    finally:
        damaged.close()
    after_bytes = database.read_bytes()
    assert before == (digest(database), digest(ledger)), {
        "databaseChangedOffsets": [i for i, (a, b) in enumerate(zip(before_bytes, after_bytes)) if a != b][:64],
        "databaseSizeBeforeAfter": [len(before_bytes), len(after_bytes)], "ledgerUnchanged": before[1] == digest(ledger)}
    with closing(sqlite3.connect(database)) as db:
        db.execute("UPDATE tasks SET accounting=? WHERE id=?", (original, task))
        db.commit()
    assert check_persisted(server, task, entries, summary) == accounting
    return {"direction": direction, "conflict": policy, "entries": len(entries),
            "accountingRequired": True, "persisted": True, "historicalSameTask": True,
            "contractDowngradeRefused": True, "historicalMismatchedCountsRefusedReadOnly": True, "passed": True}


class DamagedProgressSession(AccountingSession):
    # 日期：2026-11-06；每个独立客户机仅攻击首份进度，等待真正的服务端失败帧。
    def __init__(self, port, profile, attack):
        self.attack = attack
        self.injected = False
        super().__init__(port, profile)

    # 日期：2026-11-06；独立构造六字段混用、畸形数字、额外字段和错误身份，不更改生产校验器。
    def send(self, kind, value):
        if kind == 50 and not self.injected:
            value = dict(value)
            self.injected = True
            if self.attack == "six-fields":
                for key in COUNTERS:
                    value.pop(key)
            elif self.attack == "extra":
                value["unknown"] = "0"
            elif self.attack == "numeric-type":
                value["bytes"] = 0
            elif self.attack == "leading-zero":
                value["bytes"] = "00"
            elif self.attack == "task":
                value["taskId"] = str(uuid.uuid4())
            elif self.attack == "manifest":
                value["manifest"] = "0" * 64
            elif self.attack == "unconfirmed-copied":
                value["copiedBytes"] = "1"
            elif self.attack == "skip-in-copied-policy":
                value["skippedDirectories"] = "1"
            else:
                raise AssertionError(self.attack)
        super().send(kind, value)


# 日期：2026-11-06；畸形首份进度不得写入快照；分别核对协议数字错误2和计量错误6及真实服务事件。
def progress_attacks(port, profile, server, service, root, source, summary, entries, blocks):
    cases = []
    for attack in ["six-fields", "extra", "numeric-type", "leading-zero", "task", "manifest",
                   "unconfirmed-copied", "skip-in-copied-policy"]:
        output = root / ("attack-" + attack)
        output.mkdir()
        fields = {"requestId": str(uuid.uuid4()), "share": "data", "path": source.name,
                  "byteProgress": True, "dispositionSummary": True, "dispositionProgress": True}
        expected_code = 2 if attack in ("numeric-type", "leading-zero") else 6
        expected_state = "interrupted" if expected_code == 2 else "failed"
        closed_events = service.output_drain.events["service-connection-closed"]
        session = DamagedProgressSession(port, profile, attack)
        session.summary = summary
        try:
            session.begin("download", fields)
            assert session.receive(34)[1]["state"] == "transferring"
            receive_manifest(session, entries, blocks)
            try:
                receive_tree(session, output, entries, blocks)
                session.receive(52)
            except PeerFailure as error:
                assert error.value["code"] == expected_code
            except PeerClosed:
                # 日期：2026-11-06；协议解析边界可主动中止，随后必须独立验证原任务拒绝状态、服务错误事件及零快照。
                pass
            else:
                raise AssertionError("malformed progress accepted: " + attack)
            assert session.injected
            task = session.task
        finally:
            session.close()
        deadline = time.monotonic() + 5
        while True:
            with closing(sqlite3.connect(f"{(server / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as db:
                state, processed, error, accounting = db.execute(
                    "SELECT state,processed,error,accounting FROM tasks WHERE id=?", (task,)).fetchone()
            events = list(service.output_drain.recent)
            event_verified = (service.output_drain.events["service-connection-closed"] > closed_events
                              and any(e.get("event") == "service-connection-closed" and e.get("code") == expected_code for e in events))
            if (state == expected_state and event_verified) or time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert state == expected_state and processed == 0 and error == (6 if expected_code == 6 else 0), (attack, state, processed, error)
        assert event_verified and service.poll() is None
        assert set(json.loads(accounting).values()) == {"0"}
        cases.append({"attack": attack, "refused": True, "code": expected_code, "state": state,
                      "serviceEventVerified": True, "zeroSnapshotUnchanged": True,
                      "boundaryClose": session.boundary_close, "passed": True})
        print(json.dumps(cases[-1]), flush=True)
    return cases


# 日期：2026-11-06；拒绝未协商/错误模式/缺依赖/额外字段且不建任务，未协商skip仍拒绝。
def negotiation(port, profile, server, path):
    cases = []
    base = {"share": "data", "path": path, "byteProgress": True, "dispositionSummary": True,
            "dispositionProgress": True}
    variants = [(False, {}), (True, {"dispositionProgress": False}), (True, {"dispositionProgress": "true"}),
                (True, {"byteProgress": None}), (True, {"dispositionSummary": None}),
                (True, {"unknown": True}), (True, {"conflict": "skip"})]
    with closing(sqlite3.connect(f"{(server / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        before = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    for negotiated, extra in variants:
        fields = {**base, **extra, "requestId": str(uuid.uuid4())}
        fields = {k: v for k, v in fields.items() if v is not None}
        session = AccountingSession(port, profile, negotiated)
        try:
            kind, result = session.request(33, fields)
            assert kind == 7 and result["code"] == 2
        finally:
            session.close()
        cases.append({"negotiated": negotiated, "changes": extra, "refused": True})
    with closing(sqlite3.connect(f"{(server / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        assert db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == before
    return cases


# 日期：2026-11-06；真实客户端基线启用必需计量，独立TLS对端另核服务端契约及攻击。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    assert not args.report.exists()
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-service-accounting-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared, source = [root / name for name in ["server", "client", "shared", "计量目录"]]
        shared.mkdir()
        (source / "资料/空目录").mkdir(parents=True)
        (source / "资料/空文件").touch()
        (source / "资料/payload.bin").write_bytes(bytes(range(251)) * 33422 + b"tail")
        for i in range(101):
            (source / f"item-{i:03}.bin").write_bytes(bytes([i]) * (i + 1))
        shutil.copytree(source, shared / source.name)
        (shared / "baseline").mkdir()
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
            baseline = transfer(executable, client, ["upload", "--share", "data", "--path", str(source), "--remote-path", "baseline"])
            assert baseline["accountingVersion"] == 1
            summary, entries, blocks = frozen_manifest(server / "service" / f"manifest-{baseline['taskId']}.sqlite")
            assert len(entries) == 106 and int(summary["bytes"]) > 8 * 1024 * 1024
            refused = negotiation(port, profile, server, source.name)
            for direction in ["upload", "download"]:
                for policy in ["rename", "fail", "overwrite"]:
                    value = case(port, profile, server, shared, root, source, summary, entries, blocks, direction, policy)
                    cases.append(value)
                    print(json.dumps(value), flush=True)
            attacks = progress_attacks(port, profile, server, service, root, source, summary, entries, blocks)
        finally:
            service.kill()
            service.wait(timeout=10)
            service.output_drain.finish()
            assert not service.stderr.read()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"date": "2026-11-06", "passed": True, "cases": cases,
        "negotiation": refused, "progressAttacks": attacks,
        "ordinaryClientRequiredAccounting": True, "publicSkipEnabled": True,
        "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
        "scope": "single TLS independent client; service required accounting and historical replay"},
        ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()

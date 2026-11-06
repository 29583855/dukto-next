"""日期：2026-11-06；真实客户端必需计量、持久契约、旧请求兼容及独立TLS中继攻击验证。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid

from conflict_fail_integration import start
from disposition_summary_integration import Relay, read_frame, write_frame, verify_summary
from service_integration import free_port, run
from transfer_integration import digest, transfer

COUNTERS = ["copiedBytes", "skippedBytes", "discardedBytes", "copiedFiles",
            "copiedDirectories", "skippedFiles", "skippedDirectories"]


class AccountingRelay(Relay):
    # 日期：2026-11-06；最多保存一份创建请求和固定进度计数，TLS身份由测试自有服务提供。
    def __init__(self, *args):
        self.created = None
        self.progress_frames = 0
        self.contracts = 0
        super().__init__(*args)

    # 日期：2026-11-06；独立帧编码器只改指定契约/快照边界，正文原字节转发，不调用生产校验器。
    def forward(self, source, destination, side):
        frame = read_frame(source)
        if frame is None:
            return False
        header, payload = frame
        kind = header[3]
        value = None if kind == 40 else json.loads(payload)
        if kind == 2 and self.attack.startswith("hide-"):
            hidden = {"hide-progress": "disposition-progress-v1",
                      "hide-summary": "disposition-summary-v1", "hide-byte": "byte-progress-v1"}[self.attack]
            value["capabilities"].remove(hidden)
            self.hit += 1
        if kind in (32, 33):
            assert self.created is None
            self.created = value
        if kind == 50:
            self.progress_frames += 1
            if self.created.get("dispositionProgress") is True:
                assert len(value) == 13 and set(COUNTERS) <= value.keys()
            else:
                assert len(value) == 6 and not set(COUNTERS) & value.keys()
            if self.attack == "progress-six-fields" and side == "summary" and self.hit == 0:
                for key in COUNTERS:
                    value.pop(key)
                self.hit += 1
        if kind in (34, 46) and value.get("accountingVersion") == 1:
            self.contracts += 1
            initial = kind == 34 and value["state"] in ("queued", "scanning")
            ready = kind == 34 and value["state"] == "transferring"
            final = kind == 46 and value.get("dispositionConfirmed") is True
            if self.hit == 0 and ((self.attack == "initial-contract" and initial)
                                  or (self.attack == "ready-contract" and ready)):
                value.pop("accountingVersion")
                self.hit += 1
            if final and self.attack.startswith("final-"):
                self.hit += 1
                if self.attack == "final-missing-version":
                    value.pop("accountingVersion")
                elif self.attack == "final-classification":
                    value["copiedFiles"] = str(int(value["copiedFiles"]) - 1)
                    value["copiedDirectories"] = str(int(value["copiedDirectories"]) + 1)
                elif self.attack == "final-restored":
                    assert value["restoredBytes"] == "0"
                    value["restoredBytes"] = "1"
                elif self.attack == "final-missing-counter":
                    value.pop("copiedBytes")
                else:
                    raise AssertionError(self.attack)
        if value is not None:
            payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        write_frame(destination, header, payload)
        return True


# 日期：2026-11-06；经独立TLS中继执行真实命令，修改的资料端口仅在本次作用域内保存后恢复。
def relayed(executable, root, server, client, identity, profile, port, operation, attack, expected):
    relay = AccountingRelay(root, identity, port, profile["fingerprint"],
                            server / "service/tasks.sqlite", attack, "summary")
    profile_path = client / "clients/profile-default.json"
    saved = profile_path.read_bytes()
    try:
        profile_path.write_text(json.dumps({**profile, "port": str(relay.port)}), "utf-8")
        result = transfer(executable, client, operation, expected)
    finally:
        profile_path.write_bytes(saved)
        relay.close()
    return result, relay


# 日期：2026-11-06；只读原任务行及数据库摘要，验证完成重试/能力降级拒绝不改写原件。
def history(server, task):
    path = server / "service/tasks.sqlite"
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        row = db.execute("SELECT state,revision,processed,error,spec,accounting FROM tasks WHERE id=?", (task,)).fetchone()
    return row, digest(path)


# 日期：2026-11-06；从两份独立数据库计算清单计数、最终计量及处置SHA，禁止只依赖CLI成功事件。
def verify(executable, server, client, result, direction, policy):
    task, request = result["taskId"], result["requestId"]
    row, _ = history(server, task)
    state, _, processed, error, raw_spec, raw_snapshot = row
    spec, snapshot = json.loads(raw_spec), json.loads(raw_snapshot)
    assert state == "completed" and error == 0 and spec["version"] == 3
    assert spec["progress"] == "disposition-v1" and spec["conflict"] == policy
    with closing(sqlite3.connect(f"{(server / 'service' / f'manifest-{task}.sqlite').as_uri()}?mode=ro", uri=True)) as db:
        files, directories, total = db.execute(
            "SELECT SUM(directory=0),SUM(directory=1),SUM(bytes) FROM entries").fetchone()
    assert int(snapshot["copiedFiles"]) == files and int(snapshot["copiedDirectories"]) == directories
    assert snapshot["bytes"] == snapshot["confirmed"] == snapshot["copiedBytes"] == str(total)
    assert processed == total and set(snapshot) == {"bytes", "confirmed", "restored", *COUNTERS}
    assert result["accountingVersion"] == 1 and result["bytes"] == str(total)
    assert all(snapshot[k] == "0" for k in ["skippedBytes", "discardedBytes", "skippedFiles", "skippedDirectories"])
    verify_summary(result, server / "service" / f"disposition-{task}.sqlite")
    prefix = "upload" if direction == "upload" else "download"
    binding = json.loads((client / "transfers" / f"{prefix}-request-{request}.json").read_bytes())
    assert binding["version"] == 3 and binding["progress"] == "disposition-v1" and binding["conflict"] == policy
    count, after = 0, 0
    while True:
        page, _ = run(executable, client, ["task-items", "--task", task, "--after", str(after)])
        assert page["available"] and not page["currentContentVerified"]
        assert all(e["disposition"] == "copied" and e["confirmedBytes"] == e["bytes"] for e in page["entries"])
        count += len(page["entries"])
        after = int(page["after"])
        if not page["more"]:
            break
    assert count == files + directories == 106
    return {"entries": count, "files": files, "directories": directories, "bytes": total,
            "taskVersion": 3, "bindingVersion": 3, "itemsVerified": True}


# 日期：2026-11-06；三策略按1/4/16通道双向传输，历史拒绝前后冻结任务库及处置库原字节。
def real_case(executable, root, server, client, shared, identity, profile, port, source, direction, policy, channels):
    key = f"{direction}-{policy}-{channels}"
    destination = shared / key if direction == "upload" else root / key
    destination.mkdir()
    if policy != "fail":
        shutil.copytree(source, destination / source.name)
        (destination / source.name / "资料/payload.bin").write_bytes(b"existing independent data")
    operation = [direction, "--share", "data", "--threads", str(channels), "--on-conflict", policy,
                 "--request-id", str(uuid.uuid4())]
    operation += (["--path", str(source), "--remote-path", key] if direction == "upload" else
                  ["--remote-path", source.name, "--output", str(destination)])
    result = transfer(executable, client, operation)
    proof = verify(executable, server, client, result, direction, policy)
    original = history(server, result["taskId"])
    assert transfer(executable, client, operation)["taskId"] == result["taskId"]
    assert history(server, result["taskId"]) == original
    for attack in ["hide-progress", "hide-summary", "hide-byte"]:
        error, relay = relayed(executable, root, server, client, identity, profile, port, operation, attack, 2)
        assert error["stage"] == "progress" and relay.hit == 1 and relay.created is None
        assert history(server, result["taskId"]) == original
    binding_path = client / "transfers" / f"{direction}-request-{result['requestId']}.json"
    saved = binding_path.read_bytes()
    binding = json.loads(saved)
    binding["progress"] = "unknown"
    binding_path.write_text(json.dumps(binding), "utf-8")
    try:
        assert transfer(executable, client, operation, 6)["stage"] == ("disposition" if direction == "upload" else "transfer")
        assert history(server, result["taskId"]) == original
    finally:
        binding_path.write_bytes(saved)
    return dict(proof, direction=direction, conflict=policy, channels=channels,
                contractDowngradeRefusedBeforeCreate=True, malformedBindingRefused=True, historicalReadOnly=True)


# 日期：2026-11-06；新客户端首次遇旧能力创建旧请求，重连新能力后仍用原请求格式并保留派生恢复。
def legacy_case(executable, root, server, client, shared, identity, profile, port, source, direction):
    key = "legacy-" + direction
    destination = shared / key if direction == "upload" else root / key
    destination.mkdir()
    operation = [direction, "--share", "data", "--request-id", str(uuid.uuid4())]
    operation += (["--path", str(source), "--remote-path", key] if direction == "upload" else
                  ["--remote-path", source.name, "--output", str(destination)])
    # 日期：2026-11-06；旧契约复用106项真实目录，验证升级后的同请求重试及派生日志恢复。
    result, relay = relayed(executable, root, server, client, identity, profile, port, operation, "hide-progress", 0)
    assert "accountingVersion" not in result and "dispositionProgress" not in relay.created
    binding_path = client / "transfers" / f"{direction}-request-{result['requestId']}.json"
    binding_bytes = binding_path.read_bytes()
    assert json.loads(binding_bytes)["version"] == 1
    if direction == "download":
        ledger = client / "transfers" / f"disposition-{result['taskId']}.sqlite"
        ledger.rename(ledger.with_suffix(".saved"))
    repeated = transfer(executable, client, operation)
    assert repeated["taskId"] == result["taskId"] and "accountingVersion" not in repeated
    assert binding_path.read_bytes() == binding_bytes
    if direction == "download":
        assert ledger.is_file()
        with closing(sqlite3.connect(f"{ledger.as_uri()}?mode=ro", uri=True)) as rebuilt, closing(
                sqlite3.connect(f"{ledger.with_suffix('.saved').as_uri()}?mode=ro", uri=True)) as original:
            assert rebuilt.execute("SELECT spec FROM binding").fetchall() == original.execute("SELECT spec FROM binding").fetchall()
            assert rebuilt.execute("SELECT id,spec FROM items ORDER BY id").fetchall() == original.execute("SELECT id,spec FROM items ORDER BY id").fetchall()
        verify_summary(repeated, ledger)
    return {"direction": direction, "oldBindingRetained": True, "sameTaskAfterUpgrade": True,
            "legacyDerivedRecoveryVerified": direction == "download"}


# 日期：2026-11-06；真实新传输攻击初始/就绪/最终快照，末帧计量必须符合实际进度及本机处置。
def attacks(executable, root, server, client, shared, identity, profile, port, source):
    cases = []
    for direction in ["upload", "download"]:
        names = ["initial-contract", "ready-contract", "final-missing-version", "final-classification",
                 "final-missing-counter", "final-restored"]
        if direction == "upload":
            names.append("progress-six-fields")
        for attack in names:
            key = "attack-" + direction + "-" + attack
            destination = shared / key if direction == "upload" else root / key
            destination.mkdir()
            operation = [direction, "--share", "data", "--request-id", str(uuid.uuid4()), "--timeout", "5"]
            operation += (["--path", str(source), "--remote-path", key] if direction == "upload" else
                          ["--remote-path", source.name, "--output", str(destination)])
            expected = 6
            error, relay = relayed(executable, root, server, client, identity, profile, port, operation, attack, expected)
            assert relay.hit == 1 and relay.created["dispositionProgress"] is True
            if attack.startswith("final-"):
                with closing(sqlite3.connect(f"{(server / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as db:
                    task, state = db.execute("SELECT id,state FROM tasks WHERE request=?",
                        (operation[operation.index("--request-id") + 1],)).fetchone()
                assert state == "completed" and relay.progress_frames > 0
                result = transfer(executable, client, operation)
                assert result["taskId"] == task
            cases.append({"direction": direction, "attack": attack, "code": error["code"],
                          "refused": True, "sameTaskRecovery": attack.startswith("final-")})
            print(json.dumps(cases[-1]), flush=True)
    return cases


# 日期：2026-11-06；每例独立请求/目录，服务日志有界消费，原件固定脚本和实际二进制摘要。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    assert not args.report.exists()
    cases, legacy = [], []
    with tempfile.TemporaryDirectory(prefix="dukto-client-accounting-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared, source = [root / n for n in ["server", "client", "shared", "计量目录"]]
        shared.mkdir()
        (source / "资料/空目录").mkdir(parents=True)
        (source / "资料/空文件").touch()
        (source / "资料/payload.bin").write_bytes(bytes(range(251)) * 33422 + b"tail")
        for i in range(101):
            (source / f"item-{i:03}.bin").write_bytes(bytes([i]) * (i + 1))
        shutil.copytree(source, shared / source.name)
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
            for direction in ["upload", "download"]:
                for policy, channels in [("rename", 1), ("fail", 4), ("overwrite", 16)]:
                    value = real_case(executable, root, server, client, shared, identity, profile, port,
                                      source, direction, policy, channels)
                    cases.append(value)
                    print(json.dumps(value), flush=True)
            for direction in ["upload", "download"]:
                legacy.append(legacy_case(executable, root, server, client, shared, identity, profile, port, source, direction))
            refused = attacks(executable, root, server, client, shared, identity, profile, port, source)
        finally:
            service.kill()
            service.wait(timeout=10)
            service.output_drain.finish()
            assert not service.stderr.read()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"date": "2026-11-06", "passed": True, "cases": cases,
        "legacyCompatibility": legacy, "attacks": refused, "publicSkipEnabled": False,
        "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
        "scope": "production client mandatory accounting; persisted request binding; independent owned TLS relay mutations"},
        ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()

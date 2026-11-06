"""日期：2026-11-06；自有TLS中继逐帧攻击摘要/确认，验证普通提交边界与历史确认重试。"""

import argparse
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import select
import socket
import sqlite3
import ssl
import struct
import tempfile
import threading
import time
import uuid

from conflict_fail_integration import start
from credential_rotation_integration import IndependentSession
from service_integration import free_port, run
from transfer_integration import digest, transfer


class FrameBoundaryReset(ConnectionResetError):
    """日期：2026-11-06；仅表示尚未读取下一帧任何字节时收到RST，不能代表业务成功。"""


# 日期：2026-11-06；独立读取固定报头及有界正文；结束不把截断帧当作成功。
def read_frame(connection):
    def exact(size, eof=False):
        data = bytearray()
        while len(data) < size:
            try:
                part = connection.recv(size - len(data))
            except ConnectionResetError as error:
                if eof and not data:
                    raise FrameBoundaryReset("reset before next frame") from error
                raise AssertionError("reset within relay frame") from error
            if not part and eof and not data:
                return None
            assert part, "truncated relay frame"
            data.extend(part)
        return bytes(data)
    raw = exact(32, True)
    if raw is None:
        return None
    header = list(struct.unpack(">8sHHHHQII", raw))
    assert header[:3] == [b"DKTNEXT1", 1, 0] and header[4] == header[7] == 0
    assert 2 <= header[6] <= 262184
    return header, exact(header[6])


# 日期：2026-11-06；测试编码与生产库独立，不重用应用协议或摘要计算器。
def write_frame(connection, header, payload):
    header = list(header)
    header[6] = len(payload)
    connection.sendall(struct.pack(">8sHHHHQII", *header) + payload)


# 日期：2026-11-06；仅从测试自有日志逐条核对长度前缀哈希、类型、字节及全部统计字段。
def verify_summary(result, ledger):
    summary = result["dispositionSummary"]
    assert result["dispositionConfirmed"] is True and "confirmationRequired" not in result
    with closing(sqlite3.connect(f"{ledger.as_uri()}?mode=ro", uri=True)) as database:
        binding, = database.execute("SELECT spec FROM binding").fetchone()
        rows = database.execute("SELECT spec FROM items ORDER BY id").fetchall()
    h = hashlib.sha256()
    files = directories = size = 0
    for raw in [binding, *(row[0] for row in rows)]:
        h.update(struct.pack(">I", len(raw)))
        h.update(raw)
    for raw, in rows:
        item = json.loads(raw)
        assert item["disposition"] == "copied"
        files += item["entry"]["type"] == "file"
        directories += item["entry"]["type"] == "directory"
        size += int(item["entry"]["bytes"])
    binding = json.loads(binding)
    expected = {"version": 1, "taskId": result["taskId"], "manifest": binding["manifest"]["sha256"],
                "conflict": binding["conflict"], "complete": True, "totalEntries": str(len(rows)),
                "processedEntries": str(len(rows)), "unexecutedEntries": "0", "copiedEntries": str(len(rows)),
                "skippedEntries": "0", "copiedFiles": str(files), "copiedDirectories": str(directories),
                "skippedFiles": "0", "skippedDirectories": "0", "copiedBytes": str(size),
                "skippedBytes": "0", "totalBytes": str(size), "sha256": h.hexdigest()}
    assert summary == expected, (summary, expected)
    return summary


# 日期：2026-11-06；每个字段仅改变一个条件，真假、类型和附加字段都必须参与核对。
def changed(summary, attack):
    value = copy.deepcopy(summary)
    if attack == "missing":
        del value["copiedBytes"]
    elif attack == "extra":
        value["unknown"] = True
    elif attack == "numeric-type":
        value["copiedBytes"] = int(value["copiedBytes"])
    elif attack in ("complete",):
        value[attack] = False
    elif attack == "version":
        value[attack] = 2
    elif attack == "taskId":
        value[attack] = str(uuid.uuid4())
    elif attack in ("sha256", "manifest"):
        value[attack] = "00" * 32
    elif attack == "conflict":
        value[attack] = "fail"
    else:
        value[attack] = str(int(value[attack]) + 1)
    return value


class Relay:
    # 日期：2026-11-06；只监听回环并使用测试自有身份；数据连接限制单通道，密钥和正文不写报告。
    def __init__(self, root, identity, target, fingerprint, database, attack, side):
        self.attack, self.side, self.database = attack, side, database
        self.hit = self.acks = 0
        self.state_at_ack = None
        self.error = None
        self.boundary_reset = None
        self.stopped = threading.Event()
        self.sockets = []
        certificate, key = root / "relay.crt", root / "relay.key"
        certificate.write_text(identity["certificate"], encoding="ascii")
        key.write_text(identity["privateKey"], encoding="ascii")
        key.chmod(0o600)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(str(certificate), str(key))
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(10)
        self.port = self.listener.getsockname()[1]
        self.target, self.fingerprint = target, fingerprint
        self.worker = threading.Thread(target=self.serve, daemon=True)
        self.worker.start()

    # 日期：2026-11-06；TLS两端都为测试所有，仍核对上游指纹，避免误连其他服务。
    def serve(self):
        try:
            raw, _ = self.listener.accept()
            downstream = self.context.wrap_socket(raw, server_side=True)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            upstream = context.wrap_socket(socket.create_connection(("127.0.0.1", self.target), timeout=10),
                                           server_hostname="127.0.0.1")
            assert hashlib.sha256(upstream.getpeercert(binary_form=True)).hexdigest() == self.fingerprint
            self.sockets = [downstream, upstream]
            for connection in self.sockets:
                connection.settimeout(15)
            # 日期：2026-11-06；同一线程交替读写TLS对象，避免Python/OpenSSL并发访问同一会话。
            while not self.stopped.is_set():
                readable = [connection for connection in self.sockets if connection.pending()]
                if not readable:
                    readable, _, _ = select.select(self.sockets, [], [], 15)
                assert readable, "relay idle deadline"
                for source in readable:
                    destination = upstream if source is downstream else downstream
                    if not self.forward(source, destination, "ack" if source is downstream else "summary"):
                        return
        except FrameBoundaryReset:
            # 日期：2026-11-06；只把已命中拒绝攻击后的帧间RST列为候选，调用者必须验证退出及持久结果。
            if self.hit == 1 and self.attack not in ("valid", "busy", "legacy", "drop"):
                self.boundary_reset = {"side": "ack" if source is downstream else "summary",
                                       "operation": "read-next-header", "partialFrameBytes": 0,
                                       "attackHit": self.hit}
            elif not self.stopped.is_set():
                self.error = "UnexpectedFrameBoundaryReset"
        except Exception as error:
            if not self.stopped.is_set():
                self.error = type(error).__name__
        finally:
            self.stopped.set()
            for connection in self.sockets:
                connection.close()

    # 日期：2026-11-06；最多持有一帧；只更改指定确认边界，原正文和其他帧逐字节转发。
    def forward(self, source, destination, side):
        frame = read_frame(source)
        if frame is None:
            return False
        header, payload = frame
        kind = header[3]
        if self.attack == "legacy" and kind == 2:
            value = json.loads(payload)
            value["capabilities"].remove("disposition-summary-v1")
            payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.hit += 1
        if self.attack == "legacy" and kind in (32, 33):
            assert "dispositionSummary" not in json.loads(payload)
        if kind == 53:
            self.acks += 1
            task = json.loads(payload)["taskId"]
            with closing(sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True)) as database:
                self.state_at_ack, = database.execute("SELECT state FROM tasks WHERE id=?", (task,)).fetchone()
        target = kind == (52 if side == "summary" else 53)
        final = side == "summary" and kind == 46 and json.loads(payload).get("dispositionConfirmed") is True
        if self.side == side and (target or (final and self.attack.startswith("final-"))):
            if not self.attack.startswith("final-") or final:
                self.hit += 1
                value = json.loads(payload)
                if self.attack == "drop":
                    return False
                if self.attack == "busy":
                    # 日期：2026-11-06；忙帧不表示确认，必须等后续真实Ack才可提交。
                    write_frame(destination, [*header[:3], 46, *header[4:]], b'{"state":"busy"}')
                    time.sleep(0.3)
                elif self.attack == "wrong-correlation":
                    header[5] += 1
                elif self.attack == "wrong-type":
                    header[3] = 53 if side == "summary" else 52
                elif self.attack == "final-false":
                    value["dispositionConfirmed"] = False
                elif self.attack == "final-summary":
                    value["dispositionSummary"]["sha256"] = "00" * 32
                elif self.attack != "valid":
                    value = changed(value, self.attack)
                payload = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        write_frame(destination, header, payload)
        return True

    # 日期：2026-11-06；严格回收单个转发线程和测试连接，错误不能被后台异常吞掉。
    def close(self):
        self.worker.join(25)
        self.listener.close()
        assert not self.worker.is_alive() and self.error is None, self.error


# 日期：2026-11-06；对实际CLI/服务的摘要和Ack分别攻击，独立核对持久任务边界和原目标。
def case(executable, root, server, client, shared, identity, profile_path, profile, port,
         direction, attack, side, historical):
    key = f"{direction}-{side}-{attack}-{'history' if historical else 'normal'}"
    source = root / (key + ".bin")
    source.write_bytes(b"summary-body" * 137)
    destination = shared / key if direction == "upload" else root / key
    destination.mkdir()
    if direction == "download":
        (shared / source.name).write_bytes(source.read_bytes())
    arguments = [direction, "--share", "data", "--threads", "1", "--request-id", str(uuid.uuid4()),
                 "--timeout", "5"]
    arguments += (["--path", str(source), "--remote-path", key] if direction == "upload" else
                  ["--remote-path", source.name, "--output", str(destination)])
    original = None
    if historical:
        original = transfer(executable, client, arguments)
        ledger = server / "service" / f"disposition-{original['taskId']}.sqlite"
        verify_summary(original, ledger)
    relay = Relay(root, identity, port, profile["fingerprint"], server / "service/tasks.sqlite", attack, side)
    saved = profile_path.read_bytes()
    try:
        profile_path.write_text(json.dumps({**profile, "port": str(relay.port)}), encoding="utf-8")
        expected = (0 if attack in ("valid", "busy", "legacy") else 3 if attack == "drop" else
                    2 if attack in ("wrong-correlation", "wrong-type") and side == "summary" else 6)
        result = transfer(executable, client, arguments, expected)
    finally:
        profile_path.write_bytes(saved)
        relay.close()
    assert relay.hit == 1, (key, relay.hit)
    deadline = time.monotonic() + 5
    while True:
        with closing(sqlite3.connect(f"{(server / 'service/tasks.sqlite').as_uri()}?mode=ro", uri=True)) as database:
            task, state, error = database.execute("SELECT id,state,error FROM tasks WHERE request=?",
                                                 (arguments[arguments.index("--request-id") + 1],)).fetchone()
        if state != "verifying" or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    target = destination / source.name
    assert digest(target) == digest(source)
    if expected == 0:
        assert state == "completed"
        if attack == "legacy":
            assert relay.acks == 0 and "dispositionConfirmed" not in result
        else:
            assert relay.acks == 1
            verify_summary(result, server / "service" / f"disposition-{task}.sqlite")
    elif historical or attack.startswith("final-"):
        assert state == "completed" and error == 0
    elif side == "ack" and attack != "drop":
        assert state == "failed" and error == 6
    else:
        assert state == "interrupted", (key, state, error)
    if relay.acks and not historical:
        assert relay.state_at_ack == "verifying", (key, relay.state_at_ack)
    if side == "summary" and expected != 0 and not attack.startswith("final-"):
        assert relay.acks == 0
    if state in ("interrupted", "completed"):
        retry = transfer(executable, client, arguments)
        assert retry["taskId"] == task
        verify_summary(retry, server / "service" / f"disposition-{task}.sqlite")
        assert [entry.name for entry in destination.iterdir()] == [source.name]
    return {"direction": direction, "attack": attack, "side": side, "historical": historical,
            "clientExitCode": expected, "taskState": state, "taskError": error,
            "acksForwardedOrIntercepted": relay.acks, "stateAtAck": relay.state_at_ack,
            "bodyIntact": True, "sameTaskRetryVerified": state in ("interrupted", "completed"),
            "transportBoundaryReset": relay.boundary_reset,
            "rejectionStateVerified": expected != 0}


class WireSession(IndependentSession):
    # 日期：2026-11-06；独立旧客户端可选择声明新能力，创建字段不能替代Hello协商。
    def __init__(self, port, profile, negotiated):
        self.negotiated = negotiated
        super().__init__(port, profile)

    # 日期：2026-11-06；只在Hello注入本测试选择，其他消息沿独立编码器发送。
    def request(self, kind, value):
        if kind == 1 and self.negotiated:
            value = {**value, "capabilities": [*value["capabilities"], "disposition-summary-v1"]}
        return super().request(kind, value)


# 日期：2026-11-06；能力未声明、非true及未知创建字段必须在建任务/正文前拒绝。
def negotiation_cases(port, profile):
    cases = []
    for negotiated, extra in ((False, {"dispositionSummary": True}),
                              (True, {"dispositionSummary": False}),
                              (True, {"dispositionSummary": "true"}),
                              (True, {"dispositionSummary": True, "unknown": True})):
        session = WireSession(port, profile, negotiated)
        try:
            kind, result = session.request(33, {"requestId": str(uuid.uuid4()), "share": "data",
                                                "path": "missing.bin", **extra})
            assert kind == 7 and result["code"] == 2
            cases.append({"negotiated": negotiated, "fields": extra, "refusedBeforeTransfer": True})
        finally:
            session.close()
    return cases


# 日期：2026-11-06；运行真实服务和独立协议中继，全部原报告绑定精确CLI与脚本摘要。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    assert not args.report.exists()
    cases = []
    negotiations = []
    with tempfile.TemporaryDirectory(prefix="dukto-peer-summary-") as temporary:
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
            identity = json.loads((server / "service/identity.json").read_bytes())
            profile_path = client / "clients/profile-default.json"
            profile = json.loads(profile_path.read_bytes())
            negotiations = negotiation_cases(port, profile)
            fields = ["version", "taskId", "manifest", "conflict", "complete", "totalEntries", "processedEntries",
                      "unexecutedEntries", "copiedEntries", "skippedEntries", "copiedFiles", "copiedDirectories",
                      "skippedFiles", "skippedDirectories", "copiedBytes", "skippedBytes", "totalBytes", "sha256"]
            for direction in ("upload", "download"):
                scenarios = [(attack, "summary", False) for attack in
                             [*fields, "missing", "extra", "numeric-type", "wrong-type", "wrong-correlation",
                              "final-false", "final-summary", "valid", "busy", "legacy"]]
                scenarios += [(attack, "ack", False) for attack in ("sha256", "missing", "wrong-type", "drop", "busy")]
                scenarios += [(attack, side, True) for side in ("summary", "ack")
                              for attack in ("sha256", "missing", "drop", "valid")]
                for attack, side, historical in scenarios:
                    value = case(executable, root, server, client, shared, identity, profile_path, profile, port,
                                 direction, attack, side, historical)
                    cases.append(value)
                    print(json.dumps(value), flush=True)
        finally:
            service.kill()
            service.wait(timeout=10)
            service.output_drain.finish()
            assert not service.stderr.read()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"date": "2026-11-06", "passed": True, "cases": cases,
                                      "negotiation": negotiations,
                                      "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
                                      "scope": "single-channel owned TLS relay attacks; 1/4/16 ordinary flows in disposition-transfer",
                                      "publicSkipEnabled": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

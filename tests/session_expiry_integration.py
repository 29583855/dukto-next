"""日期：2026-11-05；真实 TLS 会话截止、策略隔离、多通道正文中途到期和原任务恢复。"""

import argparse
from collections import Counter, deque
from contextlib import closing
import hashlib
import json
from pathlib import Path
import queue
import shutil
import socket
import sqlite3
import ssl
import stat
import struct
import subprocess
import tempfile
import threading
import time
import uuid

from credential_rotation_integration import IndependentSession
from process_output import JsonOutputDrain, timeout_evidence
from proxy_pacing import ProxyPacer
from service_integration import free_port, run
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_state


class TimedTransfer(TransferProcess):
    # 日期：2026-11-05；只保留固定数量时间点与最近事件，用于区分准备、正文接收和检查点耗时。
    def __init__(self, executable, state, arguments):
        self.started = time.monotonic()
        self.milestones = {}
        self.recent = deque(maxlen=16)
        self.counts = Counter()
        self.received = 0
        self.durable = 0
        super().__init__(executable, state, arguments)

    # 日期：2026-11-05；仍将全部事件交给原断言队列，诊断不改变应用、时限或传输状态。
    def read(self):
        for line in self.process.stdout:
            event = json.loads(line)
            elapsed = round(time.monotonic() - self.started, 3)
            key = event.get("event", "")
            self.counts[key] += 1
            self.recent.append({"seconds": elapsed, "event": event})
            if key == "transfer-state" and event.get("state") in ("queued", "scanning", "checking", "transferring"):
                self.milestones.setdefault(event["state"], elapsed)
            if key == "byte-progress":
                self.received = max(self.received, int(event.get("receivedBytes", "0")))
                self.durable = max(self.durable, int(event.get("bytes", "0")))
                if self.received:
                    self.milestones.setdefault("firstReceivedBytes", elapsed)
                if self.durable:
                    self.milestones.setdefault("firstDurableBytes", elapsed)
            self.events.put(event)
        self.events.put(None)

    # 日期：2026-11-05；结束后取得小型诊断，不把网络发送量当作持久复用量。
    def evidence(self):
        return {"timingBasis": "client event observation; upload single-channel progress may be read at block acknowledgement",
                "elapsedSeconds": round(time.monotonic() - self.started, 3),
                "milestones": self.milestones, "eventCounts": dict(self.counts),
                "maxReceivedBytes": self.received, "maxDurableBytes": self.durable,
                "recentEvents": list(self.recent)}


class Session(IndependentSession):
    # 日期：2026-11-05；保留独立报文编解码和指纹核对，并记录成功认证后的本地单调参考时间。
    def __init__(self, port, profile):
        super().__init__(port, profile)
        self.authenticated = time.monotonic()

    # 日期：2026-11-05；在独立客户端实际握手中核验新能力和规范的有效期声明。
    def request(self, kind, value):
        response, data = super().request(kind, value)
        if kind == 1:
            assert "session-lifetime-v1" in data["capabilities"]
            self.seconds = int(data["sessionSeconds"])
            assert str(self.seconds) == data["sessionSeconds"] and 1 <= self.seconds <= 86400
        return response, data


class ExpiryProxy(SlowProxy):
    rate = 512 * 1024

    # 日期：2026-11-05；最多保留128个方向的固定计数，不保存TLS密文正文或无限历史。
    def __init__(self, target):
        self.observation_lock = threading.Lock()
        self.observations = deque(maxlen=128)
        self.sequence = 0
        super().__init__(target)

    # 日期：2026-11-05；发起本组进程前取序号和单调时间，排除先前配对/策略连接。
    def mark(self):
        with self.observation_lock:
            return {"sequence": self.sequence, "started": time.monotonic()}

    # 日期：2026-11-05；只报告本组密文转发量和时间，密文字节不充当正文或持久确认量。
    def evidence(self, marker):
        with self.observation_lock:
            records = [{**value, "milestones": list(value["milestones"])}
                       for value in self.observations if value["sequence"] >= marker["sequence"]]
        for value in records:
            for key in ("started", "firstForwarded", "lastForwarded"):
                if key in value:
                    value[key + "AfterCaseSeconds"] = round(value.pop(key) - marker["started"], 3)
            for key in ("throttleSeconds", "actualThrottleSeconds", "receiveWaitSeconds", "sendWaitSeconds"):
                value[key] = round(value[key], 3)
        return {"pacing": "monotonic deadline; timer oversleep catchup bounded to 0.25s; receive blocking not credited",
                "scope": "opaque TLS forwarding including handshake and control; not durable payload bytes",
                "directions": records}

    # 日期：2026-11-05；默认每通道 512 KiB/s；诊断可显式调速，不能假定任何主机都能在到期前落盘。
    def pump(self, source, destination):
        try:
            direction = "to-server" if destination.getpeername()[1] == self.target else "to-client"
        except OSError:
            return
        with self.observation_lock:
            record = {"sequence": self.sequence, "started": time.monotonic(), "forwardedBytes": 0,
                      "reads": 0, "largestRead": 0, "throttleSeconds": 0.0,
                      "actualThrottleSeconds": 0.0, "receiveWaitSeconds": 0.0,
                      "sendWaitSeconds": 0.0, "milestones": [], "direction": direction}
            self.sequence += 1
            self.observations.append(record)
        pacer = ProxyPacer()
        try:
            while not self.stopped.is_set():
                receiving = time.monotonic()
                data = source.recv(16384)
                received = time.monotonic()
                delay = len(data) / self.rate
                stopped = not data or pacer.wait(self.stopped, len(data), self.rate, received - receiving)
                throttled = time.monotonic()
                with self.observation_lock:
                    record["receiveWaitSeconds"] += received - receiving
                    record["actualThrottleSeconds"] += throttled - received
                if stopped:
                    break
                destination.sendall(data)
                with self.observation_lock:
                    now = time.monotonic()
                    record["sendWaitSeconds"] += now - throttled
                    record.setdefault("firstForwarded", now)
                    record["lastForwarded"] = now
                    record["forwardedBytes"] += len(data)
                    record["reads"] += 1
                    record["largestRead"] = max(record["largestRead"], len(data))
                    record["throttleSeconds"] += delay
                    if (len(record["milestones"]) < 32
                            and record["forwardedBytes"] >= (len(record["milestones"]) + 1) * 262144):
                        record["milestones"].append({
                            "forwardedBytes": record["forwardedBytes"],
                            "afterConnectionSeconds": round(now - record["started"], 3),
                            "receiveWaitSeconds": round(record["receiveWaitSeconds"], 3),
                            "actualThrottleSeconds": round(record["actualThrottleSeconds"], 3),
                            "sendWaitSeconds": round(record["sendWaitSeconds"], 3)})
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass


class ExpiryOutput(JsonOutputDrain):
    # 日期：2026-11-05；在后台读取器解析前计数到期响应，避免最近 16 条诊断淘汰后丢失证据。
    def __init__(self, stream):
        self.session_expiries = 0
        self.condition = threading.Condition()
        super().__init__(self.lines(stream))

    # 日期：2026-11-05；不保留历史报文，只增加固定整数，正常 JSON 校验仍由共用读取器完成。
    def lines(self, stream):
        for line in stream:
            event = json.loads(line)
            if event.get("code") == 4 and event.get("stage") == "session":
                with self.condition:
                    self.session_expiries += 1
                    self.condition.notify_all()
            yield line


    # 日期：2026-11-05；仅等原截止内的真实服务输出，不要求跨进程事件在客户端退出前同步可见。
    def wait_expiry(self, previous, deadline):
        with self.condition:
            return self.condition.wait_for(lambda: self.session_expiries > previous,
                                           timeout=max(0.0, deadline - time.monotonic()))


# 日期：2026-11-05；只读取已提交检查点，不把网络发送量或客户端进度当作持久复用量。
def confirmed(state, task):
    path = state / f"receive-{task}.sqlite"
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)) as database:
        return database.execute("SELECT COALESCE(SUM(confirmed),0) FROM files").fetchone()[0]


# 日期：2026-11-05；独立读取最多16条接收日志及自有临时文件大小，区分无正文和未满持久块。
def receiver_files(state, task, destination):
    path = state / f"receive-{task}.sqlite"
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)) as database:
        rows = database.execute("SELECT id,temporary,state,confirmed FROM files ORDER BY id LIMIT 16").fetchall()
    records = []
    for file, temporary, state, durable in rows:
        candidate = destination / temporary
        assert candidate.resolve().is_relative_to(destination.resolve())
        record = {"file": file, "state": state, "durableBytes": durable, "temporaryExists": candidate.exists()}
        if candidate.exists():
            information = candidate.lstat()
            assert stat.S_ISREG(information.st_mode)
            record["temporaryFileBytes"] = information.st_size
        records.append(record)
    return records


# 日期：2026-11-05；原生进程必须自行失败，无伪完成；TLS 数据通道先结束可使控制端得到网络错误。
def expired_transfer(active, timeout=45):
    code = active.process.wait(timeout=timeout)
    active.reader.join(5)
    assert not active.reader.is_alive()
    error = active.process.stderr.read()
    events = []
    while True:
        try:
            event = active.events.get_nowait()
        except queue.Empty:
            break
        if event:
            events.append(event)
    assert code in (3, 4) and not error, (code, events, error)
    assert events and not any(event.get("event") == "transfer-completed" for event in events)
    return code, events[-1].get("stage")


# 日期：2026-11-05；保留默认 90 秒门槛；超时输出最后 16 条事件及实际复用量，显式更长预算只作诊断。
def resumed_transfer(executable, client, arguments, timeout=90):
    started = time.monotonic()
    try:
        result = subprocess.run([executable, *arguments, "--state-directory", str(client), "--json"],
                                capture_output=True, encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired as error:
        evidence = timeout_evidence(error, timeout, time.monotonic() - started)
        evidence["kind"] = "session-resume-timeout"
        raise AssertionError(json.dumps(evidence, ensure_ascii=False)) from error
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0 and not result.stderr, (result.returncode, events[-16:], result.stderr)
    assert events[-1]["event"] == "transfer-completed" and events[-1]["state"] == "completed", events[-16:]
    restored = max(int(event["restoredBytes"]) for event in events if event.get("event") == "byte-progress")
    return events[-1], restored, round(time.monotonic() - started, 3)


class ProtocolPeer:
    # 日期：2026-11-05；独立 TLS 对端仅用于协商畸形/旧能力报文，证书和资料来自测试自有真实身份。
    def __init__(self, root, identity, profile, hello):
        certificate, key = root / "peer.crt", root / "peer.key"
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
        self.profile, self.hello, self.error = profile, hello, None
        self.worker = threading.Thread(target=self.serve, daemon=True)
        self.worker.start()

    # 日期：2026-11-05；独立按 32 字节报头读取控制帧，限制长度且只回送规定响应，不调用生产编解码器。
    def serve(self):
        try:
            connection, _ = self.listener.accept()
            with self.context.wrap_socket(connection, server_side=True) as secure:
                secure.settimeout(10)
                for _ in range(3):
                    header = bytearray()
                    while len(header) < 32:
                        part = secure.recv(32 - len(header))
                        if not part:
                            return
                        header.extend(part)
                    magic, major, minor, kind, flags, correlation, length, reserved = struct.unpack(
                        ">8sHHHHQII", header)
                    assert (magic, major, minor, flags, reserved) == (b"DKTNEXT1", 1, 0, 0, 0)
                    assert 2 <= length <= 65536
                    body = bytearray()
                    while len(body) < length:
                        part = secure.recv(length - len(body))
                        assert part
                        body.extend(part)
                    if kind == 1:
                        response, data = 2, self.hello
                    elif kind == 3:
                        response, data = 4, {"client": self.profile["client"], "revision": "1", "grants": [
                            {"share": "data", "browse": True, "download": False, "upload": False}]}
                    else:
                        assert kind == 8
                        response, data = 9, {}
                    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
                    secure.sendall(struct.pack(">8sHHHHQII", magic, 1, 0, response, 0, correlation, len(payload), 0) + payload)
        except Exception as error:
            self.error = type(error).__name__

    # 日期：2026-11-05；等待此测试线程结束；畸形协商后的 TLS 关闭允许 EOF，其他异常保留为失败。
    def close(self):
        self.listener.close()
        self.worker.join(12)
        assert not self.worker.is_alive() and self.error in (None, "SSLEOFError"), self.error


# 日期：2026-11-05；声明新能力必须含合法规范有效期；旧服务未声明此能力仍可认证且不臆测有效期。
def negotiation(executable, root, server, client, profile):
    identity = json.loads((server / "service/identity.json").read_text(encoding="utf-8"))
    profile_path = client / "clients/profile-default.json"
    original = profile_path.read_bytes()
    for index, value in enumerate((None, 1, "0", "01", "86401", "18446744073709551616", "86400", "old")):
        hello = {"version": "1.0", "serverId": profile["server"], "capabilities": ["auth-v1", "control-close-v1"]}
        if value != "old":
            hello["capabilities"].append("session-lifetime-v1")
            if value is not None:
                hello["sessionSeconds"] = value
        peer = ProtocolPeer(root, identity, profile, hello)
        try:
            record = dict(profile, port=str(peer.port))
            profile_path.write_text(json.dumps(record), encoding="utf-8")
            accepted = value in ("86400", "old")
            event, _ = run(executable, client, ["auth"], 0 if accepted else 2)
            if value == "old":
                assert "sessionSeconds" not in event
            elif accepted:
                assert event["sessionSeconds"] == value
        finally:
            profile_path.write_bytes(original)
            peer.close()
    return {"invalidRejected": 6, "validAccepted": True, "oldPeerUnknownLifetime": True}


# 日期：2026-11-05；只在独立临时状态/回环端口进行验证，服务输出持续有界消费。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--channels", type=int, nargs="+", default=[1, 4, 16])
    parser.add_argument("--directions", choices=("upload", "download"), nargs="+",
                        default=["upload", "download"])
    parser.add_argument("--resume-timeout", type=int, default=90)
    parser.add_argument("--expiry-seconds", type=int, default=20)
    parser.add_argument("--expiry-rate-kib", type=int, default=512)
    parser.add_argument("--expiry-timeout", type=int, default=45)
    parser.add_argument("--ready-timeout", type=int, default=30)
    args = parser.parse_args()
    assert 1 <= args.resume_timeout <= 600
    assert 5 <= args.expiry_seconds <= 120 and 128 <= args.expiry_rate_kib <= 4096
    assert args.expiry_seconds + 5 <= args.expiry_timeout <= 180 and 1 <= args.ready_timeout <= 180
    assert args.channels and all(value in (1, 2, 4, 8, 16) for value in args.channels)
    timing = {"sessionSeconds": args.expiry_seconds, "expiryRateKiBPerSecond": args.expiry_rate_kib,
              "expiryExitBudgetSeconds": args.expiry_timeout, "readyBudgetSeconds": args.ready_timeout,
              "resumeBudgetSeconds": args.resume_timeout}
    print(json.dumps({"kind": "session-test-configuration", **timing}), flush=True)
    executable = str(Path(args.executable).resolve())
    binary_sha = digest(Path(executable))
    script_sha = digest(Path(__file__))
    checks, cases = [], []
    negotiation_result = None
    with tempfile.TemporaryDirectory(prefix="dukto-session-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        assert info["sessionSeconds"] == "86400"
        policy, _ = run(executable, server, ["serve", "session", "show"])
        assert policy["seconds"] == "86400"
        for invalid in ("0", "01", "-1", "86401", "1.0", "18446744073709551616"):
            run(executable, server, ["serve", "session", "set", "--session-seconds", invalid], 2)
            unchanged, _ = run(executable, server, ["serve", "session", "show"])
            assert unchanged["seconds"] == "86400"
        rights = ["--share", "data", "--allow-browse", "--allow-download", "--allow-upload"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        port = free_port()
        proxy = ExpiryProxy(port)
        active = None
        output = None
        service = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
                                    "--state-directory", str(server), "--json"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            assert json.loads(service.stdout.readline())["event"] == "service-listening"
            output = ExpiryOutput(service.stdout)
            paired, _ = run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                                "--fingerprint", info["fingerprint"],
                                                "--credential-file", offer["credentialFile"]])
            assert paired["sessionSeconds"] == "86400"
            profile_path = client / "clients/profile-default.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))

            # 日期：2026-11-05；本机策略改动只影响新连接；业务重复和同连接轮换均不续期。
            def set_seconds(seconds):
                event, _ = run(executable, server, ["serve", "session", "set", "--session-seconds", str(seconds)])
                assert event["seconds"] == str(seconds)

            set_seconds(4)
            with closing(Session(port, profile)) as old:
                assert old.seconds == 4
                set_seconds(1)
                with closing(Session(port, profile)) as short:
                    assert short.seconds == 1
                    time.sleep(1.15)
                    kind, failure = short.request(16, {"share": "data", "path": "", "cursor": ""})
                    assert kind == 7 and failure["code"] == 4 and failure["stage"] == "session"
                kind, listing = old.request(16, {"share": "data", "path": "", "cursor": ""})
                assert kind == 17 and listing["entries"] == []
                replacement = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                kind, rotated = old.request(10, {"credential": replacement})
                assert kind == 11 and rotated["client"] == profile["client"]
                profile["credential"] = replacement
                profile_path.write_text(json.dumps(profile), encoding="utf-8")
                while time.monotonic() - old.authenticated < 4.15:
                    time.sleep(0.03)
                kind, failure = old.request(16, {"share": "data", "path": "", "cursor": ""})
                assert kind == 7 and failure["code"] == 4 and failure["stage"] == "session"
            set_seconds(86400)
            authenticated, _ = run(executable, client, ["auth"])
            assert authenticated["client"] == paired["client"] and authenticated["sessionSeconds"] == "86400"
            negotiation_result = negotiation(executable, root, server, client, profile)
            checks.extend(["strict local policy", "per-connection lifetime", "business does not renew",
                           "rotation does not renew", "same profile fresh authentication"])

            source = root / "会话到期.bin"
            with source.open("wb") as stream:
                block = bytes(range(256)) * 4096
                for _ in range(256):
                    stream.write(block)
                stream.write(b"session-expiry-tail")
            expected, total = digest(source), source.stat().st_size
            shutil.copyfile(source, shared / source.name)
            for channels in args.channels:
                for direction in args.directions:
                    request = str(uuid.uuid4())
                    target = root / f"{direction}-{channels}"
                    target.mkdir()
                    if direction == "upload":
                        (shared / target.name).mkdir()
                        arguments = [direction, "--share", "data", "--path", str(source),
                                     "--remote-path", target.name, "--request-id", request]
                        resume = ["--path", str(source)]
                        state = server / "service"
                        final = shared / target.name / source.name
                    else:
                        arguments = [direction, "--share", "data", "--remote-path", source.name,
                                     "--output", str(target), "--request-id", request]
                        resume = ["--output", str(target)]
                        state = client / "transfers"
                        final = target / source.name
                    proxy.rate = args.expiry_rate_kib * 1024
                    set_seconds(args.expiry_seconds)
                    prior_expiries = output.session_expiries
                    marker = proxy.mark()
                    active = TimedTransfer(executable, client, [*arguments, "--threads", str(channels)])
                    task = active.task(timeout=args.ready_timeout)
                    expiry_deadline = time.monotonic() + args.expiry_timeout
                    code, stage = expired_transfer(active, args.expiry_timeout)
                    observed = active.evidence()
                    active = None
                    # 日期：2026-11-05；新连接采用正常时长再查任务，避免查询自身因测试短策略重复到期。
                    set_seconds(86400)
                    status = wait_state(executable, client, task, "interrupted")
                    prefix = confirmed(state, task)
                    case = {"direction": direction, "channels": channels, "taskId": task,
                            "totalBytes": total, "confirmedAtExpiry": prefix, "clientExitCode": code,
                            "clientStage": stage, "timeline": observed, "passed": False,
                            "receiverFiles": receiver_files(state, task, shared / target.name if direction == "upload" else target),
                            "encryptedProxy": proxy.evidence(marker)}
                    cases.append(case)
                    print(json.dumps({"kind": "session-expiry-observation", **case}, ensure_ascii=False), flush=True)
                    assert 0 < prefix < total and not final.exists(), (prefix, total, status)
                    assert output.wait_expiry(prior_expiries, expiry_deadline), list(output.recent)
                    case["serverExpiryObservedAfterCaseSeconds"] = round(time.monotonic() - marker["started"], 3)
                    proxy.rate = 4 * 1024 * 1024
                    try:
                        completed, restored, resume_seconds = resumed_transfer(executable, client, ["resume", "--task", task, *resume, "--threads", "16"], args.resume_timeout)
                    except AssertionError as error:
                        # 日期：2026-11-05；恢复失败仍使原专项失败，将有界客户端/服务端关闭原因写入实际报告。
                        case.update(resumeFailure=error.args[0], serverEventsAtFailure=list(output.recent))
                        raise
                    assert completed["taskId"] == task and completed["requestId"] == request
                    assert restored >= prefix, (restored, prefix)
                    assert digest(final) == expected and len(list(final.parent.iterdir())) == 1
                    retried = transfer(executable, client, [*arguments, "--threads", "4"])
                    assert retried["taskId"] == task and len(list(final.parent.iterdir())) == 1
                    case.update(resumeChannels=16, restoredBytes=restored,
                                resumeSeconds=resume_seconds, passed=True)
                    print(f"{direction}/{channels}: expired at {prefix}, same task resumed and SHA verified", flush=True)
        finally:
            if active and active.process.poll() is None:
                active.process.kill()
                active.process.wait(timeout=10)
            service.kill()
            service.wait(timeout=10)
            # 日期：2026-11-05；启动失败也保存有界诊断；先写报告再断言，避免清理错误掩盖原始失败。
            service_output = output.finish() if output else {"drainStarted": False, "trailingOutput": service.stdout.read(8192)}
            service_error = service.stderr.read(8192)
            proxy.close()
            passed = (not service_error and len(cases) == len(args.directions) * len(args.channels)
                      and all(case["passed"] for case in cases))
            report = {"date": "2026-11-05", "passed": passed, "binarySha256": binary_sha,
                      "scriptSha256": script_sha, "resumeBudgetSeconds": args.resume_timeout,
                      "timingConfiguration": timing, "directions": args.directions,
                      "defaultTimingGatesPassed": passed and (args.expiry_seconds, args.expiry_rate_kib,
                                                              args.expiry_timeout, args.ready_timeout,
                                                              args.resume_timeout) == (20, 512, 45, 30, 90),
                      "defaultResumeGatePassed": passed and args.resume_timeout == 90,
                      "negotiation": negotiation_result, "checks": checks, "cases": cases,
                      "serverOutput": service_output, "serverStderr": service_error,
                      "scope": "real local TLS and independent frames; application-boundary expiry, idle/frame I/O waits remain bounded by frame timeout; no wall-clock modification or physical network claim"}
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            assert not service_error, service_error


if __name__ == "__main__":
    main()

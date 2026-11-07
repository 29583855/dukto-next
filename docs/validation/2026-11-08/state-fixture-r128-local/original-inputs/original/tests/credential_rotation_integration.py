"""日期：2026-11-05；真实 TLS 凭据轮换、丢确认、客户退出及同主体任务保持专项。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import time
import uuid

from service_integration import free_port, run
from proxy_pacing import ProxyPacer
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_checkpoint
from transfer_faults_integration import failure, stopped_task


# 日期：2026-11-05；只读取本测试小型私有记录，断言失败不打印凭据正文。
def record(path):
    return json.loads(path.read_text(encoding="utf-8"))


# 日期：2026-11-05；沿真实恢复事件证明已同步块重新校验并复用，不仅依赖最终任务 ID 相同。
def resume_with_reuse(executable, state, arguments, minimum):
    result = subprocess.run([executable, *arguments, "--state-directory", str(state), "--json"],
                            capture_output=True, encoding="utf-8", timeout=90)
    assert result.returncode == 0 and not result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events[-1]["event"] == "transfer-completed" and events[-1]["state"] == "completed"
    reused = max(int(event.get("restoredBytes", "0")) for event in events)
    assert reused >= minimum > 0, (reused, minimum)
    return events[-1], reused, result.stdout


class RotationProxy(SlowProxy):
    # 日期：2026-11-05；代理不解密 TLS，以自有持久记录核对真实切换点和新秘密预先保存顺序。
    def __init__(self, target, profile):
        self.profile = profile
        self.account = None
        self.previous_hash = None
        self.mode = None
        self.hit = threading.Event()
        self.release = threading.Event()
        self.dropped_bytes = 0
        self.rate = None
        super().__init__(target)

    # 日期：2026-11-05；只阻断轮换对应方向，不因认证失败或普通传输误触发故障。
    def pump(self, source, destination):
        pacer = ProxyPacer()
        try:
            while not self.stopped.is_set():
                receiving = time.monotonic()
                data = source.recv(16384)
                received = time.monotonic()
                if not data:
                    break
                response = source.getpeername()[1] == self.target
                if self.mode == "drop-confirmation" and response and self.account:
                    if record(self.account)["credentialHash"] != self.previous_hash:
                        self.dropped_bytes += len(data)
                        self.hit.set()
                        source.shutdown(socket.SHUT_RDWR)
                        destination.shutdown(socket.SHUT_RDWR)
                        return
                if self.mode == "hold-request" and not response:
                    if self.profile.exists() and record(self.profile).get("pendingCredential"):
                        self.hit.set()
                        deadline = time.monotonic() + 20
                        while not self.stopped.is_set() and not self.release.wait(0.02):
                            if time.monotonic() >= deadline:
                                return
                        return
                if self.rate and pacer.wait(self.stopped, len(data), self.rate, received - receiving):
                    return
                destination.sendall(data)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass


class IndependentSession:
    # 日期：2026-11-05；独立编码协议并校验证书指纹，保留旧认证连接验证轮换后的每操作重查。
    def __init__(self, port, profile):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.socket = context.wrap_socket(socket.create_connection(("127.0.0.1", port), timeout=5),
                                          server_hostname=profile["peerName"])
        assert hashlib.sha256(self.socket.getpeercert(binary_form=True)).hexdigest() == profile["fingerprint"]
        self.correlation = 0
        kind, hello = self.request(1, {"version": "1.0", "capabilities": ["credential-rotation-v1"]})
        assert kind == 2 and "credential-rotation-v1" in hello["capabilities"]
        kind, account = self.request(3, {"client": profile["client"], "credential": profile["credential"]})
        assert kind == 4 and account["client"] == profile["client"]

    # 日期：2026-11-05；固定长度读取且限制帧长，不复用生产编解码器。
    def exact(self, length):
        result = bytearray()
        while len(result) < length:
            part = self.socket.recv(length - len(result))
            assert part, "independent session closed before response"
            result.extend(part)
        return bytes(result)

    # 日期：2026-11-05；按独立偏移构造头，只返回有界公开响应；秘密不进入错误文本。
    def request(self, kind, value):
        self.correlation += 1
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.socket.sendall(struct.pack(">8sHHHHQII", b"DKTNEXT1", 1, 0, kind, 0,
                                        self.correlation, len(payload), 0) + payload)
        header = struct.unpack(">8sHHHHQII", self.exact(32))
        assert header[:3] == (b"DKTNEXT1", 1, 0) and header[4] == 0 and header[7] == 0
        assert header[5] == self.correlation and 2 <= header[6] <= 65536
        return header[3], json.loads(self.exact(header[6]))

    # 日期：2026-11-05；只关闭本测试的独立认证连接。
    def close(self):
        self.socket.close()


# 日期：2026-11-05；所有故障仅作用于测试自有 CLI、状态和代理，不改动运行中的长时验证。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    checks = []
    live_cases = []
    collected = []
    with tempfile.TemporaryDirectory(prefix="dukto-rotation-") as temporary:
        root = Path(temporary).resolve()
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-browse", "--allow-download", "--allow-upload"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        port = free_port()
        profile_path = client / "clients/profile-default.json"
        proxy = RotationProxy(port, profile_path)
        active = None
        active_transfer = None
        old_session = None
        secrets = [record(Path(offer["credentialFile"]))["credential"]]
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as service_out, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as service_err:
            service = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
                                        "--state-directory", str(server), "--json"], stdout=service_out, stderr=service_err)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    service_out.seek(0)
                    line = service_out.readline()
                    if line:
                        assert json.loads(line)["event"] == "service-listening"
                        break
                    assert service.poll() is None
                    time.sleep(0.02)
                else:
                    raise AssertionError("rotation test service startup deadline")
                paired, _ = run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                                     "--fingerprint", info["fingerprint"],
                                                     "--credential-file", offer["credentialFile"]])
                initial = record(profile_path)
                secrets.append(initial["credential"])
                proxy.account = server / "service" / ("client-" + paired["client"] + ".json")
                proxy.previous_hash = record(proxy.account)["credentialHash"]
                source = root / "轮换保持.bin"
                source.write_bytes(b"rotation identity and request preservation" * 32769)
                upload = ["upload", "--share", "data", "--path", str(source), "--threads", "4",
                          "--request-id", str(uuid.uuid4())]
                completed = transfer(executable, client, upload)
                old_session = IndependentSession(port, initial)
                stale = root / "stale"
                shutil.copytree(client / "clients", stale / "clients")
                proxy.mode = "drop-confirmation"
                failed, output = run(executable, client, ["rotate"], 3)
                collected.append(output)
                assert failed["code"] == 3 and proxy.hit.is_set() and proxy.dropped_bytes > 0
                pending = record(profile_path)
                secrets.append(pending["pendingCredential"])
                assert pending["credential"] == initial["credential"]
                assert record(proxy.account)["credentialHash"] == hashlib.sha256(bytes.fromhex(pending["pendingCredential"])).hexdigest()
                assert record(proxy.account)["revision"] == "2"
                proxy.mode = None
                awaiting, output = run(executable, client, ["auth"], 4)
                collected.append(output)
                assert awaiting["stage"] == "profile"
                assert record(profile_path) == pending
                kind, rejected = old_session.request(16, {"share": "data", "path": "", "cursor": ""})
                assert kind == 7 and rejected["code"] == 4
                old_session.close()
                old_session = None
                run(executable, stale, ["auth"], 4)
                recovered, output = run(executable, client, ["rotate"])
                collected.append(output)
                assert recovered["recovered"] and recovered["revision"] == "2"
                assert recovered["client"] == paired["client"] and recovered["grants"] == paired["grants"]
                assert "pendingCredential" not in record(profile_path)
                assert record(profile_path)["credential"] == pending["pendingCredential"]
                assert record(proxy.account)["revision"] == "2"
                assert transfer(executable, client, upload)["taskId"] == completed["taskId"]
                assert digest(shared / source.name) == digest(source)
                assert len(list(shared.iterdir())) == 1
                checks.extend(["real lost TLS rotation response with durable pending secret",
                               "recovery confirms new credential without a second rotation",
                               "old connections and fresh old-credential connections denied",
                               "same principal, grants, original request and task preserved without duplicate file"])

                proxy.hit.clear()
                proxy.mode = "hold-request"
                before = record(proxy.account)
                active = subprocess.Popen([executable, "rotate", "--state-directory", str(client), "--json"],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
                assert proxy.hit.wait(15), "rotation request did not reach pre-commit checkpoint"
                saved = profile_path.read_bytes()
                assert record(proxy.account) == before
                locked, output = run(executable, client, ["rotate"], 4)
                collected.append(output)
                assert locked["stage"] == "profile" and profile_path.read_bytes() == saved
                active.kill()
                out, err = active.communicate(timeout=10)
                collected.append(out)
                assert active.returncode != 0 and not err and "credential-rotated" not in out
                active = None
                proxy.mode = None
                proxy.release.set()
                resumed, output = run(executable, client, ["rotate"])
                collected.append(output)
                candidate = json.loads(saved)["pendingCredential"]
                secrets.append(candidate)
                assert resumed["recovered"] and resumed["revision"] == "3"
                assert record(profile_path)["credential"] == candidate
                checks.extend(["real client process killed after local secret save and before server change",
                               "same pending secret reused after pre-commit crash",
                               "concurrent profile rotation refused without modifying checkpoint"])

                for bad in ({}, {"credential": "0" * 63}, {"credential": "A" * 64},
                            {"credential": record(profile_path)["credential"]},
                            {"credential": "0" * 64, "client": str(uuid.uuid4())}):
                    connection = IndependentSession(port, record(profile_path))
                    try:
                        kind, rejected = connection.request(10, bad)
                        assert kind == 7 and rejected["code"] in (2, 4)
                    finally:
                        connection.close()
                    assert record(proxy.account)["revision"] == "3"
                normal, output = run(executable, client, ["rotate"])
                collected.append(output)
                assert normal["event"] == "credential-rotated" and not normal["recovered"] and normal["revision"] == "4"
                secrets.append(record(profile_path)["credential"])
                run(executable, client, ["auth"])
                status, _ = run(executable, client, ["task", "--task", completed["taskId"]])
                assert status["state"] == "completed" and status["requestId"] == completed["requestId"]
                live_source = root / "live.bin"
                with live_source.open("wb") as output:
                    for index in range(256):
                        output.write(bytes([index]) * (256 * 1024))
                    output.write(b"credential-rotation-live-tail")
                expected_sha = digest(live_source)
                for direction in ("upload", "download"):
                    remote = shared / ("live-" + direction)
                    remote.mkdir()
                    target = remote if direction == "upload" else root / "live-output"
                    target.mkdir(exist_ok=True)
                    if direction == "download":
                        shutil.copyfile(live_source, remote / live_source.name)
                    original = target / live_source.name
                    original.write_bytes(b"original user file")
                    original_sha = digest(original)
                    transfer_args = [direction, "--share", "data", "--threads", "4", "--request-id", str(uuid.uuid4())]
                    transfer_args += (["--path", str(live_source), "--remote-path", remote.name] if direction == "upload" else
                                      ["--remote-path", remote.name + "/" + live_source.name, "--output", str(target)])
                    proxy.rate = 512 * 1024
                    active_transfer = TransferProcess(executable, client, transfer_args)
                    live_task = active_transfer.task()
                    checkpoint = wait_checkpoint(server / "service" if direction == "upload" else client / "transfers", live_task)
                    assert active_transfer.process.poll() is None
                    started = time.monotonic()
                    rotated, output = run(executable, client, ["rotate"])
                    collected.append(output)
                    secrets.append(record(profile_path)["credential"])
                    error = failure(active_transfer)
                    active_transfer = None
                    stopped = stopped_task(server, live_task)
                    # 日期：2026-11-06；原断言前保存非秘密字段；失败不能只留下AssertionError而丢失实际分类。
                    observation = {"direction": direction, "channels": 4, "taskId": live_task,
                                   "checkpoint": checkpoint, "errorCode": error.get("code"),
                                   "errorStage": error.get("stage"), "serverStoppedState": stopped.get("state"),
                                   "secondsToStop": round(time.monotonic() - started, 3)}
                    Path(args.report).write_text(json.dumps({
                        "date": "2026-11-06", "passed": False, "completed": False,
                        "phase": "live credential rotation stop assertion", "observation": observation,
                        "completedLiveCases": live_cases, "checks": checks,
                        "executableSha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                        "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    assert error["code"] in (3, 4) and stopped["state"] == "interrupted", observation
                    seconds = round(time.monotonic() - started, 3)
                    assert seconds < 15
                    assert digest(original) == original_sha
                    assert sorted(path.name for path in target.iterdir() if not path.name.startswith(".")) == [live_source.name]
                    proxy.rate = None
                    resumed_transfer, reused, output = resume_with_reuse(executable, client, transfer_args, checkpoint)
                    collected.append(output)
                    assert resumed_transfer["taskId"] == live_task
                    assert digest(target / "live (2).bin") == expected_sha and digest(original) == original_sha
                    assert len(list(target.iterdir())) == 2
                    live_cases.append({"direction": direction, "channels": 4, "taskId": live_task,
                                       "checkpoint": checkpoint, "secondsToStop": seconds,
                                       "restoredBytes": reused,
                                       "serverStoppedState": stopped["state"], "errorCode": error["code"],
                                       "sameTaskResumed": True, "originalPreserved": True, "sha256": expected_sha})
                checks.append("live upload/download old channels stop after rotation and new credential resumes same task")
                run(executable, server, ["serve", "revoke", "--client", paired["client"]])
                run(executable, client, ["rotate"], 4)
                assert "pendingCredential" not in record(profile_path)
                assert record(proxy.account)["revoked"] and record(proxy.account)["revision"] == "7"
                checks.extend(["strict malformed/redundant/same-secret rotation rejected without state change",
                               "normal CLI rotation and subsequent owned task query",
                               "revoked principal cannot rotate or revive"])
            finally:
                if active and active.poll() is None:
                    active.kill()
                    active.communicate(timeout=10)
                if active_transfer and active_transfer.process.poll() is None:
                    active_transfer.process.kill()
                    active_transfer.process.wait(10)
                if old_session:
                    old_session.close()
                proxy.close()
                service.kill()
                service.wait(10)
                service_out.seek(0)
                collected.append(service_out.read())
                service_err.seek(0)
                assert not service_err.read()
        all_output = "\n".join(collected)
        assert all(secret not in all_output for secret in secrets)
        assert all(secret not in proxy.account.read_text(encoding="utf-8") for secret in secrets)
        checks.append("all current and pending secrets absent from stdout/stderr and server records")
    report = {"date": "2026-11-05", "passed": True, "checks": checks, "liveCases": live_cases,
              "executableSha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
              "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "platform": os.name,
              "scope": "real independent TLS CLI rotation, response loss and pre-commit client kill; GUI covered separately; no arbitrary power-loss qualification"}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "checks": len(checks)}), flush=True)


if __name__ == "__main__":
    main()

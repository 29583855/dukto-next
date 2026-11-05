"""日期：2026-11-05；真实TLS续期、双向检查点恢复、指纹迁移、过期诊断及并发更新专项。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from credential_rotation_integration import resume_with_reuse
from process_output import JsonOutputDrain
from secure_channel_integration import certificates
from service_integration import free_port, run
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_checkpoint, wait_state


# 日期：2026-11-05；小型测试私有记录只在临时目录操作，异常不展示秘密内容。
def record(path):
    return json.loads(path.read_text(encoding="utf-8"))


# 日期：2026-11-05；覆盖自有已保护文件时保持其权限，不向报告复制私钥或访问秘密。
def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


# 日期：2026-11-05；按公开前置条件运行，任何失败保留部分报告且返回非零。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    # 日期：2026-11-05；独立包需要保留相邻qt.conf及SQL插件，避免复制单个EXE后误报部署失败。
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()
    original_executable = Path(args.executable).resolve()
    before = digest(original_executable)
    result = {"passed": False, "checks": [], "recoveries": [], "executableSha256": before,
              "inPlaceRequested": args.in_place}
    outputs, secrets = [], []
    service = active = proxy = None
    try:
        with tempfile.TemporaryDirectory(prefix="dukto-certificate-") as temporary:
            root = Path(temporary).resolve()
            executable = str(original_executable)
            if os.name == "nt" and not args.in_place:
                local = root / "dukto-cli.exe"
                shutil.copyfile(executable, local)
                executable = str(local)
            server, client, shared = root / "server", root / "client", root / "shared"
            shared.mkdir()
            original, text = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1",
                                                       "--server-name", "localhost", "--certificate-days", "1"])
            outputs.append(text)
            assert original["expiringSoon"] and original["certificateStatus"] == "valid"
            identity_path = server / "service/identity.json"
            initial_bytes = identity_path.read_bytes()
            for invalid in ("0", "01", "826", "-1", "bad"):
                run(executable, server, ["serve", "renew", "--fingerprint", original["fingerprint"],
                                         "--certificate-days", invalid], 2)
                assert identity_path.read_bytes() == initial_bytes
            run(executable, server, ["serve", "renew", "--fingerprint", "00" * 32], 4)
            assert identity_path.read_bytes() == initial_bytes
            result["checks"].append("expiry-warning-and-invalid-renewal-preserves-original")
            rights = ["--share", "data", "--allow-browse", "--allow-upload", "--allow-download"]
            run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
            offer, _ = run(executable, server, ["serve", "pairing", *rights])
            port = free_port()
            proxy = SlowProxy(port)

            # 日期：2026-11-05；每次重启同一自有端口，输出持续有界排空，监听信息必须对应实际证书。
            def start_server():
                process = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1",
                                            "--port", str(port), "--state-directory", str(server), "--json"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
                event = json.loads(process.stdout.readline())
                assert event["event"] == "service-listening"
                outputs.append(json.dumps(event))
                process.output_drain = JsonOutputDrain(process.stdout)
                return process

            # 日期：2026-11-05；仅终止本测试启动的服务，严格检查标准错误并归还管道线程。
            def stop_server(process):
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
                process.output_drain.finish()
                assert not process.stderr.read()

            try:
                service = start_server()
                run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                         "--fingerprint", original["fingerprint"],
                                         "--credential-file", offer["credentialFile"]])
                profile_path = client / "clients/profile-default.json"
                unchanged_profile = profile_path.read_bytes()
                for override in (["--to", "192.0.2.1"], ["--port", "1"], ["--server-name", "other"]):
                    run(executable, client, ["trust", "--old-fingerprint", original["fingerprint"],
                                             "--fingerprint", "00" * 32, *override], 2)
                    assert profile_path.read_bytes() == unchanged_profile
                initial_profile = record(profile_path)
                secrets.append(initial_profile["credential"])
                source = root / "payload.bin"
                with source.open("wb") as stream:
                    for _ in range(32):
                        stream.write(b"certificate lifecycle" * 65536)
                expected_sha = digest(source)
                shutil.copyfile(source, shared / source.name)
                old_pin = original["fingerprint"]
                # 日期：2026-11-05；两方向各自真实落盘后暂停，续期/重启/迁移后改变通道数恢复同一任务。
                for direction in ("upload", "download"):
                    destination = root / (direction + "-output")
                    destination.mkdir()
                    request = str(uuid.uuid4())
                    if direction == "upload":
                        (shared / direction).mkdir()
                        arguments = ["upload", "--share", "data", "--remote-path", direction,
                                     "--path", str(source)]
                        receive = server / "service"
                        final = shared / direction / source.name
                        resume_arguments = ["--path", str(source)]
                    else:
                        arguments = ["download", "--share", "data", "--remote-path", source.name,
                                     "--output", str(destination)]
                        receive = client / "transfers"
                        final = destination / source.name
                        resume_arguments = ["--output", str(destination)]
                    gate = proxy.arm_checkpoint(direction)
                    active = TransferProcess(executable, client, [*arguments, "--threads", "4", "--request-id", request])
                    task = active.task()
                    checkpoint = wait_checkpoint(receive, task, 4 * 1024 * 1024, gate)
                    assert active.process.poll() is None and not final.exists()
                    run(executable, client, ["pause", "--task", task])
                    gate.release()
                    active.finish()
                    active = None
                    wait_state(executable, client, task, "paused")
                    stable_profile = profile_path.read_bytes()
                    auth_files = {path.name: digest(path) for path in (server / "service").glob("client-*.json")}
                    renewed, text = run(executable, server, ["serve", "renew", "--fingerprint", old_pin])
                    outputs.append(text)
                    new_pin = renewed["fingerprint"]
                    assert renewed["serverId"] == original["serverId"] and new_pin != old_pin
                    assert set(renewed["names"]) == set(original["names"]) and renewed["restartRequired"]
                    assert auth_files == {path.name: digest(path) for path in (server / "service").glob("client-*.json")}
                    run(executable, client, ["auth"])
                    trust = ["trust", "--old-fingerprint", old_pin, "--fingerprint", new_pin]
                    # 日期：2026-11-05；磁盘新证书不能让仍使用旧证书的监听器通过新pin校验。
                    run(executable, client, trust, 4)
                    assert profile_path.read_bytes() == stable_profile
                    stop_server(service)
                    service = None
                    service = start_server()
                    run(executable, client, ["auth"], 4)
                    run(executable, client, ["trust", "--old-fingerprint", "00" * 32, "--fingerprint", new_pin], 4)
                    run(executable, client, ["trust", "--old-fingerprint", old_pin, "--fingerprint", "00" * 32], 4)
                    assert profile_path.read_bytes() == stable_profile
                    wrong_server = record(profile_path)
                    wrong_server["server"] = str(uuid.uuid4())
                    save(profile_path, wrong_server)
                    wrong_bytes = profile_path.read_bytes()
                    refused, _ = run(executable, client, trust, 4)
                    assert refused["stage"] == "hello" and profile_path.read_bytes() == wrong_bytes
                    profile_path.write_bytes(stable_profile)
                    migrated, text = run(executable, client, trust)
                    outputs.append(text)
                    assert not migrated["alreadyUpdated"]
                    actual = record(profile_path)
                    old_record = json.loads(stable_profile)
                    assert actual == dict(old_record, fingerprint=new_pin)
                    repeated, _ = run(executable, client, trust)
                    assert repeated["alreadyUpdated"] and record(profile_path) == actual
                    info, text = run(executable, client, ["profile-info"])
                    outputs.append(text)
                    assert info["fingerprint"] == new_pin and info["serverId"] == original["serverId"]
                    resumed, reused, text = resume_with_reuse(executable, client,
                        ["resume", "--task", task, "--threads", "8", *resume_arguments], checkpoint)
                    outputs.append(text)
                    assert resumed["taskId"] == task and digest(final) == expected_sha
                    completed = transfer(executable, client, [*arguments, "--request-id", request, "--threads", "16"])
                    assert completed["taskId"] == task and digest(final) == expected_sha
                    assert len([path for path in final.parent.iterdir() if not path.name.startswith(".")]) == 1
                    result["recoveries"].append({"direction": direction, "taskId": task, "checkpointBytes": checkpoint,
                                                  "reusedBytes": reused, "resumeChannels": 8, "repeatChannels": 16})
                    old_pin = new_pin
                result["checks"].append("both-directions-real-checkpoints-renew-restart-trust-resume-idempotency")
                # 日期：2026-11-05；待轮换秘密的两个远程状态都须保持检查点，不自动删除或改写秘密。
                for applied in (False, True):
                    profile = record(profile_path)
                    pending = os.urandom(32).hex()
                    secrets.append(pending)
                    profile["pendingCredential"] = pending
                    save(profile_path, profile)
                    if applied:
                        account_path = server / "service" / ("client-" + profile["client"] + ".json")
                        account = record(account_path)
                        account["credentialHash"] = hashlib.sha256(bytes.fromhex(pending)).hexdigest()
                        account["revision"] = str(int(account["revision"]) + 1)
                        save(account_path, account)
                    before_profile = profile_path.read_bytes()
                    migrated, _ = run(executable, client, ["trust", "--old-fingerprint", original["fingerprint"],
                                                           "--fingerprint", old_pin])
                    assert migrated["rotationPending"] and profile_path.read_bytes() == before_profile
                    run(executable, client, ["rotate"])
                    recovered = record(profile_path)
                    assert recovered["credential"] == pending and "pendingCredential" not in recovered
                    run(executable, client, ["auth"])
                result["checks"].append("pending-rotation-both-states-retained-then-explicitly-recovered")
                run(executable, server, ["serve", "revoke", "--client", initial_profile["client"]])
                stable = profile_path.read_bytes()
                run(executable, client, ["trust", "--old-fingerprint", original["fingerprint"], "--fingerprint", old_pin], 4)
                assert profile_path.read_bytes() == stable
                result["checks"].append("revoked-principal-cannot-migrate")
            finally:
                if active is not None:
                    active.finish(kill=True)
                if service is not None:
                    stop_server(service)
                    service = None
                proxy.close()
                proxy = None
            # 日期：2026-11-05；使用独立OpenSSL构造真实过期/未来材料，不改系统时钟；私有文件权限不变。
            openssl = os.environ.get("DUKTO_TEST_OPENSSL", shutil.which("openssl"))
            assert openssl, "Independent OpenSSL is required"
            fixture = root / "independent-certificates"
            fixture.mkdir()
            fixtures, key = certificates(fixture, openssl)
            for name, status in (("expired", "expired"), ("future", "not-yet-valid")):
                current = record(identity_path)
                pem = fixtures[name].read_text(encoding="ascii")
                begin = pem.index("-----BEGIN CERTIFICATE-----")
                end = pem.index("-----END CERTIFICATE-----")
                current["certificate"] = pem[begin:end] + "-----END CERTIFICATE-----\n"
                current["privateKey"] = key.read_text(encoding="ascii")
                save(identity_path, current)
                checked, text = run(executable, server, ["serve", "info"])
                outputs.append(text)
                assert checked["certificateStatus"] == status
                run(executable, server, ["serve", "start", "--bind", "127.0.0.1", "--port", str(port)], 4)
                renewed, _ = run(executable, server, ["serve", "renew", "--fingerprint", checked["fingerprint"]])
                assert renewed["certificateStatus"] == "valid" and renewed["serverId"] == original["serverId"]
            result["checks"].append("expired-and-future-readable-start-rejected-explicit-renewal-works")
            # 日期：2026-11-05；两个进程同时确认同一个旧指纹，恰好一个发布，其余不能覆盖新身份。
            checked, _ = run(executable, server, ["serve", "info"])
            command = [executable, "serve", "renew", "--fingerprint", checked["fingerprint"],
                       "--state-directory", str(server), "--json"]
            processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8") for _ in range(2)]
            codes = []
            for process in processes:
                text, error = process.communicate(timeout=60)
                assert not error
                outputs.append(text)
                codes.append(process.returncode)
            assert sorted(codes) == [0, 4], codes
            checked, _ = run(executable, server, ["serve", "info"])
            assert checked["serverId"] == original["serverId"] and checked["certificateStatus"] == "valid"
            result["checks"].append("concurrent-old-fingerprint-renewal-exactly-one-writer")
            combined = "\n".join(outputs)
            assert "PRIVATE KEY" not in combined and "privateKey" not in combined
            assert all(secret not in combined for secret in secrets)
            result["checks"].append("public-events-contain-no-private-material")
            result["passed"] = True
    finally:
        result["binaryUnchanged"] = digest(original_executable) == before
        result["passed"] = result["passed"] and result["binaryUnchanged"]
        Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

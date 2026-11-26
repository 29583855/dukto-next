"""日期：2026-11-26；真实多进程TLS验证移动资料地址修改、离线删除及秘密不外泄。"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

from service_integration import free_port, run


# 日期：2026-11-26；仅在回环端口启动同一核心的独立服务进程，并确认实际监听事件。
def start(executable, state, port):
    process = subprocess.Popen(
        [executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
         "--state-directory", str(state), "--timeout", "2", "--json"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    first = json.loads(process.stdout.readline())
    assert first["event"] == "service-listening" and first["port"] == port
    return process


# 日期：2026-11-26；每个服务进程在finally停止，不留下监听或临时认证资料。
def stop(process):
    if process.poll() is None:
        if os.name == "nt":
            process.kill()
        else:
            process.send_signal(signal.SIGTERM)
    _, err = process.communicate(timeout=10)
    assert not err, err
    if os.name != "nt":
        assert process.returncode == 7, process.returncode


# 日期：2026-11-26；失败操作必须保持原始资料逐字节不变，允许的错误类别由调用点给出。
def preserved_failure(executable, state, arguments, expected, original):
    run(executable, state, arguments, expected)
    assert (state / "clients/profile-default.json").read_bytes() == original


# 日期：2026-11-26；验证重新启动后的持久身份、候选端点的原指纹认证和独立别名选择。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    output = []
    with tempfile.TemporaryDirectory(prefix="dukto-profiles-") as temporary:
        root = Path(temporary).resolve()
        server, client, other = root / "server", root / "client", root / "other"
        data = root / "data"
        data.mkdir()
        info, _ = run(executable, server, ["serve", "init", "--server-name", "localhost",
                                            "--server-name", "127.0.0.1"])
        run(executable, server, ["serve", "share", "add", "--share", "docs", "--path", str(data),
                                "--allow-browse"])
        port = free_port()
        process = start(executable, server, port)
        try:
            identities = []
            for alias in ["default", "second"]:
                offer, _ = run(executable, server, ["serve", "pairing", "--share", "docs", "--allow-browse"])
                paired, text = run(executable, client,
                    ["pair", "--profile", alias, "--to", "127.0.0.1:" + str(port),
                     "--server-name", "localhost", "--fingerprint", info["fingerprint"],
                     "--credential-file", offer["credentialFile"]])
                identities.append(paired["client"])
                output.append(text)
            page, text = run(executable, client, ["profiles"])
            output.append(text)
            assert [item["profile"] for item in page["entries"]] == ["default", "second"]
            assert not page["more"] and page["after"] == "second"
            for alias, identity in zip(["default", "second"], identities):
                account, text = run(executable, client, ["auth", "--profile", alias])
                output.append(text)
                assert account["client"] == identity
        finally:
            stop(process)
        original = (client / "clients/profile-default.json").read_bytes()
        before = json.loads(original)
        second_bytes = (client / "clients/profile-second.json").read_bytes()
        # 日期：2026-11-26；同一服务器状态迁移到新端口，保存前必须完整认证并正常关闭。
        moved_port = free_port()
        process = start(executable, server, moved_port)
        try:
            updated, text = run(executable, client,
                ["profile-update", "--to", "127.0.0.1:" + str(moved_port), "--timeout", "2"])
            output.append(text)
            assert updated["event"] == "profile-updated"
            current = (client / "clients/profile-default.json").read_bytes()
            after = json.loads(current)
            assert after["port"] == str(moved_port)
            assert {k: v for k, v in before.items() if k != "port"} == {
                k: v for k, v in after.items() if k != "port"}
            account, text = run(executable, client, ["auth"])
            output.append(text)
            assert account["client"] == identities[0]
            base = ["profile-update", "--to", "127.0.0.1:" + str(moved_port), "--timeout", "2"]
            preserved_failure(executable, client, base + ["--server-name", "wrong.invalid"], 4, current)
            preserved_failure(executable, client, base + ["--share", "docs"], 2, current)
            preserved_failure(executable, client, base + ["--timeout", "2"], 2, current)
            preserved_failure(executable, client,
                ["profile-update", "--to", "127.0.0.1:" + str(port), "--timeout", "1"], 3, current)
            run(executable, other, ["serve", "init", "--server-name", "localhost"])
            other_port = free_port()
            stranger = start(executable, other, other_port)
            try:
                preserved_failure(executable, client,
                    ["profile-update", "--to", "127.0.0.1:" + str(other_port), "--timeout", "2"], 4, current)
            finally:
                stop(stranger)
            assert (client / "clients/profile-second.json").read_bytes() == second_bytes
        finally:
            stop(process)
        # 日期：2026-11-26；服务离线也能删除本地资料，其他别名、任务文件和服务器授权必须保留。
        transfers = client / "transfers"
        transfers.mkdir(exist_ok=True)
        sentinel = transfers / "profile-delete-sentinel.txt"
        sentinel.write_bytes(b"retain task state")
        deleted, text = run(executable, client, ["profile-delete"])
        output.append(text)
        assert deleted["event"] == "profile-deleted" and deleted["serverRevoked"] is False
        assert not (client / "clients/profile-default.json").exists()
        assert sentinel.read_bytes() == b"retain task state"
        assert (client / "clients/profile-second.json").read_bytes() == second_bytes
        server_record = json.loads((server / "service" / ("client-" + identities[0] + ".json")).read_bytes())
        assert not server_record["revoked"]
        page, text = run(executable, client, ["profiles"])
        output.append(text)
        assert [item["profile"] for item in page["entries"]] == ["second"]
        public = "\n".join(output)
        assert before["credential"] not in public and "pendingCredential" not in public
    result = {"date": "2026-11-26", "passed": True, "deviceTest": False,
              "checks": ["two real paired profiles selected independently", "public profile whitelist",
                         "same identity moved to new port and authenticated before atomic save",
                         "original pin UUID and credential retained", "fresh process auth after update",
                         "wrong name pin port and options preserve original bytes",
                         "offline local deletion preserves second alias and transfer state",
                         "local deletion does not revoke remote authorization", "no secret in public results"],
              "scope": "independent CLI processes and loopback TLS; mobile UI acceptance is separate"}
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

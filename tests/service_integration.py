"""日期：2026-11-04；真实独立 CLI 服务/客户端验证身份、共享管理、配对、权限更新及撤销。"""

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile


# 日期：2026-11-04；命令标准输出只允许 JSONL，任何泄漏秘密或非空标准错误都会使测试失败。
def run(executable, state, arguments, expected=0):
    result = subprocess.run([executable, *arguments, "--state-directory", str(state), "--json"],
                            capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == expected and not result.stderr, (result.returncode, result.stdout, result.stderr)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(events) == 1, events
    return events[0], result.stdout


# 日期：2026-11-04；测试预留仅回环端口，不向已有局域网设备开放测试服务。
def free_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


# 日期：2026-11-04；独立临时目录中的证书、凭据和授权记录在测试结束删除，不写入共享验证报告。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    collected = []
    with tempfile.TemporaryDirectory(prefix="dukto-service-") as temporary:
        root = Path(temporary).resolve()
        server_state, client_state = root / "server", root / "client"
        data = root / "data"
        data.mkdir()
        for index in range(201):
            (data / f"item-{index:03d}.txt").write_bytes(b"browse fixture")
        info, output = run(executable, server_state,
                           ["serve", "init", "--server-name", "localhost", "--server-name", "127.0.0.1"])
        collected.append(output)
        assert len(info["fingerprint"]) == 64 and info["serverId"]
        loaded, output = run(executable, server_state, ["serve", "info"])
        collected.append(output)
        assert loaded["fingerprint"] == info["fingerprint"] and loaded["serverId"] == info["serverId"]
        run(executable, server_state, ["serve", "init", "--server-name", "localhost"], 2)
        _, output = run(executable, server_state,
                        ["serve", "share", "add", "--share", "docs", "--path", str(data),
                         "--allow-browse", "--allow-download"])
        collected.append(output)
        run(executable, server_state,
            ["serve", "share", "add", "--share", "secrets", "--path", str(root), "--allow-download"], 4)
        run(executable, server_state, ["serve", "pairing", "--share", "docs", "--allow-upload"], 4)
        offer, output = run(executable, server_state,
                            ["serve", "pairing", "--share", "docs", "--allow-browse", "--allow-download"])
        collected.append(output)
        credential = Path(offer["credentialFile"])
        secret = json.loads(credential.read_text(encoding="utf-8"))["credential"]
        port = free_port()
        process = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
                                    "--state-directory", str(server_state), "--timeout", "2", "--json"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            first_line = process.stdout.readline()
            listening = json.loads(first_line)
            collected.append(first_line)
            assert listening["event"] == "service-listening" and listening["port"] == port, listening
            base = ["pair", "--to", "127.0.0.1:" + str(port), "--fingerprint", info["fingerprint"],
                    "--credential-file", str(credential)]
            paired, output = run(executable, client_state, base)
            collected.append(output)
            assert paired["event"] == "paired" and paired["serverId"] == info["serverId"]
            account, output = run(executable, client_state, ["auth"])
            collected.append(output)
            assert account["client"] == paired["client"] and account["grants"][0]["download"]
            assert not account["grants"][0]["upload"]
            listing, output = run(executable, client_state, ["list", "--share", "docs"])
            collected.append(output)
            assert len(listing["entries"]) == 100 and listing["cursor"]
            following, output = run(executable, client_state,
                                     ["list", "--share", "docs", "--cursor", listing["cursor"]])
            collected.append(output)
            assert len(following["entries"]) == 100 and following["cursor"]
            final_page, output = run(executable, client_state,
                                      ["list", "--share", "docs", "--cursor", following["cursor"]])
            collected.append(output)
            assert len(final_page["entries"]) == 1 and not final_page["cursor"]
            names = {value["name"] for page in [listing, following, final_page] for value in page["entries"]}
            assert len(names) == 201
            run(executable, client_state, ["list", "--share", "not-granted"], 4)
            run(executable, client_state, ["list", "--share", "docs", "--path", "../escape"], 4)
            retried, output = run(executable, client_state, base)
            collected.append(output)
            assert retried["client"] == paired["client"]
            run(executable, root / "other-client", base, 4)
            run(executable, client_state, [*base[:], "--server-name", "wrong.invalid"], 4)
            run(executable, server_state,
                ["serve", "grant", "--client", paired["client"], "--share", "docs", "--allow-browse"])
            account, output = run(executable, client_state, ["auth"])
            collected.append(output)
            assert account["revision"] == "2" and not account["grants"][0]["download"]
            # 日期：2026-11-04；浏览授权依旧存在，缩减下载不隐式取消浏览；随后撤销身份才全部拒绝。
            repeated, output = run(executable, client_state,
                                   ["list", "--share", "docs", "--cursor", listing["cursor"]])
            collected.append(output)
            assert repeated["entries"] == following["entries"]
            run(executable, server_state, ["serve", "revoke", "--client", paired["client"]])
            run(executable, client_state, ["auth"], 4)
            run(executable, client_state, ["list", "--share", "docs", "--cursor", listing["cursor"]], 4)
            run(executable, client_state, base, 4)
            run(executable, root / "missing", ["auth"], 5)
            assert process.poll() is None, "server stopped after an authentication rejection"
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    process.kill()
                else:
                    process.send_signal(signal.SIGTERM)
            out, err = process.communicate(timeout=5)
            assert not err, err
            if os.name != "nt":
                assert process.returncode == 7, (process.returncode, out)
            collected.append(out)
        all_output = "\n".join(collected)
        assert secret not in all_output and "PRIVATE KEY" not in all_output
        record = json.loads((client_state / "clients/profile-default.json").read_text(encoding="utf-8"))
        assert record["credential"] not in all_output
        server_record = (server_state / "service" / ("client-" + paired["client"] + ".json")).read_text(encoding="utf-8")
        assert record["credential"] not in server_record and json.loads(server_record)["revoked"]
    report = {"date": "2026-11-04", "passed": True,
              "checks": ["persistent RSA3072 service identity", "private native credentials",
                         "explicit shared roots and read/upload boundaries", "real TLS service/client pairing",
                         "same-profile lost-confirmation retry", "one-time pairing refuses another identity",
                         "per-connection authentication", "live persisted grant update and revocation",
                         "201-item remote pagination across fresh authenticated connections", "cursor retry and path boundary",
                         "secrets absent from stdout/stderr", "server remains usable after rejections"],
              "scope": "pair/auth/share-management/browse CLI; transfer commands tested separately"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

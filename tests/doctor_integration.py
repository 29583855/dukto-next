"""日期：2026-11-07；真实CLI核验本地诊断、原子导出、端口冲突及已配对TLS能力检查。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile

from process_output import JsonOutputDrain
from service_integration import free_port, run


# 日期：2026-11-07；每次只收一个有界JSON事件，错误输出同样保留退出语义，不允许令牌进入报告。
def diagnose(executable, arguments, expected):
    process = subprocess.run([executable, "doctor", *arguments, "--json"],
                             capture_output=True, encoding="utf-8", timeout=30)
    assert process.returncode == expected and not process.stderr, (
        "doctor exit or stderr mismatch", process.returncode, expected)
    assert len(process.stdout.encode("utf-8")) <= 65536
    lines = process.stdout.splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


# 日期：2026-11-07；每项检查只按固定ID取状态，不从本地配置或文件名推断通过。
def check_status(report, name, status):
    rows = [row for row in report["checks"] if row["id"] == name]
    assert len(rows) == 1 and rows[0]["status"] == status


# 日期：2026-11-07；全部自建数据处于临时目录，配对/撤销资料不写公共报告，程序摘要前后必须相同。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    before = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-doctor-") as temporary:
        root = Path(temporary).resolve()
        output, state = root / "接收 目录", root / "state"
        output.mkdir()
        state.mkdir()
        config = root / "settings.ini"
        secret = "DOCTOR-PRIVATE-MARKER-20261107"
        original = ("[General]\nport=4644\ntimeout=30\ncredential=" + secret + "\n").encode()
        config.write_bytes(original)
        base = ["--config-file", str(config), "--state-directory", str(state), "--output", str(output)]
        target = root / "中文 诊断.json"
        report = diagnose(executable, [*base, "--report", str(target)], 0)
        assert report["passed"] and report["reportVersion"] == 1
        assert report["cxxStandard"] == "C++14" and report["sqlite"] and report["tls"]
        assert report["peer"] == {"status": "not-requested"}
        assert json.loads(target.read_text("utf-8")) == report
        assert secret not in target.read_text("utf-8") and str(root) not in target.read_text("utf-8")
        assert config.read_bytes() == original and not list(state.iterdir()) and not list(output.iterdir())
        check_status(report, "configuration", "passed")
        cases.append("bounded local JSON and exact export; no configuration values or absolute paths")

        preserved = target.read_bytes()
        refused = diagnose(executable, [*base, "--report", str(target)], 2)
        assert refused["event"] == "error" and target.read_bytes() == preserved
        assert not list(root.glob("*.part"))
        cases.append("existing report refused and unchanged; no partial final report")

        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            failed = diagnose(executable, [*base, "--bind", "127.0.0.1", "--port", str(port)], 3)
            check_status(failed, "tcp-listener", "failed")
        healthy = diagnose(executable, [*base, "--bind", "127.0.0.1", "--port", str(port)], 0)
        check_status(healthy, "tcp-listener", "passed")
        with socket.socket() as released:
            released.bind(("127.0.0.1", port))
        cases.append("actual occupied TCP failure and post-probe port release")

        for name, data in (("invalid-port", b"[General]\nport=65536\n"),
                           ("malformed-ini", b"[broken\nport=4644\n"),
                           ("oversized-ini", b"x" * 65537)):
            path = root / (name + ".ini")
            path.write_bytes(data)
            failed = diagnose(executable, ["--config-file", str(path)], 2)
            check_status(failed, "configuration", "failed")
            assert path.read_bytes() == data
            cases.append(name + " refused without modifying source")
        missing = root / "missing.ini"
        failed = diagnose(executable, ["--config-file", str(missing)], 2)
        check_status(failed, "configuration", "failed")
        assert not missing.exists()
        cases.append("explicit missing configuration refused without creating it")

        failed = diagnose(executable, ["--output", str(root / "missing-directory")], 2)
        check_status(failed, "output-directory", "failed")
        not_directory = root / "ordinary-file"
        not_directory.write_bytes(b"keep-original")
        failed = diagnose(executable, ["--output", str(not_directory)], 5)
        check_status(failed, "output-directory", "failed")
        assert not_directory.read_bytes() == b"keep-original"
        cases.append("missing or ordinary-file output rejected; original preserved")
        for arguments in (["extra"], ["--to", "127.0.0.1"], ["--threads", "4"],
                          ["--port", "0"], ["--bind", "invalid"],
                          ["--report", ""], ["--port", "4644", "--port", "4645"]):
            result = diagnose(executable, arguments, 2)
            assert result["event"] == "error"
        cases.append("inapplicable, duplicate, malformed and extra arguments rejected")
        process = subprocess.run([executable, "config", "show", "--report", str(root / "wrong.json"), "--json"],
                                 capture_output=True, encoding="utf-8", timeout=10)
        assert process.returncode == 2 and not (root / "wrong.json").exists()
        cases.append("report option rejected for other commands")

        link_checks = []
        if os.name != "nt":
            linked = root / "linked.ini"
            linked.symlink_to(config)
            failed = diagnose(executable, ["--config-file", str(linked)], 4)
            check_status(failed, "configuration", "failed")
            alias = root / "linked-output"
            alias.symlink_to(output, target_is_directory=True)
            failed = diagnose(executable, ["--output", str(alias)], 5)
            check_status(failed, "output-directory", "failed")
            link_checks = ["linked configuration rejected", "linked output rejected"]

        server_state, client_state = root / "server", root / "client"
        shared = root / "share"
        shared.mkdir()
        info, _ = run(executable, server_state, ["serve", "init", "--server-name", "127.0.0.1"])
        run(executable, server_state, ["serve", "share", "add", "--share", "data", "--path", str(shared), "--allow-browse"])
        offer, _ = run(executable, server_state, ["serve", "pairing", "--share", "data", "--allow-browse"])
        port = free_port()
        server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(server_state),
                                   "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        drain = None
        try:
            assert json.loads(server.stdout.readline())["event"] == "service-listening"
            drain = JsonOutputDrain(server.stdout)
            pair, _ = run(executable, client_state, ["pair", "--to", "127.0.0.1:" + str(port),
                         "--fingerprint", info["fingerprint"], "--credential-file", offer["credentialFile"]])
            profile = client_state / "clients/profile-default.json"
            original_profile = profile.read_bytes()
            capability_report = root / "capabilities.json"
            report = diagnose(executable, ["--state-directory", str(client_state), "--profile", "default",
                                          "--timeout", "3", "--report", str(capability_report)], 0)
            assert report["peer"]["status"] == "passed" and report["peer"]["tlsIdentityVerified"]
            assert report["peer"]["authenticated"]
            assert report["peer"]["capabilities"]["parallel-transfer-v1"]
            assert all(type(value) is bool for value in report["peer"]["capabilities"].values())
            credential = json.loads(original_profile)["credential"]
            assert credential not in capability_report.read_text("utf-8")
            assert profile.read_bytes() == original_profile
            cases.append("explicit paired TLS identity/authentication and fixed capability booleans; profile unchanged")
            run(executable, server_state, ["serve", "revoke", "--client", pair["client"]])
            failed = diagnose(executable, ["--state-directory", str(client_state), "--profile", "default", "--timeout", "3"], 4)
            assert failed["peer"]["status"] == "failed" and not failed["passed"]
            assert profile.read_bytes() == original_profile
            cases.append("revoked peer fails authentication without changing trust or falling back")
        finally:
            if server.poll() is None:
                server.kill() if os.name == "nt" else server.send_signal(signal.SIGTERM)
            server.wait(timeout=10)
            if drain:
                drain.finish()
            assert not server.stderr.read()
    after = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    assert before == after
    report = {"date": "2026-11-07", "passed": True, "binarySha256": before,
              "binaryUnchanged": True, "checks": cases, "posixLinkChecks": link_checks,
              "nativeSaveDialogVerified": False, "entireR10Qualified": False}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"passed": True, "checks": len(cases), "posixLinkChecks": len(link_checks)}))


if __name__ == "__main__":
    main()

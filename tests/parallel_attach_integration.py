"""日期：2026-11-05；实际TLS重复目录冲突验证：加入握手不得被尚未发出的组错误中断。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time


# 日期：2026-11-05；检查客户端退出、全部数据连接根因和持久状态，失败仍保存完整报告。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    from parallel_failure_integration import CauseDrain
    from service_integration import free_port, run
    executable = str(args.executable.resolve())
    assert not args.report.exists()
    cases = []
    report = {"date": "2026-11-05", "passed": False, "cases": cases,
              "executableSha256": hashlib.sha256(args.executable.read_bytes()).hexdigest(),
              "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "16 immediate directory conflicts; 4/16 TLS lanes; original target, all connection causes and task state"}
    with tempfile.TemporaryDirectory(prefix="dukto-r38-cause-") as temporary:
        root = Path(temporary)
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        source = root / "source"
        (source / "资料/empty-dir").mkdir(parents=True)
        (source / "资料/empty-file").touch()
        (source / "资料/content.bin").write_bytes(bytes(range(251)) * 4099 + b"tail")
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        port = free_port()
        process = subprocess.Popen([executable, "serve", "start", "--state-directory", str(server),
                                    "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        drain = CauseDrain(process.stdout)
        try:
            deadline = time.monotonic() + 15
            while not drain.events.get("service-listening"):
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)
            run(executable, client, ["pair", "--to", f"127.0.0.1:{port}",
                                    "--fingerprint", info["fingerprint"],
                                    "--credential-file", offer["credentialFile"]])
            for channels in (4, 16):
                for trial in range(8):
                    destination = shared / f"target-{channels}-{trial}"
                    (destination / source.name).mkdir(parents=True)
                    preserved = destination / source.name / "preserved"
                    preserved.write_bytes(b"original")
                    previous = drain.causes.copy()
                    started = time.monotonic()
                    result = subprocess.run([executable, "upload", "--path", str(source), "--share", "data",
                                             "--remote-path", destination.name, "--threads", str(channels),
                                             "--on-conflict", "fail", "--state-directory", str(client), "--json"],
                                            capture_output=True, encoding="utf-8", timeout=90)
                    events = [json.loads(line) for line in result.stdout.splitlines()]
                    task = next(event["taskId"] for event in events if event.get("taskId"))
                    status, _ = run(executable, client, ["task", "--task", task])
                    deadline = time.monotonic() + 5
                    while sum(drain.causes.values()) - sum(previous.values()) < channels + 1 and time.monotonic() < deadline:
                        time.sleep(0.01)
                    causes = drain.causes - previous
                    case = {"channels": channels, "trial": trial, "exitCode": result.returncode,
                            "lastEvent": events[-1], "stderr": result.stderr,
                            "seconds": round(time.monotonic() - started, 3),
                            "serverCauses": [{"code": key[0], "stage": key[1], "count": count}
                                             for key, count in sorted(causes.items())],
                            "persistedState": status["state"], "persistedError": status["error"],
                            "originalPreserved": preserved.read_bytes() == b"original"}
                    case["passed"] = (result.returncode == 4 and events[-1].get("stage") == "conflict"
                                      and causes == Counter({(4, "conflict"): channels + 1})
                                      and status["state"] == "failed" and status["error"] == 4
                                      and case["originalPreserved"] and not result.stderr)
                    cases.append(case)
                    print(json.dumps(case, ensure_ascii=False), flush=True)
        finally:
            process.kill()
            process.wait(timeout=10)
            drain.finish()
            assert not process.stderr.read()
    report["passed"] = all(case["passed"] for case in cases)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": len(cases)}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

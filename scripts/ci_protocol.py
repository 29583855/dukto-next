"""日期：2026-11-05；独立执行各协议专项并汇总失败，任一失败仍使CI失败。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


# 日期：2026-11-05；集中声明既有真实专项，三平台保持原参数和时限，不用后续成功覆盖先前失败。
def commands(build):
    windows = sys.platform == "win32"
    binary = build / "Release" if windows else build
    suffix = ".exe" if windows else ""
    cli = str(binary / ("dukto-cli" + suffix))
    cases = []

    # 日期：2026-11-05；每个专项拥有唯一报告，统一使用当前解释器和UTF-8输出。
    def add(name, script, *arguments, executable=cli):
        report = build / (name + ".json")
        cases.append((name, [sys.executable, "-X", "utf8", "tests/" + script + ".py",
                             executable, *arguments, "--report", str(report)], report))

    add("parallel-failure", "parallel_failure_integration")
    add("legacy", "legacy_integration")
    add("cli", "cli_contracts")
    add("crash", "crash_integration")
    if windows:
        add("windows-path", "windows_path_integration")
        add("windows-signal", "windows_signal_integration")
    else:
        add("posix-path", "posix_path_integration")
    add("service", "service_integration")
    add("client-list", "client_list_integration")
    add("credential-rotation", "credential_rotation_integration")
    add("session-expiry", "session_expiry_integration")
    add("task-admission-upload", "task_admission_integration")
    add("task-admission-download", "task_admission_integration", "--mode", "download")
    add("task-admission-mixed", "task_admission_integration", "--mode", "mixed")
    add("transfer-retry", "transfer_retry_integration")
    add("conflict-fail", "conflict_fail_integration")
    add("task-items", "task_items_integration")
    recovery = ("--threads", "4", "--resume-threads", "8", "--files", "4", "--payload-mib", "8",
                "--checkpoint-percent", "50")
    add("conflict-fail-recovery", "transfer_recovery_integration", "--on-conflict", "fail", *recovery)
    add("transfer", "transfer_integration")
    add("transfer-recovery", "transfer_recovery_integration")
    add("parallel-transfer", "parallel_transfer_integration")
    add("parallel-recovery", "transfer_recovery_integration", *recovery)
    add("parallel-isolation", "parallel_isolation_integration")
    add("byte-progress", "byte_progress_integration")
    add("transfer-faults", "transfer_faults_integration")
    add("final-ack", "final_ack_integration")
    add("final-ack-auto-retry", "final_ack_integration", "--auto-retries", "3")
    add("gui-process-recovery", "gui_process_recovery_integration",
        str(binary / ("server-panel-process-probe" + suffix)))
    add("task-store", "task_store_integration", executable=str(binary / ("task-store-probe" + suffix)))
    if windows:
        add("secure-channel", "secure_channel_integration", "--openssl", ".tools/openssl/Library/bin/openssl.exe",
            executable=str(binary / "secure-channel-probe.exe"))
    return cases


# 日期：2026-11-05；实时转发子进程输出、不积累日志正文，分别保存退出码/耗时/摘要并在结束返回总失败。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-directory", type=Path, default=Path("build"))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    build = args.build_directory
    cases = commands(build)
    if args.list:
        print(json.dumps([{"name": name, "command": command} for name, command, _ in cases],
                         ensure_ascii=False, indent=2))
        return 0
    summary = {"date": datetime.now(timezone.utc).isoformat(), "platform": sys.platform,
               "sourceCommit": os.environ.get("GITHUB_SHA"), "passed": False, "completed": False,
               "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "cases": []}
    destination = build / "protocol-suite.json"
    build.mkdir(parents=True, exist_ok=True)
    for name, command, report in cases:
        assert not report.exists(), ("Existing CI report cannot be reused", report)
        print("::group::Protocol integration: " + name, flush=True)
        started = time.monotonic()
        result = subprocess.run(command, check=False)
        entry = {"name": name, "exitCode": result.returncode,
                 "seconds": round(time.monotonic() - started, 3), "report": str(report),
                 "reportCreated": report.is_file(), "passed": result.returncode == 0 and report.is_file()}
        if report.is_file():
            entry["reportSha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
        summary["cases"].append(entry)
        destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        print("::endgroup::", flush=True)
        if not entry["passed"]:
            print("::error::Protocol integration failed: " + name, flush=True)
    summary["completed"] = True
    summary["passed"] = all(case["passed"] for case in summary["cases"])
    destination.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

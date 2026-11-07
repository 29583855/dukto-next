"""日期：2026-11-07；使用指定原生预览包复验故障契约，区分应用源码与新测试脚本的提交。"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile

from transfer_integration import digest


# 日期：2026-11-07；先核对已知归档摘要、路径与链接边界，迁移后再逐件核对包清单。
def unpack(archive, expected, working, application_source):
    assert digest(archive) == expected
    with tarfile.open(archive) as source:
        names = set()
        total = 0
        for item in source.getmembers():
            assert item.name not in names
            names.add(item.name)
            path = working / item.name
            assert not Path(item.name).is_absolute() and path.resolve().is_relative_to(working)
            assert not item.islnk() and (item.isfile() or item.isdir() or item.issym())
            total += item.size
            assert 0 <= item.size <= 256 * 1024**2 and total <= 1024**3
            if item.issym():
                assert not Path(item.linkname).is_absolute()
                assert (path.parent / item.linkname).resolve().is_relative_to(working)
        source.extractall(working, filter="data")
    stage, = working.iterdir()
    manifest = json.loads((stage / "package-manifest.json").read_text("utf-8"))
    assert manifest["sourceCommit"] == application_source
    assert manifest["architecture"] == platform.machine()
    for item in manifest["files"]:
        path = stage / item["path"]
        assert path.resolve().is_relative_to(stage) and path.is_file() and not path.is_symlink()
        assert path.stat().st_size == item["bytes"] and digest(path) == item["sha256"]
    for item in manifest["links"]:
        path = stage / item["path"]
        assert path.is_symlink() and os.readlink(path) == item["target"]
        assert path.resolve(strict=True).is_relative_to(stage)
    executable = stage / "Dukto Next.app/Contents/MacOS/dukto-cli"
    assert os.access(executable, os.X_OK)
    return executable


# 日期：2026-11-07；独立两轮rename/overwrite故障保留真实报告、期限和数据保护断言，不覆盖历史失败。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--application-source", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assert platform.system() == "Darwin"
    report = args.report.resolve()
    assert not report.exists()
    report.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("QT_", "QML", "DYLD_"))}
    environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    records = []
    with tempfile.TemporaryDirectory(prefix="dukto-fault-regression-") as temporary:
        working = Path(temporary).resolve() / "中文路径 with spaces"
        working.mkdir()
        executable = unpack(args.archive.resolve(), args.sha256, working, args.application_source)
        binary_before = digest(executable)
        commands = [("expectations", [sys.executable, "-X", "utf8", "tests/transfer_fault_expectations_tests.py"])]
        for round_number in (1, 2):
            for policy in ("rename", "overwrite"):
                name = f"{policy}-{round_number}"
                target = report.with_name(name + ".json")
                commands.append((name, [sys.executable, "-X", "utf8", "tests/transfer_faults_integration.py",
                                       str(executable), "--on-conflict", policy, "--report", str(target)]))
        for name, command in commands:
            result = subprocess.run(command, cwd=root, env=environment, capture_output=True, timeout=180)
            log = report.with_name(name + ".log")
            log.write_bytes(result.stdout + result.stderr)
            assert result.returncode == 0, (name, result.returncode, result.stdout, result.stderr)
            record = {"name": name, "exitCode": 0, "logSha256": digest(log)}
            if name != "expectations":
                target = report.with_name(name + ".json")
                value = json.loads(target.read_text("utf-8"))
                assert value["passed"] and len(value["cases"]) == 6
                assert value["executableSha256"] == binary_before
                assert value["testScriptSha256"] == digest(root / "tests/transfer_faults_integration.py")
                for case in value["cases"]:
                    assert case["originalPreserved"] and case["noPublishedCopy"]
                    assert case["secondsAfterFault"] < case["deadlineSeconds"]
                    assert case["serverTask"]["state"] in ("failed", "interrupted")
                record.update(report=target.name, reportSha256=digest(target), cases=6,
                              pathIntegrityRefusals=sum(case["pathIntegrityRefusalAccepted"] for case in value["cases"]))
            records.append(record)
        binary_after = digest(executable)
        assert binary_before == binary_after
    value = {"date": datetime.now(timezone.utc).isoformat(), "passed": True,
             "applicationSourceCommit": args.application_source, "harnessCommit": os.environ.get("GITHUB_SHA"),
             "architecture": platform.machine(), "archiveSha256": args.sha256,
             "scriptSha256": digest(Path(__file__)), "faultScriptSha256": digest(root / "tests/transfer_faults_integration.py"),
             "cliSha256Before": binary_before, "cliSha256After": binary_after, "binaryUnchanged": True,
             "systemPathOnly": True, "records": records, "faultCases": 24,
             "scope": "Two rounds of six fault cases for rename and overwrite using the immutable R111 preview; original full-suite failure retained; no full-suite requalification",
             "deliveryComplete": False, "releaseQualified": False}
    report.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"passed": True, "architecture": platform.machine(), "faultCases": 24,
                      "binaryUnchanged": True}), flush=True)


if __name__ == "__main__":
    main()

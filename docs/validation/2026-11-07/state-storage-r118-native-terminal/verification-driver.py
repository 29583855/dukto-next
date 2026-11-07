"""日期：2026-11-07；增量收验R118终态作业及原协议附件，原失败和未完成作业分别保留。"""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import runpy
import stat
import zipfile

SOURCE = json.loads(Path(".cache/r118-ci-runs.json").read_bytes())["sourceCommit"]
RUN = json.loads(Path(".cache/r118-ci-runs.json").read_bytes())["nativeRunId"]


# 日期：2026-11-07；先验证官方ZIP摘要与安全路径，仅将原始文本证据写入发布目录，完整ZIP保存在缓存。
def extract(raw, output):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set()
        total = 0
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            assert not name.is_absolute() and ".." not in name.parts and ":" not in member.filename
            assert member.filename not in names and not stat.S_ISLNK(member.external_attr >> 16)
            names.add(member.filename)
            total += member.file_size
            assert member.file_size <= 32 * 1024**2 and total <= 128 * 1024**2
            if member.is_dir() or name.suffix.lower() not in (".json", ".xml", ".log", ".txt", ".sha256"):
                continue
            path = output / member.filename
            data = archive.read(member)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                assert path.read_bytes() == data
            else:
                path.write_bytes(data)


# 日期：2026-11-07；每个真正终态job分别核对精确源脚本、全部协议原件和关键业务报告，不替其他job授予资格。
def main():
    root = Path(r"E:\project\dukto")
    repo = root / ".cache/github-29583855-dukto-next-r28"
    request = runpy.run_path(str(root / ".cache/github-actions-r28.py"))["request"]
    helper = runpy.run_path(str(root / ".cache/collect-exact-native-r87.py"))
    base = "/repos/29583855/dukto-next"
    run_path = base + "/actions/runs/" + str(RUN)
    run = request(run_path)
    assert run["head_sha"] == SOURCE and run["run_attempt"] == 1
    jobs = request(run_path + "/jobs?per_page=100")["jobs"]
    artifacts = request(run_path + "/artifacts?per_page=100")["artifacts"]
    output = repo / "docs/validation/2026-11-07/state-storage-r118-native-terminal"
    output.mkdir(exist_ok=True)
    records = []
    for runner in ("ubuntu-22.04", "macos-15", "macos-15-intel", "windows-2022"):
        job, = [job for job in jobs if job["name"].startswith("native (" + runner + ",")]
        if job["status"] != "completed":
            records.append({"runner": runner, "status": job["status"], "qualified": False})
            continue
        folder = output / runner
        receipt_path = folder / "receipt.json"
        if receipt_path.exists():
            existing = json.loads(receipt_path.read_text("utf-8"))
            if existing.get("status") == "completed":
                records.append(existing)
                continue
        item, = [item for item in artifacts if item["name"] == "validation-" + runner]
        cache = root / ".cache/state-storage-r118-terminal-artifacts"
        cache.mkdir(exist_ok=True)
        archive = cache / (str(item["id"]) + ".zip")
        raw = archive.read_bytes() if archive.exists() else request(base + "/actions/artifacts/" + str(item["id"]) + "/zip", binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item["digest"] == "sha256:" + digest and not item["expired"]
        if not archive.exists():
            archive.write_bytes(raw)
        folder.mkdir(exist_ok=True)
        extract(raw, folder)
        log_path = folder / "job.log"
        if not log_path.exists():
            log_path.write_bytes(request(base + "/actions/jobs/" + str(job["id"]) + "/logs", binary=True))
        record = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": SOURCE,
                  "runner": runner, "jobId": job["id"], "status": job["status"],
                  "conclusion": job["conclusion"], "artifactId": item["id"],
                  "artifactSha256": digest, "jobLogSha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
                  "steps": job["steps"], "qualified": False,
                  "deliveryComplete": False, "releaseQualified": False}
        suite_path = folder / "build/protocol-suite.json"
        if job["conclusion"] == "success":
            suite = helper["protocol"](suite_path, SOURCE)
            assert suite["passed"]
            tls = json.loads((folder / "build/secure-channel.json").read_text("utf-8"))
            assert tls["passed"] and len(tls["cases"]) == 31
            guard = json.loads((folder / "build/task-store.json").read_text("utf-8"))
            assert guard["passed"] and guard["competingProcesses"] == 8 and guard["leaseRecoveredAfterKill"]
            assert guard["stateDirectoryUse"]["sharedProcesses"] == 8
            doctor = json.loads((folder / "build/doctor.json").read_text("utf-8"))
            assert doctor["passed"] and doctor["binaryUnchanged"] and len(doctor["checks"]) == 12
            navigation = json.loads((folder / "build/main-window-navigation.json").read_text("utf-8"))
            assert navigation["passed"] and navigation["sourceCommit"] == SOURCE and navigation["binaryUnchanged"]
            extras = [folder / "proxy-pacing.json", folder / "build/main-window-navigation.json"]
            if runner.startswith("macos-"):
                extras += [folder / "build/macos-native-render.json", folder / "build/macos-native-process-recovery.json"]
            if runner == "ubuntu-22.04":
                extras += [folder / "build/disk.json", folder / "build/parallel-disk.json"]
            for path in extras:
                value = json.loads(path.read_text("utf-8"))
                assert value["passed"]
                helper["verify_passed"](value)
            record.update(qualified=True, verifiedProtocol=suite, secureChannelCases=31,
                          taskStoreCompetingProcesses=8, sharedStateProcesses=8,
                          doctorChecks=12, additionalReports=[helper["proof"](path) for path in extras])
        elif suite_path.exists():
            suite = json.loads(suite_path.read_text("utf-8"))
            assert suite["sourceCommit"] == SOURCE
            record["failedProtocolCases"] = [case for case in suite["cases"] if not case["passed"]]
        receipt_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")
        records.append(record)
        print(json.dumps({"runner": runner, "conclusion": job["conclusion"], "qualified": record["qualified"],
                          "protocolCases": record.get("verifiedProtocol", {}).get("cases"),
                          "failedCases": record.get("failedProtocolCases")}), flush=True)
    receipt = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": SOURCE,
               "run": {key: run[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
               "records": records, "allFourNativeProtocolJobsVerified": len(records) == 4 and all(row["qualified"] for row in records),
               "releaseQualified": False, "deliveryComplete": False}
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (output / "verification-driver.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"runStatus": run["status"], "runConclusion": run["conclusion"],
                      "verifiedJobs": sum(row["qualified"] for row in records)}), flush=True)


if __name__ == "__main__":
    main()

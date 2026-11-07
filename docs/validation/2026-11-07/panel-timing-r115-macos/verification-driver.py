"""日期：2026-11-07；逐架构收验R115完整面板原件，不覆盖R114失败或授予整体资格。"""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import runpy
import stat
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
SOURCE = "cfd66f596098ee747066752db90b15bbe0586970"
BASELINE = "d922dc4c793c77de0553ddf44c0fe1fa2d998c24"
RUN = 42372364118
OUTPUT = REPO / "docs/validation/2026-11-07/panel-timing-r115-macos"
METHODS = {"initTestCase", "publicSkipQml", "uploadManifestAcrossPanelRestart",
           "certificateLifecycleQml", "queuedProductionControls",
           "productionServiceAndQml", "cleanupTestCase"}


# 日期：2026-11-07；只从官方摘要匹配的ZIP读取有界普通文本，拒绝重复、链接和Windows路径穿越。
def extract(raw, folder):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        seen = set()
        total = 0
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            assert not path.is_absolute() and ".." not in path.parts
            assert "\\" not in item.filename and ":" not in item.filename
            assert item.filename not in seen and not stat.S_ISLNK(item.external_attr >> 16)
            seen.add(item.filename)
            total += item.file_size
            assert item.file_size <= 8 * 1024**2 and total <= 32 * 1024**2
            if item.is_dir():
                continue
            assert path.suffix in (".txt", ".sha256", ".log", ".xml")
            target = folder / item.filename
            data = archive.read(item)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == data
            else:
                target.write_bytes(data)


# 日期：2026-11-07；各轮独立核对退出码、完整CTest和七个真实Qt方法，不以某个业务子集替代全套。
def verify_round(folder):
    assert (folder / "exit-code.txt").read_text("utf-8").strip() == "0"
    ctest = (folder / "ctest.log").read_text("utf-8")
    assert re.search(r"100% tests passed(?:, 0 tests failed)? out of 1(?:\r?\n|$)", ctest)
    assert re.search(r"Test\s+#\d+: server-panel-tests\s+\.+\s+Passed", ctest)
    log = (folder / "server-panel-tests.log").read_text("utf-8")
    assert "7 passed, 0 failed, 0 skipped" in log
    xml = ET.parse(folder / "server-panel-tests.xml").getroot()
    assert xml.tag == "testsuite" and xml.get("name") == "ServerPanelTests"
    assert xml.get("tests") == "7" and xml.get("failures") == "0" and xml.get("errors") == "0"
    cases = xml.findall("testcase")
    assert len(cases) == 7 and {case.get("name") for case in cases} == METHODS
    assert all(case.get("result") == "pass" and len(case) == 0 for case in cases)
    return {"passed": True, "completePanelMethodsPassed": 7,
            "files": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                      for path in sorted(folder.iterdir()) if path.is_file()]}


# 日期：2026-11-07；每次观察同一次运行，先保留失败原件再判定；未完成作业维持待验。
def main():
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    base = "/repos/29583855/dukto-next"
    run_path = base + "/actions/runs/" + str(RUN)
    run = request(run_path)
    assert run["head_sha"] == SOURCE and run["run_attempt"] == 1
    jobs = request(run_path + "/jobs?per_page=100")["jobs"]
    artifacts = request(run_path + "/artifacts?per_page=100")["artifacts"]
    assert len(jobs) == 2
    application_paths = ["CMakeLists.txt", ".clang-format", "src", "ui", "resources", "scripts"]
    comparison = subprocess.run(["git", "diff", "--quiet", BASELINE, SOURCE, "--"] + application_paths,
                                cwd=REPO, capture_output=True)
    assert comparison.returncode == 0
    OUTPUT.mkdir(exist_ok=True)
    records = []
    for runner, architecture in (("macos-15", "ARM64"), ("macos-15-intel", "X64")):
        job, = [item for item in jobs if item["name"] == "panel (" + runner + ")"]
        record = {"runner": runner, "architecture": architecture, "jobId": job["id"],
                  "status": job["status"], "conclusion": job["conclusion"], "qualified": False}
        if job["status"] == "completed":
            artifact, = [item for item in artifacts if item["name"] == "macos-panel-" + architecture]
            cache = ROOT / ".cache/r115-macos-panel-artifacts"
            cache.mkdir(exist_ok=True)
            saved = cache / (str(artifact["id"]) + ".zip")
            raw = saved.read_bytes() if saved.exists() else request(
                base + "/actions/artifacts/" + str(artifact["id"]) + "/zip", binary=True)
            digest = hashlib.sha256(raw).hexdigest()
            assert not artifact["expired"] and artifact["digest"] == "sha256:" + digest
            assert len(raw) == artifact["size_in_bytes"]
            if not saved.exists():
                saved.write_bytes(raw)
            folder = OUTPUT / runner
            folder.mkdir(exist_ok=True)
            extract(raw, folder)
            log = folder / "job.log"
            if not log.exists():
                log.write_bytes(request(base + "/actions/jobs/" + str(job["id"]) + "/logs", binary=True))
            record.update(artifactId=artifact["id"], artifactSha256=digest,
                          artifactUrl=run["html_url"] + "/artifacts/" + str(artifact["id"]),
                          jobLogSha256=hashlib.sha256(log.read_bytes()).hexdigest())
            source_path, = list(folder.rglob("source-commit.txt"))
            evidence = source_path.parent
            assert source_path.read_text("utf-8").strip() == SOURCE
            before = (evidence / "binary-before.sha256").read_bytes()
            after = (evidence / "binary-after.sha256").read_bytes()
            assert before == after
            match = re.fullmatch(rb"([a-f0-9]{64})\s+build/server-panel-tests\r?\n", before)
            assert match
            record["binarySha256"] = match.group(1).decode("ascii")
            if job["conclusion"] == "success":
                record["rounds"] = [verify_round(evidence / ("round-" + str(i))) for i in (1, 2)]
                record["qualified"] = True
            else:
                record["failureOriginalsRetained"] = True
        records.append(record)
    passed = (run["status"] == "completed" and run["conclusion"] == "success"
              and len(records) == 2 and all(item["qualified"] for item in records))
    receipt = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": SOURCE,
               "baselineApplicationSourceCommit": BASELINE, "applicationInputsMatchBaseline": True,
               "run": {key: run[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
               "records": records, "bothArchitecturesTwoCompleteRoundsVerified": passed,
               "originalR114FailureRetained": True, "deliveryComplete": False, "releaseQualified": False}
    (OUTPUT / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (OUTPUT / "verification-driver.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"run": RUN, "status": run["status"], "conclusion": run["conclusion"],
                      "qualified": passed, "records": records}))


if __name__ == "__main__":
    main()

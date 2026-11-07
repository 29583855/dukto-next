"""日期：2026-11-07；逐件收验指定Mac故障专项，不以新夹具通过覆盖原完整协议失败。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
HARNESS = "10c026577449e089720471fc4a43c3da5bf627a4"
APPLICATION = "dfe245b502f586e7df7219e8fb0d5e4030a6b032"
RUN = 42366735173


# 日期：2026-11-07；原件摘要以字节为准，脚本必须匹配实际运行提交。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-07；严格核对两架构24个真实故障、原始报告SHA及冻结程序，不授予完整协议资格。
def main():
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    helper = runpy.run_path(str(ROOT / ".cache/collect-r111-completed-native-jobs.py"))
    api = "/repos/29583855/dukto-next"
    path = api + "/actions/runs/" + str(RUN)
    run = request(path)
    assert run["head_sha"] == HARNESS and run["run_attempt"] == 1
    jobs = request(path + "/jobs?per_page=100")["jobs"]
    artifacts = request(path + "/artifacts?per_page=100")["artifacts"]
    output = REPO / "docs/validation/2026-11-07/fault-refusal-r112-macos"
    output.mkdir(exist_ok=True)
    records = []
    for runner, architecture in (("macos-15", "arm64"), ("macos-15-intel", "x86_64")):
        job, = [item for item in jobs if item["name"].startswith("fault-regression (" + runner + ",")]
        if job["status"] != "completed":
            records.append({"architecture": architecture, "status": job["status"], "qualified": False})
            continue
        folder = output / architecture
        folder.mkdir(exist_ok=True)
        receipt = folder / "receipt.json"
        if receipt.exists():
            records.append(json.loads(receipt.read_text("utf-8")))
            continue
        log = request(api + "/actions/jobs/" + str(job["id"]) + "/logs", binary=True)
        (folder / "job.log").write_bytes(log)
        item, = [item for item in artifacts if item["name"] == "macos-fault-regression-" + architecture]
        raw = request(api + "/actions/artifacts/" + str(item["id"]) + "/zip", binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item["digest"] == "sha256:" + digest and not item["expired"]
        archive = ROOT / (".cache/r112-macos-fault-" + architecture + ".zip")
        if archive.exists():
            assert archive.read_bytes() == raw
        else:
            archive.write_bytes(raw)
        helper["extract"](raw, folder)
        record = {"architecture": architecture, "jobId": job["id"], "status": job["status"],
                  "conclusion": job["conclusion"], "artifactId": item["id"], "artifactSha256": digest,
                  "jobLogSha256": sha(folder / "job.log"), "qualified": False}
        if job["conclusion"] == "success":
            value = json.loads((folder / "report.json").read_text("utf-8"))
            assert value["passed"] and value["harnessCommit"] == HARNESS and value["applicationSourceCommit"] == APPLICATION
            assert value["architecture"] == architecture and value["faultCases"] == 24
            assert value["binaryUnchanged"] and value["cliSha256Before"] == value["cliSha256After"]
            assert value["systemPathOnly"]
            expected = {"scriptSha256": "tests/macos_fault_regression_integration.py",
                        "faultScriptSha256": "tests/transfer_faults_integration.py"}
            for field, name in expected.items():
                content = subprocess.check_output(["git", "show", HARNESS + ":" + name], cwd=REPO)
                assert value[field] == hashlib.sha256(content).hexdigest()
            assert [item["name"] for item in value["records"]] == ["expectations", "rename-1", "overwrite-1", "rename-2", "overwrite-2"]
            path_refusals = 0
            for item in value["records"]:
                assert item["exitCode"] == 0 and sha(folder / (item["name"] + ".log")) == item["logSha256"]
                if item["name"] == "expectations":
                    assert "Ran 4 tests" in (folder / "expectations.log").read_text("utf-8")
                    continue
                report = folder / item["report"]
                assert sha(report) == item["reportSha256"] and item["cases"] == 6
                body = json.loads(report.read_text("utf-8"))
                assert body["passed"] and len(body["cases"]) == 6
                assert body["executableSha256"] == value["cliSha256Before"] and body["testScriptSha256"] == value["faultScriptSha256"]
                hits = 0
                for case in body["cases"]:
                    assert case["originalPreserved"] and case["noPublishedCopy"]
                    assert case["secondsAfterFault"] < case["deadlineSeconds"]
                    assert case["serverTask"]["state"] in ("failed", "interrupted")
                    if case["pathIntegrityRefusalAccepted"]:
                        error = case["clientError"]
                        assert case["fault"] in ("revoke", "root-reconfigure")
                        assert error["code"] == 6 and error["stage"] == "read"
                        assert error["message"] in ("源文件路径在读取期间已被替换", "读取期间源文件已变化")
                        assert case["serverTask"]["confirmed"] < case["serverTask"]["total"]
                        hits += 1
                assert hits == item["pathIntegrityRefusals"]
                path_refusals += hits
            record.update(qualified=True, cases=24, exactPathIntegrityRefusals=path_refusals,
                          summarySha256=sha(folder / "report.json"), binarySha256=value["cliSha256Before"])
        receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")
        records.append(record)
    result = {"observedUtc": datetime.now(timezone.utc).isoformat(), "harnessCommit": HARNESS,
              "applicationSourceCommit": APPLICATION, "run": {key: run[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
              "records": records, "bothArchitecturesVerified": len(records) == 2 and all(item["qualified"] for item in records),
              "originalFullSuiteFailuresRetained": True, "fullSuiteRequalified": False,
              "deliveryComplete": False, "releaseQualified": False}
    (output / "receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(Path(__file__), output / "verification-driver.py")
    print(json.dumps({"runStatus": run["status"], "runConclusion": run["conclusion"],
                      "bothArchitecturesVerified": result["bothArchitecturesVerified"], "records": records}), flush=True)


if __name__ == "__main__":
    main()

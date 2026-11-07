"""日期：2026-11-07；保存旧源码原生失败原件，避免把已结束的失败写作进行中。"""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import runpy
import stat
import zipfile


# 日期：2026-11-07；核验指定旧运行身份及附件摘要，只保留协议失败相关文本，不改写原始结果。
def main():
    root = Path(r"E:\project\dukto")
    repo = root / ".cache/github-29583855-dukto-next-r28"
    request = runpy.run_path(str(root / ".cache/github-actions-r28.py"))["request"]
    base = "/repos/29583855/dukto-next"
    run_path = base + "/actions/runs/42340140189"
    run = request(run_path)
    assert run["head_sha"] == "6eea9d23a254ac0095e588b03d76c19faf7bf5cf"
    assert run["status"] == "completed" and run["conclusion"] == "failure"
    jobs = request(run_path + "/jobs?per_page=100")["jobs"]
    failed, = [job for job in jobs if job["conclusion"] == "failure"]
    assert failed["name"] == "native (macos-15-intel, brew)"
    artifacts = request(run_path + "/artifacts?per_page=100")["artifacts"]
    item, = [item for item in artifacts if item["name"] == "validation-macos-15-intel"]
    raw = request(base + "/actions/artifacts/" + str(item["id"]) + "/zip", binary=True)
    digest = hashlib.sha256(raw).hexdigest()
    assert item["digest"] == "sha256:" + digest and not item["expired"]
    cache = root / ".cache/r109-prior-ci-artifacts"
    cache.mkdir(exist_ok=True)
    (cache / (str(item["id"]) + ".zip")).write_bytes(raw)
    output = repo / "docs/validation/2026-11-07/client-cleanup-r109-prior-ci"
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        assert len({member.filename for member in members}) == len(members)
        total = 0
        for member in members:
            name = PurePosixPath(member.filename)
            assert not name.is_absolute() and ".." not in name.parts and ":" not in member.filename
            assert not stat.S_ISLNK(member.external_attr >> 16)
            total += member.file_size
            assert member.file_size < 32 * 1024**2 and total < 128 * 1024**2
        suite = json.loads(archive.read("build/protocol-suite.json"))
        assert suite["sourceCommit"] == run["head_sha"] and suite["completed"] and not suite["passed"]
        failed_cases = [case for case in suite["cases"] if not case["passed"]]
        assert failed_cases
        selected = {"build/protocol-suite.json"}
        for case in failed_cases:
            name = PurePosixPath(case["report"].replace("\\", "/")).name
            if case["reportCreated"]:
                data = archive.read("build/" + name)
                assert hashlib.sha256(data).hexdigest() == case["reportSha256"]
                selected.add("build/" + name)
            for candidate in archive.namelist():
                if candidate.endswith(".log") and (case["name"] in PurePosixPath(candidate).name):
                    selected.add(candidate)
        for name in sorted(selected):
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    job_log = request(base + "/actions/jobs/" + str(failed["id"]) + "/logs", binary=True)
    (output / "intel-job.log").write_bytes(job_log)
    receipt = {
        "observedUtc": datetime.now(timezone.utc).isoformat(),
        "sourceCommit": run["head_sha"],
        "run": {key: run[key] for key in ("id", "status", "conclusion", "html_url")},
        "jobs": [{key: job[key] for key in ("id", "name", "status", "conclusion", "steps")} for job in jobs],
        "artifactId": item["id"],
        "artifactSha256": digest,
        "jobLogSha256": hashlib.sha256(job_log).hexdigest(),
        "failedProtocolCases": failed_cases,
        "protocolCaseCount": len(suite["cases"]),
        "originalFailureRetained": True,
        "fullRunQualified": False,
        "deliveryComplete": False,
        "releaseQualified": False,
    }
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    (output / "collection-driver.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"run": run["id"], "conclusion": run["conclusion"], "failedCases": failed_cases}))


if __name__ == "__main__":
    main()

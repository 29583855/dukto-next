"""日期：2026-11-07；增量核验R111双Mac含依赖预览包、精确源码与迁移原件，未终态不授予资格。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil

SOURCE = "dfe245b502f586e7df7219e8fb0d5e4030a6b032"
RUN = 42363743119


# 日期：2026-11-07；分别收验真正成功的架构，失败保存原始日志；ZIP和程序仅留本机dist。
def main():
    root = Path(r"E:\project\dukto")
    repo = root / ".cache/github-29583855-dukto-next-r28"
    request = runpy.run_path(str(root / ".cache/github-actions-r28.py"))["request"]
    helper = runpy.run_path(str(root / ".cache/verify-client-history-r80-packages.py"))
    helper["payload_proof"].__globals__.update(COMMIT=SOURCE, CHECKOUT=repo)
    api = "/repos/29583855/dukto-next"
    path = api + "/actions/runs/" + str(RUN)
    run = request(path)
    assert run["head_sha"] == SOURCE and run["run_attempt"] == 1
    jobs = request(path + "/jobs?per_page=100")["jobs"]
    artifacts = request(path + "/artifacts?per_page=100")["artifacts"]
    output = repo / "docs/validation/2026-11-07/skip-directory-r111-macos-package"
    dist = root / "dist/macos-preview-20261107-r111-skip-directory"
    output.mkdir(parents=True, exist_ok=True)
    dist.mkdir(exist_ok=True)
    records = []
    for runner, architecture, label in (("macos-15", "arm64", "ARM64"), ("macos-15-intel", "x86_64", "X64")):
        job, = [item for item in jobs if item["name"] == "package (" + runner + ")"]
        folder = output / architecture
        if job["status"] != "completed":
            records.append({"architecture": architecture, "status": job["status"], "qualified": False})
            continue
        folder.mkdir(exist_ok=True)
        receipt = folder / "receipt.json"
        if receipt.exists():
            value = json.loads(receipt.read_text("utf-8"))
            assert value["sourceCommit"] == SOURCE
            records.append(value)
            continue
        log = request(api + "/actions/jobs/" + str(job["id"]) + "/logs", binary=True)
        (folder / "job.log").write_bytes(log)
        value = {"sourceCommit": SOURCE, "architecture": architecture, "jobId": job["id"],
                 "status": job["status"], "conclusion": job["conclusion"], "qualified": False,
                 "jobLogSha256": hashlib.sha256(log).hexdigest(), "steps": job["steps"],
                 "releaseQualified": False, "deliveryComplete": False}
        if job["conclusion"] == "success":
            for name in ("Compile GUI and CLI", "Validate Cocoa main window server navigation", "Deploy native preview", "Validate relocated native preview", "Preserve package and deployment evidence"):
                step, = [item for item in job["steps"] if item["name"] == name]
                assert step["conclusion"] == "success"
            artifact, = [item for item in artifacts if item["name"] == "macos-preview-" + label]
            assert not artifact["expired"]
            local = dist / (artifact["name"] + ".zip")
            raw = local.read_bytes() if local.exists() else request(api + "/actions/artifacts/" + str(artifact["id"]) + "/zip", binary=True)
            zip_sha = hashlib.sha256(raw).hexdigest()
            assert artifact["digest"] == "sha256:" + zip_sha
            if not local.exists():
                local.write_bytes(raw)
            files = helper["checked_zip"](raw)
            tar_name = "package-output/DuktoNext-macos-" + architecture + "-preview.tar.gz"
            payload = files[tar_name]
            digest = hashlib.sha256(payload).hexdigest()
            assert files[tar_name + ".sha256"].decode("ascii").split()[0] == digest
            for name in (tar_name, tar_name + ".sha256"):
                target = dist / Path(name).name
                if target.exists():
                    assert target.read_bytes() == files[name]
                else:
                    target.write_bytes(files[name])
            proof = helper["payload_proof"](payload, architecture)
            runtime = helper["runtime_proof"](files, architecture, folder)
            for key in ("screenshot", "navigationScreenshot"):
                runtime[key] = Path(runtime[key]).relative_to(repo).as_posix()
            navigation = json.loads(files["build/main-window-navigation.json"])
            assert navigation["passed"] and navigation["sourceCommit"] == SOURCE and navigation["nativePlatform"] == "cocoa"
            for case in navigation["cases"]:
                assert case["passed"] and case["exitCode"] == 0
                for frame in case["frames"]:
                    assert frame["chineseGlyphCoverage"]["passed"] and frame["chineseGlyphCoverage"]["missingGlyphs"] == 0
                    image_name = "build/main-window-navigation/" + case["name"] + "/Testing/QtTest/main-server-" + "x".join(str(size) for size in frame["requestedSize"]) + ".png"
                    assert hashlib.sha256(files[image_name]).hexdigest() == frame["pngSha256"]
            value.update(qualified=True, artifactId=artifact["id"], artifactUrl=run["html_url"] + "/artifacts/" + str(artifact["id"]),
                         artifactSha256=zip_sha, packageSha256=digest, archive=Path(tar_name).name,
                         package=proof, runtime=runtime, cocoaNavigationAndDpiCasesPassed=True)
        receipt.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append(value)
        print(json.dumps({"architecture": architecture, "conclusion": job["conclusion"], "qualified": value["qualified"]}), flush=True)
    result = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": SOURCE,
              "run": {key: run[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
              "records": records, "bothArchitecturesVerified": len(records) == 2 and all(item["qualified"] for item in records),
              "screenshotsViewed": False, "releaseQualified": False, "deliveryComplete": False}
    (output / "receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(Path(__file__), output / "verification-driver.py")
    print(json.dumps({"runStatus": run["status"], "runConclusion": run["conclusion"], "bothArchitecturesVerified": result["bothArchitecturesVerified"]}))


if __name__ == "__main__":
    main()

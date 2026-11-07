"""日期：2026-11-07；按最终提交逐runner核验目录清理原件，不转授完整协议或发布资格。"""

from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import re
import runpy
import stat
import xml.etree.ElementTree as ET
import zipfile


# 日期：2026-11-07；每次观察仅下载首次出现的官方核心附件，先验摘要再读取有界原件。
def main():
    workspace = Path(r"E:\project\dukto")
    repo = workspace / ".cache/github-29583855-dukto-next-r28"
    request = runpy.run_path(str(workspace / ".cache/github-actions-r28.py"))["request"]
    api = "/repos/29583855/dukto-next"
    path = api + "/actions/runs/42370990486"
    run = request(path)
    assert run["head_sha"] == "d922dc4c793c77de0553ddf44c0fe1fa2d998c24"
    jobs = request(path + "/jobs?per_page=100")["jobs"]
    artifacts = request(path + "/artifacts?per_page=100")["artifacts"]
    output = repo / "docs/validation/2026-11-07/private-read-r114-native-core"
    output.mkdir(parents=True, exist_ok=True)
    cache = workspace / ".cache/private-read-r114-native-artifacts"
    cache.mkdir(exist_ok=True)
    records = []
    for runner in ("ubuntu-22.04", "macos-15", "macos-15-intel", "windows-2022"):
        job, = [job for job in jobs if job["name"].startswith("native (" + runner + ",")]
        candidates = [item for item in artifacts if item["name"] == "core-validation-" + runner]
        if not candidates:
            records.append({"runner": runner, "available": False, "jobStatus": job["status"]})
            continue
        item, = candidates
        assert not item["expired"]
        local = cache / (str(item["id"]) + ".zip")
        if local.exists():
            raw = local.read_bytes()
        else:
            raw = request(api + "/actions/artifacts/" + str(item["id"]) + "/zip", binary=True)
            local.write_bytes(raw)
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == item["digest"]
        folder = output / runner
        folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            assert len(set(names)) == len(names)
            total = 0
            for member in archive.infolist():
                source = PurePosixPath(member.filename)
                assert not source.is_absolute() and ".." not in source.parts and ":" not in member.filename
                assert not stat.S_ISLNK(member.external_attr >> 16)
                if member.is_dir():
                    continue
                assert member.file_size < 32 * 1024 * 1024
                total += member.file_size
                assert total < 128 * 1024 * 1024
                if "/Testing/QtTest/" not in "/" + member.filename and source.name not in ("ctest.log", "macos-environment.log", "macos-dependencies.json", "source-snapshot.json"):
                    continue
                target = folder / member.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                data = archive.read(member)
                if target.exists():
                    assert target.read_bytes() == data
                else:
                    target.write_bytes(data)
        xml, = list(folder.rglob("directory-cleanup-tests.xml"))
        log, = list(folder.rglob("directory-cleanup-tests.log"))
        suite = ET.fromstring(xml.read_bytes())
        assert suite.get("failures") == "0" and suite.get("errors") == "0"
        assert not suite.findall(".//failure") and not suite.findall(".//error")
        methods = suite.findall("testcase")
        assert len(methods) == 19 and all(method.get("result") == "pass" for method in methods)
        text = log.read_text("utf-8-sig")
        assert "Totals: 59 passed, 0 failed, 0 skipped" in text
        for role in ("client", "server"):
            for policy in ("rename", "fail", "overwrite", "skip"):
                assert "PASS   : DirectoryCleanupTests::policies(" + role + "-" + policy + ")" in text
        # 日期：2026-11-07；逐行核对四种真实进程退出交错和六种坏证明反例，不能仅用总行数授予资格。
        for role in ("client", "server"):
            for phase in ("before-delete", "after-delete"):
                assert "PASS   : DirectoryCleanupTests::finalSkipReceiverMaintenanceConvergence(" + role + "-" + phase + ")" in text
            for damage in ("directory-proof", "skip-proof", "reverse"):
                assert "PASS   : DirectoryCleanupTests::finalSkipReconciliationRejectsDamage(" + role + "-" + damage + ")" in text
        step, = [step for step in job["steps"] if step["name"] == "Core and GUI controller tests"]
        ctest, = list(folder.rglob("ctest.log"))
        # 日期：2026-11-07；26个CTest和25份Qt原件逐份核验；Darwin只允许已有的精确端口独占XFAIL。
        ctest_text = ctest.read_text("utf-8-sig")
        if not re.search(r"^100% tests passed(?:, 0 tests failed)? out of 26$", ctest_text, re.M):
            # 日期：2026-11-07；先保留真实失败并分别核对可证明的子项，绝不放宽整套CTest通过要求。
            assert step["conclusion"] == "failure"
            assert "96% tests passed, 1 tests failed out of 26" in ctest_text
            assert "26 - server-panel-tests (Failed)" in ctest_text
            failed_xml, = list(folder.rglob("server-panel-tests.xml"))
            failed_tree = ET.fromstring(failed_xml.read_bytes())
            failed_cases = [case for case in failed_tree.findall("testcase") if case.get("result") == "fail"]
            assert len(failed_cases) == 1 and failed_cases[0].get("name") == "productionServiceAndQml"
            failure, = failed_cases[0].findall("failure")
            assert failure.get("message") == "'server.busy()' returned FALSE. ()"
            core_original, = list(folder.rglob("core-tests.log"))
            assert "PASS   : CoreTests::posixPrivateReadAtomicReplacement()" in core_original.read_text("utf-8-sig")
            record = {"runner": runner, "available": True, "artifactId": item["id"],
                      "artifactSha256": hashlib.sha256(raw).hexdigest(), "jobId": job["id"],
                      "coreStep": step["conclusion"], "cleanupRowsPassed": 59,
                      "cleanupJUnitMethodsPassed": 19, "cleanupQualified": True,
                      "privateReadRegressionPassed": True, "coreQualified": False,
                      "ctestTargetsPassed": 25, "ctestTargetsFailed": 1,
                      "failedMethod": failed_cases[0].get("name"), "failureMessage": failure.get("message"),
                      "ctestSha256": hashlib.sha256(ctest.read_bytes()).hexdigest(),
                      "xmlSha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                      "logSha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                      "originalFailureRetained": True}
            (folder / "receipt.json").write_text(json.dumps(record, indent=2) + "\n", "utf-8")
            records.append(record)
            continue
        assert re.search(r"^100% tests passed(?:, 0 tests failed)? out of 26$", ctest_text, re.M)
        xmls = sorted(folder.rglob("*.xml"))
        assert len(xmls) == 25
        expected_failures = []
        diagnostic_counts = []
        for path in xmls:
            tree = ET.fromstring(path.read_bytes())
            assert tree.get("failures", "0") == "0"
            # 日期：2026-11-07；Qt JUnit把qinfo/qwarn及XFAIL说明计入errors；核对原消息后按实际用例判定。
            comments_tree = ET.fromstring(path.read_bytes(), ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
            comments = [node.text for node in comments_tree.iter() if node.tag is ET.Comment]
            kinds = {}
            for comment in comments:
                match = re.search(r'type="([^"]+)"', comment)
                assert match and match.group(1) in ("qinfo", "qwarn", "info")
                kind = match.group(1)
                kinds[kind] = kinds.get(kind, 0) + 1
                if kind == "qwarn":
                    assert path.name == "avatars-tests.xml" and (
                        'message="QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once."' in comment)
                if kind == "info":
                    assert runner.startswith("macos-") and path.name == "core-tests.xml"
                if kind == "qinfo":
                    assert path.name == "file-exchange-tests.xml" and "terminal fixture " in comment
            assert int(tree.get("errors", "0")) == len(comments)
            if comments:
                diagnostic_counts.append({"xml": path.name, "qtDiagnosticMessages": kinds})
            assert not tree.findall(".//failure") and not tree.findall(".//error")
            cases = tree.findall("testcase")
            assert cases
            for case in cases:
                if case.get("result") == "xfail":
                    assert runner.startswith("macos-") and path.name == "core-tests.xml"
                    assert case.get("name") == "exclusiveTcpBinding"
                    expected_failures.append({"xml": path.name, "method": case.get("name")})
                else:
                    assert case.get("result") == "pass", (runner, path.name, case.attrib)
        assert len(expected_failures) == (1 if runner.startswith("macos-") else 0)
        core_log, = list(folder.rglob("core-tests.log"))
        if runner != "windows-2022":
            # 日期：2026-11-07；POSIX新增真实并发读取维护用例必须在原件中通过，不能只验旧目录子集。
            assert "PASS   : CoreTests::posixPrivateReadAtomicReplacement()" in core_log.read_text("utf-8-sig")
        boundary = [line for line in core_log.read_text("utf-8-sig").splitlines()
                    if line.startswith(("XFAIL  :", "XPASS  :", "FAIL!  :", "QFATAL :"))]
        if runner.startswith("macos-"):
            assert len(boundary) == 1 and boundary[0] == (
                "XFAIL  : CoreTests::exclusiveTcpBinding(exclusive-first-ipv4-wildcard-then-specific) "
                "Darwin permits later Qt wildcard/specific sharing even with SO_REUSEADDR disabled; kernel exclusivity is not qualified")
        else:
            assert not boundary
        assert step["conclusion"] == "success"
        record = {"runner": runner, "available": True, "artifactId": item["id"],
                  "artifactSha256": hashlib.sha256(raw).hexdigest(), "jobId": job["id"],
                  "coreStep": step["conclusion"], "cleanupRowsPassed": 59,
                  "cleanupJUnitMethodsPassed": 19, "cleanupQualified": True, "coreQualified": True, "ctestTargetsPassed": 26,
                  "qtXmlReportsVerified": len(xmls), "explicitDarwinExpectedFailures": expected_failures,
                  "qtDiagnosticCounts": diagnostic_counts,
                  "ctestSha256": hashlib.sha256(ctest.read_bytes()).hexdigest(),
                  "xmlSha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
                  "logSha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        (folder / "receipt.json").write_text(json.dumps(record, indent=2) + "\n", "utf-8")
        records.append(record)
    receipt = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": run["head_sha"],
               "runId": run["id"], "runStatus": run["status"], "runConclusion": run["conclusion"],
               "records": records, "allNativeCleanupTestsPassed": all(row.get("cleanupQualified", False) for row in records),
               "allNativeCoreTestsPassed": all(row.get("coreQualified", False) for row in records),
               "jobs": [{key: job[key] for key in ("id", "name", "status", "conclusion", "steps")} for job in jobs],
               "verifierCorrection": "Qt JUnit errors counts qinfo/qwarn/XFAIL diagnostics; verified exact original comments, testcase results, CTest and negative failure nodes; initial strict errors==0 collector assertion granted no qualification",
               "fullProtocolQualified": False, "deliveryComplete": False, "releaseQualified": False}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")
    (output / "verification-driver.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"allNativeCleanupTestsPassed": receipt["allNativeCleanupTestsPassed"],
                      "records": records, "runStatus": run["status"]}))


if __name__ == "__main__":
    main()

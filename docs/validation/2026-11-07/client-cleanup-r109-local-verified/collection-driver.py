"""日期：2026-11-07；汇集本轮真实测试原件、失败记录与构建输入，不将子项通过当成交付。"""

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；每份证据以相对路径和原始字节摘要记录，避免可变日志覆盖旧结论。
def proof(root, path):
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


# 日期：2026-11-07；严格读取Qt原件，拒绝失败、跳过、错误或用例缺失。
def verify(path, expected=None):
    suite = ET.fromstring(path.read_bytes())
    assert suite.get("failures") == "0", path
    assert not suite.findall(".//failure") and not suite.findall(".//error"), path
    cases = suite.findall("testcase")
    assert cases and all(item.get("result") == "pass" for item in cases), path
    if expected is not None:
        assert len(cases) == expected, (path, len(cases))
    return {"tests": len(cases), "methods": [item.get("name") for item in cases]}


# 日期：2026-11-07；只收验本轮两个隔离构建的七个相关测试目标，完整GUI与协议另验。
def main():
    workspace = Path(r"E:\project\dukto")
    repo = workspace / ".cache/github-29583855-dukto-next-r28"
    output = repo / "docs/validation/2026-11-07/client-cleanup-r109-local-verified"
    output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo).decode().strip()
    assert commit == "bea5d8181fd4e474216ad613120e20c3c086f217"
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    inputs = []
    for name in names:
        if not name:
            continue
        path = repo / name
        if name.startswith(("src/", "tests/", "scripts/", "ui/", "resources/", "third-party/", ".github/")) or name in ("CMakeLists.txt", ".clang-format"):
            inputs.append(proof(repo, path))
    (output / "build-inputs.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    targets = ["core-tests", "sqlite-cache-tests", "strong-manifest-tests", "task-store-tests",
               "expired-task-cleanup-tests", "client-download-cleanup-tests", "durable-receive-tests"]
    results = []
    for label in ("ucrt", "msvc"):
        build = workspace / (".cache/client-cleanup-r109-" + label)
        destination = output / label
        destination.mkdir()
        binaries = build / "Release" if label == "msvc" else build
        record = {"toolchain": label, "passed": True, "targets": {}, "binaries": []}
        for name in ("dukto-cli", "client-download-cleanup-tests"):
            data = (binaries / (name + ".exe")).read_bytes()
            record["binaries"].append({"name": name + ".exe", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        log = build / "related-ctest.log"
        assert "100% tests passed out of 7" in log.read_text("utf-8-sig"), label
        shutil.copyfile(log, destination / "related-ctest.log")
        shutil.copyfile(build / "Testing/Temporary/LastTest.log", destination / "LastTest.log")
        for target in targets:
            xml = build / ("Testing/QtTest/" + target + ".xml")
            record["targets"][target] = verify(xml, 13 if target == "client-download-cleanup-tests" else None)
            if target == "client-download-cleanup-tests":
                text_log = (build / "Testing/QtTest/client-download-cleanup-tests.log").read_text("utf-8-sig")
                assert "Totals: 16 passed, 0 failed, 0 skipped" in text_log
                for policy in ("rename", "fail", "overwrite", "skip"):
                    assert f"PASS   : ClientDownloadCleanupTests::policies({policy})" in text_log
                record["targets"][target]["actualRowsIncludingData"] = 16
            for suffix in ("xml", "log"):
                source = build / ("Testing/QtTest/" + target + "." + suffix)
                shutil.copyfile(source, destination / source.name)
        for name in ("final-test.log", "final-test.xml"):
            shutil.copyfile(build / name, destination / name)
        cache = (build / "CMakeCache.txt").read_text("utf-8-sig")
        record["cmakeCache"] = [line for line in cache.splitlines() if line.startswith(("CMAKE_CXX_COMPILER:", "CMAKE_CXX_COMPILER_VERSION:", "CMAKE_PREFIX_PATH:", "OPENSSL_ROOT_DIR:", "DUKTO_BUILD_GUI:"))]
        results.append(record)
    failures = output / "initial-failures"
    failures.mkdir()
    for name, source in [
        ("ucrt-first-test.log", workspace / ".cache/client-cleanup-r109-ucrt/first-test.log"),
        ("ucrt-first-test.xml", workspace / ".cache/client-cleanup-r109-ucrt/first-test.xml"),
        ("ubuntu-job.log", workspace / ".cache/ci-42346262910-ubuntu/job-logs.zip"),
        ("mac-arm-job.log", workspace / ".cache/ci-42346262910-failure/mac-arm-job.log"),
        ("mac-intel-job.log", workspace / ".cache/ci-42346262910-failure/mac-intel-job.log"),
        ("windows-job.log", workspace / ".cache/ci-42346262910-failure/windows-job.log"),
    ]:
        shutil.copyfile(source, failures / name)
    audit = json.loads((workspace / ".cache/client-cleanup-r109-final-audit.json").read_text("utf-8"))
    assert audit["sourceMarkersPassed"] and audit["cxx14Configuration"] and not audit["findings"]
    shutil.copyfile(workspace / ".cache/client-cleanup-r109-final-audit.json", output / "source-audit.json")
    formatter = workspace / ".cache/tools/clang-format-py/clang_format/data/bin/clang-format.exe"
    changed = ["src/cli/main.cpp", "src/cli/servicecommands.cpp", "src/core/clientdownloadcleanup.cpp",
               "src/core/clientdownloadcleanup.h", "tests/client_download_cleanup_tests.cpp"]
    formatted = subprocess.run([str(formatter), "--dry-run", "--Werror", *changed], cwd=repo, capture_output=True, check=True)
    assert not formatted.stderr
    for name in changed:
        raw = (repo / name).read_bytes()
        raw.decode("utf-8")
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
    receipt = {
        "observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": commit,
        "scope": "Two local Windows toolchains; seven related CTest targets each; final cleanup tests 16 each including init/cleanup",
        "passed": True, "results": results, "inputCount": len(inputs),
        "audit": {"files": len(audit["files"]), "findings": 0, "cxx14Configuration": True,
                  "formattingChangedCppPassed": True, "changedFilesUtf8NoBomLf": True},
        "failuresPreserved": ["4884016: all four CI runners failed compiling private openFile calls; fixed public open API",
                              "first UCRT fixture: QTemporaryFile replacement rename failed; fixed move-original/create-replacement fixture",
                              "initial PATH inspection missed preinstalled .tools CMake/Qt/MSVC/UCRT; corrected explicit tool paths",
                              "initial evidence collector expected 16 JUnit method elements; Qt emits 13 methods and four policy rows in text; checked both originals after correction"],
        "files": [proof(output, path) for path in sorted(output.rglob("*")) if path.is_file()],
        "deliveryComplete": False, "releaseQualified": False,
        "openScope": ["final native four-runner regression", "directory temporary cleanup", "global GC and disk budgets",
                      "full R6 GUI", "physical LAN and 3x3 matrix", "24-hour stability", "clean-system signed distribution"],
    }
    (output / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(__file__, output / "collection-driver.py")
    print(json.dumps({"sourceCommit": commit, "passed": True, "relatedTargets": 14, "cleanupCases": 32,
                      "files": len(receipt["files"]), "deliveryComplete": False}))


if __name__ == "__main__":
    main()

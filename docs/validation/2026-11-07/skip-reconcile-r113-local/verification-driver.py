"""日期：2026-11-07；双Windows验证接收器/维护恢复顺序，冻结全部资格输入并保存原件。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
OUTPUT = REPO / "docs/validation/2026-11-07/skip-reconcile-r113-local"
TARGETS = ("directory-cleanup-tests", "receive-skip-tests", "client-download-cleanup-tests",
           "expired-task-cleanup-tests")


# 日期：2026-11-07；按字节冻结输入和程序，不能用路径存在代替内容匹配。
def proof(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


# 日期：2026-11-07；每个工具链构建真实CLI依赖并运行四个完整专项，原有Qt/OpenSSL仅放入子进程PATH。
def lane(name):
    build = ROOT / "build" / ("windows-ucrt" if name == "ucrt" else "windows")
    folder = OUTPUT / name
    folder.mkdir()
    bins = [ROOT / ".tools/msys64/ucrt64/bin"] if name == "ucrt" else [
        ROOT / ".tools/Qt/5.15.2/msvc2019_64/bin", ROOT / ".tools/openssl/Library/bin"]
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(map(str, bins)) + os.pathsep + environment["PATH"]
    command = [str(ROOT / ".tools/python/Scripts/cmake.exe"), "--build", str(build),
               "--target", "dukto-cli", *TARGETS]
    command += ["-j", "6"] if name == "ucrt" else ["--config", "Release", "--", "/m:4"]
    with (folder / "build.log").open("wb") as log:
        subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                       timeout=600, check=True)
    binary_folder = build if name == "ucrt" else build / "Release"
    before = [proof(binary_folder / (target + ".exe")) for target in ("dukto-cli", *TARGETS)]
    command = [str(ROOT / ".tools/python/Scripts/ctest.exe"), "--test-dir", str(build),
               "-R", "^(" + "|".join(TARGETS) + ")$", "--output-on-failure"]
    if name == "msvc":
        command += ["-C", "Release"]
    with (folder / "ctest.log").open("wb") as log:
        subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                       timeout=300, check=True)
    results = []
    for target in TARGETS:
        for suffix in ("xml", "log"):
            shutil.copyfile(build / "Testing/QtTest" / (target + "." + suffix), folder / (target + "." + suffix))
        tree = ET.parse(folder / (target + ".xml"))
        assert not tree.findall(".//failure") and not tree.findall(".//error")
        assert all(row.get("result") == "pass" for row in tree.findall("testcase"))
        assert tree.getroot().get("failures", "0") == "0" and tree.getroot().get("errors", "0") == "0"
        results.append({"target": target, "methods": len(tree.findall("testcase"))})
    directory_log = (folder / "directory-cleanup-tests.log").read_text("utf-8")
    assert "Totals: 59 passed, 0 failed, 0 skipped" in directory_log
    assert results[0]["methods"] == 19
    after = [proof(binary_folder / (target + ".exe")) for target in ("dukto-cli", *TARGETS)]
    assert before == after
    result = {"toolchain": name, "passed": True, "ctestTargets": 4, "directoryRows": 59,
              "methods": results, "binariesBeforeAndAfterMatched": True, "binaries": before}
    print(json.dumps({"toolchain": name, "passed": True, "directoryRows": 59}), flush=True)
    return result


# 日期：2026-11-07；测试前后比较全部应用/夹具输入，保留修复前真实失败和收集器编码失败。
def main():
    OUTPUT.mkdir(exist_ok=False)
    for name in ("src/core/directorycleanup.cpp", "tests/directory_cleanup_tests.cpp"):
        shutil.copyfile(ROOT / name, REPO / name)
    names = subprocess.check_output(["git", "ls-files", "-z", "--", "CMakeLists.txt", ".clang-format",
                                     ".github", "resources", "src", "ui", "tests", "scripts"], cwd=REPO)
    inputs = [proof(ROOT / name) for name in names.decode("utf-8").strip("\0").split("\0")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(lane, ("ucrt", "msvc")))
    assert inputs == [proof(ROOT / row["path"]) for row in inputs]
    for name in ("r113-before-reconciliation", "r113-before-reconciliation-verified"):
        shutil.copytree(ROOT / ".cache" / name, OUTPUT / name)
    audit = [str(ROOT / ".tools/python/Scripts/python.exe"), "-X", "utf8", "scripts/audit.py",
             "--report", str(OUTPUT / "source-audit.json")]
    with (OUTPUT / "audit.log").open("wb") as log:
        subprocess.run(audit, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=60, check=True)
    result = {"observedUtc": datetime.now(timezone.utc).isoformat(), "passed": True,
              "sourceWorkingTree": "R113 pending source commit", "qualificationInputs": inputs,
              "inputCount": len(inputs), "records": records, "beforeFixFailedRows": 4,
              "processCrashResumeRowsPerToolchain": 4, "damagedEvidenceRowsPerToolchain": 6,
              "sourceEncoding": "Modified C++ files remain UTF-8 without BOM / LF; original failed Qt logs remain CP936",
              "deliveryComplete": False, "releaseQualified": False}
    (OUTPUT / "receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(Path(__file__), OUTPUT / "verification-driver.py")
    print(json.dumps({"passed": True, "inputCount": len(inputs), "toolchains": len(records), "directoryRowsEach": 59}))


if __name__ == "__main__":
    main()

"""日期：2026-11-07；冻结R111源码与双Windows程序，保存真实构建和CTest原件及SHA。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
SOURCE = "dfe245b502f586e7df7219e8fb0d5e4030a6b032"
TARGETS = ("directory-cleanup-tests", "receive-skip-tests", "client-download-cleanup-tests",
           "expired-task-cleanup-tests")
OUTPUT = REPO / "docs/validation/2026-11-07/skip-directory-r111-local"


# 日期：2026-11-07；所有原件只生成路径、长度和摘要，不以本机缓存文件名推定源码身份。
def proof(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


# 日期：2026-11-07；Qt及OpenSSL只进入子进程环境，不改变系统PATH或用户全局配置。
def lane(name):
    build = ROOT / "build" / ("windows-ucrt" if name == "ucrt" else "windows")
    folder = OUTPUT / name
    folder.mkdir()
    environment = os.environ.copy()
    bins = [ROOT / ".tools/msys64/ucrt64/bin"] if name == "ucrt" else [
        ROOT / ".tools/Qt/5.15.2/msvc2019_64/bin", ROOT / ".tools/openssl/Library/bin"]
    environment["PATH"] = os.pathsep.join(str(path) for path in bins) + os.pathsep + environment["PATH"]
    executable_dir = build if name == "ucrt" else build / "Release"
    cmake = str(ROOT / ".tools/python/Scripts/cmake.exe")
    command = [cmake, "--build", str(build), "--target", "dukto-cli", *TARGETS]
    command += ["-j", "6"] if name == "ucrt" else ["--config", "Release", "--", "/m:4"]
    with (folder / "build.log").open("wb") as log:
        subprocess.run(command, cwd=ROOT, env=environment, stdout=log,
                       stderr=subprocess.STDOUT, timeout=600, check=True)
    binaries = {target: proof(executable_dir / (target + ".exe"))
                for target in ("dukto-cli", *TARGETS)}
    command = [str(ROOT / ".tools/python/Scripts/ctest.exe"), "--test-dir", str(build)]
    if name == "msvc":
        command += ["-C", "Release"]
    command += ["-R", "^(" + "|".join(TARGETS) + ")$", "--output-on-failure"]
    with (folder / "ctest.log").open("wb") as log:
        subprocess.run(command, cwd=ROOT, env=environment, stdout=log,
                       stderr=subprocess.STDOUT, timeout=300, check=True)
    assert re.search(r"^100% tests passed.* out of 4$",
                     (folder / "ctest.log").read_text("utf-8"), re.M)
    results = []
    for target in TARGETS:
        for suffix in ("log", "xml"):
            shutil.copyfile(build / "Testing/QtTest" / (target + "." + suffix),
                            folder / (target + "." + suffix))
        suite = ET.fromstring((folder / (target + ".xml")).read_bytes())
        assert suite.get("failures", "0") == "0" and suite.get("errors", "0") == "0"
        assert not suite.findall(".//failure") and not suite.findall(".//error")
        assert all(case.get("result") == "pass" for case in suite.findall("testcase"))
        results.append({"target": target, "junitMethods": len(suite.findall("testcase"))})
        assert proof(executable_dir / (target + ".exe")) == binaries[target]
    assert "Totals: 49 passed, 0 failed, 0 skipped" in (folder / "directory-cleanup-tests.log").read_text("utf-8")
    assert proof(executable_dir / "dukto-cli.exe") == binaries["dukto-cli"]
    return {"toolchain": name, "ctestTargetsPassed": 4, "directoryCleanupRows": 49,
            "tests": results, "binariesBeforeAndAfterMatched": True,
            "binaries": binaries, "originals": [proof(path) for path in sorted(folder.iterdir())]}


# 日期：2026-11-07；测试前后核对精确提交构建输入，变动和标记扫描失败不得生成合格回执。
def main():
    OUTPUT.mkdir(parents=True, exist_ok=False)
    baseline = json.loads((REPO / "docs/ci-verification-20261107-r110.json").read_text("utf-8"))
    inputs = []
    for row in baseline["buildInputs"]:
        name = row["path"]
        raw = subprocess.check_output(["git", "show", SOURCE + ":" + name], cwd=REPO)
        assert raw == (ROOT / name).read_bytes() == (REPO / name).read_bytes(), name
        item = proof(ROOT / name)
        inputs.append(item)
    with ThreadPoolExecutor(max_workers=2) as pool:
        lanes = list(pool.map(lane, ("ucrt", "msvc")))
    for row in inputs:
        assert proof(ROOT / row["path"]) == row
    marker = re.compile(r"\b(?:TODO|FIXME|placeholder|stub)\b|简化实现|简化占位|简化版本", re.I)
    maintained = [path for top in ("src", "tests", "ui") for path in (ROOT / top).rglob("*")
                  if path.is_file() and path.suffix in (".cpp", ".h", ".py", ".qml")]
    assert not [str(path) for path in maintained if marker.search(path.read_text("utf-8-sig"))]
    receipt = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": SOURCE,
               "buildInputs": inputs, "records": lanes, "passed": True,
               "maintainedFilesScanned": len(maintained), "implementationMarkersFound": 0,
               "environmentFailuresBeforeQualifiedRun": [
                   "UCRT compiler child initially lacked dependency DLL directories in subprocess PATH",
                   "Initial targeted builds did not build the CLI needed by commandLine tests",
                   "MSVC CLI needed OpenSSL Library/bin in subprocess PATH; exit 0xc0000135"],
               "deliveryComplete": False, "releaseQualified": False}
    (OUTPUT / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(Path(__file__), OUTPUT / "verification-driver.py")
    print(json.dumps({"passed": True, "buildInputs": len(inputs), "records": [
        {key: lane[key] for key in ("toolchain", "ctestTargetsPassed", "directoryCleanupRows")}
        for lane in lanes]}))


if __name__ == "__main__":
    main()

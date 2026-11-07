"""日期：2026-11-07；两套Windows程序只读冻结，在独立临时目录复验修正后的故障夹具。"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
OUTPUT = REPO / "docs/validation/2026-11-07/fault-refusal-r112-local"


# 日期：2026-11-07；按真实文件流式计算程序及脚本摘要。
def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(256 * 1024):
            value.update(chunk)
    return value.hexdigest()


# 日期：2026-11-07；每个工具链串行复验两种冲突策略，保持原程序与所有撤权期限/数据保护断言。
def lane(name):
    folder = OUTPUT / name
    folder.mkdir()
    executable = ROOT / ("build/windows-ucrt/dukto-cli.exe" if name == "ucrt" else "build/windows/Release/dukto-cli.exe")
    before = sha(executable)
    environment = os.environ.copy()
    bins = [ROOT / ".tools/msys64/ucrt64/bin"] if name == "ucrt" else [
        ROOT / ".tools/Qt/5.15.2/msvc2019_64/bin", ROOT / ".tools/openssl/Library/bin"]
    environment["PATH"] = os.pathsep.join(map(str, bins)) + os.pathsep + environment["PATH"]
    records = []
    for policy in ("rename", "overwrite"):
        report = folder / (policy + ".json")
        command = [str(ROOT / ".tools/python/Scripts/python.exe"), "-X", "utf8",
                   "tests/transfer_faults_integration.py", str(executable), "--on-conflict", policy, "--report", str(report)]
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=300)
        (folder / (policy + ".log")).write_bytes(result.stdout + result.stderr)
        assert result.returncode == 0, (name, policy, result.returncode, result.stdout, result.stderr)
        value = json.loads(report.read_text("utf-8"))
        assert value["passed"] and len(value["cases"]) == 6 and value["executableSha256"] == before
        assert value["testScriptSha256"] == sha(ROOT / "tests/transfer_faults_integration.py")
        for case in value["cases"]:
            assert case["originalPreserved"] and case["noPublishedCopy"]
            assert case["secondsAfterFault"] < case["deadlineSeconds"]
        records.append({"policy": policy, "cases": 6, "reportSha256": sha(report)})
    assert before == sha(executable)
    print(json.dumps({"toolchain": name, "faultCases": 12, "passed": True}), flush=True)
    return {"toolchain": name, "passed": True, "executableSha256": before,
            "binaryUnchanged": True, "records": records}


# 日期：2026-11-07；独立契约负例和双工具链原件不覆盖R111的ARM原失败。
def main():
    OUTPUT.mkdir(exist_ok=False)
    result = subprocess.run([str(ROOT / ".tools/python/Scripts/python.exe"), "-X", "utf8",
                             "tests/transfer_fault_expectations_tests.py"], cwd=ROOT, capture_output=True, timeout=30)
    (OUTPUT / "expectations.log").write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(lane, ("ucrt", "msvc")))
    value = {"observedUtc": datetime.now(timezone.utc).isoformat(), "passed": True, "records": records,
             "faultScriptSha256": sha(ROOT / "tests/transfer_faults_integration.py"),
             "expectationsScriptSha256": sha(ROOT / "tests/transfer_fault_expectations_tests.py"),
             "applicationSourceCommit": "dfe245b502f586e7df7219e8fb0d5e4030a6b032",
             "faultCases": 24, "originalArmFullSuiteFailureRetained": True,
             "deliveryComplete": False, "releaseQualified": False}
    (OUTPUT / "receipt.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(Path(__file__), OUTPUT / "verification-driver.py")


if __name__ == "__main__":
    main()

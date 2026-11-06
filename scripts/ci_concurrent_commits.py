"""日期：2026-11-06；独立重复原八线程提交测试，保留每轮失败且不以重试成功覆盖。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


# 日期：2026-11-06；测试子进程输出直接写有界轮次文件，不把完整日志累积在内存。
def execute(binary, directory, number):
    stem = directory / ("round-%04d" % number)
    started = time.monotonic()
    with stem.with_suffix(".driver.log").open("x", encoding="utf-8") as log:
        result = subprocess.run(
            [str(binary), "concurrentExclusiveCommits", "-o", str(stem.with_suffix(".log")) + ",txt",
             "-o", str(stem.with_suffix(".xml")) + ",junitxml"],
            stdout=log, stderr=subprocess.STDOUT, check=False, timeout=120)
    text = stem.with_suffix(".log")
    xml = stem.with_suffix(".xml")
    passed = result.returncode == 0 and text.is_file() and xml.is_file()
    if passed:
        passed = "3 passed, 0 failed, 0 skipped" in text.read_text("utf-8")
    return {"round": number, "exitCode": result.returncode, "passed": passed,
            "seconds": round(time.monotonic() - started, 3),
            "logSha256": hashlib.sha256(text.read_bytes()).hexdigest() if text.is_file() else None,
            "xmlSha256": hashlib.sha256(xml.read_bytes()).hexdigest() if xml.is_file() else None}


# 日期：2026-11-06；单轮异常也形成失败证据，后续轮次只能提供额外观察而不能抹去它。
def observed(binary, directory, number):
    try:
        return execute(binary, directory, number)
    except Exception as error:
        return {"round": number, "exitCode": None, "passed": False,
                "runnerError": (type(error).__name__ + ": " + str(error))[:2048]}


# 日期：2026-11-06；最多512轮和8个测试进程，二进制前后身份固定；任一失败返回非零。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--rounds", type=int, default=128)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert 1 <= args.rounds <= 512 and 1 <= args.jobs <= 8
    binary = args.binary.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve(strict=True)
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(observed, binary, output, number)
                   for number in range(1, args.rounds + 1)]
        for future in futures:
            value = future.result()
            results.append(value)
            print(json.dumps(value), flush=True)
    after = hashlib.sha256(binary.read_bytes()).hexdigest()
    summary = {"sourceCommit": os.environ.get("GITHUB_SHA"), "binarySha256": before,
               "binaryUnchanged": before == after, "rounds": args.rounds,
               "processes": args.jobs, "workersPerRound": 8, "completed": True,
               "passed": before == after and all(result["passed"] for result in results),
               "cases": results, "originalFailureCauseResolved": False}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""日期：2026-11-06；原样重复Mac并行退出用例，慢子进程退出前采集原生堆栈，不改变原十秒断言。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import psutil


# 日期：2026-11-06；只终止本诊断启动的测试进程树，预算失败保持失败，不操作其他软件或监听。
def stop_test(process):
    try:
        owned = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        owned = []
    for child in owned:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    process.kill()
    process.wait()


# 日期：2026-11-06；每个独立进程保留原日志/XML；自有服务存活五秒时额外采样，不延长测试内时限。
def attempt(binary, output, number):
    prefix = output / ("parallel-" + str(number))
    xml = prefix.with_suffix(".xml")
    captures = []
    observed = {}
    started = time.monotonic()
    expired = False
    with prefix.with_suffix(".stdout.log").open("xb") as log:
        process = subprocess.Popen([str(binary), "parallelDispositions:download-4-2",
                                    "-o", str(prefix.with_suffix(".log")) + ",txt",
                                    "-o", str(xml) + ",junitxml"],
                                   stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if time.monotonic() - started > 90:
                expired = True
                stop_test(process)
                break
            try:
                children = psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            for child in children:
                try:
                    if "--parallel-disposition-server" not in child.cmdline():
                        continue
                    key = (child.pid, child.create_time())
                    first, sampled = observed.setdefault(key, (time.monotonic(), False))
                    if sampled or time.monotonic() - first < 5:
                        continue
                    observed[key] = (first, True)
                    path = output / ("parallel-" + str(number) + "-server-" + str(child.pid) + ".sample.txt")
                    sample_log = path.with_suffix(".log").open("xb")
                    try:
                        sampler = subprocess.Popen(["/usr/bin/sample", str(child.pid), "1", "-file", str(path)],
                                                   stdout=sample_log, stderr=subprocess.STDOUT)
                    finally:
                        sample_log.close()
                    captures.append((path, sampler))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            time.sleep(0.025)
    samples = []
    for path, sampler in captures:
        try:
            code = sampler.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sampler.kill()
            code = sampler.wait()
        samples.append({"path": path.name, "exitCode": code,
                        "stackFileCreated": path.is_file() and path.stat().st_size > 0})
    xml_passed = False
    if xml.is_file():
        tree = ET.parse(xml)
        xml_passed = not tree.findall(".//failure") and not tree.findall(".//error")
    return {"attempt": number, "exitCode": process.returncode, "outerBudgetExceeded": expired,
            "seconds": round(time.monotonic() - started, 3), "samples": samples,
            "passed": process.returncode == 0 and xml_passed and not expired}


# 日期：2026-11-06；原失败测试保持逐字节不变；重复成功只说明本轮未复现，不宣称超时根因已修复。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=10)
    args = parser.parse_args()
    assert sys.platform == "darwin" and 1 <= args.attempts <= 20
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for number in range(1, args.attempts + 1):
        cases.append(attempt(args.binary.resolve(strict=True), args.output.resolve(), number))
        value = {"cases": cases, "completed": len(cases) == args.attempts,
                 "passed": all(case["passed"] for case in cases),
                 "originalExitWaitMs": 10000, "failureRootCauseProven": False,
                 "releaseQualified": False, "deliveryComplete": False}
        (args.output / "report.json").write_text(json.dumps(value, indent=2) + "\n", "utf-8")
        print(json.dumps(cases[-1]), flush=True)
    return 0 if value["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

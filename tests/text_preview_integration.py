"""日期：2026-11-06；对真实接收/翻页/全文复制/历史重开的GUI进程采样内存，最大8MiB正文不截断。"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from process_sampling import sample


# 日期：2026-11-06；逐场景独立进程，复用既有512MiB门槛；原XML和业务摘要都必须实际通过。
def run_case(executable, root, name):
    peak = {}
    started = time.monotonic()
    with (root / (name + ".log")).open("wb") as log:
        process = subprocess.Popen(
            [executable, "receivedLargeTextThroughQml:" + name,
             "-o", str(root / (name + ".txt")) + ",txt",
             "-o", str(root / (name + ".xml")) + ",junitxml"],
            cwd=root, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                sample(process, peak)
                assert time.monotonic() - started < 120, "GUI text preview did not finish within 120 seconds"
                time.sleep(0.005)
            assert process.returncode == 0, (name, process.returncode, (root / (name + ".txt")).read_text("utf-8"))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    tree = ET.parse(root / (name + ".xml"))
    assert not tree.findall(".//failure") and not tree.findall(".//error")
    assert all(case.get("result") == "pass" for case in tree.findall(".//testcase"))
    evidence = json.loads((root / ("text-preview-" + name + ".json")).read_text("utf-8"))
    assert evidence["passed"] and evidence["clipboardFullTextVerified"] and evidence["historyReopenVerified"]
    assert evidence["firstPageBlocks"] <= 513
    assert peak and peak["rss"] < 512 * 1024**2 and peak["private"] < 512 * 1024**2, peak
    return {"name": name, "seconds": round(time.monotonic() - started, 3), "peak": peak,
            "guiEvidence": evidence, "passed": True}


# 日期：2026-11-06；报告总失败与原报告同时保留；失败不能靠后续场景通过变为成功。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assert not args.report.exists()
    executable = str(args.executable.resolve())
    report = {"passed": False, "completed": False, "cases": [], "memoryLimitBytes": 512 * 1024**2}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    # 日期：2026-11-06；原件使用报告旁新目录保存，不在TemporaryDirectory退出时丢失测试证据。
    root = Path(tempfile.mkdtemp(prefix=args.report.stem + "-originals-", dir=args.report.parent)).resolve()
    report["originalReports"] = str(root)
    try:
        for name in ("paragraph-boundary", "maximum-paragraphs", "maximum-single-line", "unicode-boundaries"):
            report["cases"].append(run_case(executable, root, name))
        report.update(passed=True, completed=True)
    finally:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

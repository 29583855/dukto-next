"""日期：2026-11-07；真实运行两套隔离目录清理测试，每次保留独立原件，拒绝覆盖历史失败。"""

import argparse
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import time


# 日期：2026-11-07；调用真实CTest并冻结Qt日志，返回原退出码而不按文本放宽失败。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=("ucrt", "msvc"))
    parser.add_argument("attempt")
    parser.add_argument("--related", action="store_true")
    args = parser.parse_args()
    root = Path(r"E:\project\dukto")
    build = root / (".cache/directory-cleanup-r110-" + args.label)
    output = build / args.attempt
    output.mkdir(exist_ok=False)
    env = runpy.run_path(str(root / ".cache/validate-overwrite-r62.py"))["environment"](args.label)
    ctest = root / (".tools/msys64/ucrt64/bin/ctest.exe" if args.label == "ucrt" else ".tools/python/Scripts/ctest.exe")
    targets = ["directory-cleanup-tests"]
    if args.related:
        targets += ["client-download-cleanup-tests", "expired-task-cleanup-tests", "durable-receive-tests", "core-tests",
                    "sqlite-cache-tests", "strong-manifest-tests", "task-store-tests"]
    command = [str(ctest), "--test-dir", str(build), "-C", "Release", "--output-on-failure", "-R", "^(" + "|".join(targets) + ")$"]
    started = time.monotonic()
    with (output / "ctest.log").open("wb") as log:
        result = subprocess.run(command, env=env, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    for folder in ("Testing/Temporary", "Testing/QtTest"):
        shutil.copytree(build / folder, output / Path(folder).name)
    record = {"toolchain": args.label, "exitCode": result.returncode, "targets": targets,
              "seconds": round(time.monotonic() - started, 3)}
    (output / "summary.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record), flush=True)
    if result.returncode:
        print((output / "ctest.log").read_text("utf-8-sig"), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()

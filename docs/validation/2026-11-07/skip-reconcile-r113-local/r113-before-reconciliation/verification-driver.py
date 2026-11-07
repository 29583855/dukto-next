"""日期：2026-11-07；先运行真实交错崩溃回归，保存未修复程序的原始失败。"""

import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-07；只构建新增测试，未修改产品时保存精确四行回归失败，不能把异常作为通过。
def main():
    root = Path(r"E:\project\dukto")
    output = root / ".cache/r113-before-reconciliation"
    output.mkdir(exist_ok=False)
    environment = os.environ.copy()
    environment["PATH"] = str(root / ".tools/msys64/ucrt64/bin") + os.pathsep + environment["PATH"]
    command = [str(root / ".tools/python/Scripts/cmake.exe"), "--build", "build/windows-ucrt",
               "--target", "directory-cleanup-tests", "-j", "6"]
    with (output / "build.log").open("wb") as log:
        subprocess.run(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT,
                       timeout=300, check=True)
    result = subprocess.run([str(root / "build/windows-ucrt/directory-cleanup-tests.exe"),
                             "finalSkipReceiverMaintenanceConvergence", "-o", str(output / "regression.txt") + ",txt",
                             "-o", str(output / "regression.xml") + ",junitxml"], cwd=root, env=environment,
                            capture_output=True, timeout=180)
    (output / "process.log").write_bytes(result.stdout + result.stderr)
    original = (output / "regression.txt").read_text("utf-8")
    assert result.returncode != 0 and "4 failed" in original and "跳过与目录清理状态不一致" in original
    (output / "receipt.json").write_text(json.dumps({"reproduced": True, "exitCode": result.returncode,
        "failedRows": 4, "productSourceCommit": "dfe245b502f586e7df7219e8fb0d5e4030a6b032",
        "scope": "New regression against unchanged R111 product; before/after deletion process exits followed by original receiver and maintenance", "passed": False},
        ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"reproduced": True, "failedRows": 4, "exitCode": result.returncode}))


if __name__ == "__main__":
    main()

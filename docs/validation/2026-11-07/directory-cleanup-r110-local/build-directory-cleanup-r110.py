"""日期：2026-11-07；为目录清理创建全新隔离构建，不改写R109原件或冻结长测输入。"""

import argparse
import json
from pathlib import Path
import runpy
import subprocess
import time


# 日期：2026-11-07；两套工具链分别记录真实配置/编译输出，后续按同一二进制执行公开核心测试。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=("ucrt", "msvc"))
    args = parser.parse_args()
    root = Path(r"E:\project\dukto")
    repo = root / ".cache/github-29583855-dukto-next-r28"
    env = runpy.run_path(str(root / ".cache/validate-overwrite-r62.py"))["environment"](args.label)
    build = root / (".cache/directory-cleanup-r110-" + args.label)
    build.mkdir(exist_ok=True)
    cmake = root / (".tools/msys64/ucrt64/bin/cmake.exe" if args.label == "ucrt" else ".tools/python/Scripts/cmake.exe")
    configure = [str(cmake), "-S", str(repo), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release"]
    if args.label == "ucrt":
        configure += ["-G", "Ninja", "-DCMAKE_CXX_COMPILER=" + str(root / ".tools/msys64/ucrt64/bin/g++.exe"),
                      "-DCMAKE_MAKE_PROGRAM=" + str(root / ".tools/msys64/ucrt64/bin/ninja.exe"),
                      "-DCMAKE_PREFIX_PATH=" + str(root / ".tools/msys64/ucrt64"),
                      "-DOPENSSL_ROOT_DIR=" + str(root / ".tools/msys64/ucrt64")]
    else:
        configure += ["-G", "Visual Studio 17 2022", "-A", "x64",
                      "-DCMAKE_PREFIX_PATH=" + str(root / ".tools/Qt/5.15.2/msvc2019_64"),
                      "-DOPENSSL_ROOT_DIR=" + str(root / ".tools/openssl/Library")]
    targets = ["dukto-cli", "directory-cleanup-tests", "client-download-cleanup-tests",
               "expired-task-cleanup-tests", "durable-receive-tests", "core-tests", "sqlite-cache-tests",
               "strong-manifest-tests", "task-store-tests"]
    steps = [("configure", configure), ("build", [str(cmake), "--build", str(build), "--config", "Release",
                                                "--parallel", "2", "--target", *targets])]
    for name, command in steps:
        started = time.monotonic()
        with (build / (name + ".log")).open("wb") as log:
            result = subprocess.run(command, env=env, cwd=repo, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        print(json.dumps({"toolchain": args.label, "step": name, "exitCode": result.returncode,
                          "seconds": round(time.monotonic() - started, 3)}), flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()

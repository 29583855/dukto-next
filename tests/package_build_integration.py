"""日期：2026-11-09；使用真实CMake编译复现错误构建根与旧mtime对象，验证打包拒绝混源。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package_build import refresh_build, verify_build


# 日期：2026-11-09；稳定要求拒绝，不能以日志字段或模拟构建进程代替真实编译检查。
def refused(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Mismatched application build was accepted")


# 日期：2026-11-09；隔离编译两个C++14程序，修改源后恢复旧时间戳，最终程序必须输出新正文。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--generator", default="Ninja")
    args = parser.parse_args()
    report = Path(args.report).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dukto-package-build-") as temporary:
        base = Path(temporary)
        root, build = base / "中文 source", base / "build"
        (root / "src").mkdir(parents=True)
        (root / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20)\nproject(DuktoNext LANGUAGES CXX)\n"
            "set(CMAKE_CXX_STANDARD 14)\nset(CMAKE_CXX_STANDARD_REQUIRED ON)\n"
            "add_executable(dukto-cli src/main.cpp)\nadd_executable(dukto-gui src/main.cpp)\n", "utf-8")
        source = root / "src/main.cpp"
        source.write_text('#include <iostream>\nint main() { std::cout << "one"; }\n', "utf-8")
        stamp = source.stat().st_mtime_ns
        subprocess.run(["cmake", "-S", str(root), "-B", str(build), "-G", args.generator,
                        "-DCMAKE_BUILD_TYPE=Release"], check=True)
        suffix = ".exe" if os.name == "nt" else ""
        binaries = ["dukto-cli" + suffix, "dukto-gui" + suffix]
        first = refresh_build(root, build, binaries, report.with_suffix(".first.log"))
        verify_build(root, build, first)
        assert subprocess.check_output([str(build / binaries[0])]) == b"one"
        source.write_text('#include <iostream>\nint main() { std::cout << "two"; }\n', "utf-8")
        os.utime(source, ns=(stamp, stamp))
        refused(lambda: verify_build(root, build, first))
        # 日期：2026-11-09；普通增量构建确实复用了旧对象，证明夹具触发了实际风险。
        subprocess.run(["cmake", "--build", str(build)], check=True)
        assert subprocess.check_output([str(build / binaries[0])]) == b"one"
        second = refresh_build(root, build, binaries, report.with_suffix(".second.log"))
        verify_build(root, build, second)
        for name in binaries:
            assert subprocess.check_output([str(build / name)]) == b"two"
        other = base / "other"
        shutil.copytree(root, other)
        refused(lambda: refresh_build(other, build, binaries, report.with_suffix(".wrong-root.log")))
        assert not report.with_suffix(".wrong-root.log").exists()
        cache = build / "CMakeCache.txt"
        original_cache = cache.read_bytes()
        try:
            cache.write_text("CMAKE_PROJECT_NAME:STATIC=DuktoNext\n", "utf-8")
            refused(lambda: refresh_build(root, build, binaries, report.with_suffix(".missing-root.log")))
            assert not report.with_suffix(".missing-root.log").exists()
        finally:
            cache.write_bytes(original_cache)
        binary = build / binaries[0]
        with binary.open("ab") as stream:
            stream.write(b"changed")
        refused(lambda: verify_build(root, build, second))
    result = {"passed": True, "realCpp14Build": True, "oldMtimeRiskReproduced": True,
              "cleanRebuildUsedNewContent": True, "differentSourceRootRejected": True,
              "missingSourceRootRejected": True, "sourceDriftRejected": True, "binaryDriftRejected": True}
    report.write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

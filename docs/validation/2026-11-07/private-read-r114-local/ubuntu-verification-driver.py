"""日期：2026-11-07；隔离验证私有配置重读，Qt回归用例直接取自实际维护测试函数。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；固定归档加四个明确修改源构成候选源码，原R113目录与程序保持不变。
def main():
    root = Path.cwd()
    output = root / ".cache/private-read-r114-validation"
    output.mkdir(exist_ok=False)
    ssh = runpy.run_path(str(root / ".cache/validate-exit-state-r98-final-glibc.py"))["SSH"]
    remote = "/home/dukto/private-read-r114-validation"
    subprocess.run(ssh + ["mkdir " + remote], check=True, timeout=30, capture_output=True)
    names = ("src/core/sourcefile.h", "src/core/sourcefile.cpp", "src/core/privatestore.cpp", "tests/core_tests.cpp")
    files = {name: (root / name).read_bytes() for name in names}
    for raw in files.values():
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw
    source = files["tests/core_tests.cpp"].decode("utf-8")
    a = source.index("    // 日期：2026-11-07；真实原子配置写入与并发读取竞争")
    b = source.index("\n#endif", a)
    case = source[a:b]
    qt_source = '''#include "core/privatestore.h"
#include "core/error.h"
#include <QTemporaryDir>
#include <QtTest>
#include <array>
#include <atomic>
#include <exception>
#include <thread>
class PrivateReadTests final : public QObject {
    Q_OBJECT
  private slots:
''' + case + '''
};
QTEST_GUILESS_MAIN(PrivateReadTests)
#include "q.moc"
'''
    files["q.cpp"] = qt_source.encode("utf-8")
    files["probe.cpp"] = (root / ".cache/private-read-r114-probe.cpp").read_bytes()
    objects = ["error", "files", "nativecommit", "filecredit"]
    cmake = '''cmake_minimum_required(VERSION 3.20)
project(PrivateReadValidation LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
find_package(Qt5 5.15 REQUIRED COMPONENTS Core Network Test)
add_library(candidate STATIC src/core/sourcefile.cpp src/core/privatestore.cpp)
target_include_directories(candidate PUBLIC src)
target_link_libraries(candidate PUBLIC Qt5::Core Qt5::Network)
'''
    cmake += "target_sources(candidate PRIVATE\n" + "".join(
        "  /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/src/core/" + name + ".cpp.o\n" for name in objects) + ")\n"
    cmake += '''add_executable(probe probe.cpp)
target_link_libraries(probe PRIVATE candidate)
add_executable(private-read-tests q.cpp)
target_link_libraries(private-read-tests PRIVATE candidate Qt5::Test)
'''
    files["CMakeLists-validation.txt"] = cmake.encode("utf-8")
    setup = "set -eu\ncd " + remote + "\ntar xzf /home/dukto/private-read-r113-diagnostic/source.tar.gz\nmkdir -p tests\n"
    subprocess.run(ssh + ["sh -s"], input=setup.encode(), check=True, timeout=60, capture_output=True)
    for name, raw in files.items():
        # 日期：2026-11-07；仅覆盖新隔离副本的明确候选文件，原始R113源码和长测不变。
        subprocess.run(ssh + ["cat > " + remote + "/" + name], input=raw, check=True, timeout=30, capture_output=True)
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    script = '''set -eu
cd /home/dukto/private-read-r114-validation
cp CMakeLists-validation.txt CMakeLists.txt
cmake -S . -B candidate-build -G Ninja -DCMAKE_BUILD_TYPE=Release > configure.log 2>&1
nice -n 10 cmake --build candidate-build --parallel 2 > build.log 2>&1
sha256sum candidate-build/probe candidate-build/private-read-tests > binaries-before.sha256
candidate-build/private-read-tests -o qt.log,txt -o qt.xml,junitxml
candidate-build/probe > probe-result.json
sha256sum candidate-build/probe candidate-build/private-read-tests > binaries-after.sha256
cmp binaries-before.sha256 binaries-after.sha256
cat probe-result.json
'''
    (output / "driver.sh").write_text(script, "utf-8")
    with (output / "driver.log").open("xb") as log:
        result = subprocess.run(ssh + ["sh -s"], input=script.encode(), stdout=log,
                                stderr=subprocess.STDOUT, timeout=600)
    for name in ("configure.log", "build.log", "qt.log", "qt.xml", "probe-result.json", "binaries-before.sha256", "binaries-after.sha256"):
        fetched = subprocess.run(ssh + ["cat " + remote + "/" + name], capture_output=True, timeout=30)
        if fetched.returncode == 0:
            (output / name).write_bytes(fetched.stdout)
    value = {"observedUtc": datetime.now(timezone.utc).isoformat(), "baselineSourceCommit": "400e0621745dc250b3390ad01a5e9f47dfc924a4",
             "candidateFiles": [{"path": name, "sha256": hashlib.sha256(files[name]).hexdigest()} for name in names],
             "qtMethodExtractedFromActualCoreTests": True, "frozenR113ObjectFiles": objects,
             "exitCode": result.returncode, "deliveryComplete": False, "releaseQualified": False}
    (output / "receipt.json").write_text(json.dumps(value, indent=2) + "\n", "utf-8")
    print(json.dumps(value), flush=True)
    if (output / "probe-result.json").exists():
        print((output / "probe-result.json").read_text("utf-8"), flush=True)


if __name__ == "__main__":
    main()

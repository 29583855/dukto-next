"""日期：2026-11-07；独立Ubuntu目录构建精确R113原件，复现配置读取竞争，不修改长测。"""

import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；只新建隔离源目录，归档来自固定Git对象而非正在编辑的工作区。
def main():
    root = Path.cwd()
    output = root / ".cache/private-read-r113-diagnostic"
    output.mkdir(exist_ok=False)
    repo = root / ".cache/github-29583855-dukto-next-r28"
    source = "400e0621745dc250b3390ad01a5e9f47dfc924a4"
    archive = subprocess.check_output(["git", "archive", "--format=tar.gz", source, "--",
                                       "CMakeLists.txt", "src", "resources", "ui", ".clang-format"], cwd=repo)
    (output / "source.tar.gz").write_bytes(archive)
    probe = (root / ".cache/private-read-r113-probe.cpp").read_bytes()
    ssh = runpy.run_path(str(root / ".cache/validate-exit-state-r98-final-glibc.py"))["SSH"]
    remote = "/home/dukto/private-read-r113-diagnostic"
    subprocess.run(ssh + ["mkdir " + remote], check=True, timeout=30, capture_output=True)
    for name, data in (("source.tar.gz", archive), ("probe.cpp", probe)):
        subprocess.run(ssh + ["set -C; cat > " + remote + "/" + name], input=data,
                       check=True, timeout=60, capture_output=True)
    script = r'''set -eu
cd /home/dukto/private-read-r113-diagnostic
sha256sum source.tar.gz probe.cpp
tar xzf source.tar.gz
cmake -S . -B build -G Ninja -DDUKTO_BUILD_GUI=OFF -DDUKTO_BUILD_TESTS=OFF -DCMAKE_BUILD_TYPE=Release > configure.log 2>&1
cmake --build build --target dukto-core --parallel 2 > build.log 2>&1
g++ -std=c++14 -fPIC -pthread -Isrc probe.cpp build/libdukto-core.a $(pkg-config --cflags --libs Qt5Core Qt5Network Qt5Sql) -lcrypto -o probe > probe-build.log 2>&1
sha256sum probe build/libdukto-core.a > binaries-before.sha256
./probe > probe-result.json
sha256sum probe build/libdukto-core.a > binaries-after.sha256
cmp binaries-before.sha256 binaries-after.sha256
cat probe-result.json
'''
    with (output / "driver.log").open("xb") as log:
        result = subprocess.run(ssh + ["sh -s"], input=script.encode("utf-8"), stdout=log,
                                stderr=subprocess.STDOUT, timeout=900)
    for name in ("probe-result.json", "configure.log", "build.log", "probe-build.log", "binaries-before.sha256", "binaries-after.sha256"):
        result_file = subprocess.run(ssh + ["cat " + remote + "/" + name], capture_output=True, timeout=30)
        if result_file.returncode == 0:
            (output / name).write_bytes(result_file.stdout)
    value = {"sourceCommit": source, "sourceArchiveSha256": hashlib.sha256(archive).hexdigest(),
             "probeSha256": hashlib.sha256(probe).hexdigest(), "exitCode": result.returncode,
             "originalProcessesAndInputsNotModified": True}
    (output / "receipt.json").write_text(json.dumps(value, indent=2) + "\n", "utf-8")
    print(json.dumps(value), flush=True)
    if (output / "probe-result.json").exists():
        print((output / "probe-result.json").read_text("utf-8"), flush=True)


if __name__ == "__main__":
    main()

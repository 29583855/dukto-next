"""日期：2026-11-09；部署前从同一源码干净编译，并冻结实际输入及原始程序身份。"""

import hashlib
import json
from pathlib import Path
import subprocess


# 日期：2026-11-09；流式读取，源码压缩包和程序的大小不决定摘要计算的内存用量。
def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


# 日期：2026-11-09；只枚举真正参与应用编译的维护输入，不把测试输出或凭据收入构建凭据。
def build_inputs(root):
    paths = [root / "CMakeLists.txt"]
    for folder in ("src", "ui", "resources", "third-party/sqlite-runtime"):
        paths.extend(path for path in (root / folder).rglob("*") if path.is_file())
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}


# 日期：2026-11-09；先核对CMake真实源目录；清理旧对象后编译，旧mtime不能让过期对象冒充当前源码。
def refresh_build(root, build, binaries, log, environment=None):
    root, build = root.resolve(strict=True), build.resolve(strict=True)
    cache = {}
    for line in (build / "CMakeCache.txt").read_text(encoding="utf-8").splitlines():
        if not line.startswith(("#", "//")) and "=" in line and ":" in line.split("=", 1)[0]:
            key, value = line.split("=", 1)
            cache[key.split(":", 1)[0]] = value
    source_directory = cache.get("CMAKE_HOME_DIRECTORY")
    if (cache.get("CMAKE_PROJECT_NAME") != "DuktoNext" or not source_directory
            or Path(source_directory).resolve() != root):
        raise ValueError("Build directory belongs to different application sources")
    inputs = build_inputs(root)
    commands = [["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release"],
                ["cmake", "--build", str(build), "--config", "Release", "--clean-first",
                 "--target", "dukto-cli", "dukto-gui", "--parallel", "2"]]
    with log.open("xb") as stream:
        for command in commands:
            stream.write((json.dumps(command, ensure_ascii=False) + "\n").encode("utf-8"))
            stream.flush()
            result = subprocess.run(command, env=environment, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=7200)
            if result.returncode:
                raise RuntimeError("Application refresh failed; inspect " + str(log))
    if inputs != build_inputs(root):
        raise ValueError("Application sources changed during compilation")
    binary_hashes = {name: digest(build / name) for name in binaries}
    return {"sourceRoot": str(root), "buildRoot": str(build), "cleanBuild": True,
            "configuration": "Release", "sourceHashes": inputs, "binaryHashes": binary_hashes}


# 日期：2026-11-09；归档前再次核对编译源与原始程序，部署工具只能修改复制到包内的副本。
def verify_build(root, build, provenance):
    if (build_inputs(root) != provenance["sourceHashes"]
            or any(digest(build / name) != value for name, value in provenance["binaryHashes"].items())):
        raise ValueError("Application inputs changed during packaging")

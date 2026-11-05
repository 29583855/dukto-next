"""日期：2026-11-05；按内容校验源码快照，安装时刷新构建输入时间，避免 tar 旧时间戳混用旧对象。"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile
import time

ROOT_FILES = {"CMakeLists.txt", ".clang-format", ".gitignore", "LICENSE", "README.md", "开发计划与进度.md", "AGENTS.md"}
ROOT_DIRS = {"src", "ui", "resources", "scripts", "tests", "docs", ".github"}
RECEIPT = ".dukto-source-snapshot.json"
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024


# 日期：2026-11-05；只允许维护源码目录，排除验证结果、解释器缓存、原版程序、秘密及构建依赖。
def allowed(name):
    path = PurePosixPath(name)
    return (bool(path.parts) and path.as_posix() == name and not path.is_absolute()
            and all(part not in ("", ".", "..", "validation", "__pycache__") and ":" not in part and "\\" not in part
                    for part in path.parts)
            and (name in ROOT_FILES or (len(path.parts) > 1 and path.parts[0] in ROOT_DIRS))
            and path.suffix not in (".pyc", ".exe", ".dll", ".sqlite", ".key"))


# 日期：2026-11-05；逐文件核对普通文件和目录链，不沿符号链接或 Windows 重解析点写入。
def safe_path(root, name):
    if not allowed(name):
        raise ValueError("Disallowed source path: " + name)
    current = root
    for part in PurePosixPath(name).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked source path: " + name)
    return current


# 日期：2026-11-05；仅归档明确管理的普通源码，保留原始字节；每份快照包含独立大小和 SHA-256 清单。
def create(root, archive):
    paths = [root / name for name in ROOT_FILES if (root / name).is_file()]
    for folder in ROOT_DIRS:
        for directory, children, files in os.walk(root / folder, followlinks=False):
            children[:] = [name for name in children if name not in ("validation", "__pycache__")]
            paths.extend(Path(directory) / name for name in files
                         if allowed((Path(directory) / name).relative_to(root).as_posix()))
    paths.sort()
    values, total = {}, 0
    for path in paths:
        name = path.relative_to(root).as_posix()
        safe_path(root, name)
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_TOTAL or len(values) >= 4096:
            raise ValueError("Source snapshot exceeds limits")
        values[name] = raw
    if "CMakeLists.txt" not in values:
        raise ValueError("CMake project is missing")
    manifest = {"version": 1, "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                                        for name, raw in values.items()}}
    with tarfile.open(archive, "x:gz") as output:
        for name, raw in [(RECEIPT, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")), *values.items()]:
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(raw), 0o644
            output.addfile(member, io.BytesIO(raw))
    return {"files": len(values), "bytes": total, "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


# 日期：2026-11-05；所有成员与摘要先验证完毕才写盘，重复/额外成员、链接和路径穿越一律拒绝。
def read_archive(archive):
    values, total = {}, 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            if (not member.isfile() or member.name in values or member.size < 0 or member.size > MAX_FILE
                    or (member.name != RECEIPT and not allowed(member.name))):
                raise ValueError("Invalid snapshot member: " + member.name)
            raw = source.extractfile(member).read(MAX_FILE + 1)
            total += len(raw)
            if len(raw) != member.size or total > MAX_TOTAL or len(values) >= 4097:
                raise ValueError("Source snapshot exceeds limits")
            values[member.name] = raw
    manifest = json.loads(values.pop(RECEIPT))
    if (manifest.get("version") != 1 or set(values) != set(manifest["files"]) or "CMakeLists.txt" not in values):
        raise ValueError("Snapshot manifest differs from members")
    for name, raw in values.items():
        if manifest["files"][name] != {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}:
            raise ValueError("Source digest mismatch: " + name)
    return manifest, values


# 日期：2026-11-05；同目录临时文件替换后显式刷新时间，不继承归档旧 mtime；原始编码/换行保持。
def replace_bytes(path, raw, stamp):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".dukto-sync-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.utime(temporary, ns=(stamp, stamp))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# 日期：2026-11-05；首次安装刷新全部输入，后续按内容更新；构建产物来自未来时拒绝增量并要求 clean。
def install(root, archive):
    manifest, values = read_archive(archive)
    if not root.is_dir():
        raise ValueError("Destination project directory must exist")
    receipt = root / RECEIPT
    if receipt.is_symlink():
        raise ValueError("Linked snapshot receipt")
    previous = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else {"files": {}}
    for name in set(values) | set(previous["files"]):
        safe_path(root, name)
    stamp = time.time_ns()
    build = root / "build"
    if build.exists():
        for path in build.rglob("*"):
            if path.is_file() and path.suffix in (".o", ".obj", ".a", ".lib") and path.stat().st_mtime_ns >= stamp:
                raise ValueError("Build artifact timestamp is in the future; clean rebuild required")
    removed = sorted(set(previous["files"]) - set(values))
    for name in removed:
        path = safe_path(root, name)
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != previous["files"][name]["sha256"]:
            raise ValueError("Locally changed obsolete source: " + name)
    changed = []
    for name, raw in values.items():
        path = safe_path(root, name)
        if not receipt.exists() or not path.is_file() or path.read_bytes() != raw:
            replace_bytes(path, raw, stamp)
            changed.append(name)
    for name in removed:
        safe_path(root, name).unlink(missing_ok=True)
    replace_bytes(receipt, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), stamp)
    return {"files": len(values), "updated": changed, "removed": removed, "timestampNanoseconds": stamp}


# 日期：2026-11-05；构建必须在安装成功之后单独执行，调用方负责等待先前构建/测试结束。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "install"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.absolute()
    if root.is_symlink() or getattr(root.lstat(), "st_file_attributes", 0) & 0x400:
        raise ValueError("Project root must not be a link")
    result = create(root, args.archive) if args.operation == "create" else install(root, args.archive)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

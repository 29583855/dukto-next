"""日期：2026-11-25；导出指定Git提交和固定依赖原归档，生成可逐件核验的完整源码交付包。"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor


# 日期：2026-11-25；只执行参数数组，Git对象作为独立参数传递，禁止解释为Shell命令。
def git(repository, *arguments):
    return subprocess.check_output(["git", "-C", str(repository), *arguments])


# 日期：2026-11-25；流式核对大型归档，避免将全部Qt源码同时装入内存。
def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


# 日期：2026-11-25；直接读取Git树和blob原字节，避免git archive受宿主换行及导出属性改写。
def tracked_files(repository, commit, paths):
    listing = git(repository, "ls-tree", "-rz", "--full-tree", commit, "--", *paths)
    entries = []
    for line in listing.split(b"\0"):
        if not line:
            continue
        metadata, path = line.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("源码树含非常规文件，必须显式审查: " + path.decode("utf-8"))
        entries.append((path.decode("utf-8"), mode, object_id))
    request = b"".join(object_id + b"\n" for _, _, object_id in entries)
    response = subprocess.check_output(["git", "-C", str(repository), "cat-file", "--batch"], input=request)
    stream = io.BytesIO(response)
    result = []
    for path, mode, object_id in entries:
        actual_id, kind, size_text = stream.readline().split()
        size = int(size_text)
        data = stream.read(size)
        if actual_id != object_id or kind != b"blob" or len(data) != size or stream.read(1) != b"\n":
            raise ValueError("Git blob读取结果不完整")
        result.append((path, data, 0o755 if mode == b"100755" else 0o644))
    if stream.read():
        raise ValueError("Git blob读取包含额外数据")
    return result


# 日期：2026-11-25；来源名称限于单级归档文件名，防止锁文件覆盖缓存外路径。
def archive_name(source):
    name = source["url"].rsplit("/", 1)[-1]
    if not name or name in (".", "..") or "\\" in name or ":" in name or "?" in name or "#" in name:
        raise ValueError("非法源码归档文件名")
    return name


# 日期：2026-11-25；命中缓存仍核对锁定摘要；下载临时文件失败会清理，不接受不完整归档。
def acquire(source, cache):
    target = cache / archive_name(source)
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or digest(target) != source["sha256"]:
            raise ValueError("缓存源码摘要或类型错误: " + source["name"])
        return target
    descriptor, temporary_name = tempfile.mkstemp(prefix=".source-", dir=cache)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            with urllib.request.urlopen(source["url"], timeout=180) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        if digest(temporary) != source["sha256"]:
            raise ValueError("下载源码摘要错误: " + source["name"])
        temporary.replace(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


# 日期：2026-11-25；交付只包含常规文件，拒绝路径穿越、符号链接、硬链接及重复成员。
def safe_member(member, root):
    path = PurePosixPath(member.name)
    if ("\\" in member.name or path.is_absolute() or ".." in path.parts or
            not path.parts or path.parts[0] != root or len(path.parts) < 2 or
            member.name != path.as_posix() or not member.isfile()):
        raise ValueError("源码包包含非法成员: " + member.name)


# 日期：2026-11-25；每项字节与可执行位写入清单，归档头固定，禁止随包携带本机用户名和路径。
def add_bytes(bundle, name, data, mode, records):
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mode = mode
    member.mtime = 0
    bundle.addfile(member, io.BytesIO(data))
    records.append({"path": name, "size": len(data), "mode": mode,
                    "sha256": hashlib.sha256(data).hexdigest()})


# 日期：2026-11-25；大型上游压缩包直接流式写入，记录原始摘要，不重新压缩改写源码字节。
def add_file(bundle, name, path, records):
    member = tarfile.TarInfo(name)
    member.size = path.stat().st_size
    member.mode = 0o644
    member.mtime = 0
    with path.open("rb") as stream:
        bundle.addfile(member, stream)
    records.append({"path": name, "size": member.size, "mode": member.mode, "sha256": digest(path)})


# 日期：2026-11-25；验证清单和完整包内容，无提取动作，损坏、遗漏或额外文件均拒绝。
def verify(path):
    with tarfile.open(path, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members:
            raise ValueError("源码包为空")
        root = members[0].name.split("/", 1)[0]
        selected = {}
        for member in members:
            safe_member(member, root)
            if member.name in selected:
                raise ValueError("源码包存在重复成员")
            selected[member.name] = member
        manifest_name = root + "/SOURCE-MANIFEST.json"
        if manifest_name not in selected or selected[manifest_name].size > 8 * 1024 * 1024:
            raise ValueError("源码包清单缺失或过大")
        manifest = json.load(bundle.extractfile(selected[manifest_name]))
        expected = manifest["files"]
        names = [entry["path"] for entry in expected]
        if len(set(names)) != len(names) or set(names) != set(selected) - {manifest_name}:
            raise ValueError("源码清单存在重复、缺失或额外文件")
        for entry in expected:
            member = selected[entry["path"]]
            with bundle.extractfile(member) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if (actual != entry["sha256"] or member.size != entry["size"] or
                    member.mode != entry["mode"]):
                raise ValueError("源码成员摘要、大小或权限错误: " + entry["path"])
        lock_name = root + "/DuktoNextMobile/scripts/dependencies.json"
        lock = json.load(bundle.extractfile(selected[lock_name]))
        for source in lock["sources"]:
            upstream = root + "/upstream/" + archive_name(source)
            record = next((entry for entry in expected if entry["path"] == upstream), None)
            if not record or record["sha256"] != source["sha256"]:
                raise ValueError("固定依赖源码缺失或摘要不符")
        return {"passed": True, "scope": "精确Git源码与固定依赖归档完整性；不表示真机或发行许可验收",
                "sourceCommit": manifest["sourceCommit"], "fileCount": len(expected),
                "dependencyCount": len(lock["sources"]), "archiveSha256": digest(path),
                "deviceTestsPassed": False, "rebuildPassed": False}


# 日期：2026-11-25；精确导出提交内的项目与构建流程，排除所有工作区、缓存、密钥和未跟踪文件。
def create(repository, reference, output, cache):
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", reference + "^{commit}").decode().strip()
    root = "DuktoNextMobile-source-" + commit[:12]
    paths = ["DuktoNextMobile", "docs/iOS与Android开发计划与进度.md",
             ".github/workflows/mobile-build.yml", ".github/workflows/mobile-storage.yml",
             ".github/workflows/mobile-extended.yml", ".github/workflows/mobile-source.yml"]
    sources = tracked_files(repository, commit, paths)
    lock = json.loads(next(data for path, data, _ in sources
                           if path == "DuktoNextMobile/scripts/dependencies.json"))
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / (root + ".tar.gz")
    if archive_path.exists():
        raise FileExistsError("输出源码包已存在，禁止覆盖: " + str(archive_path))
    with ThreadPoolExecutor(max_workers=3) as pool:
        upstream = list(pool.map(lambda item: acquire(item, cache), lock["sources"]))
    temporary = archive_path.with_suffix(".partial")
    records = []
    instructions = """# 源码交付与重建

日期：2026-11-25。源码来自SOURCE-MANIFEST.json记录的精确Git提交；不包含工作区改动。
upstream/保存依赖锁列明的全部原始源码压缩包，包括构建未使用的锁定模块。

1. 用发布方随附SHA256SUMS.txt核对本归档；解包后核对SOURCE-MANIFEST.json。
2. 使用Linux构建Android，macOS构建iOS，工具链版本和命令见项目docs/构建与许可证说明.md及.github/workflows/。
3. 将DUKTO_SOURCE_ARCHIVES设置为解包后的upstream绝对路径，依赖及许可采集均从本地归档读取；摘要不符或缺失立即失败，不回退联网。
4. 在DuktoNextMobile目录执行scripts/build_dependencies.py，再执行scripts/build_app.py，参数见构建文档。
5. iOS静态库、应用源码、Qt修改点及完整构建脚本均可从此源码重新生成；需macOS/Xcode及系统SDK。签名/安装仍需接收方有效Apple团队配置。

此源码包没有内置第三方SDK/JDK/NDK/Gradle仓库缓存，不代表完全断网安装工具链或Gradle构建。
上游原归档按锁定SHA256保存，平台补丁由build_dependencies.py显式应用，未对上游归档改字节。
完整源码可用于修改、重建与重新链接；本包完整性通过不等于已验证两平台从交付包重建或完成正式分发许可审核。
许可证原文在项目LICENSE、上游源码及对应开发包licenses/。真机、签名及正式发行状态以项目当前验收文档为准。
"""
    try:
        with temporary.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as bundle:
                for path, data, mode in sources:
                    member = tarfile.TarInfo(path)
                    safe_member(member, path.split("/", 1)[0])
                    add_bytes(bundle, root + "/" + path, data, mode, records)
                for path in upstream:
                    add_file(bundle, root + "/upstream/" + path.name, path, records)
                add_bytes(bundle, root + "/源码重建说明.md", instructions.encode("utf-8"), 0o644, records)
                manifest = {"format": 1, "date": "2026-11-25", "sourceCommit": commit,
                            "files": records, "deviceTestsPassed": False, "rebuildPassed": False}
                add_bytes(bundle, root + "/SOURCE-MANIFEST.json",
                          (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), 0o644, [])
        result = verify(temporary)
        temporary.replace(archive_path)
        result["archiveFile"] = archive_path.name
        (output / "source-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
        (output / "SHA256SUMS.txt").write_text(result["archiveSha256"] + "  " + archive_path.name + "\n", "utf-8")
        return result
    finally:
        temporary.unlink(missing_ok=True)


# 日期：2026-11-25；创建和复核模式分开，复核不联网、不执行归档内代码。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("create")
    export.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[2])
    export.add_argument("--ref", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--cache", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("archive", type=Path)
    args = parser.parse_args()
    result = verify(args.archive) if args.command == "verify" else create(args.repository, args.ref, args.output, args.cache)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

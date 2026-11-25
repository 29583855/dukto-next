"""日期：2026-11-25；仅复用已审查为iOS等价的固定构建器缓存，拒绝未来脚本的隐式兼容。"""
import argparse
import hashlib
import json
from pathlib import Path
import platform


# 日期：2026-11-26；f20c51ab仅增加固定摘要离线归档读取；iOS编译参数及补丁与前版相同。
REVIEWED_CURRENT = "b623c4a8c1e0a1958401d9d8978d54e6d80d48441f43d8cbe2000c40d6d323a8"
REVIEWED_BUILDERS = {
    REVIEWED_CURRENT,
    "eac5dc293da229bfcacd8b8cc4737493fb44af9c29b9f0242cfbd4e4182ba3e5",
    "156348002b46a68d03495194e0e756fb5d295ee4b1bf236adc9f175d9fd6fac9",
}
REQUIRED = (
    "qt/bin/qmake", "qt/lib/libQt5Core.a", "qt/lib/libQt5Gui.a",
    "qt/lib/libQt5Network.a", "qt/lib/libQt5Sql.a", "qt/lib/libQt5Qml.a",
    "qt/lib/libQt5Quick.a", "qt/lib/libQt5QuickControls2.a",
    "openssl/lib/libssl.a", "openssl/lib/libcrypto.a",
)


# 日期：2026-11-25；旧脚本与当前脚本仅有Android分支补丁差异，精确锁定两者及完整依赖清单。
def validate(prefix, lock, builder_hash, machine):
    if builder_hash != REVIEWED_CURRENT:
        return False, "当前构建器未在iOS等价性审查名单中"
    if machine != "arm64":
        return False, "缓存仅审查过macOS arm64宿主"
    try:
        manifest = json.loads((prefix / "dependency-manifest.json").read_text("utf-8"))
        if manifest.get("platform") != "ios" or manifest.get("sourceBuild") is not True:
            return False, "缓存平台或源码构建标记不匹配"
        if manifest.get("dependencies") != lock:
            return False, "缓存依赖源码锁不匹配"
        if manifest.get("builderSha256") not in REVIEWED_BUILDERS:
            return False, "缓存构建器未经等价性审查"
        host = manifest.get("host", "")
        if not host.startswith("macOS-15.") or "-arm64-" not in host:
            return False, "缓存宿主与macOS15 arm64构建环境不匹配"
        for relative in REQUIRED:
            path = prefix / relative
            if not path.is_file() or path.stat().st_size == 0:
                return False, "缓存安装文件缺失: " + relative
        return True, "固定源码锁与iOS等价构建器检查通过；应用仍须完整原生编译和验包"
    except (OSError, ValueError, TypeError) as error:
        return False, "缓存收据不可用: " + str(error)


# 日期：2026-11-25；向GitHub输出可用状态；未知缓存执行原构建，不把命中缓存当成验包通过。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = Path(__file__).parent
    lock = json.loads((directory / "dependencies.json").read_text("utf-8"))
    builder_hash = hashlib.sha256((directory / "build_dependencies.py").read_bytes()).hexdigest()
    usable, reason = validate(args.prefix, lock, builder_hash, platform.machine())
    print(json.dumps({"usable": usable, "reason": reason}, ensure_ascii=False))
    with args.output.open("a", encoding="utf-8") as output:
        output.write("usable=" + str(usable).lower() + "\n")


if __name__ == "__main__":
    main()

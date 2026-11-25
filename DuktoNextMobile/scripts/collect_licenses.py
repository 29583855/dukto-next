"""日期：2026-11-25；核对Qt归属元数据引用，补齐开发包第三方声明，不触发原生库重编译。"""
import hashlib
import json
from pathlib import Path
import shutil
from build_dependencies import extract


# 日期：2026-11-25；完整采集固定来源许可及Qt显式引用的任意名称声明，缺失即失败。
def licenses(source, prefix, name):
    destination = prefix / "licenses" / name
    destination.mkdir(parents=True, exist_ok=True)
    selected = set()
    attributions = []
    # 日期：2026-11-25；除惯例文件名外，必须收集Qt归属元数据显式引用的任意名称许可证。
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(source)
        upper = path.name.upper()
        if (any(word in upper for word in ("LICENSE", "LICENCE", "COPYING", "NOTICE")) or
                upper == "QT_ATTRIBUTION.JSON" or "LICENSES" in relative.parts):
            selected.add(path)
        if upper != "QT_ATTRIBUTION.JSON":
            continue
        # 日期：2026-11-25；官方Qt5归属文件含多行字符串，按Qt元数据约定允许字符串内换行。
        records = json.loads(path.read_text("utf-8"), strict=False)
        if not isinstance(records, list):
            records = [records]
        for record in records:
            references = record.get("LicenseFile", [])
            if isinstance(references, str):
                references = [references]
            files = []
            for reference in references:
                target = (path.parent / reference).resolve()
                if not target.is_relative_to(source.resolve()) or not target.is_file():
                    raise ValueError("许可证引用缺失或越界: " + str(path) + " / " + reference)
                selected.add(target)
                files.append(target.relative_to(source.resolve()).as_posix())
            attributions.append({"metadata": relative.as_posix(), "id": record.get("Id", ""),
                                 "licenseFiles": files})
    entries = []
    for path in sorted(selected):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        entries.append({"path": relative.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not entries:
        raise ValueError("依赖未收集到许可证: " + name)
    (destination / "license-manifest.json").write_bytes(
        (json.dumps({"source": name, "files": entries, "attributions": attributions},
                    ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# 日期：2026-11-25；旧依赖缓存的编译结果可复用，但旧声明清单必须按固定源码重新采集。
def refresh(prefix, work, platform):
    work.mkdir(parents=True, exist_ok=True)
    lock = json.loads(Path(__file__).with_name("dependencies.json").read_text("utf-8"))
    selected = {"openssl", "qtbase", "qtdeclarative", "qtquickcontrols2", "qtgraphicaleffects"}
    if platform == "android":
        selected.add("qtandroidextras")
    result = []
    for entry in lock["sources"]:
        if entry["name"] not in selected:
            continue
        source = extract(entry, work)
        licenses(source, prefix, entry["name"])
        manifest = prefix / "licenses" / entry["name"] / "license-manifest.json"
        result.append({"module": entry["name"], "sourceSha256": entry["sha256"],
                       "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest()})
    (prefix / "licenses/collection-receipt.json").write_bytes(
        (json.dumps({"date": "2026-11-25", "platform": platform, "modules": result},
                    ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

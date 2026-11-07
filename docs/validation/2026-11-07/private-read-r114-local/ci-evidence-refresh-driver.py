"""日期：2026-11-07；把R114编译及核心原件增量绑定计划，完整协议和部署独立验收。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
BASE = REPO / "docs/validation/2026-11-07"
SOURCE = "d922dc4c793c77de0553ddf44c0fe1fa2d998c24"


# 日期：2026-11-07；JSON只读原件，明确按固定源提交核对。
def receipt(suffix):
    path = BASE / ("private-read-r114-" + suffix) / "receipt.json"
    value = json.loads(path.read_text("utf-8"))
    assert value.get("sourceCommit", SOURCE) == SOURCE
    return value


# 日期：2026-11-07；维护文档保留原编码和换行，状态只来源于实际回执。
def main():
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    api = "/repos/29583855/dukto-next/actions/runs/"
    native = request(api + "42370990486")
    package = request(api + "42371059159")
    assert native["head_sha"] == package["head_sha"] == SOURCE
    core = receipt("native-core")
    terminal = receipt("native-terminal")
    deployed = receipt("macos-package")
    compiled = receipt("macos-compiled")
    assert compiled["bothArchitecturesCompiledAndVerified"]
    preview = deployed["bothArchitecturesVerified"] and deployed["screenshotsViewed"]
    verified = [row["runner"] for row in core["records"] if row.get("coreQualified")]
    index_path = REPO / "docs/ci-verification-20261107-r114.json"
    index = json.loads(index_path.read_text("utf-8"))
    paths = [REPO / row["path"] for row in index["receipts"]]
    paths += [BASE / ("private-read-r114-" + suffix) / "receipt.json" for suffix in
              ("native-core", "native-terminal", "macos-compiled", "macos-package")]
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(),
                 receipts=[{"path": path.relative_to(REPO).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                           for path in dict.fromkeys(paths)],
                 nativeRun={key: native[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                 macosPackageRun={key: package[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                 nativeCoreVerifiedRunners=verified, nativeCoreQualified=len(verified) == 4,
                 nativeQualificationPending=native["status"] != "completed",
                 fullNativeProtocolQualified=terminal["allFourNativeProtocolJobsVerified"],
                 macosCompiledArchitecturesVerified=2,
                 macosDeploymentQualified=preview)
    if preview:
        index["macosPreviewSourceCommit"] = SOURCE
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", "utf-8")
    replace = runpy.run_path(str(ROOT / ".cache/finalize-r111-snapshot.py"))["replace"]
    plan = ROOT / "开发计划与进度.md"
    lines = plan.read_text("utf-8").splitlines()
    old, = [line for line in lines if line.startswith("- [ ] 同源[四平台原生CI42370990486]")]
    deployed_label = "R114含依赖双Mac预览已验" if preview else "当前已验含依赖Mac预览仍为R113"
    new = "- [ ] 同源[四平台原生CI42370990486](https://github.com/29583855/dukto-next/actions/runs/42370990486)实际运行状态`" + native["status"] + "`；双Mac编译归档已验，核心已验" + str(len(verified)) + "/4平台。完整协议继续按原始附件验收；" + deployed_label + "。"
    replace(plan, old, new)
    if not any(line.startswith("- [x] R114双Mac原生编译归档") for line in lines):
        replace(plan, new, "- [x] R114双Mac原生编译归档官方ZIP/内部tar摘要、精确源码、LICENSE、Mach-O架构与GUI/CLI执行权限通过。[回执](docs/validation/2026-11-07/private-read-r114-macos-compiled/receipt.json)。\n" + new)
    if preview and not any(line.startswith("- [x] R114含依赖双Mac预览") for line in lines):
        replace(plan, new, "- [x] R114含依赖双Mac预览包、精确源码/全部载荷/框架链接、系统PATH迁移、各五项真实CLI/传输报告及Cocoa/高DPI通过，四张截图已查看。[部署回执](docs/validation/2026-11-07/private-read-r114-macos-package/receipt.json)。\n" + new)
    mac = ROOT / "docs/macOS独立预览包.md"
    paragraphs = mac.read_text("utf-8-sig").split("\n\n")
    old = paragraphs[1]
    assert old.startswith("R114精确")
    preview_label = "含依赖双架构预览、迁移运行及四张截图已验，下方可下载R114包" if preview else "含依赖打包继续验收，下方已验含依赖包仍为R113"
    new = "R114精确`" + SOURCE + "`已上传，增加私有配置原子换代有界重读。Apple Silicon/Intel的C++14 GUI及独立CLI已编译并核验两份归档；原生核心已验" + str(len(verified)) + "/4。" + preview_label + "。[完整原生CI](https://github.com/29583855/dukto-next/actions/runs/42370990486)按实际附件另验。"
    replace(mac, old, new)
    if "## R114原生编译归档" not in mac.read_text("utf-8-sig"):
        table = "## R114原生编译归档\n\n双架构官方ZIP、内部tar摘要、源码提交、LICENSE、Mach-O架构和执行权限均已核验。本机副本`dist/macos-compiled-20261107-r114-private-read/`。[回执](validation/2026-11-07/private-read-r114-macos-compiled/receipt.json)。这是编译归档，仍需匹配Qt5/OpenSSL运行依赖。\n\n| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n"
        for row in compiled["packages"]:
            table += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | `{row['artifactSha256']}` | `{row['sha256']}` |\n"
        replace(mac, "## R113最新含依赖预览", table + "\n## R113最新含依赖预览")
    if preview and "## R114最新含依赖预览" not in mac.read_text("utf-8-sig"):
        table = "## R114最新含依赖预览\n\n两架构包内Qt5/OpenSSL、全部载荷与框架链接、对应应用源码逐件核验。各五项真实CLI/传输报告、系统PATH迁移和Cocoa/高DPI通过，四张首页/服务器截图已查看。本机副本`dist/macos-preview-20261107-r114-private-read/`。[原件回执](validation/2026-11-07/private-read-r114-macos-package/receipt.json)。\n\n| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n"
        for row in deployed["records"]:
            table += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | `{row['artifactSha256']}` | `{row['packageSha256']}` |\n"
        table += "\n这是adhoc签名开发预览。正式签名、公证、干净系统、当前版本24h与完整项目仍待验；包部署通过不能替代完整协议。解压与CLI用法见下文。\n\n"
        replace(mac, "## R114原生编译归档", table + "## R114原生编译归档")
        replace(mac, "## R113最新含依赖预览", "## R113含依赖预览（历史）")
    for name in ("开发计划与进度.md", "docs/macOS独立预览包.md"):
        shutil.copyfile(ROOT / name, REPO / name)
    shutil.copyfile(Path(__file__), BASE / "private-read-r114-local/ci-evidence-refresh-driver.py")
    for suffix in ("local", "native-core", "native-terminal", "macos-compiled", "macos-package"):
        folder = BASE / ("private-read-r114-" + suffix)
        shutil.copytree(folder, ROOT / folder.relative_to(REPO), dirs_exist_ok=True)
    shutil.copyfile(index_path, ROOT / index_path.relative_to(REPO))
    print(json.dumps({"macosArchitecturesCompiled": 2, "coreVerifiedRunners": verified,
                      "nativeStatus": native["status"], "packageStatus": package["status"]}))


if __name__ == "__main__":
    main()

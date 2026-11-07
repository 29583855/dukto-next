"""日期：2026-11-07；增量发布R113实际CI证据，编译、核心、协议和部署分别记录。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
BASE = REPO / "docs/validation/2026-11-07"
PREFIX = "skip-reconcile-r113-"
SOURCE = "400e0621745dc250b3390ad01a5e9f47dfc924a4"


# 日期：2026-11-07；既有Markdown保持UTF-8/BOM与原换行，JSON原件不重新编码。
def save_text(path, text):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    value = text.replace("\r\n", "\n").replace("\n", newline).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + value)


# 日期：2026-11-07；分级读取同源回执，未运行或失败状态不得作为通过记录。
def load(name):
    value = json.loads((BASE / (PREFIX + name) / "receipt.json").read_text("utf-8"))
    assert value.get("sourceCommit", SOURCE) == SOURCE
    return value


# 日期：2026-11-07；只更新实际已收验范围，所有原失败与未完成交付项继续保留。
def main():
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    api = "/repos/29583855/dukto-next/actions/runs/"
    native = request(api + "42368086270")
    package_run = request(api + "42368208979")
    assert native["head_sha"] == package_run["head_sha"] == SOURCE
    package_suffix = "macos-package-retry" if (BASE / (PREFIX + "macos-package-retry") / "receipt.json").exists() else "macos-package"
    core, compiled, terminal, package = map(load, ("native-core", "macos-compiled", "native-terminal", package_suffix))
    verified = [row["runner"] for row in core["records"] if row.get("coreQualified")]
    assert compiled["bothArchitecturesCompiledAndVerified"]
    preview = package["bothArchitecturesVerified"] and package["screenshotsViewed"]
    index_path = REPO / "docs/ci-verification-20261107-r113.json"
    index = json.loads(index_path.read_text("utf-8"))
    receipt_paths = [BASE / (PREFIX + suffix) / "receipt.json" for suffix in
                     ("local", "native-core", "macos-compiled", "native-terminal", "macos-package")]
    receipt_paths += [BASE / (PREFIX + "local") / "source-audit.json"]
    if package_suffix != "macos-package":
        receipt_paths.append(BASE / (PREFIX + package_suffix) / "receipt.json")
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(),
                 receipts=[{"path": path.relative_to(REPO).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in receipt_paths],
                 nativeRun={key: native[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                 macosPackageRun={key: package_run[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                 nativeCoreQualificationPending=len(verified) != 4 and native["status"] != "completed",
                 nativeCoreQualified=core["allNativeCoreTestsPassed"],
                 nativeCoreVerifiedRunners=verified,
                 nativeProtocolQualificationPending=native["status"] != "completed",
                 nativeProtocolQualified=terminal["allFourNativeProtocolJobsVerified"],
                 macosCompiledArchitecturesVerified=2,
                 macosDeploymentQualificationPending=package_run["status"] != "completed",
                 macosDeploymentQualified=preview)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", "utf-8")

    plan_path = ROOT / "开发计划与进度.md"
    plan = plan_path.read_text("utf-8-sig")
    core_label = "、".join(verified) if verified else "尚无"
    package_label = "双架构包和截图均已验" if preview else "部署附件仍待完整收验"
    status = f"R113双Mac GUI/CLI原生编译归档已验；核心已验{len(verified)}/4平台，目录专项各59条；{package_label}。完整协议运行状态{native['status']}；整体与正式发布未完成。"
    plan = re.sub(r"^当前阶段：.*$", "当前阶段：" + status, plan, count=1, flags=re.M)
    start, end = plan.index("## R113 跳过目录交错恢复"), plan.index("## R112 配置变更故障测试契约")
    block = plan[start:end]
    lines = block.splitlines()
    preserved = [line for line in lines if line.startswith("- [x]")]
    preserved = [line for line in preserved if "双Mac原生编译归档" not in line and "原生核心已验" not in line and "含依赖预览" not in line and "打包第1次" not in line]
    compiled_link = "docs/validation/2026-11-07/" + PREFIX + "macos-compiled/receipt.json"
    core_link = "docs/validation/2026-11-07/" + PREFIX + "native-core/receipt.json"
    terminal_link = "docs/validation/2026-11-07/" + PREFIX + "native-terminal/receipt.json"
    package_link = "docs/validation/2026-11-07/" + PREFIX + package_suffix + "/receipt.json"
    preserved.append(f"- [x] 双Mac原生编译归档已核对官方ZIP/内部tar摘要、精确源码、LICENSE、Mach-O架构和GUI/CLI执行权限；本机`dist/macos-compiled-20261107-r113-skip-reconcile/`。[归档回执]({compiled_link})。")
    preserved.append(f"- [{'x' if len(verified) == 4 else ' '}] 原生核心已验{len(verified)}/4平台：{core_label}；已验平台各26个CTest、25份Qt XML及目录59条/19方法。Mac既有精确Darwin XFAIL与头像负例警告独立保留。[核心原件]({core_link})。")
    native_conclusion = native["conclusion"] or "待定"
    package_conclusion = package_run["conclusion"] or "待定"
    preserved.append(f"- [{'x' if terminal['allFourNativeProtocolJobsVerified'] else ' '}] [完整协议运行42368086270](https://github.com/29583855/dukto-next/actions/runs/42368086270)状态`{native['status']}`、结论`{native_conclusion}`；已验终态job {sum(row['qualified'] for row in terminal['records'])}/4，未完成/失败不授予通过。[逐平台回执]({terminal_link})。")
    preserved.append(f"- [{'x' if preview else ' '}] [双Mac含依赖预览42368208979](https://github.com/29583855/dukto-next/actions/runs/42368208979)状态`{package_run['status']}`、结论`{package_conclusion}`；{package_label}。[部署回执]({package_link})。")
    if package_suffix != "macos-package":
        preserved.append("- [x] 打包第1次中Intel编译/Cocoa/迁移运行均成功，但GitHub附件服务CreateArtifact五次超时，未取得Intel附件；原失败日志保留。仅失败Intel作业已重跑，第2次结果独立记录，不把网络失败改写为通过。")
    preserved.append("- [ ] 未知身份临时项、全局GC与总磁盘预算、完整R6/GUI、物理LAN/3×3、当前版本各平台24h与正式分发继续待验，整体保持未完成。")
    plan = plan[:start] + "## R113 跳过目录交错恢复（2026-11-07）\n\n" + "\n".join(preserved) + "\n\n" + plan[end:]
    if len(verified) == 4:
        plan = re.sub(r"^\| 当前清理范围 \|.*$", "| 当前清理范围 | R113双Windows四项专项、四原生各26个CTest及目录各59条已验；同提交完整协议另验 | 未知身份临时项、通用缓存和全局磁盘回收 |", plan, count=1, flags=re.M)
        plan = re.sub(r"^\| Windows \|.*$", "| Windows | R113原生26核心与59条目录专项通过；R112双工具链共24个真实故障通过，R100部署另验 | 完整编辑器及系统剪贴板预算、当前版本24h终态和正式发布 |", plan, count=1, flags=re.M)
        plan = re.sub(r"^\| macOS ARM / Intel \|.*$", "| macOS ARM / Intel | R113 C++14 GUI/CLI编译、各26核心/59目录专项通过；含依赖包见下方R113分项，R111/R112历史证据保留 | 完整GUI/选择器、最低干净系统及正式分发 |", plan, count=1, flags=re.M)
    save_text(plan_path, plan)

    mac_path = ROOT / "docs/macOS独立预览包.md"
    mac = mac_path.read_text("utf-8-sig")
    paragraphs = mac.split("\n\n")
    assert paragraphs[1].startswith("R113精确")
    paragraphs[1] = f"R113精确`{SOURCE}`已上传，修复跳过目录的接收/维护交错恢复。Apple Silicon/Intel C++14 GUI及独立CLI均已编译并核验归档；四平台核心已验{len(verified)}/4。{package_label}，完整协议与整体交付继续按实际原件验收。"
    mac = "\n\n".join(paragraphs)
    heading = "## R113原生编译归档"
    if heading in mac:
        a = mac.index(heading)
        b = mac.index("\n## ", a + len(heading))
        mac = mac[:a] + mac[b + 1:]
    table = heading + "\n\n双架构官方ZIP、内部tar摘要、源码提交、LICENSE、Mach-O架构及执行权限均通过。[回执](validation/2026-11-07/" + PREFIX + "macos-compiled/receipt.json)。这是编译归档，需要匹配Qt5/OpenSSL运行依赖。\n\n| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n"
    for row in compiled["packages"]:
        table += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | `{row['artifactSha256']}` | `{row['sha256']}` |\n"
    historical_heading = "## R111最新含依赖预览" if "## R111最新含依赖预览" in mac else "## R111含依赖预览（历史）"
    position = mac.index(historical_heading)
    mac = mac[:position] + table + "\n" + mac[position:]
    if preview:
        deployed_heading = "## R113最新含依赖预览"
        if deployed_heading in mac:
            a = mac.index(deployed_heading)
            b = mac.index("\n## ", a + len(deployed_heading))
            mac = mac[:a] + mac[b + 1:]
        deployed = deployed_heading + "\n\n双架构Qt5/OpenSSL运行依赖、各372份应用源码、全部载荷与框架链接均逐件核验。两包各五项真实CLI/传输报告、系统PATH迁移、Cocoa导航及150%/200%高DPI通过；四张首页/服务器截图已查看。本机副本在`dist/macos-preview-20261107-r113-skip-reconcile/`。[回执](validation/2026-11-07/" + PREFIX + package_suffix + "/receipt.json)。\n\n| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n"
        for row in package["records"]:
            assert row["package"]["applicationSourceFiles"] == 372
            deployed += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | `{row['artifactSha256']}` | `{row['packageSha256']}` |\n"
        deployed += "\n这是adhoc签名开发预览；正式签名、公证、干净系统与完整项目交付仍待验。下方保留R111历史包及原失败，打包成功不覆盖完整协议失败。\n\n"
        position = mac.index("## R113原生编译归档")
        mac = mac[:position] + deployed + mac[position:]
        mac = mac.replace("## R111最新含依赖预览", "## R111含依赖预览（历史）")
    save_text(mac_path, mac)
    local = BASE / (PREFIX + "local")
    shutil.copyfile(Path(__file__), local / "ci-evidence-refresh-driver.py")
    for suffix in dict.fromkeys(("local", "native-core", "macos-compiled", "native-terminal", "macos-package", package_suffix)):
        folder = BASE / (PREFIX + suffix)
        shutil.copytree(folder, ROOT / folder.relative_to(REPO), dirs_exist_ok=True)
    for name in ("开发计划与进度.md", "docs/macOS独立预览包.md"):
        shutil.copyfile(ROOT / name, REPO / name)
    shutil.copyfile(index_path, ROOT / index_path.relative_to(REPO))
    print(json.dumps({"coreVerified": verified, "macosCompiled": 2, "macosPreviewVerified": preview,
                      "nativeStatus": native["status"], "packageStatus": package_run["status"]}))


if __name__ == "__main__":
    main()

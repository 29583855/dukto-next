"""日期：2026-11-07；仅凭四平台核心原件与双Mac编译产物更新公开文档，完整协议不被转授。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
SOURCE = "a29960a38fb46368dd8ac190caed2f4c515f8731"
BASE = "docs/validation/2026-11-07/"


# 日期：2026-11-07；每个公开索引使用相对路径、大小与SHA，原始报告不做格式化或修补。
def proof(path):
    data = path.read_bytes()
    return {"path": path.relative_to(REPO).as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


# 日期：2026-11-07；读真实终态资格，未完成运行保留pending，不能从核心通过反推协议通过。
def main():
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO).decode().strip() == SOURCE
    helper = runpy.run_path(str(ROOT / ".cache/finalize-client-cleanup-r109-publication.py"))
    write, replace, line = helper["write_preserving"], helper["replace_once"], helper["replace_line"]
    core_path = REPO / BASE / "directory-cleanup-r110-native-core/receipt.json"
    mac_path = REPO / BASE / "directory-cleanup-r110-macos-compiled/receipt.json"
    package_path = REPO / BASE / "directory-cleanup-r110-macos-package/receipt.json"
    prior_path = REPO / BASE / "client-cleanup-r109-native-terminal/receipt.json"
    native_path = REPO / BASE / "directory-cleanup-r110-native-terminal/receipt.json"
    core = json.loads(core_path.read_text("utf-8"))
    mac = json.loads(mac_path.read_text("utf-8"))
    deployed = json.loads(package_path.read_text("utf-8"))
    prior = json.loads(prior_path.read_text("utf-8"))
    native = json.loads(native_path.read_text("utf-8"))
    assert core["sourceCommit"] == mac["sourceCommit"] == SOURCE
    assert core["allNativeCoreTestsPassed"] and core["allNativeCleanupTestsPassed"] and len(core["records"]) == 4
    assert all(row["ctestTargetsPassed"] == 26 and row["cleanupRowsPassed"] == 45 for row in core["records"])
    assert mac["bothArchitecturesCompiledAndVerified"] and len(mac["packages"]) == 2
    assert deployed["sourceCommit"] == SOURCE and any(
        row.get("qualified") and row["architecture"] == "arm64" for row in deployed["records"])
    assert deployed["bothArchitecturesVerified"] and all(row.get("qualified") for row in deployed["records"])
    verified_prior = [row["runner"] for row in prior["records"] if row.get("qualified")]
    assert len(verified_prior) >= 3
    prior_all = prior["allFourNativeProtocolJobsVerified"]
    prior_message = ("R109精确bea5d81四平台完整job已终态success、各47协议项原件通过" if prior_all else
                     "R109 Ubuntu及两种Mac架构完整job各47协议项已验，Windows终态继续待验")
    verified_native = [row["runner"] for row in native["records"] if row.get("qualified")]
    native_all = native["allFourNativeProtocolJobsVerified"]
    assert native["run"]["status"] == "completed"
    assert native["run"]["conclusion"] == "success"
    assert len(verified_native) == 4 if native_all else len(verified_native) < 4
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    run = request("/repos/29583855/dukto-next/actions/runs/42351739970")
    assert run["head_sha"] == SOURCE
    index_path = REPO / "docs/ci-verification-20261107-r110.json"
    value = json.loads(index_path.read_text("utf-8"))
    for row in value["buildInputs"]:
        assert proof(REPO / row["path"]) == row
        actual = subprocess.check_output(["git", "show", SOURCE + ":" + row["path"]], cwd=REPO)
        assert hashlib.sha256(actual).hexdigest() == row["sha256"]

    plan = REPO / "开发计划与进度.md"
    text = plan.read_text("utf-8")
    native_message = ("四平台完整协议终态success" if native_all else "四平台完整协议仍执行")
    text = line(text, "当前阶段：", "当前阶段：R110精确a29960a已公开，四平台C++14 GUI/CLI编译及各26个CTest、目录专项各45条数据行已核验；双Mac含依赖预览和迁移验证均通过，" + native_message + "。" + prior_message + "。整体与正式发布未完成。")
    text = line(text, "公开仓库：[29583855/dukto-next]", "公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R110扩展客户端及服务器空临时目录维护，双Windows各8相关核心目标通过，四原生各26个CTest及目录清理各45条数据行通过。父目录原生身份、持久删除意图、真实进程退出、链接/WAL/损坏日志拒绝和同任务恢复已验；skip/未知目录及全局GC仍待完成。[清理范围](docs/过期任务临时文件清理.md)。双Mac含Qt5/OpenSSL预览和迁移均通过，各保留精确Darwin端口独占XFAIL；头像负例既有警告保留，完整协议与整体/发布资格单独验收。")
    cleanup_open = "完整协议、skip/未知目录、通用缓存和全局磁盘回收" if not native_all else "skip/未知目录、通用缓存和全局磁盘回收"
    text = line(text, "| 当前清理范围 |", "| 当前清理范围 | R110四原生各26个CTest、目录专项各45条；双Windows各8相关核心目标通过 | " + cleanup_open + " |")
    mac_open = "R110完整协议、完整GUI/选择器、最低干净系统及正式分发" if not native_all else "完整GUI/选择器、最低干净系统及正式分发"
    text = line(text, "| macOS ARM / Intel |", "| macOS ARM / Intel | R110 C++14 GUI/CLI编译、双架构Qt5/OpenSSL部署包及系统PATH迁移、归档SHA/架构及各26个CTest和目录专项各45条通过；各一条精确Darwin XFAIL | " + mac_open + " |")
    text = line(text, "| 原生复验 |", "| 原生复验 | R110 a29960a运行42351739970四平台完整协议均终态success；" + prior_message + " | 各精确提交完整协议终态和冻结长测；核心子集不能授予长期/交付资格 |")
    pending_native = next((item for item in text.splitlines()
                           if item.startswith("- [ ] 同提交完整协议")), None)
    if pending_native and native_all:
        native_done = "- [x] R110精确`a29960a38fb46368dd8ac190caed2f4c515f8731`运行`42351739970`四平台完整协议终态success：Ubuntu/两种Mac各47项、Windows 51项；原始附件、TLS/任务库及平台报告均已逐项收验。[终态原件](docs/validation/2026-11-07/directory-cleanup-r110-native-terminal/receipt.json)。\n- [ ] skip目录、无身份临时项、完整处置协调、通用缓存/全局GC及历史256MiB和活动清单总磁盘预算仍未完成；[清理语义](docs/过期任务临时文件清理.md)。"
        text = replace(text, pending_native, native_done)
    elif pending_native:
        native_done = "- [ ] 同提交完整协议仍执行，不能由核心子集授予终态。skip目录、无身份临时项、完整处置协调、通用缓存/全局GC及历史256MiB和活动清单总磁盘预算仍未完成；[清理语义](docs/过期任务临时文件清理.md)。"
        text = replace(text, pending_native, native_done)
    else:
        assert native_all and any(item.startswith("- [x] R110精确`a29960a") for item in text.splitlines())
    old_package_line = "当前双Mac含依赖部署包为R108精确641920f，Windows和Linux仍为R100精确ed4f5cf"
    new_package_line = "当前双Mac含依赖部署包为R110精确a29960a，Windows和Linux仍为R100精确ed4f5cf"
    if old_package_line in text:
        text = replace(text, old_package_line, new_package_line)
    else:
        assert new_package_line in text
    if prior_all:
        old_prior_prefix = "- [x] R109精确`bea5d81`运行`42347962868`的Ubuntu"
        new_prior_line = "- [x] R109精确`bea5d81`运行`42347962868`四平台完整job终态success，各47协议项、31 TLS、任务库8进程与平台报告均已从官方附件收验；旧失败及精确Darwin XFAIL保留。[终态原件](docs/validation/2026-11-07/client-cleanup-r109-native-terminal/receipt.json)。"
        if any(item.startswith(old_prior_prefix) for item in text.splitlines()):
            text = line(text, old_prior_prefix, new_prior_line)
        else:
            assert new_prior_line in text
        old_prior_pending = "- [ ] 同一运行的完整协议仍执行，不能用核心通过替代整轮终态。"
        new_prior_done = "- [x] 同一运行完整协议四平台终态success并逐项收验，新增验证范围不覆盖旧失败。"
        if old_prior_pending in text:
            text = replace(text, old_prior_pending, new_prior_done)
        else:
            assert new_prior_done in text
    write(plan, text)

    progress = REPO / "docs/执行进度.md"
    text = progress.read_text("utf-8")
    if native_all:
        old_progress_pending = "- [ ] 同提交完整协议、skip完整处置协调、全局GC/总磁盘预算、完整R6 GUI、物理LAN/3×3、各平台24h及正式分发仍待验；整体与发布资格保持false。"
        new_progress_open = "- [ ] skip完整处置协调、全局GC/总磁盘预算、完整R6 GUI、物理LAN/3×3、各平台24h及正式分发仍待验；整体与发布资格保持false。"
        new_progress_done = "- [x] R110精确a29960a四平台完整协议终态success，四原生各26个CTest及目录专项各45条通过；双Mac GUI/CLI归档SHA和架构通过。[验证索引](ci-verification-20261107-r110.json)。\n" + new_progress_open
        if old_progress_pending in text:
            text = replace(text, old_progress_pending, new_progress_done)
        else:
            assert new_progress_done in text
    if prior_all:
        old_r109_progress = "- [x] R109 Ubuntu/Apple Silicon/Intel完整job各47协议终态success，附件与关键报告已验；Windows仍待终态。"
        new_r109_progress = "- [x] R109四平台完整job终态success，各47协议项和关键原报告均已验，历史失败及精确Darwin XFAIL保留。"
        if old_r109_progress in text:
            text = replace(text, old_r109_progress, new_r109_progress)
        else:
            assert new_r109_progress in text
    write(progress, text)

    readme = REPO / "README.md"
    text = readme.read_text("utf-8")
    text = line(text, "公开仓库为", "公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R110精确`a29960a`已上传，Windows/Ubuntu/Apple Silicon/Intel以C++14编译GUI和独立CLI，各26个CTest与目录专项各45条数据行通过；双Mac编译归档、含Qt5/OpenSSL部署包及系统PATH迁移报告已验，[下载入口](docs/macOS独立预览包.md)。新增客户端/服务器未发布空目录临时项维护，见[清理范围](docs/过期任务临时文件清理.md)。" + ("四平台完整协议终态success" if native_all else "完整协议仍执行") + "，双Mac精确Darwin端口独占XFAIL与已有头像负例警告保留。" + prior_message + "；完整项目/发布按[计划](开发计划与进度.md)继续验收。")
    write(readme, text)

    manual = REPO / "docs/过期任务临时文件清理.md"
    text = manual.read_text("utf-8")
    old_cleanup_line = "双Windows工具链各45条目录专项及各8相关核心CTest已验；原生四平台结果另验。"
    new_cleanup_line = "双Windows工具链各8相关核心CTest已验；R110四原生各26个CTest及目录专项各45条数据行/15个JUnit方法通过，双Mac精确Darwin XFAIL保留；完整协议另验。"
    if old_cleanup_line in text:
        text = replace(text, old_cleanup_line, new_cleanup_line)
    else:
        assert new_cleanup_line in text
    write(manual, text)

    mac_doc = REPO / "docs/macOS独立预览包.md"
    text = mac_doc.read_text("utf-8")
    text = line(text, "更新日期：", "更新日期：2026-11-07。R110精确`a29960a38fb46368dd8ac190caed2f4c515f8731`已在Apple Silicon和Intel原生环境以C++14/Qt5编译GUI及独立CLI；两架构各26个CTest、目录清理各45条已验，归档摘要/架构/执行位通过。双架构Qt5/OpenSSL含依赖预览、系统PATH搬迁、各五项真实CLI/传输报告和Cocoa导航均通过；" + ("四平台完整协议终态success" if native_all else "原生完整协议仍运行") + "。各一条精确Darwin端口独占XFAIL保留。")
    if "## R109最新原生编译归档" in text:
        text = replace(text, "## R109最新原生编译归档", "## R109原生编译归档（历史）")
    else:
        assert "## R109原生编译归档（历史）" in text
    if "## 当前R108含依赖部署包" in text:
        text = replace(text, "## 当前R108含依赖部署包", "## R108含依赖部署包（历史）")
    else:
        assert "## R108含依赖部署包（历史）" in text
    deployed_packages = sorted(deployed["records"], key=lambda row: row["architecture"])
    rows = ["## R110最新含依赖预览\n\n",
            "[双架构打包运行42352207494](https://github.com/29583855/dukto-next/actions/runs/42352207494)终态success。两架构的Qt/OpenSSL依赖、364份应用源码、全部载荷与框架链接、归档摘要和Mach-O身份均通过核验；系统PATH下搬迁启动、各五项CLI/传输报告及Cocoa导航均通过。[原件回执](validation/2026-11-07/directory-cleanup-r110-macos-package/receipt.json)。\n\n",
            "| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n"]
    for package in deployed_packages:
        rows.append("| " + package["architecture"] + " | [下载](" + package["artifactUrl"] + ") | `" + package["artifactSha256"] + "` | `" + package["packageSha256"] + "` |\n")
    rows.append("\n")
    rows += ["## R110原生编译归档\n\n", "对应[运行42351739970](https://github.com/29583855/dukto-next/actions/runs/42351739970)。官方ZIP、内部tar SHA、精确源码、LICENSE、Mach-O架构及GUI/CLI执行权限逐件通过；本机副本在`dist/macos-compiled-20261107-r110-directory-cleanup/`。[回执](validation/2026-11-07/directory-cleanup-r110-macos-compiled/receipt.json)。\n\n", "| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n"]
    for package in mac["packages"]:
        rows.append("| " + package["architecture"] + " | [下载](" + package["artifactUrl"] + ") | `" + package["artifactSha256"] + "` | `" + package["sha256"] + "` |\n")
    rows.append("\n这是编译归档，需要匹配Qt5/OpenSSL运行依赖；当前双架构含依赖预览见本节顶部。核心通过不替代完整协议、干净系统或正式签名公证。\n\n")
    if "## R110最新含依赖预览" not in text:
        text = replace(text, "## R109原生编译归档（历史）", "".join(rows) + "## R109原生编译归档（历史）")
    else:
        assert "## R110原生编译归档" in text and "## R109原生编译归档（历史）" in text
    old_latest = "当前最新编译归档和核心结果见上方R109"
    new_latest = "当前最新编译归档和核心结果见上方R110"
    if old_latest in text:
        text = replace(text, old_latest, new_latest)
    else:
        assert new_latest in text
    write(mac_doc, text)

    evidence = REPO / BASE / "directory-cleanup-r110-publication"
    evidence.mkdir(exist_ok=True)
    for name in ("r110-published-tree-verification.json", "r110-workspace-sync.json", "r110-macos-package-dispatch.json"):
        shutil.copyfile(ROOT / ".cache" / name, evidence / name)
    shutil.copyfile(Path(__file__), evidence / "publication-driver.py")
    value.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourceCommit=SOURCE,
                 nativeRun={key: run[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                 nativeR110Pending=not native_all, nativeR110CorePending=False, nativeCompilationVerified=True,
                 nativeFullProtocolPending=not native_all, nativeCoreTargetsEach=26,
                 nativeR110AllFourProtocolJobsVerified=native_all,
                 nativeVerifiedProtocolJobs=verified_native,
                 nativeTerminalEvidence=proof(native_path),
                 nativeCoreEvidence=proof(core_path), macosCompiledEvidence=proof(mac_path),
                 macosCompiledPackages=mac["packages"], priorR109TerminalEvidence=proof(prior_path),
                 priorR109AllFourProtocolJobsVerified=prior_all, priorR109VerifiedProtocolJobs=verified_prior,
                 macosDeployedPackageEvidence=proof(package_path),
                 macosDependenciesDeployedForR110=True,
                 macosDependenciesDeployedForR110VerifiedArchitectures=[row["architecture"] for row in deployed["records"] if row.get("qualified")],
                 currentSelfContainedMacPreviewSource=SOURCE)
    package_runs = request("/repos/29583855/dukto-next/actions/workflows/macos-package.yml/runs?head_sha=" + SOURCE + "&per_page=100")["workflow_runs"]
    assert len(package_runs) == 1
    package_run = {key: package_runs[0][key] for key in ("id", "head_sha", "status", "conclusion", "html_url")}
    value["macosDeployedPackageRun"] = package_run
    (ROOT / ".cache/r110-macos-package-run.json").write_text(json.dumps(package_run, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / ".cache/r110-macos-package-run.json", evidence / "macos-package-run.json")
    value["openScope"] = [*[item for item in value["openScope"] if item not in (
        "native four-platform R110 validation", "Intel macOS R110 deployed package validation")],
        *([] if native_all else ["R110 full native protocol terminal"])]
    write(index_path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    folders = [core_path.parent, mac_path.parent, package_path.parent, prior_path.parent,
               native_path.parent, evidence]
    names = {path.relative_to(REPO).as_posix() for folder in folders for path in folder.rglob("*") if path.is_file()}
    names.update(["README.md", "开发计划与进度.md", "docs/执行进度.md", "docs/过期任务临时文件清理.md", "docs/macOS独立预览包.md", "docs/ci-verification-20261107-r110.json"])
    manifest = [proof(REPO / name) for name in sorted(names)]
    (ROOT / ".cache/r110-final-publication-files.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pathspec = ROOT / ".cache/r110-final-publication-stage.nul"
    pathspec.write_bytes("\0".join(sorted(names)).encode("utf-8") + b"\0")
    subprocess.run(["git", "add", "-f", "--pathspec-from-file=" + str(pathspec), "--pathspec-file-nul"], cwd=REPO, check=True)
    staged = set(filter(None, subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"], cwd=REPO).decode().split("\0")))
    assert staged <= names
    print(json.dumps({"sourceCommit": SOURCE, "stagedFiles": len(staged), "nativeCoreTargetsEach": 26,
                      "directoryRowsEach": 45, "bothMacArchitecturesVerified": True,
                      "allFourNativeProtocolJobsVerified": native_all,
                      "fullProtocolStillPending": not native_all}))


if __name__ == "__main__":
    main()

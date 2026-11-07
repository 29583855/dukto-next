"""日期：2026-11-07；保留ARM原失败并核验成功子集，更新双Mac已验预览与精确进度快照。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
from types import SimpleNamespace

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
BASE = REPO / "docs/validation/2026-11-07"
SOURCE = "dfe245b502f586e7df7219e8fb0d5e4030a6b032"


# 日期：2026-11-07；逐字节保留已有UTF-8编码、BOM与换行，只有唯一匹配才允许替换。
def replace(path, old, new):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = text.replace("\r\n", "\n")
    assert text.count(old) == 1, (path, old[:100])
    value = text.replace(old, new).replace("\n", newline).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + value)


# 日期：2026-11-07；失败作业成功子集也核对来源与每份报告，不以46项成功覆盖缺失的第47项。
def audit_failure():
    folder = BASE / "skip-directory-r111-native-terminal/macos-15"
    suite = json.loads((folder / "build/protocol-suite.json").read_text("utf-8"))
    source = subprocess.check_output(["git", "show", SOURCE + ":scripts/ci_protocol.py"], cwd=REPO)
    assert suite["scriptSha256"] == hashlib.sha256(source).hexdigest()
    module = {"__name__": "frozen_ci_protocol"}
    exec(compile(source, SOURCE + ":scripts/ci_protocol.py", "exec"), module)
    module["commands"].__globals__["sys"] = SimpleNamespace(platform="darwin", executable="python")
    assert [item["name"] for item in suite["cases"]] == [row[0] for row in module["commands"](Path("build"))]
    assert suite["sourceCommit"] == SOURCE and suite["completed"] and not suite["passed"]
    helper = runpy.run_path(str(ROOT / ".cache/collect-exact-native-r87.py"))
    passed, failed = [], []
    for case in suite["cases"]:
        report = folder / case["report"]
        if case["passed"]:
            assert case["exitCode"] == 0 and case["reportCreated"]
            assert hashlib.sha256(report.read_bytes()).hexdigest() == case["reportSha256"]
            helper["verify_passed"](json.loads(report.read_text("utf-8")))
            passed.append({"name": case["name"], "reportSha256": case["reportSha256"]})
        else:
            assert case["name"] == "overwrite-faults" and case["exitCode"] == 1
            assert not case["reportCreated"] and not report.exists()
            failed.append(case)
    assert len(passed) == 46 and len(failed) == 1
    log = (folder / "job.log").read_text("utf-8")
    assert "AssertionError: {'code': 6, 'event': 'error', 'eventVersion': 1," in log
    assert "源文件路径在读取期间已被替换" in log
    result = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": SOURCE,
              "suiteSha256": hashlib.sha256((folder / "build/protocol-suite.json").read_bytes()).hexdigest(),
              "verifiedPassedCases": passed, "failedCases": failed,
              "failure": {"fault": "revoke", "direction": "download", "conflictPolicy": "overwrite",
                          "code": 6, "stage": "read", "message": "源文件路径在读取期间已被替换",
                          "postFailureAssertionsExecuted": False,
                          "specificReplacedFileIdentifiedByOriginalLog": False},
              "analysis": "PrivateStore.read verifies both opened object and current path; AuthStore.revoke atomically replaces client JSON. This explains a possible integrity refusal, but the original error does not identify the concrete file. Original failure remains unqualified; targeted regression is required.",
              "allProtocolCasesPassed": False, "releaseQualified": False, "deliveryComplete": False}
    (folder / "failure-analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(Path(__file__), folder / "failure-analysis-driver.py")


# 日期：2026-11-07；只更新已取得原件的状态，其他平台协议、长时与正式发布继续留空。
def main():
    audit_failure()
    package_path = BASE / "skip-directory-r111-macos-package/receipt.json"
    package = json.loads(package_path.read_text("utf-8"))
    assert package["bothArchitecturesVerified"] and package["run"]["conclusion"] == "success"
    package["screenshotsViewed"] = True
    package["screenshotReview"] = {"date": "2026-11-07", "architectures": ["arm64", "x86_64"],
                                   "homeAndServerNavigationViewed": True,
                                   "scope": "Four recorded Cocoa screenshots; no clean-machine or full-GUI qualification"}
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", "utf-8")

    path = ROOT / "开发计划与进度.md"
    replace(path,
        "当前阶段：R111精确dfe245b已公开；Windows、Ubuntu与双Mac C++14 GUI/CLI编译及各26个CTest、目录专项各49条已核验，双Mac归档SHA/架构通过，完整协议仍运行。双Mac含依赖预览正在构建。整体与正式发布未完成。",
        "当前阶段：R111精确dfe245b已公开；四平台C++14 GUI/CLI编译、各26个CTest和目录专项各49条已验，双Mac含Qt5/OpenSSL预览及迁移运行已验。完整协议Ubuntu成功，Apple Silicon为46/47、overwrite-faults原失败保留，Intel/Windows待终态。整体与正式发布未完成。")
    replace(path, "完整协议和双Mac含依赖预览另等终态；R110历史资格保留。", "双Mac含依赖预览已终态success并逐件核验；完整协议Ubuntu成功，Apple Silicon的overwrite-faults失败保留，Intel/Windows继续收验；R110历史资格保留。")
    replace(path, "R111双Windows本机四项专项、四原生各26个CTest和目录专项各49条已验，完整协议运行中", "R111双Windows四项专项、四原生各26个CTest及目录各49条已验；完整协议ARM 46/47，原失败保留")
    replace(path, "当前双Mac含依赖部署包为R110精确a29960a", "当前双Mac含依赖部署包为R111精确dfe245b")
    replace(path, "这是编译归档，含Qt5/OpenSSL预览仍为R110，R111打包运行`42363743119`继续验收。", "这是编译归档；R111含Qt5/OpenSSL预览运行`42363743119`双架构终态success，包摘要、364份源码、载荷/框架链接及系统PATH迁移另已核验。")
    replace(path, "- [ ] 同一精确提交的完整协议作业和双Mac含依赖预览均未终态，不把核心和编译归档资格转授完整运行及发布。", "- [x] R111双Mac含Qt5/OpenSSL预览、各五项真实CLI/传输报告、系统PATH迁移及Cocoa导航/高DPI均通过；四张首页/服务器截图已查看。[预览回执](docs/validation/2026-11-07/skip-directory-r111-macos-package/receipt.json)。\n- [ ] 同提交完整协议：Ubuntu 47/47且终态success；Apple Silicon 46/47，overwrite-faults在下载撤权时收到精确6/read路径完整性拒绝而断言失败，后续数据保护断言未执行，不能算通过。原始日志和成功46项摘要均保存。[失败分析](docs/validation/2026-11-07/skip-directory-r111-native-terminal/macos-15/failure-analysis.json)。Intel/Windows待终态，不能转授完整协议或发布资格。")
    replace(ROOT / "README.md", "双Mac编译归档摘要/架构已验，完整协议和含依赖预览继续等实际终态。", "双Mac编译归档及含Qt5/OpenSSL预览、系统PATH迁移已验；完整协议Ubuntu通过，Apple Silicon 46/47、下载撤权错误断言原失败保留，Intel/Windows待终态。")
    replace(ROOT / "docs/执行进度.md", "含依赖预览构建和完整协议继续等实际终态。", "双Mac含Qt5/OpenSSL预览终态success，系统PATH迁移、各五项CLI/传输报告及Cocoa导航/高DPI均通过，四张截图已查看。\n- [ ] 完整协议Ubuntu 47/47通过；Apple Silicon 46/47，overwrite-faults下载撤权断言失败，原件和成功子集逐份摘要保留，后续保护断言未执行。Intel/Windows仍待终态；不能把包/核心通过写成完整协议通过。")
    replace(ROOT / "docs/macOS独立预览包.md", "完整协议运行中。R111含Qt5/OpenSSL预览[构建42363743119](https://github.com/29583855/dukto-next/actions/runs/42363743119)尚未终态，当前已验含依赖预览仍见R110。", "完整协议Ubuntu通过，Apple Silicon 46/47、overwrite-faults原失败保留，Intel/Windows待终态。R111含Qt5/OpenSSL预览[构建42363743119](https://github.com/29583855/dukto-next/actions/runs/42363743119)双架构终态success，系统PATH迁移与包内运行报告已验。")
    marker = "## R111原生编译归档"
    text = "## R111最新含依赖预览\n\n双架构Qt5/OpenSSL依赖、各364份应用源码、全部载荷与71个框架链接、Mach-O架构/执行权限及归档摘要均逐件核验。两包各五项真实CLI/传输报告、系统PATH迁移、Cocoa导航与150%/200%高DPI通过，四张界面截图已查看。[原件回执](validation/2026-11-07/skip-directory-r111-macos-package/receipt.json)。本机副本在`dist/macos-preview-20261107-r111-skip-directory/`。\n\n| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n"
    for row in package["records"]:
        text += f'| {row["architecture"]} | [下载]({row["artifactUrl"]}) | `{row["artifactSha256"]}` | `{row["packageSha256"]}` |\n'
    text += "\n这是adhoc签名开发预览；Developer ID、公证、干净系统和完整项目仍待验。原协议失败不由打包成功覆盖。解压与CLI命令见本文下方使用说明。\n\n" + marker
    replace(ROOT / "docs/macOS独立预览包.md", marker, text)
    for name in ("README.md", "开发计划与进度.md", "docs/执行进度.md", "docs/macOS独立预览包.md",
                 "docs/过期任务临时文件清理.md", "docs/decisions/0025-最终跳过目录与维护清理协调.md"):
        shutil.copyfile(ROOT / name, REPO / name)
    print(json.dumps({"macPackageArchitecturesVerified": 2, "armProtocolPassed": 46,
                      "armProtocolFailed": 1, "originalFailureRetained": True}))


if __name__ == "__main__":
    main()

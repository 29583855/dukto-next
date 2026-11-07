"""日期：2026-11-07；按精确原件刷新当前计划与资格索引，历史失败和未完成范围分别保留。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
BASE = REPO / "docs/validation/2026-11-07"
SOURCE = "cfd66f596098ee747066752db90b15bbe0586970"


# 日期：2026-11-07；所有证据按原始字节绑定SHA，不重排原日志或处理其换行。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-07；保持UTF-8的原BOM与换行，按当前实际状态更新唯一对应段落。
def update_text(path, transform):
    raw = path.read_bytes()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw[len(bom):].decode("utf-8").replace("\r\n", "\n")
    changed = transform(text)
    path.write_bytes(bom + changed.replace("\n", newline).encode("utf-8"))


# 日期：2026-11-07；只替换唯一前缀行，避免误改历史版本的结果。
def line(text, prefix, replacement):
    scope = text.split("\n## R115 ", 1)[0] if prefix.startswith("| ") else text
    found = [item for item in scope.splitlines() if item.startswith(prefix)]
    assert len(found) == 1, (prefix, len(found))
    return text.replace(found[0], replacement, 1)


# 日期：2026-11-07；索引只刷新已有证据摘要与对应运行事实，完整项目仍未验收。
def refresh_index(name, terminal, field):
    path = REPO / name
    value = json.loads(path.read_text("utf-8"))
    for row in value["receipts"]:
        row["sha256"] = sha(REPO / row["path"])
    value.update(observedUtc=datetime.now(timezone.utc).isoformat(), nativeRun=terminal["run"])
    value[field] = terminal["allFourNativeProtocolJobsVerified"]
    if name.endswith("r113.json"):
        value["nativeProtocolQualificationPending"] = terminal["run"]["status"] != "completed"
    else:
        value["nativeQualificationPending"] = terminal["run"]["status"] != "completed"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


# 日期：2026-11-07；核对提交树、专项结果、长测只读观察与所有当前回执后同步两份工作区。
def main():
    panel = json.loads((BASE / "panel-timing-r115-macos/receipt.json").read_text("utf-8"))
    assert panel["sourceCommit"] == SOURCE and panel["originalR114FailureRetained"]
    passed = panel["bothArchitecturesTwoCompleteRoundsVerified"]
    r113 = json.loads((BASE / "skip-reconcile-r113-native-terminal/receipt.json").read_text("utf-8"))
    r114 = json.loads((BASE / "private-read-r114-native-terminal/receipt.json").read_text("utf-8"))
    local = BASE / "panel-timing-r115-local"
    for original, name in ((ROOT / ".cache/r115-final-source-audit.json", "final-source-audit.json"),
                           (ROOT / ".cache/r115-frozen-long-observation.json", "frozen-long-observation.json")):
        target = local / name
        if target.exists():
            assert target.read_bytes() == original.read_bytes()
        else:
            shutil.copyfile(original, target)
    shutil.copyfile(ROOT / ".cache/observe-r115-frozen-long.py", local / "frozen-long-observation-driver.py")
    shutil.copyfile(Path(__file__), local / "evidence-finalizer.py")
    index_path = REPO / "docs/ci-verification-20261107-r115.json"
    index = json.loads(index_path.read_text("utf-8"))
    assert index["sourceCommit"] == SOURCE and index["inputCount"] == 244
    for row in index["qualificationInputs"]:
        content = subprocess.check_output(["git", "show", SOURCE + ":" + row["path"]], cwd=REPO)
        assert len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"]
        assert sha(ROOT / row["path"]) == sha(REPO / row["path"]) == row["sha256"]
    receipt_paths = [REPO / row["path"] for row in index["receipts"]]
    receipt_paths += [BASE / "panel-timing-r115-macos/receipt.json", local / "final-source-audit.json",
                      local / "frozen-long-observation.json", local / "source-publication.json",
                      local / "macos-panel-dispatch.json"]
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(),
                 receipts=[{"path": path.relative_to(REPO).as_posix(), "sha256": sha(path)}
                           for path in dict.fromkeys(receipt_paths)],
                 macosPanelRun=panel["run"], macosRegressionQualified=passed,
                 exactGitInputsVerified=True, deliveryComplete=False, releaseQualified=False)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", "utf-8")
    refresh_index("docs/ci-verification-20261107-r113.json", r113, "nativeProtocolQualified")
    refresh_index("docs/ci-verification-20261107-r114.json", r114, "fullNativeProtocolQualified")
    count113 = sum(row["qualified"] for row in r113["records"])
    panel_label = "双Mac各两轮完整面板专项已验" if passed else "双Mac两轮专项实际运行中"

    # 日期：2026-11-07；当前总览采用最新R114应用与R115测试事实，旧R111失败继续在历史小节保留。
    def plan_change(text):
        text = line(text, "当前阶段：", "当前阶段：R114双Mac GUI/CLI编译、Qt5/OpenSSL预览、迁移运行和截图已验；Windows/Ubuntu/Apple Silicon各26核心通过，Intel25/26（界面时序断言原失败保留），四平台目录各59条通过。R115测试修正已上传、双Windows完整面板专项通过，" + panel_label + "。R113三平台完整协议各47/47，Windows仍在执行。整体与正式发布未完成。")
        text = line(text, "公开仓库：", "公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。当前已验Mac预览为R114，双架构Qt5/OpenSSL、GUI/独立CLI、迁移运行及截图通过；R115只修正面板读取测试时序，产品输入与R114一致，" + panel_label + "。R114 Windows/Ubuntu/Apple Silicon各26核心通过，Intel25/26原失败保留。R113三平台完整协议各47/47，Windows仍在执行。未知身份临时项、通用缓存及全局GC仍待完成。[清理范围](docs/过期任务临时文件清理.md)。历史失败和完整项目资格继续分别保留。")
        text = line(text, "| 当前清理范围 |", "| 当前清理范围 | R114四原生目录各59条已验；R113三平台完整协议各47/47 | 未知身份临时项、通用缓存和全局磁盘回收 |")
        text = line(text, "| Windows |", "| Windows | R114原生26核心/59目录用例，R115两工具链各7个面板方法通过；部署仍为R100 | 完整编辑器及系统剪贴板预算、当前版本24h终态和正式发布 |")
        text = line(text, "| Linux |", "| Linux | R114原生26核心/59目录与私有配置原子换代测试通过；R113完整job 47/47 | 当前提交完整协议终态、完整交互及24h |")
        text = line(text, "| macOS ARM / Intel |", "| macOS ARM / Intel | R114含Qt5/OpenSSL双架构GUI/CLI预览可下载；ARM26核心通过、Intel25/26原失败保留；R115" + panel_label + " | 完整GUI/选择器、最低干净系统及正式分发 |")
        text = line(text, "| 原生复验 |", "| 原生复验 | R113 Ubuntu/Apple Silicon/Intel完整job各47/47；R114核心3/4平台通过，Intel原失败独立保留 | 各精确提交完整协议终态和冻结长测 |")
        text = line(text, "首轮取消测试中的非零进度断言有误", "首轮取消测试中的非零进度断言有误，诊断已纠正；原监听器已有接收起始状态，未改变传输核心。当前双Mac含依赖部署包为R114精确d922dc4，Windows和Linux仍为R100精确ed4f5cf，下载与摘要见各平台预览包说明。历史失败、两条精确Darwin XFAIL及依赖证据边界继续保留，整体与正式发布仍为false。")
        old, = [item for item in text.splitlines() if "[双Mac专项42372364118]" in item]
        if passed:
            replacement = "- [x] [双Mac专项42372364118](https://github.com/29583855/dukto-next/actions/runs/42372364118)终态success；Apple Silicon/Intel各两轮完整面板CTest通过，每轮7个方法，四轮合计28个方法执行。精确提交、官方ZIP、原日志、JUnit与程序前后SHA均已验。[专项回执](docs/validation/2026-11-07/panel-timing-r115-macos/receipt.json)。R114原失败不改写，现有预览应用输入与R115完全一致。"
        else:
            replacement = "- [ ] [双Mac专项42372364118](https://github.com/29583855/dukto-next/actions/runs/42372364118)实际状态`" + panel["run"]["status"] + "`，每架构两轮完整面板用例按官方附件收验。[专项观察](docs/validation/2026-11-07/panel-timing-r115-macos/receipt.json)。原R114完整CI与已有包来源分别保留。"
        text = text.replace(old, replacement, 1)
        old, = [item for item in text.splitlines() if "[完整协议运行42368086270]" in item]
        replacement = re.sub(r"已验终态job \d/4", "已验终态job " + str(count113) + "/4", old)
        text = text.replace(old, replacement, 1)
        marker = "- [ ] 完整R6/GUI、全局预算/安全回收、物理LAN/3×3、当前版本各平台24h、干净系统和正式分发仍未完成。"
        if "12:30 UTC只读核对冻结长测" not in text:
            assert marker in text
            text = text.replace(marker, "- [x] 12:30 UTC只读核对冻结长测：Windows214轮/64664.906秒、Ubuntu181轮/59421.984秒，实际服务存活、程序SHA与原报告一致；未改原输入，未到86400秒，不授予R114长期资格。[观察原件](docs/validation/2026-11-07/panel-timing-r115-local/frozen-long-observation.json)。\n" + marker, 1)
        return text

    update_text(ROOT / "开发计划与进度.md", plan_change)
    mac = ROOT / "docs/macOS独立预览包.md"

    # 日期：2026-11-07；标明测试提交与可下载产品的对应关系，避免为测试变化重复包装同一产品。
    def mac_change(text):
        paragraph = "R115仅修正面板测试的读取时序，产品应用输入与R114完全一致。" + ("双Mac各两轮完整面板专项已通过，四轮各7方法；原Intel失败日志继续保留。" if passed else "双Mac各两轮完整面板专项仍按实际原件验收，原Intel失败日志继续保留。") + "[专项回执](validation/2026-11-07/panel-timing-r115-macos/receipt.json)。"
        existing = [part for part in text.split("\n\n") if part.startswith("R115仅修正")]
        if existing:
            assert len(existing) == 1
            return text.replace(existing[0], paragraph, 1)
        return text.replace("## R114最新含依赖预览", paragraph + "\n\n## R114最新含依赖预览", 1)

    update_text(mac, mac_change)
    for name in ("开发计划与进度.md", "docs/macOS独立预览包.md"):
        shutil.copyfile(ROOT / name, REPO / name)
    for suffix in ("panel-timing-r115-local", "panel-timing-r115-macos", "private-read-r114-local",
                   "private-read-r114-native-core", "private-read-r114-native-terminal", "skip-reconcile-r113-native-terminal"):
        folder = BASE / suffix
        shutil.copytree(folder, ROOT / folder.relative_to(REPO), dirs_exist_ok=True)
    for version in (113, 114, 115):
        name = "docs/ci-verification-20261107-r" + str(version) + ".json"
        shutil.copyfile(REPO / name, ROOT / name)
    print(json.dumps({"sourceCommit": SOURCE, "exactInputs": 244, "macosPanelQualified": passed,
                      "r113VerifiedJobs": count113, "deliveryComplete": False}))


if __name__ == "__main__":
    main()

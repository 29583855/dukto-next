"""日期：2026-11-07；核对新增终态与原失败子集，保留精确包和测试版本的独立资格。"""

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
HARNESS = "10c026577449e089720471fc4a43c3da5bf627a4"


# 日期：2026-11-07；散列仅以原件字节为准。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-07；Intel成功45项与失败2项分别核验SHA，完整协议资格保持失败。
def intel_failure():
    folder = BASE / "skip-directory-r111-native-terminal/macos-15-intel"
    suite = json.loads((folder / "build/protocol-suite.json").read_text("utf-8"))
    source = subprocess.check_output(["git", "show", SOURCE + ":scripts/ci_protocol.py"], cwd=REPO)
    assert suite["scriptSha256"] == hashlib.sha256(source).hexdigest()
    module = {"__name__": "frozen_ci_protocol"}
    exec(compile(source, SOURCE + ":scripts/ci_protocol.py", "exec"), module)
    module["commands"].__globals__["sys"] = SimpleNamespace(platform="darwin", executable="python")
    assert [row["name"] for row in suite["cases"]] == [row[0] for row in module["commands"](Path("build"))]
    assert suite["sourceCommit"] == SOURCE and suite["completed"] and not suite["passed"]
    verify = runpy.run_path(str(ROOT / ".cache/collect-exact-native-r87.py"))["verify_passed"]
    passed, failed = [], []
    for row in suite["cases"]:
        path = folder / row["report"]
        assert row["reportCreated"] and sha(path) == row["reportSha256"]
        value = json.loads(path.read_text("utf-8"))
        if row["passed"]:
            assert row["exitCode"] == 0
            verify(value)
            passed.append({"name": row["name"], "reportSha256": row["reportSha256"]})
        else:
            assert row["exitCode"] == 1 and value["passed"] is False
            failed.append(row)
    assert len(passed) == 45 and [row["name"] for row in failed] == ["credential-rotation", "session-expiry"]
    rotation = json.loads((folder / "build/credential-rotation.json").read_text("utf-8"))
    assert rotation["observation"]["errorCode"] == 6 and rotation["observation"]["errorStage"] == "read"
    assert rotation["observation"]["serverStoppedState"] == "failed"
    result = {"observedUtc": datetime.now(timezone.utc).isoformat(), "sourceCommit": SOURCE,
              "suiteSha256": sha(folder / "build/protocol-suite.json"), "verifiedPassedCases": passed,
              "failedCases": failed, "credentialRotationObservation": rotation["observation"],
              "sessionExpiryFailure": "16-channel download recovery returned code 3/parallel after partial restored progress; original report and job log retained; cause unresolved",
              "allProtocolCasesPassed": False, "deliveryComplete": False, "releaseQualified": False}
    (folder / "failure-analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")


# 日期：2026-11-07；替换固定语句并保留原UTF-8、BOM与换行。
def replace_all(path, old, new):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    value = raw.decode("utf-8-sig").replace("\r\n", "\n")
    assert old in value, (path, old)
    value = value.replace(old, new).replace("\n", newline).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + value)


# 日期：2026-11-07；双Mac定向专项通过不替代原完整协议，更新计划与摘要引用后同步主目录证据。
def main():
    package = json.loads((BASE / "skip-directory-r111-macos-package/receipt.json").read_text("utf-8"))
    regression = json.loads((BASE / "fault-refusal-r112-macos/receipt.json").read_text("utf-8"))
    assert package["bothArchitecturesVerified"] and regression["bothArchitecturesVerified"]
    assert regression["run"]["conclusion"] == "success" and regression["harnessCommit"] == HARNESS
    intel_failure()
    native_path = BASE / "skip-directory-r111-native-terminal/receipt.json"
    native = json.loads(native_path.read_text("utf-8"))
    windows, = [row for row in native["records"] if row["runner"] == "windows-2022"]
    windows_status = "Windows完整协议已通过" if windows.get("qualified") else "Windows完整协议尚待终态"
    for name in ("开发计划与进度.md", "README.md", "docs/执行进度.md", "docs/macOS独立预览包.md"):
        path = ROOT / name
        if "Intel/Windows待终态" in path.read_text("utf-8"):
            replace_all(path, "Intel/Windows待终态", "Intel 45/47（凭据轮换与会话恢复失败），" + windows_status)
        if "Intel/Windows继续收验" in path.read_text("utf-8"):
            replace_all(path, "Intel/Windows继续收验", "Intel 45/47、两项原失败保留，" + windows_status)
        if "Intel/Windows仍待终态" in path.read_text("utf-8"):
            replace_all(path, "Intel/Windows仍待终态", "Intel 45/47、两项原失败保留，" + windows_status)
    replace_all(ROOT / "开发计划与进度.md",
                "- [ ] 双Mac手动专项将复用R111指定artifact及固定tar SHA，在系统PATH/中文空格目录各执行两轮24个真实故障；状态按独立运行回执验收，应用来源和测试脚本提交分别记录。",
                "- [x] [双Mac专项42366735173](https://github.com/29583855/dukto-next/actions/runs/42366735173)终态success；R111固定包的系统PATH/中文空格路径、各两轮24个真实故障通过，共48项，程序前后SHA一致。应用来源与测试提交分别记录。[原件回执](docs/validation/2026-11-07/fault-refusal-r112-macos/receipt.json)。\n- [x] 218份维护文件零遗留标记，C++14和全量C++格式检查通过。原241份输入中仅故障Python脚本按计划变化，其余240份未变；最初全241份不变的错误断言及其原因已保留。[输入对照](docs/validation/2026-11-07/fault-refusal-r112-local/input-comparison.json)。")
    replace_all(ROOT / "开发计划与进度.md", "C++产品与C++14构建输入不变", "C++产品与C++14配置不变")
    replace_all(ROOT / "README.md", "双Mac专项单独复验", "双Mac专项48个真实故障用例已通过")
    replace_all(ROOT / "docs/执行进度.md", "ARM原失败保持，Mac专项等待实际回执", "ARM原失败保持，双Mac专项各24项已通过（共48项），原完整协议失败未被覆盖")
    decision = ROOT / "docs/decisions/0026-配置变更竞态与故障测试预期.md"
    hits = {row["architecture"]: row["exactPathIntegrityRefusals"] for row in regression["records"]}
    replace_all(decision, "专项状态以独立回执为准，不能覆盖R111原失败或授予完整协议、干净系统和正式发布资格。",
                "[专项运行42366735173](https://github.com/29583855/dukto-next/actions/runs/42366735173)双架构终态success，各24个真实故障通过，共48项；精确路径完整性分支实际命中次数为" + json.dumps(hits) + "，未命中不能宣称原竞态已真实重现。[独立回执](../validation/2026-11-07/fault-refusal-r112-macos/receipt.json)。不能覆盖R111原失败或授予完整协议、干净系统和正式发布资格。")
    old_index = REPO / "docs/ci-verification-20261107-r111.json"
    value = json.loads(old_index.read_text("utf-8"))
    for row in value["verificationReceipts"]:
        row["sha256"] = sha(REPO / row["path"])
    value["observedUtc"] = datetime.now(timezone.utc).isoformat()
    value["limitations"].append("Original ARM overwrite-faults and Intel credential-rotation/session-expiry failures remain; R112 targeted regression does not requalify the full suite")
    old_index.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    receipts = [BASE / "fault-refusal-r112-local/receipt.json", BASE / "fault-refusal-r112-local/input-comparison.json",
                BASE / "fault-refusal-r112-local/source-audit.json", BASE / "fault-refusal-r112-macos/receipt.json", native_path]
    index = {"observedUtc": datetime.now(timezone.utc).isoformat(), "planVersion": "v0.112",
             "applicationSourceCommit": SOURCE, "harnessCommit": HARNESS,
             "nativeMacFaultRegressionRun": regression["run"]["html_url"],
             "receipts": [{"path": path.relative_to(REPO).as_posix(), "sha256": sha(path)} for path in receipts],
             "windowsFaultCases": 24, "macFaultCases": 48, "cxx14Configuration": True,
             "productCppInputsUnchanged": True, "originalFullSuiteFailuresRetained": True,
             "fullSuiteRequalified": False, "deliveryComplete": False, "releaseQualified": False}
    index_path = REPO / "docs/ci-verification-20261107-r112.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", "utf-8")
    for name in ("README.md", "开发计划与进度.md", "docs/执行进度.md", "docs/macOS独立预览包.md", "docs/decisions/0026-配置变更竞态与故障测试预期.md"):
        shutil.copyfile(ROOT / name, REPO / name)
    shutil.copyfile(Path(__file__), BASE / "fault-refusal-r112-local/evidence-index-driver.py")
    for path in BASE.glob("skip-directory-r111-*"):
        shutil.copytree(path, ROOT / path.relative_to(REPO), dirs_exist_ok=True)
    for path in BASE.glob("fault-refusal-r112-*"):
        shutil.copytree(path, ROOT / path.relative_to(REPO), dirs_exist_ok=True)
    for path in (old_index, index_path):
        shutil.copyfile(path, ROOT / path.relative_to(REPO))
    print(json.dumps({"plan": "v0.112", "macFaultCases": 48, "windowsFaultCases": 24,
                      "intelProtocolPassed": 45, "intelProtocolFailed": 2, "windowsProtocolQualified": windows.get("qualified", False)}))


if __name__ == "__main__":
    main()

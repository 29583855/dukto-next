"""日期：2026-11-07；把双Windows实际结果绑定公开R113精确Git对象，原生作业仍按现态记录。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
SOURCE = "400e0621745dc250b3390ad01a5e9f47dfc924a4"


# 日期：2026-11-07；按字节绑定原件，不能用新文档描述替换原始失败日志。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-07；逐Git blob核对输入并确认远端提交，只授予实际双Windows范围的资格。
def main():
    receipt_path = REPO / "docs/validation/2026-11-07/skip-reconcile-r113-local/receipt.json"
    local = json.loads(receipt_path.read_text("utf-8"))
    assert local["passed"] and local["inputCount"] == 243
    tree_raw = subprocess.check_output(["git", "ls-tree", "-r", "-z", SOURCE, "--", "CMakeLists.txt",
                                        ".clang-format", ".github", "resources", "src", "ui", "tests", "scripts"], cwd=REPO)
    entries = {}
    for row in tree_raw.split(b"\0"):
        if row:
            metadata, name = row.split(b"\t", 1)
            entries[name.decode("utf-8")] = metadata.decode("ascii").split()[2]
    for row in local["qualificationInputs"]:
        raw = (ROOT / row["path"]).read_bytes()
        assert raw == (REPO / row["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest() == entries[row["path"]]
    assert set(entries) == {row["path"] for row in local["qualificationInputs"]}
    remote = subprocess.check_output(["git", "-c", "http.proxy=http://127.0.0.1:10808", "ls-remote",
                                      "origin", "refs/heads/main"], cwd=REPO).decode().split()[0]
    assert remote == SOURCE
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    api = "/repos/29583855/dukto-next/actions/runs/"
    native = request(api + "42368086270")
    package = request(api + "42368208979")
    assert native["head_sha"] == package["head_sha"] == SOURCE
    receipts = [receipt_path, receipt_path.with_name("source-audit.json"),
                REPO / "docs/validation/2026-11-07/skip-reconcile-r113-native-core/receipt.json"]
    result = {"observedUtc": datetime.now(timezone.utc).isoformat(), "planVersion": "v0.113",
              "sourceCommit": SOURCE, "sourceTree": subprocess.check_output(["git", "rev-parse", SOURCE + "^{tree}"], cwd=REPO).decode().strip(),
              "remoteSourceVerified": True, "localInputsMatchExactSource": True,
              "qualificationInputs": local["qualificationInputs"], "inputCount": 243,
              "receipts": [{"path": path.relative_to(REPO).as_posix(), "sha256": sha(path)} for path in receipts],
              "localWindowsToolchainsQualified": 2, "directoryRowsPerToolchain": 59,
              "nativeRun": {key: native[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
              "macosPackageRun": {key: package[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
              "nativeCoreQualificationPending": True, "nativeProtocolQualificationPending": True,
              "macosDeploymentQualificationPending": True,
              "limitations": ["R111 ARM overwrite-faults and Intel credential-rotation/session-expiry failures remain retained and unresolved",
                              "Unknown-identity temporary objects, general GC and global disk budgets remain incomplete",
                              "Full R6 GUI, physical LAN/3x3, all-platform current-version 24h, corresponding-source rebuilds and formal distribution remain incomplete"],
              "deliveryComplete": False, "releaseQualified": False}
    path = REPO / "docs/ci-verification-20261107-r113.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(path, ROOT / path.relative_to(REPO))
    replace = runpy.run_path(str(ROOT / ".cache/finalize-r111-snapshot.py"))["replace"]
    replace(ROOT / "开发计划与进度.md", "- [ ] R113精确提交的四平台原生构建、59行目录专项与完整协议待CI实际验收；当前Mac含依赖包仍精确R111，不冒充包含本修复。",
            "- [x] R113精确`400e0621745dc250b3390ad01a5e9f47dfc924a4`已非强制推送，远端main一致，243份输入与提交树逐blob匹配。[验证索引](docs/ci-verification-20261107-r113.json)。\n- [ ] 同源[原生运行42368086270](https://github.com/29583855/dukto-next/actions/runs/42368086270)与[Mac打包42368208979](https://github.com/29583855/dukto-next/actions/runs/42368208979)实际运行中；四平台构建、59行专项、完整协议及部署包按原件验收。当前已验含依赖Mac包仍为R111，不冒充包含本修复。")
    replace(ROOT / "docs/macOS独立预览包.md", "# macOS独立开发预览包",
            "# macOS独立开发预览包\n\nR113精确`400e0621745dc250b3390ad01a5e9f47dfc924a4`已上传，新增跳过目录的接收/维护交错恢复修复。双Windows各59条目录专项通过；[四平台原生构建](https://github.com/29583855/dukto-next/actions/runs/42368086270)与[双Mac含依赖打包](https://github.com/29583855/dukto-next/actions/runs/42368208979)仍待实际原件验收，当前已验含依赖下载仍为下方R111。")
    for name in ("开发计划与进度.md", "docs/macOS独立预览包.md"):
        shutil.copyfile(ROOT / name, REPO / name)
    folder = REPO / "docs/validation/2026-11-07/skip-reconcile-r113-local"
    shutil.copyfile(Path(__file__), folder / "evidence-index-driver.py")
    shutil.copytree(folder, ROOT / folder.relative_to(REPO), dirs_exist_ok=True)
    native_folder = REPO / "docs/validation/2026-11-07/skip-reconcile-r113-native-core"
    shutil.copytree(native_folder, ROOT / native_folder.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({"sourceCommit": SOURCE, "exactInputsVerified": 243, "nativeRunStatus": native["status"],
                      "macosPackageRunStatus": package["status"], "deliveryComplete": False}))


if __name__ == "__main__":
    main()

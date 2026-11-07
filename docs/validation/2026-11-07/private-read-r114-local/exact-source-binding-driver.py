"""日期：2026-11-07；核对R114公开输入与两项实际运行，不把待验CI写成完成。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
SOURCE = "d922dc4c793c77de0553ddf44c0fe1fa2d998c24"


# 日期：2026-11-07；全部输入与精确Git blob和本机字节比较，补证据的文档提交不改变应用来源。
def main():
    path = REPO / "docs/ci-verification-20261107-r114.json"
    index = json.loads(path.read_text("utf-8"))
    assert index["sourcePublicationPending"]
    entries = {}
    for row in subprocess.check_output(["git", "ls-tree", "-r", "-z", SOURCE], cwd=REPO).split(b"\0"):
        if row:
            meta, name = row.split(b"\t", 1)
            entries[name.decode("utf-8")] = meta.decode().split()[2]
    for row in index["qualificationInputs"]:
        raw = (ROOT / row["path"]).read_bytes()
        assert raw == (REPO / row["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entries[row["path"]]
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    api = "/repos/29583855/dukto-next/actions/runs/"
    native = request(api + "42370990486")
    package = request(api + "42371059159")
    assert native["head_sha"] == package["head_sha"] == SOURCE
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourceCommit=SOURCE,
                 sourceTree=subprocess.check_output(["git", "rev-parse", SOURCE + "^{tree}"], cwd=REPO).decode().strip(),
                 sourcePublicationPending=False, exactGitInputsVerified=243,
                 nativeRun={key: native[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                 macosPackageRun={key: package[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")})
    for row in index["receipts"]:
        assert hashlib.sha256((REPO / row["path"]).read_bytes()).hexdigest() == row["sha256"]
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", "utf-8")
    replace = runpy.run_path(str(ROOT / ".cache/finalize-r111-snapshot.py"))["replace"]
    replace(ROOT / "开发计划与进度.md", "- [ ] 精确候选源码公开上传，四平台完整原生CI及Mac编译/含依赖部署按实际附件收验；当前已验Mac预览仍为R113，不包含本项修复。",
            "- [x] 精确`" + SOURCE + "`已非强制上传，243份资格输入与Git提交树逐blob一致。[索引](docs/ci-verification-20261107-r114.json)。\n- [ ] 同源[四平台原生CI42370990486](https://github.com/29583855/dukto-next/actions/runs/42370990486)与[双Mac含依赖打包42371059159](https://github.com/29583855/dukto-next/actions/runs/42371059159)已实际启动；按原始附件逐项验收。当前已验Mac预览仍为R113，不包含本项修复。")
    replace(ROOT / "docs/macOS独立预览包.md", "# macOS独立开发预览包",
            "# macOS独立开发预览包\n\nR114精确`" + SOURCE + "`已上传，增加私有配置原子换代有界重读。[原生CI42370990486](https://github.com/29583855/dukto-next/actions/runs/42370990486)和[含依赖打包42371059159](https://github.com/29583855/dukto-next/actions/runs/42371059159)实际运行中，尚未收验；下方已验可下载包仍为R113。")
    for name in ("开发计划与进度.md", "docs/macOS独立预览包.md"):
        shutil.copyfile(ROOT / name, REPO / name)
    folder = REPO / "docs/validation/2026-11-07/private-read-r114-local"
    shutil.copyfile(Path(__file__), folder / "exact-source-binding-driver.py")
    shutil.copyfile(ROOT / ".cache/r114-source-publication.json", folder / "source-publication.json")
    shutil.copyfile(ROOT / ".cache/r114-macos-package-dispatch.json", folder / "macos-package-dispatch.json")
    shutil.copyfile(path, ROOT / path.relative_to(REPO))
    shutil.copytree(folder, ROOT / folder.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({"sourceCommit": SOURCE, "exactInputsVerified": 243,
                      "nativeStatus": native["status"], "macosPackageStatus": package["status"]}))


if __name__ == "__main__":
    main()

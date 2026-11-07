"""日期：2026-11-07；发布四个已验证输入与分级证据，非强制推送并核对远端精确提交。"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
BASE = REPO / "docs/validation/2026-11-07"


# 日期：2026-11-07；所有公开摘要绑定原始字节，不规范化日志或重新编码既有文件。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-07；发布仅包括明确维护文件与本次已审查证据，依赖二进制和私有状态不进入仓库。
def main():
    local_folder = BASE / "private-read-r114-local"
    local = json.loads((local_folder / "receipt.json").read_text("utf-8"))
    assert local["passed"] and local["inputCount"] == 243
    for row in local["qualificationInputs"]:
        assert sha(ROOT / row["path"]) == sha(REPO / row["path"]) == row["sha256"]
    request = runpy.run_path(str(ROOT / ".cache/github-actions-r28.py"))["request"]
    api = "/repos/29583855/dukto-next/actions/runs/"
    native = request(api + "42368086270")
    package = request(api + "42368208979")
    r113_path = REPO / "docs/ci-verification-20261107-r113.json"
    r113 = json.loads(r113_path.read_text("utf-8"))
    terminal = json.loads((BASE / "skip-reconcile-r113-native-terminal/receipt.json").read_text("utf-8"))
    for row in r113["receipts"]:
        row["sha256"] = sha(REPO / row["path"])
    r113.update(observedUtc=datetime.now(timezone.utc).isoformat(),
                nativeRun={key: native[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                macosPackageRun={key: package[key] for key in ("id", "head_sha", "status", "conclusion", "html_url")},
                nativeProtocolQualified=terminal["allFourNativeProtocolJobsVerified"],
                nativeProtocolQualificationPending=native["status"] != "completed")
    r113_path.write_text(json.dumps(r113, ensure_ascii=False, indent=2) + "\n", "utf-8")
    replace = runpy.run_path(str(ROOT / ".cache/finalize-r111-snapshot.py"))["replace"]
    plan = ROOT / "开发计划与进度.md"
    text = plan.read_text("utf-8")
    line, = [line for line in text.splitlines() if line.startswith("- [ ] [完整协议运行42368086270]")]
    count = sum(row["qualified"] for row in terminal["records"])
    replace(plan, line, re.sub(r"已验终态job \d/4", "已验终态job " + str(count) + "/4", line))
    if any(row.get("runner") == "macos-15" and row.get("qualified") for row in terminal["records"]):
        replace(plan, "同源完整协议Ubuntu47/47，其他平台仍在执行", "同源完整协议Ubuntu/Apple Silicon各47/47，其他平台仍在执行")
    shutil.copyfile(plan, REPO / "开发计划与进度.md")
    receipts = [local_folder / "receipt.json", local_folder / "source-audit.json",
                local_folder / "ubuntu-focused/receipt.json", local_folder / "windows/receipt.json"]
    value = {"observedUtc": datetime.now(timezone.utc).isoformat(), "planVersion": "v0.114",
             "baselineSourceCommit": local["baselineSourceCommit"], "sourcePublicationPending": True,
             "qualificationInputs": local["qualificationInputs"], "inputCount": 243,
             "changedInputs": local["changedInputs"],
             "receipts": [{"path": path.relative_to(REPO).as_posix(), "sha256": sha(path)} for path in receipts],
             "localChecksPassed": True, "nativeQualificationPending": True,
             "fullNativeProtocolQualified": False, "macosPreviewSourceCommit": r113["sourceCommit"],
             "deliveryComplete": False, "releaseQualified": False}
    index = REPO / "docs/ci-verification-20261107-r114.json"
    assert not index.exists()
    index.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(Path(__file__), local_folder / "publication-driver.py")
    paths = ["开发计划与进度.md", "docs/macOS独立预览包.md", "docs/decisions/0028-私有配置原子换代的有界重读.md",
             "docs/ci-verification-20261107-r113.json", "docs/ci-verification-20261107-r114.json", *local["changedInputs"]]
    for folder in sorted(BASE.iterdir()):
        if folder.name.startswith("skip-reconcile-r113-") or folder == local_folder:
            paths.extend(path.relative_to(REPO).as_posix() for path in folder.rglob("*") if path.is_file())
    assert len(paths) == len(set(paths))
    patterns = [re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
                re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
                re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
                re.compile(rb"Bearer\s+[A-Za-z0-9_.-]{20,}")]
    for name in paths:
        raw = (REPO / name).read_bytes()
        assert len(raw) <= 32 * 1024**2
        assert not any(pattern.search(raw) for pattern in patterns), name
    for offset in range(0, len(paths), 75):
        subprocess.run(["git", "-c", "core.autocrlf=false", "add", "-f", "--", *paths[offset:offset + 75]],
                       cwd=REPO, capture_output=True, check=True)
    subprocess.run(["git", "diff", "--cached", "--check", "--", ".", ":(exclude)docs/validation"],
                   cwd=REPO, check=True, capture_output=True)
    entries = {}
    for row in subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=REPO).split(b"\0"):
        if row:
            metadata, name = row.split(b"\t", 1)
            entries[name.decode("utf-8")] = metadata.decode().split()[1]
    for name in paths:
        raw = (REPO / name).read_bytes()
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == entries[name], name
    subprocess.run(["git", "commit", "-qm", "Retry atomic private configuration replacements within a fixed read budget"],
                   cwd=REPO, check=True, capture_output=True)
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO).decode().strip()
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    push = subprocess.run(["git", "-c", "http.proxy=http://127.0.0.1:10808", "-c", "http.lowSpeedLimit=1000",
                           "-c", "http.lowSpeedTime=30", "push", "origin", "main"],
                          cwd=REPO, env=environment, capture_output=True, text=True, timeout=120)
    assert push.returncode == 0, push.stderr
    remote = subprocess.check_output(["git", "-c", "http.proxy=http://127.0.0.1:10808", "ls-remote", "origin", "refs/heads/main"],
                                     cwd=REPO, env=environment).decode().split()[0]
    assert remote == source
    receipt = {"sourceCommit": source, "remoteMainVerified": True, "exactInputsVerified": 243,
               "publishedFilesAudited": len(paths), "allStagedBytesPreserved": True,
               "pushWasNonForced": True, "deliveryComplete": False, "releaseQualified": False}
    (ROOT / ".cache/r114-source-publication.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")
    for name in ("docs/ci-verification-20261107-r113.json", "docs/ci-verification-20261107-r114.json"):
        shutil.copyfile(REPO / name, ROOT / name)
    shutil.copytree(local_folder, ROOT / local_folder.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()

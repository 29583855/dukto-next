"""日期：2026-11-07；汇总R111已核验原件及明确边界，证据提交不改变冻结编译输入。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
SOURCE = "dfe245b502f586e7df7219e8fb0d5e4030a6b032"
EVIDENCE = REPO / "docs/validation/2026-11-07"


# 日期：2026-11-07；校验原件摘要、原提交构建输入与主目录同一内容，不能仅引用存在性。
def main():
    records = {}
    for label in ("local", "native-core", "native-terminal", "macos-compiled", "macos-package"):
        path = EVIDENCE / ("skip-directory-r111-" + label) / "receipt.json"
        value = json.loads(path.read_text("utf-8"))
        assert value["sourceCommit"] == SOURCE
        records[label] = {"path": path.relative_to(REPO).as_posix(),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "receipt": value}
    local = records["local"]["receipt"]
    assert local["passed"] and records["native-core"]["receipt"]["allNativeCoreTestsPassed"]
    assert records["native-core"]["receipt"]["allNativeCleanupTestsPassed"]
    assert records["macos-compiled"]["receipt"]["bothArchitecturesCompiledAndVerified"]
    for row in local["buildInputs"]:
        original = subprocess.check_output(["git", "show", SOURCE + ":" + row["path"]], cwd=REPO)
        assert hashlib.sha256(original).hexdigest() == row["sha256"]
        assert original == (ROOT / row["path"]).read_bytes() == (REPO / row["path"]).read_bytes()
    changed = subprocess.check_output(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", SOURCE], cwd=REPO)
    encoding = []
    for name in changed.decode("utf-8").split("\0"):
        if not name or not name.endswith((".cpp", ".h")):
            continue
        before = subprocess.check_output(["git", "show", SOURCE + "^:" + name], cwd=REPO)
        current = (ROOT / name).read_bytes()
        before.decode("utf-8-sig")
        current.decode("utf-8-sig")
        assert before.startswith(b"\xef\xbb\xbf") == current.startswith(b"\xef\xbb\xbf")
        old_crlf = before.count(b"\r\n")
        old_lf = before.count(b"\n")
        if old_crlf == old_lf:
            assert current.count(b"\r\n") == current.count(b"\n")
        elif old_crlf == 0:
            assert current.count(b"\r\n") == 0
        else:
            raise AssertionError("mixed original line endings require individual review: " + name)
        encoding.append({"path": name, "encoding": "UTF-8", "bomPreserved": True,
                         "lineEndings": "CRLF" if old_crlf else "LF", "lineEndingsPreserved": True})
    config = (ROOT / "CMakeLists.txt").read_text("utf-8")
    assert "set(CMAKE_CXX_STANDARD 14)" in config
    observation = ROOT / ".cache/r111-frozen-long-observation.json"
    shutil.copyfile(observation, EVIDENCE / "skip-directory-r111-local/frozen-long-observation.json")
    value = {"observedUtc": datetime.now(timezone.utc).isoformat(), "planVersion": "v0.111",
             "sourceCommit": SOURCE, "repositoryUrl": "https://github.com/29583855/dukto-next",
             "nativeRun": "https://github.com/29583855/dukto-next/actions/runs/42362014363",
             "macosPackageRun": "https://github.com/29583855/dukto-next/actions/runs/42363743119",
             "buildInputs": local["buildInputs"], "buildInputCount": len(local["buildInputs"]),
             "codeEncodingAndLineEndings": encoding,
             "verificationReceipts": [{key: row[key] for key in ("path", "sha256")} for row in records.values()],
             "allFourNativeCoreTestsPassed": True, "allFourNativeCleanupTestsPassed": True,
             "bothMacArchitecturesCompiledAndVerified": True,
             "allFourNativeProtocolJobsVerified": records["native-terminal"]["receipt"]["allFourNativeProtocolJobsVerified"],
             "bothMacDeployedPackagesVerified": records["macos-package"]["receipt"]["bothArchitecturesVerified"],
             "limitations": ["Precise existing Darwin exclusiveTcpBinding XFAIL remains",
                             "Maintenance interruption followed by receiver recovery needs cleanup-intent convergence qualification",
                             "Unknown-identity temporary objects, general caches and global disk budgets remain incomplete",
                             "Full R6 GUI, physical LAN/3x3, all-platform 24h, clean systems and formal distribution remain incomplete"],
             "deliveryComplete": False, "releaseQualified": False}
    target = REPO / "docs/ci-verification-20261107-r111.json"
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")
    shutil.copyfile(Path(__file__), EVIDENCE / "skip-directory-r111-local/evidence-index-driver.py")
    print(json.dumps({key: value[key] for key in ("sourceCommit", "buildInputCount", "allFourNativeCoreTestsPassed",
        "allFourNativeProtocolJobsVerified", "bothMacDeployedPackagesVerified", "deliveryComplete", "releaseQualified")}))


if __name__ == "__main__":
    main()

"""日期：2026-11-07；冻结R110本机原始验证记录并按真实范围更新计划，保留全部待验收项。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(r"E:\project\dukto")
REPO = ROOT / ".cache/github-29583855-dukto-next-r28"
OUTPUT = REPO / "docs/validation/2026-11-07/directory-cleanup-r110-local"
CHANGED = ["CMakeLists.txt", "src/core/clientdownloadcleanup.cpp", "src/core/expiredtaskcleanup.cpp",
           "src/core/nativecommit.cpp", "src/core/nativecommit.h", "src/core/directorycleanup.cpp",
           "src/core/directorycleanup.h", "tests/directory_cleanup_tests.cpp", "tests/expired_task_cleanup_tests.cpp"]


# 日期：2026-11-07；使用相对路径和原始字节摘要绑定证据，不把工作目录路径当下载入口。
def proof(root, path):
    data = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


# 日期：2026-11-07；保持现有文档编码/BOM/换行，每处精确替换都要求唯一匹配。
def edit(name, changes, after=None, content=None):
    path = REPO / name
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    value = raw.decode("utf-8-sig").replace("\r\n", "\n")
    for old, new in changes:
        assert value.count(old) == 1, (name, old[:90], value.count(old))
        value = value.replace(old, new)
    if after is not None:
        assert value.count(after) == 1
        value = value.replace(after, after + content, 1)
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + value.replace("\n", newline).encode("utf-8"))


# 日期：2026-11-07；分别核验八个真实CTest目标和Qt原件，45条数据行与15个方法节点独立计数。
def collect():
    OUTPUT.mkdir(parents=True, exist_ok=False)
    records = []
    targets = ["core-tests", "sqlite-cache-tests", "strong-manifest-tests", "task-store-tests",
               "expired-task-cleanup-tests", "client-download-cleanup-tests", "directory-cleanup-tests", "durable-receive-tests"]
    for label in ("ucrt", "msvc"):
        build = ROOT / (".cache/directory-cleanup-r110-" + label)
        source = build / "related-final"
        record = json.loads((source / "summary.json").read_text("utf-8"))
        assert record["exitCode"] == 0 and set(record["targets"]) == set(targets)
        assert "100% tests passed out of 8" in (source / "ctest.log").read_text("utf-8-sig")
        destination = OUTPUT / label
        destination.mkdir()
        tests = {}
        for target in targets:
            suite = ET.fromstring((source / "QtTest" / (target + ".xml")).read_bytes())
            cases = suite.findall("testcase")
            assert suite.get("failures") == "0" and cases and not suite.findall(".//failure")
            assert all(item.get("result") == "pass" for item in cases)
            text = (source / "QtTest" / (target + ".log")).read_text("utf-8-sig")
            match = re.search(r"Totals: (\d+) passed, 0 failed, 0 skipped", text)
            assert match, target
            tests[target] = {"junitMethods": len(cases), "actualRowsIncludingData": int(match[1])}
            if target == "directory-cleanup-tests":
                assert int(match[1]) == 45 and len(cases) == 15
                for name in ("damagedIntent", "interruptionBeforeRemoval", "linkedDirectoryIsRejected", "walModeWithoutSidecars"):
                    assert "PASS   : DirectoryCleanupTests::" + name in text
            if target == "expired-task-cleanup-tests":
                for flag in ("wide-zero", "wide-one"):
                    assert "PASS   : ExpiredTaskCleanupTests::wideConfirmationFlag(" + flag + ")" in text
            for suffix in ("xml", "log"):
                shutil.copyfile(source / "QtTest" / (target + "." + suffix), destination / (target + "." + suffix))
        for original, name in [(source / "ctest.log", "ctest.log"), (source / "Temporary/LastTest.log", "LastTest.log"),
                               (build / "configure.log", "configure.log"), (build / "build.log", "incremental-build.log")]:
            shutil.copyfile(original, destination / name)
        binaries = build / "Release" if label == "msvc" else build
        record.update(tests=tests, binaries=[proof(binaries, binaries / (name + ".exe")) for name in ("dukto-cli", "directory-cleanup-tests", "expired-task-cleanup-tests")])
        records.append(record)
    audit_path = ROOT / ".cache/directory-cleanup-r110-source-audit.json"
    audit = json.loads(audit_path.read_text("utf-8"))
    assert audit["sourceMarkersPassed"] and audit["cxx14Configuration"] and not audit["findings"]
    shutil.copyfile(audit_path, OUTPUT / "source-audit.json")
    formatter = ROOT / ".cache/tools/clang-format-py/clang_format/data/bin/clang-format.exe"
    subprocess.run([str(formatter), "--dry-run", "--Werror", *[name for name in CHANGED if name.endswith((".cpp", ".h"))]], cwd=REPO, check=True, capture_output=True)
    encoding = []
    for name in CHANGED:
        data = (REPO / name).read_bytes()
        data.decode("utf-8")
        assert not data.startswith(b"\xef\xbb\xbf") and b"\r\n" not in data
        old = subprocess.run(["git", "show", "HEAD:" + name], cwd=REPO, capture_output=True)
        if old.returncode == 0:
            assert not old.stdout.startswith(b"\xef\xbb\xbf") and b"\r\n" not in old.stdout
        encoding.append({"path": name, "encoding": "UTF-8", "bom": False, "lineEnding": "LF", "existingFormatPreserved": old.returncode == 0})
    names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=REPO).decode().split("\0")
    inputs = [proof(REPO, REPO / name) for name in sorted(set(names)) if name and
              (name.startswith(("src/", "tests/", "scripts/", "ui/", "resources/", "third-party/", ".github/")) or name in ("CMakeLists.txt", ".clang-format"))]
    (OUTPUT / "build-inputs.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / ".cache/r110-frozen-long-observation.json", OUTPUT / "frozen-long-observation.json")
    for script in (Path(__file__), ROOT / ".cache/test-directory-cleanup-r110.py", ROOT / ".cache/build-directory-cleanup-r110.py"):
        shutil.copyfile(script, OUTPUT / script.name)
    result = {"observedUtc": datetime.now(timezone.utc).isoformat(),
              "sourceBaseCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO).decode().strip(),
              "scope": "Local Windows UCRT/Qt5.15.19 and MSVC/Qt5.15.2; exact build inputs attached; native CI pending",
              "passed": True, "results": records, "sourceAuditFiles": len(audit["files"]), "inputCount": len(inputs),
              "changedFiles": encoding, "formattingChangedCppPassed": True,
              "files": [proof(OUTPUT, path) for path in sorted(OUTPUT.rglob("*")) if path.is_file()],
              "openScope": ["native four-platform R110 validation", "skip-policy directory coordination", "unknown-identity temporary directories", "global GC and total disk budgets", "full R6 GUI", "physical LAN and 3x3 matrix", "24-hour stability", "dependency source rebuild and clean signed distribution"],
              "deliveryComplete": False, "releaseQualified": False}
    (OUTPUT / "receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result, inputs


# 日期：2026-11-07；只勾选双本机实测范围，原生CI、全局预算和正式交付保持独立待验收。
def documents(result, inputs):
    section = """## R110未发布空目录临时项清理（2026-11-07）

- [x] 扩展已有客户端及服务器cleanup命令，按强清单ID合并文件与目录分页，每页至多100项，执行逐条维护；新增`kind`、`cleanedDirectories`与`preservedDirectories`。不要求用户使用新的参数。
- [x] 只删除原生身份匹配、未发布的空`.dukto-UUID.dir`；FULL持久意图支持删除前后真实进程退出及取消事务回滚后重入。客户端确认时原子复位预约，原任务可重新创建；服务器保留确认，同名新目录不重复删除。
- [x] 删除所用原生父句柄核对原父目录身份，拒绝替换、链接/reparse、损坏日志、未知提交结果及WAL；非空目录不递归删除。原普通文件清理同时拒绝超32位损坏确认标志，避免截断为0/1。
- [x] Windows UCRT/Qt5.15.19、MSVC/Qt5.15.2各8个相关CTest通过，目录专项各45条数据行/15个JUnit方法，零失败、零跳过；真实CLI、四策略、父目录替换、真实junction、删除前后子进程退出和103条混合分页均已核验。[原件与构建输入](docs/validation/2026-11-07/directory-cleanup-r110-local/receipt.json)。216份维护源码零TODO/FIXME/占位标记；C++14、修改代码格式、UTF-8无BOM/LF保留通过。
- [x] R109精确`bea5d81`运行`42347962868`的Ubuntu与Apple Silicon完整job各47协议项终态success，官方附件SHA、31 TLS、任务库8进程及平台报告逐项收验；Intel和Windows在本次观察仍执行。[终态原件](docs/validation/2026-11-07/client-cleanup-r109-native-terminal/receipt.json)。双Mac已有精确Darwin端口独占XFAIL和历史失败继续保留。
- [ ] R110四平台原生编译/核心/完整协议尚待上传后实际运行；本机子集不授予原生或完整交付资格。skip目录、无身份临时项、完整处置协调、通用缓存/全局GC及历史256MiB和活动清单总磁盘预算仍未完成。[清理语义](docs/过期任务临时文件清理.md)。
- [ ] 2026-11-07 07:27 UTC只读核对冻结长测服务进程和原程序摘要：Windows154轮/46470秒，Ubuntu125轮/41256秒，实际服务均存活；尚未86400秒终态，原输入和进程未修改。完整R6/GUI、物理LAN/3×3、各平台24h、依赖源码独立重建、最低干净系统及正式签名公证继续待验；deliveryComplete=false、releaseQualified=false。

"""
    edit("开发计划与进度.md", [
        ("文档版本：v0.109", "文档版本：v0.110"),
        ("当前阶段：R109源码`bea5d81`已公开，四平台C++14编译和各25个核心/GUI控制器CTest均已核验；客户端下载清理各16条数据行通过。Apple Silicon/Intel GUI及独立CLI归档身份和摘要通过；完整协议仍执行，完整项目与发布资格继续未完成。", "当前阶段：R110扩展客户端/服务器未发布空目录临时项清理，双Windows工具链各8个相关核心目标及目录专项各45条数据行已通过，原生CI待验；R109双Mac编译已验，Ubuntu/Apple Silicon完整回归终态通过，Intel/Windows仍执行。完整项目与发布资格继续未完成。"),
        ("## 当前验收快照（2026-11-07，v0.109 / 客户端未完成下载临时文件维护）", "## 当前验收快照（2026-11-07，v0.110 / 未发布空目录临时项维护）"),
        ("| R109客户端清理 | 四平台各25个CTest及下载清理各16条数据行通过；本机UCRT/MSVC各7个相关目标通过 | 最终源码完整协议；目录、通用缓存和全局磁盘回收 |", "| 当前清理范围 | R110双Windows各8相关CTest、目录专项各45条；R109四原生各25个CTest与下载清理各16条已验 | R110原生CI；skip/未知目录、通用缓存和全局磁盘回收 |"),
    ], after="## R109客户端未完成下载临时正文清理（2026-11-07）", content="")
    path = REPO / "开发计划与进度.md"
    raw = path.read_bytes()
    marker = "## R109客户端未完成下载临时正文清理（2026-11-07）".encode("utf-8")
    assert raw.count(marker) == 1
    path.write_bytes(raw.replace(marker, section.encode("utf-8") + marker, 1))
    latest = """## R110最新已核验进度（2026-11-07）

- [x] 客户端与服务器cleanup共用文件/目录有界分页，增加未发布空临时目录的原生身份核对、FULL删除意图、客户端预约复位及服务器幂等确认。已发布、复用、skip和无身份项保留；非空或损坏/替换证据明确拒绝。
- [x] 双Windows各8个相关CTest通过；目录专项各45条数据行/15个方法，真实CLI、junction、父目录替换、WAL、损坏意图、删除前后子进程退出及回滚恢复通过。216份维护源码审计、C++14/格式/原编码换行通过。[本机原件](validation/2026-11-07/directory-cleanup-r110-local/receipt.json)。
- [x] R109 Ubuntu/Apple Silicon完整job各47协议终态success，附件与关键报告已验；Intel/Windows仍待终态。R109双MacGUI/CLI编译归档及[下载入口](macOS独立预览包.md)继续可用。
- [ ] R110原生四平台CI、skip完整处置协调、全局GC/总磁盘预算、完整R6 GUI、物理LAN/3×3、各平台24h及正式分发仍待验；整体与发布资格保持false。

"""
    edit("docs/执行进度.md", [], after="按主计划逐项实施。`[x]` 只表示该行明确范围已经取得证据；子项通过不等于整个阶段完成。主计划的三平台、全功能、服务器、多线程、恢复和稳定性范围继续有效。\n\n", content=latest)
    edit("README.md", [], after="公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。", content="R110增加客户端/服务器未发布空目录临时项维护；双Windows各8个相关CTest、目录专项各45条通过，原生四平台待验。按原生身份和FULL持久意图删除，已发布及未知项保留；[清理范围](docs/过期任务临时文件清理.md)。")
    edit("docs/过期任务临时文件清理.md", [
        ("`preview`每页最多100个接收文件条目", "`preview`每页最多100个接收文件/目录条目（R110起按同一清单ID混合分页）"),
        ("用户源文件、已发布最终文件、目录、没有已记录身份的创建中临时项均保留。文件或目录存在提交结果不确定的记录时，预览和执行都会拒绝，必须先按原任务恢复并核验结果；不能将其推定为垃圾。", "用户源文件、已发布最终文件/目录、复用目录及没有已记录身份的创建中临时项均保留。R110允许清理有完整身份和意图的未发布空临时目录，见下节；普通文件存在提交结果不确定记录时仍拒绝，必须先按原任务恢复核验，不能推定为垃圾。"),
        ("`preview`每页最多列出100个文件", "`preview`每页最多列出100个文件/目录（R110起）"),
        ("已完成文件、目录项、跳过策略下的文件、任务历史及清单均保留", "已完成文件/目录、复用目录、跳过策略项、任务历史及清单均保留"),
        ("该入口不清理通用缓存、目录临时项或全局过期任务，也不实现总磁盘预算", "R110仅扩展下述可验证空临时目录；入口仍不清理通用缓存或全局过期任务，也不实现总磁盘预算"),
        ("这两种清理入口尚不承担全局自动回收、目录临时项回收、元数据删除或总磁盘配额。", "这两种清理入口尚不承担全局自动回收、未知身份/skip目录回收、元数据删除或总磁盘配额。"),
    ])
    details = """
## 未发布空临时目录（R110）

已有两套`preview|run`命令自动包含目录，不增加操作参数。预览条目增加`kind: file|directory`；`after`是两种条目共用的强清单ID。JSON增加`cleanedDirectories`、`preservedDirectories`；服务器已确认清理项按幂等结果计入cleaned，同名新目录不会被再次删除。`run`不积累全部条目数组。

仅处理日志为`committing`、已记录原生身份、随机`.dukto-UUID.dir`名/映射/冻结强清单全部一致的目录。父目录须为原接收器已完成预约且实际身份匹配，顶层核对原接收根；实际查询和删除使用的固定父句柄再次核对该身份。仅系统空目录删除，不递归；目录中出现外部文件即拒绝，保存意图及内容。

删除前FULL提交绑定ID、临时名、目标名、原生身份、原spec SHA及维护模式的意图；删除后FULL确认。客户端同一事务将预约复位planned/清空native并移除意图，支持原任务重新创建目录；服务器保留cleaned确认，重跑只报告原结果。删除前/后进程退出可重入；事务中取消回滚后同样恢复。

临时名消失但最终目标具有相同原生身份时返回`preserved-published`。两者均缺失且没有持久删除意图时明确拒绝未知提交结果；不能推定已经清理。已完成/复用目录、skip策略及没有身份的创建中项继续保留，完整skip处置日志协调仍待实现。替换父目录、链接/junction/reparse、非目录对象、损坏意图或WAL均拒绝；SQLite确认标志使用完整64位整数核对，不能截断超范围值为0/1。POSIX原生API不提供对任意外部改名的文件系统CAS，不能将本机维护锁宣称为外部进程锁。

双Windows工具链各45条目录专项及各8相关核心CTest已验；原生四平台结果另验。[实现](../src/core/directorycleanup.cpp)、[测试](../tests/directory_cleanup_tests.cpp)、[本机原件](validation/2026-11-07/directory-cleanup-r110-local/receipt.json)。
"""
    path = REPO / "docs/过期任务临时文件清理.md"
    raw = path.read_bytes()
    assert b"\r\n" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    path.write_bytes(raw + details.encode("utf-8"))
    value = {"observedUtc": datetime.now(timezone.utc).isoformat(), "planVersion": "v0.110", "sourceBaseCommit": result["sourceBaseCommit"],
             "repositoryUrl": "https://github.com/29583855/dukto-next", "localEvidence": proof(REPO, OUTPUT / "receipt.json"),
             "localToolchains": ["UCRT Qt5.15.19", "MSVC Qt5.15.2"], "localRelatedTargetsEach": 8,
             "directoryCleanupRowsEach": 45, "directoryCleanupJUnitMethodsEach": 15,
             "nativeR110Pending": True, "priorR109TerminalEvidence": proof(REPO, REPO / "docs/validation/2026-11-07/client-cleanup-r109-native-terminal/receipt.json"),
             "buildInputs": inputs, "openScope": result["openScope"], "deliveryComplete": False, "releaseQualified": False}
    (REPO / "docs/ci-verification-20261107-r110.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result, inputs = collect()
    documents(result, inputs)
    print(json.dumps({"localToolchains": 2, "relatedTargetsEach": 8, "directoryRowsEach": 45, "inputCount": len(inputs), "deliveryComplete": False}))

"""日期：2026-11-26；完整Qt应用经真实Files界面导入导出，宿主独立回读内容与目录。"""
import hashlib
import json
from pathlib import Path
import time

from android_emulator import send_r6
from ios_send import command


# 日期：2026-11-26；等待真实产品或系统提供器提交，不由测试脚本补写目标内容。
def wait_entries(documents, entries, exact_directory=None):
    deadline = time.monotonic() + 25
    while True:
        valid = True
        for name, data in entries:
            path = documents / name
            if path.is_symlink() or not (path.is_dir() if data is None else
                                         path.is_file() and path.read_bytes() == data):
                valid = False
                break
        if valid:
            if exact_directory:
                root = documents / exact_directory
                actual = {p.relative_to(documents).as_posix() for p in root.rglob("*")}
                expected = {name for name, _ in entries if name != exact_directory}
                if actual != expected:
                    raise RuntimeError("系统复制后的目录条目不一致: " + str(actual ^ expected))
            return [{"path": name, "directory": data is None,
                     "bytes": None if data is None else len(data),
                     "sha256": None if data is None else hashlib.sha256(data).hexdigest()}
                    for name, data in entries]
        if time.monotonic() >= deadline:
            raise RuntimeError("系统提供器未正确提交文件或目录: " + name)
        time.sleep(0.1)


# 日期：2026-11-26；四项真实界面操作逐项独立读取落盘数据，任何一步失败保留原始记录。
def verify_storage(device, build, documents):
    source = "a-ios-io-source"
    target = "a-ios-io-export"
    filename = "a-ios-import.bin"
    folder = "a-ios-import-directory"
    payload = "iOS系统导入导出\n".encode("utf-8") + bytes(range(256)) * 259
    content = [(folder, None), (folder + "/中文 空格.bin", payload),
               (folder + "/empty.bin", b""), (folder + "/空目录", None)]
    fixtures = [(source, None), (target, None), (source + "/" + filename, payload)]
    fixtures.extend((source + "/" + name, data) for name, data in content)
    report = {"passed": False, "deviceTest": False, "realUiActions": True,
              "systemDocumentPicker": True, "cloudProviderTest": False, "operations": []}
    log = build / "ios-storage-ui.log"
    try:
        for path in [documents / filename, documents / folder]:
            if path.exists():
                raise RuntimeError("导入验收目标必须在操作前不存在: " + path.name)
        send_r6(4644, fixtures)
        report["fixtures"] = wait_entries(documents, fixtures)
        operations = [
            ("import-file", "testImportFileFromSystemDocuments", [(filename, payload)], None),
            ("import-directory", "testImportDirectoryFromSystemDocuments", content, folder),
            ("export-file", "testExportFileToSystemDocuments", [(target + "/" + filename, payload)], None),
            ("export-directory", "testExportDirectoryToSystemDocuments",
             [(target + "/" + name, data) for name, data in content], target + "/" + folder),
        ]
        for name, case, entries, directory in operations:
            operation = {"name": name, "passed": False, "cancelAndReopen": False}
            report["operations"].append(operation)
            command(log, "xcodebuild", "-project", build / "ui" / "MobileSendTests.xcodeproj",
                    "-scheme", "MobileSendTests", "-configuration", "Debug",
                    "-destination", "platform=iOS Simulator,id=" + device,
                    "-derivedDataPath", build / "ui-derived", "CODE_SIGNING_ALLOWED=NO",
                    "CODE_SIGNING_REQUIRED=NO", "-parallel-testing-enabled", "NO",
                    "-only-testing:MobileSendTests/MobileSendTests/" + case,
                    "-resultBundlePath", build / ("ios-storage-" + name + ".xcresult"),
                    "test-without-building", timeout=480)
            operation["diskReadback"] = wait_entries(documents, entries, directory)
            operation.update(passed=True, cancelAndReopen=True, sourcePreserved=True)
            wait_entries(documents, fixtures)
        wait_entries(documents, [(filename, payload)] + content)
        report.update(passed=True, processRestarts=0, sendRetries=0,
                      fixturesReceivedByProductionR6=True, sourcePreserved=True,
                      storage="iOS simulator real system Files provider; no cloud or device claim")
        return report
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        (build / "ios-storage.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

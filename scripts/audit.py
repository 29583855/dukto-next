"""日期：2026-11-04；检查本工程源码的遗留标记和交付缺项，不能用零标记代替验收。"""

import argparse
from datetime import date
import json
from pathlib import Path
import re
import subprocess


# 日期：2026-11-08；扫描维护的C/C++及脚本，保留交付缺项，零标记不能替代实际验收。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    marker = re.compile(r"\b(?:TODO|FIXME|XXX|HACK|stub|placeholder|NotImplemented)\b|未实现|占位实现|简化实现", re.I)
    unsupported = re.compile(r"std::(?:filesystem|optional|variant|string_view|span|jthread)\b")
    findings = []
    files = []
    for folder in ("src", "ui", "scripts", "tests"):
        for path in sorted((root / folder).rglob("*")):
            if path.suffix not in (".c", ".h", ".cpp", ".qml", ".py", ".ps1") or path == Path(__file__):
                continue
            raw = path.read_bytes()
            relative = path.relative_to(root).as_posix()
            text = raw.decode("utf-8-sig")
            files.append({"path": relative, "encoding": "UTF-8 BOM" if raw.startswith(b"\xef\xbb\xbf") else "UTF-8",
                          "lineEnding": "CRLF" if b"\r\n" in raw else "LF"})
            for number, line in enumerate(text.splitlines(), 1):
                for kind, expression in (("marker", marker), ("C++17-or-newer-library", unsupported)):
                    if expression.search(line):
                        findings.append({"path": relative, "line": number, "kind": kind, "text": line.strip()})
    cmake = (root / "CMakeLists.txt").read_text(encoding="utf-8")
    standard = all(value in cmake for value in ("CMAKE_CXX_STANDARD 14", "CMAKE_CXX_STANDARD_REQUIRED ON",
                                                "CMAKE_CXX_EXTENSIONS OFF"))
    formatter = root / ".tools/python/Scripts/clang-format.exe"
    formatting = None
    if formatter.exists():
        sources = [str(root / item["path"]) for item in files if Path(item["path"]).suffix in (".c", ".cpp", ".h")]
        result = subprocess.run([str(formatter), "--dry-run", "--Werror", *sources], capture_output=True, timeout=30)
        formatting = {"passed": result.returncode == 0, "diagnostics": result.stderr.decode("utf-8", "replace")}
    report = {"date": date.today().isoformat(), "sourceMarkersPassed": not findings, "cxx14Configuration": standard,
              "formatting": formatting, "files": files, "findings": findings,
              "scope": "audit.py excludes itself because it contains the search expressions; external and generated files excluded",
              "deliveryComplete": False,
              "openRequirements": ["complete R6 GUI and native interaction comparison", "macOS native build/runtime; Linux glibc/X11/Wayland; complete 3x3 protocol matrix",
                                   "macOS native directory/commit verification; source mutation/content identity boundaries",
                                   "complete server main-window/platform and certificate lifecycle verification; session expiry/configuration/checkpoint recovery, credential rotation, response-loss recovery and live-transfer continuation tested on Windows MSVC/UCRT",
                                   "complete fair global resource budgets, R6/SQLite/model cache accounting; TLS control/data classification and Windows MSVC/UCRT isolation subcases tested",
                                   "extended multi-file/fault-offset and completion-ack loss recovery; public pause/checkpoints/restart/idempotent subcases tested separately",
                                   "Windows/macOS disk exhaustion; extended crash/low-memory injection; 24-hour and physical LAN validation",
                                   "macOS/glibc native dependencies, native installers and clean-system validation; Windows Qt5.15.19/OpenSSL3.6.4/GCC16 C++14 verified",
                                   "Windows UCRT and Alpine TLS five-level upload/download matrix passed; full three-platform matrix and physical LAN remain open"]}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(files), "findings": len(findings), "cxx14Configuration": standard,
                      "formatting": formatting, "deliveryComplete": False}, ensure_ascii=False))
    return 0 if not findings and standard and (formatting is None or formatting["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

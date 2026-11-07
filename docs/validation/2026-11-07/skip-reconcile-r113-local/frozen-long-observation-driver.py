"""日期：2026-11-07；只读核对冻结长测的真实进程与摘要，不干预原输入或运行。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import psutil
import runpy
import subprocess


# 日期：2026-11-07；核对服务进程执行文件与报告身份，观测不授予长期终态资格。
def main():
    root = Path(r"E:\project\dukto")
    source = root / "docs/validation/2026-11-07/current-windows-r98-long/summary24h.json"
    windows = json.loads(source.read_text("utf-8"))
    process = psutil.Process(windows["servicePid"])
    digest = hashlib.sha256(Path(process.exe()).read_bytes()).hexdigest()
    assert process.is_running() and digest == windows["executableSha256"] == "2fdecefae477b2415dd9282964eee85ece9d50e582027fe2012f2828a91c394b"
    keys = ("status", "passed", "rounds", "elapsedSeconds", "durationRequestedSeconds", "requestedChannels", "executableSha256", "servicePid")
    selected = {key: windows[key] for key in keys}
    selected["serviceProcessAlive"] = True
    ssh = runpy.run_path(str(root / ".cache/validate-exit-state-r98-final-glibc.py"))["SSH"]
    program = '''import hashlib, json, os
from pathlib import Path
root = Path('/home/dukto/current-linux-r98-long')
value = json.loads((root / 'results/summary24h.json').read_text('utf-8'))
os.kill(value['servicePid'], 0)
actual = hashlib.sha256(Path('/proc/' + str(value['servicePid']) + '/exe').read_bytes()).hexdigest()
assert actual == value['executableSha256'] == '816b549fd5c34be611e9e1f669e54ab8a2c224ace1206cc3b314adcceb9d2412'
selected = {key: value[key] for key in ('status', 'passed', 'rounds', 'elapsedSeconds', 'durationRequestedSeconds', 'requestedChannels', 'executableSha256', 'servicePid')}
selected['serviceProcessAlive'] = True
print(json.dumps(selected))
'''
    result = subprocess.run(ssh + ["python3 -"], input=program.encode("utf-8"), capture_output=True, cwd=root, timeout=45)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    value = {"observedUtc": datetime.now(timezone.utc).isoformat(), "windows": selected,
             "ubuntu": json.loads(result.stdout), "originalProcessesAndInputsNotModified": True,
             "terminalQualificationGrantedByThisObservation": False, "deliveryComplete": False,
             "releaseQualified": False}
    target = root / ".cache/r113-frozen-long-observation.json"
    assert not target.exists()
    target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value))


if __name__ == "__main__":
    main()

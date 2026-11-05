"""日期：2026-11-05；在保留既有运行中脚本原件的条件下，为同一完整长测安装可移植采样适配。"""

import hashlib
import json
from pathlib import Path
import sys

import parallel_soak_integration as suite
from process_sampling import sample, thread_inventory


# 日期：2026-11-05；只替换资源采样入口，传输、摘要、双向重试、限额、暖机及持续时长断言保持原样。
def main():
    report = Path(sys.argv[sys.argv.index("--report") + 1])
    source = Path(__file__).resolve().parent
    names = [Path(__file__).name, "parallel_soak_integration.py", "process_sampling.py",
             "soak_transfer.py", "service_integration.py", "transfer_integration.py", "process_output.py"]
    manifest = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}
    receipt = report.with_name(report.stem + "-test-inputs.json")
    assert not receipt.exists() and not report.exists()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"date": "2026-11-05", "files": manifest,
        "scope": "frozen wrapper and original full harness; only exit-race sampling and OS thread inventory adapter"}, indent=2) + "\n", encoding="utf-8")
    original_inventory = suite.thread_inventory
    suite.sample = sample
    suite.thread_inventory = lambda process: thread_inventory(process, original_inventory)
    suite.main()


if __name__ == "__main__":
    main()

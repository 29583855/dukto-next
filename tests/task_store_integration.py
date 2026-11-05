"""日期：2026-11-04；八个真实进程验证持久幂等竞争、活动所有权和强制退出后的锁恢复。"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import uuid


# 日期：2026-11-04；探针输出必须为单个 JSON，非零退出码和标准错误不能当作成功吞掉。
def finish(process, expected=0):
    out, err = process.communicate(timeout=20)
    assert process.returncode == expected and not err, (process.returncode, out, err)
    return json.loads(out)


# 日期：2026-11-04；所有测试状态均为隔离临时目录，不访问已有服务和用户传输文件。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    owner, request = str(uuid.uuid4()), str(uuid.uuid4())
    processes = []
    with tempfile.TemporaryDirectory(prefix="dukto-task-store-") as temporary:
        root = Path(temporary).resolve()
        command = [executable, "create", str(root / "private"), owner, request, str(root)]
        try:
            for _ in range(8):
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
                processes.append(process)
            events = [finish(process) for process in processes]
            task_id = events[0]["taskId"]
            assert all(value["taskId"] == task_id for value in events)
            with closing(sqlite3.connect(root / "private/tasks.sqlite")) as database:
                assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
                assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            hold = command[:]
            hold[1] = "hold"
            active = subprocess.Popen(hold, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(active)
            locked = json.loads(active.stdout.readline())
            assert locked["taskId"] == task_id and locked["executionOwner"]
            rejected = subprocess.Popen(hold, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(rejected)
            assert finish(rejected, 4)["stage"] == "task"
            active.kill()
            active.communicate(timeout=5)
            recovered = subprocess.Popen(hold, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(recovered)
            restored = json.loads(recovered.stdout.readline())
            assert restored["taskId"] == task_id and restored["executionOwner"] and restored["state"] == "scanning"
            recovered.kill()
            recovered.communicate(timeout=5)
            repeated = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(repeated)
            assert finish(repeated)["taskId"] == task_id
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
    report = {"date": "2026-11-04", "passed": True, "competingProcesses": 8,
              "persistedTasks": 1, "activeLeaseRefused": True, "leaseRecoveredAfterKill": True,
              "scope": "persistent task metadata and execution ownership; no file resume or durable file commit claim"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

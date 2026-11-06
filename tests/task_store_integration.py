"""日期：2026-11-04；八个真实进程验证持久幂等竞争、活动所有权和强制退出后的锁恢复。"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import uuid


# 日期：2026-11-04；探针输出必须为单个 JSON，非零退出码和标准错误不能当作成功吞掉。
def finish(process, expected=0):
    out, err = process.communicate(timeout=20)
    assert process.returncode == expected and not err, (process.returncode, out, err)
    return json.loads(out)


# 日期：2026-11-06；隔离目录验证幂等/进程退出及八进程旧库升级，不访问用户状态。
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
            # 日期：2026-11-05；先持锁再同时启动八个创建进程，原5秒初始化预算内必须全部返回同一个持久任务。
            contested = [executable, "init-lock", str(root / "contended"), owner, request, str(root)]
            initializer = subprocess.Popen(contested, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(initializer)
            assert json.loads(initializer.stdout.readline())["initializationHeld"]
            contenders = []
            contested[1] = "create"
            started = time.monotonic()
            for _ in range(8):
                contender = subprocess.Popen(contested, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
                processes.append(contender)
                contenders.append(contender)
            time.sleep(0.15)
            initializer.terminate()
            initializer.communicate(timeout=5)
            contested_results = [finish(process) for process in contenders]
            contested_seconds = time.monotonic() - started
            assert contested_seconds < 5, contested_seconds
            assert len({value["taskId"] for value in contested_results}) == 1
            with closing(sqlite3.connect(root / "contended/tasks.sqlite")) as database:
                assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
                assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            # 日期：2026-11-06；实际旧列结构同时被八进程打开，只有一次升级且幂等键/原15列逐字节保持。
            migration = [executable, "create", str(root / "migration"), owner, request, str(root)]
            initial = subprocess.Popen(migration, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(initial)
            legacy = finish(initial)
            with closing(sqlite3.connect(root / "migration/tasks.sqlite")) as database:
                assert database.execute("PRAGMA user_version").fetchone() == (2,)
                assert database.execute("SELECT accounting FROM tasks").fetchone() == (b"",)
                database.execute("ALTER TABLE tasks DROP COLUMN accounting")
                database.execute("PRAGMA user_version=1")
                database.commit()
                before_migration = database.execute("SELECT * FROM tasks").fetchone()
                assert len(before_migration) == 15
            migrating = []
            migration_started = time.monotonic()
            for _ in range(8):
                process = subprocess.Popen(migration, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
                processes.append(process)
                migrating.append(process)
            migrated = [finish(process) for process in migrating]
            migration_seconds = time.monotonic() - migration_started
            assert all(value == legacy for value in migrated), migrated
            with closing(sqlite3.connect(root / "migration/tasks.sqlite")) as database:
                assert database.execute("PRAGMA user_version").fetchone() == (2,)
                rows = database.execute("SELECT * FROM tasks").fetchall()
                assert len(rows) == 1 and rows[0][:-1] == before_migration and rows[0][-1] == b""
                assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            # 日期：2026-11-05；活进程持续持锁仍须在原5秒预算拒绝，不能删除活锁或无限延长初始化等待。
            blocked_command = [executable, "init-lock", str(root / "held-timeout"), owner, request, str(root)]
            blocker = subprocess.Popen(blocked_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(blocker)
            assert json.loads(blocker.stdout.readline())["initializationHeld"]
            blocked_command[1] = "create"
            started = time.monotonic()
            blocked = subprocess.Popen(blocked_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            processes.append(blocked)
            refused = finish(blocked, 4)
            initialization_timeout_seconds = time.monotonic() - started
            assert refused["stage"] == "task" and 4.8 <= initialization_timeout_seconds < 6
            assert blocker.poll() is None
            blocker.terminate()
            blocker.communicate(timeout=5)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
    report = {"date": "2026-11-04", "passed": True, "competingProcesses": 8,
              "persistedTasks": 1, "activeLeaseRefused": True, "leaseRecoveredAfterKill": True,
              "schemaMigrationProcesses": 8, "schemaMigrationSeconds": round(migration_seconds, 3),
              "oldFifteenColumnsUnchanged": True, "migratedSchemaVersion": 2,
              "contendedInitializationProcesses": 8, "contendedInitializationSeconds": round(contested_seconds, 3),
              "activeInitializationOwnerPreserved": True,
              "initializationTimeoutSeconds": round(initialization_timeout_seconds, 3),
              "scope": "persistent task metadata and execution ownership; no file resume or durable file commit claim"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

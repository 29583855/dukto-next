"""日期：2026-11-05；独立进程专项共用的有界 JSONL 服务输出读取器。"""

from collections import Counter, deque
import io
import json
import threading


class JsonOutputDrain:
    # 日期：2026-11-05；监听首行由调用方读取，后续始终消费，避免故障关闭事件塞满平台管道。
    def __init__(self, stream):
        self.stream = stream
        self.bytes = 0
        self.events = Counter()
        self.recent = deque(maxlen=16)
        self.error = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    # 日期：2026-11-05；只累计计数并保留最后 16 条诊断，不按故障次数或运行时间积累事件数组。
    def read(self):
        try:
            for line in self.stream:
                event = json.loads(line)
                with self.lock:
                    self.bytes += len(line.encode("utf-8"))
                    self.events[event.get("event", "")] += 1
                    self.recent.append(event)
        except Exception as error:
            self.error = repr(error)

    # 日期：2026-11-09；原子复制固定汇总，后台活动和资源取样间可核对生命周期修订。
    def snapshot(self):
        with self.lock:
            return {"bytes": self.bytes, "events": dict(self.events), "lastEvents": list(self.recent)}

    # 日期：2026-11-05；只有服务真实退出后调用；读取异常和未退出线程必须使专项失败。
    def finish(self):
        self.thread.join(5)
        assert not self.thread.is_alive() and not self.error, (self.error, list(self.recent))
        return self.snapshot()


# 日期：2026-11-05；截断末行、非 JSON 输出不能覆盖原期限失败；最多保留十六条有效事件和固定整数。
def timeout_evidence(error, budget, elapsed):
    captured = error.stdout or b""
    if isinstance(captured, bytes):
        captured = captured.decode("utf-8", errors="replace")
    recent = deque(maxlen=16)
    counts = Counter()
    invalid = 0
    maximum = restored = 0
    for line in io.StringIO(captured):
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("non-object event")
            counts[event.get("event", "")] += 1
            recent.append(event)
            if event.get("event") == "byte-progress":
                maximum = max(maximum, int(event["bytes"]))
                restored = max(restored, int(event["restoredBytes"]))
        except (ValueError, KeyError, TypeError):
            invalid += 1
    return {"kind": "transfer-test-timeout", "budgetSeconds": budget,
            "elapsedSeconds": round(elapsed, 3), "eventCounts": dict(counts),
            "invalidOrPartialLines": invalid, "maxBytes": maximum, "maxRestoredBytes": restored,
            "lastEvents": list(recent)}

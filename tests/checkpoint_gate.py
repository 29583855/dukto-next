"""日期：2026-11-05；在真实持久检查点协调故障注入，透明TLS代理不解密或修改业务报文。"""

import threading
import time


class CheckpointGate:
    # 日期：2026-11-05；初始额度仅供握手/控制及少量正文；固定连接上限限制测试协调器内存。
    def __init__(self, direction):
        assert direction in ("upload", "download")
        self.direction = direction
        self.condition = threading.Condition()
        self.streams = []
        self.accepting = True
        self.released = False

    # 日期：2026-11-05；只限制选定正文方向；冻结后新控制连接不受阻挡，最多保留128个流记录。
    def attach(self, direction):
        with self.condition:
            if not self.accepting or direction != self.direction:
                return None
            assert len(self.streams) < 128, "checkpoint connection limit"
            record = {"index": len(self.streams), "limit": 128 * 1024, "reserved": 0,
                      "forwarded": 0, "waiting": False, "finished": False, "grants": 0}
            self.streams.append(record)
            return record

    # 日期：2026-11-05；在读取下一片密文前取得有限额度，避免把整文件缓存在代理中。
    def allowance(self, record, stopped):
        with self.condition:
            while not self.released and record["reserved"] >= record["limit"] and not stopped.is_set():
                record["waiting"] = True
                self.condition.notify_all()
                self.condition.wait(0.05)
            record["waiting"] = False
            if stopped.is_set():
                return 0
            amount = 16384 if self.released else min(16384, record["limit"] - record["reserved"])
            record["reserved"] += amount
            return amount

    # 日期：2026-11-05；只累计成功转发的密文字节，不能将其冒充接收端持久确认量。
    def forwarded(self, record, size, allowance):
        with self.condition:
            record["reserved"] -= allowance - size
            record["forwarded"] += size

    # 日期：2026-11-05；结束标志允许协调器转到另一数据流，不给已关闭连接追加额度。
    def finished(self, record):
        with self.condition:
            record["finished"] = True
            record["waiting"] = False
            self.condition.notify_all()

    # 日期：2026-11-09；逐次追加4MiB；无确认进展250ms后轮换等待流，避免跨通道依赖饿死其他TLS连接。
    def checkpoint(self, read_confirmed, minimum, timeout=120):
        deadline = time.monotonic() + timeout
        selected, baseline, granted_at = None, 0, 0.0
        while time.monotonic() < deadline:
            confirmed = read_confirmed()
            with self.condition:
                if confirmed >= minimum:
                    self.accepting = False
                    return confirmed
                if selected is not None and (confirmed > baseline or selected["finished"]
                                             or time.monotonic() - granted_at >= 0.25):
                    selected = None
                if selected is None:
                    waiting = [value for value in self.streams if value["waiting"] and not value["finished"]]
                    if waiting:
                        selected = min(waiting, key=lambda value: (value["grants"], -value["forwarded"]))
                        baseline = confirmed
                        granted_at = time.monotonic()
                        selected["limit"] += 4 * 1024 * 1024
                        selected["grants"] += 1
                        self.condition.notify_all()
                self.condition.wait(0.01)
        raise AssertionError(("no durable checkpoint before fault", minimum, self.evidence()))

    # 日期：2026-11-05；控制请求已提交或进程已结束后放开旧数据流，恢复传输仍使用原速率和期限。
    def release(self):
        with self.condition:
            self.accepting = False
            self.released = True
            self.condition.notify_all()

    # 日期：2026-11-05；进度最多每250ms发布；每条已有数据流再准许有限片段，完成在途TLS帧并触发真实进度。
    def publish_progress(self):
        with self.condition:
            assert not self.accepting and not self.released
            assert not self.condition.wait_for(lambda: self.released, timeout=0.3)
            candidates = [value for value in self.streams if value["forwarded"] >= 128 * 1024 and not value["finished"]]
            assert candidates, self.evidence()
            for selected in candidates:
                selected["limit"] += 512 * 1024
            self.condition.notify_all()

    # 日期：2026-11-05；报告固定上限的流额度与密文量，真实确认量由接收日志独立记录。
    def evidence(self):
        with self.condition:
            return {"direction": self.direction, "accepting": self.accepting,
                    "released": self.released, "streams": [dict(value) for value in self.streams],
                    "scope": "opaque TLS forwarding barrier; forwarded bytes include protocol overhead"}

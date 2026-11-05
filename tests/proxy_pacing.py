"""日期：2026-11-05；限速代理采用单调期限，补偿系统定时器超睡而不积累无限突发额度。"""

import time


class ProxyPacer:
    # 日期：2026-11-05；每条转发方向独立计时，最多补偿四分之一秒，禁止空闲后无限追赶。
    def __init__(self):
        self.deadline = None
        self.maximum_catchup_seconds = 0.25

    # 日期：2026-11-05；收包阻塞时间不获得额度；只补偿此前定时器超睡，仍逐16KiB片段可取消等待。
    def wait(self, stopped, size, rate, receive_seconds):
        assert 0 < size <= 16384 and rate > 0 and receive_seconds >= 0
        now = time.monotonic()
        if self.deadline is None:
            self.deadline = now
        else:
            self.deadline += receive_seconds
        self.deadline = max(self.deadline, now - self.maximum_catchup_seconds) + size / rate
        return stopped.wait(max(0.0, self.deadline - now))

"""日期：2026-11-05；真实TCP转发注入每次70ms超睡，独立验证限速上界、吞吐与取消。"""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import threading
import time

from proxy_pacing import ProxyPacer


class Oversleep:
    # 日期：2026-11-05；注入定时器超睡而非修改单调时钟，真实网络和取消仍由原生线程事件完成。
    def __init__(self):
        self.event = threading.Event()

    # 日期：2026-11-05；正等待模拟70ms额外延迟，已落后期限时不再人为睡眠。
    def wait(self, seconds):
        return self.event.wait(seconds + 0.07 if seconds > 0 else 0)


# 日期：2026-11-05；固定2MiB样本流式收发，不在内存累积网络历史；每次收包检查累计速率边界。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assert not args.report.exists()
    rate, size = 512 * 1024, 2 * 1024 * 1024
    block = bytes(range(256)) * 64
    expected = hashlib.sha256(block * (size // len(block))).hexdigest()
    pacer, delayed = ProxyPacer(), Oversleep()
    received, failures = [], []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        started = time.monotonic()

        # 日期：2026-11-05；接收端独立核对实际到达字节、SHA和速率上界，网络断开或超时明确失败。
        def receive():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(10)
                    count, digest = 0, hashlib.sha256()
                    while count < size:
                        data = connection.recv(65536)
                        assert data
                        count += len(data)
                        digest.update(data)
                        assert count <= rate * (time.monotonic() - started + 0.25) + 65536
                    received.append({"bytes": count, "sha256": digest.hexdigest(),
                                     "seconds": time.monotonic() - started})
            except Exception as error:
                failures.append(repr(error))

        worker = threading.Thread(target=receive, daemon=True)
        worker.start()
        with socket.create_connection(listener.getsockname(), timeout=10) as sender:
            sender.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            for _ in range(size // len(block)):
                assert not pacer.wait(delayed, len(block), rate, 0)
                sender.sendall(block)
        worker.join(10)
    assert not worker.is_alive() and not failures and len(received) == 1, failures
    actual, = received
    assert actual["bytes"] == size and actual["sha256"] == expected
    assert size / rate - 0.25 <= actual["seconds"] <= 7, actual
    delayed.event.set()
    cancelled = time.monotonic()
    assert pacer.wait(delayed, len(block), rate, 0)
    assert time.monotonic() - cancelled < 0.1
    value = {"date": "2026-11-05", "passed": True, "injectedExtraWaitSeconds": 0.07,
             "rateBytesPerSecond": rate, "maximumCatchupSeconds": 0.25, "received": actual,
             "cancelled": True, "scope": "real TCP fixture pacing under injected timer oversleep; not application or physical LAN throughput"}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value))


if __name__ == "__main__":
    main()

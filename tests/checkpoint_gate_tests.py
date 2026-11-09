"""日期：2026-11-09；验证透明代理跨通道依赖可继续，确认字节仍只取自接收日志。"""

import threading
import unittest

from checkpoint_gate import CheckpointGate


class CheckpointGateTests(unittest.TestCase):
    # 日期：2026-11-09；第一流等待第二流产生确认时，代理不能一直等待第一流而饿死第二流。
    def test_waiting_lane_dependency_makes_progress(self):
        gate = CheckpointGate("upload")
        first, second = gate.attach("upload"), gate.attach("upload")
        first.update(waiting=True, forwarded=65536)
        second.update(waiting=True, forwarded=16384)
        confirmed = [0]
        stopped = threading.Event()

        # 日期：2026-11-09；模拟真实跨流依赖，只在两个流都取得有限额度后提交独立确认量。
        def receiver():
            with gate.condition:
                gate.condition.wait_for(lambda: stopped.is_set() or
                                        (first["grants"] and second["grants"]), timeout=2)
                if first["grants"] and second["grants"]:
                    confirmed[0] = 4194304
                    gate.condition.notify_all()

        worker = threading.Thread(target=receiver)
        worker.start()
        try:
            self.assertEqual(gate.checkpoint(lambda: confirmed[0], 4194304, timeout=1.5), 4194304)
            self.assertFalse(gate.accepting)
            self.assertFalse(gate.released)
            self.assertEqual(first["grants"], 1)
            self.assertEqual(second["grants"], 1)
        finally:
            stopped.set()
            with gate.condition:
                gate.condition.notify_all()
            worker.join(2)
            self.assertFalse(worker.is_alive())

    # 日期：2026-11-09；大量已转发密文不能替代持久日志确认，达到超时仍须保留失败证据。
    def test_ciphertext_does_not_count_as_durable_checkpoint(self):
        gate = CheckpointGate("download")
        stream = gate.attach("download")
        stream.update(forwarded=16 * 1024 * 1024, finished=True)
        with self.assertRaisesRegex(AssertionError, "no durable checkpoint before fault"):
            gate.checkpoint(lambda: 0, 1, timeout=0.02)
        self.assertTrue(gate.accepting)
        self.assertFalse(gate.released)


if __name__ == "__main__":
    unittest.main()

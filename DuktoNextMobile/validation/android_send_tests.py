"""日期：2026-11-25；验证独立验收接收器不把截断、错误或多余字节算作通过。"""
import socket
import struct
import threading
import unittest

from android_send import receive_exact, receive_text


class IndependentReceiverTests(unittest.TestCase):
    # 日期：2026-11-25；TCP任意分片下仍按真实UTF-8字节核对，并等待发送端EOF。
    def test_fragmented_utf8(self):
        text = "中文 with space".encode("utf-8")
        wire = struct.pack("<qq", 1, len(text)) + b"___DUKTO___TEXT___\0" + struct.pack("<q", len(text)) + text
        receiver, sender = socket.socketpair()
        receiver.settimeout(3)
        def send():
            # 日期：2026-11-25；按三字节切片覆盖UTF-8和64位整数跨网络分片。
            with sender:
                for offset in range(0, len(wire), 3):
                    sender.sendall(wire[offset:offset + 3])
        worker = threading.Thread(target=send)
        worker.start()
        try:
            with receiver:
                self.assertEqual(receive_text(receiver, text)["bytes"], len(text))
        finally:
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())

    # 日期：2026-11-25；畸形名称、条目数、长度、正文和尾随数据均必须拒绝。
    def test_invalid_frames(self):
        valid = struct.pack("<qq", 1, 1) + b"___DUKTO___TEXT___\0" + struct.pack("<q", 1) + b"x"
        invalid = [valid[:-1], valid + b"extra", valid[:-1] + b"y",
                   struct.pack("<qq", 2, 1) + valid[16:],
                   struct.pack("<qq", 1, 2) + valid[16:],
                   valid.replace(b"___DUKTO___TEXT___", b"invalid"),
                   valid[:34] + struct.pack("<q", -1) + b"x"]
        for wire in invalid:
            with self.subTest(frame=wire):
                receiver, sender = socket.socketpair()
                with receiver, sender:
                    receiver.settimeout(3)
                    sender.sendall(wire)
                    sender.shutdown(socket.SHUT_WR)
                    with self.assertRaises((RuntimeError, ValueError)):
                        receive_text(receiver, b"x")

    # 日期：2026-11-25；验收工具自身同样有内存上限，拒绝负长度和超限申请。
    def test_bounded_allocation(self):
        for length in [-1, 262145]:
            with self.assertRaises(ValueError):
                receive_exact(None, length)


if __name__ == "__main__":
    unittest.main()

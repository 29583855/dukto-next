"""日期：2026-11-25；验证独立验收接收器不把截断、错误或多余字节算作通过。"""
import socket
import struct
import threading
import unittest

from android_send import file_fixtures, receive_exact, receive_files, receive_text


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

    # 日期：2026-11-26；独立组装文件帧，避免调用被测应用的序列化器。
    def file_wire(self, fixtures):
        return (struct.pack("<qq", len(fixtures), sum(len(data) for _, data in fixtures if data is not None)) +
                b"".join(name.encode("utf-8") + b"\0" + struct.pack("<q", -1 if data is None else len(data)) + (b"" if data is None else data)
                         for name, data in fixtures))

    # 日期：2026-11-26；真实大小样本任意分片下核对中文名称、全部二进制和空文件。
    def test_file_content_and_empty(self):
        fixtures = file_fixtures()
        wire = self.file_wire(list(reversed(fixtures)))
        receiver, sender = socket.socketpair()
        receiver.settimeout(3)
        failures = []

        # 日期：2026-11-26；独立线程分片发送，避免大帧受本机socket缓冲区大小影响。
        def send():
            try:
                with sender:
                    for offset in range(0, len(wire), 997):
                        sender.sendall(wire[offset:offset + 997])
            except Exception as error:
                failures.append(error)

        worker = threading.Thread(target=send)
        worker.start()
        try:
            with receiver:
                result = receive_files(receiver, fixtures)
            self.assertEqual(result["bytes"], sum(len(data) for _, data in fixtures if data is not None))
            self.assertEqual({item["name"] for item in result["files"]}, {name for name, _ in fixtures})
            self.assertTrue(result["emptyFile"])
        finally:
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures)

    # 日期：2026-11-26；错误条目、总长、名称、正文、截断及额外尾部一律不能通过。
    def test_invalid_file_frames(self):
        fixtures = [("中文 x", b"x"), ("empty", b"")]
        valid = self.file_wire(fixtures)
        invalid = [valid[:-1], valid + b"extra", valid.replace(b"x\0", b"y\0", 1),
                   struct.pack("<qq", 3, 1) + valid[16:],
                   struct.pack("<qq", 2, 2) + valid[16:],
                   valid.replace(b"empty\0", "中文 x".encode("utf-8") + b"\0"),
                   valid.replace("中文 x".encode("utf-8"), b"\xff"),
                   valid[:16] + b"a" * 512,
                   self.file_wire([("中文 x", b"y"), ("empty", b"")]),
                   valid.replace(struct.pack("<q", 1) + b"x", struct.pack("<q", -1) + b"x")]
        for wire in invalid:
            with self.subTest(frame=wire[:40]):
                receiver, sender = socket.socketpair()
                with receiver, sender:
                    receiver.settimeout(3)
                    sender.sendall(wire)
                    sender.shutdown(socket.SHUT_WR)
                    with self.assertRaises((RuntimeError, ValueError)):
                        receive_files(receiver, fixtures)
        with self.assertRaises(ValueError):
            receive_files(None, [("same", b"x"), ("same", b"y")])

    # 日期：2026-11-26；目录与空文件必须区分，根和嵌套空目录逐项核对，拒绝其他负数哨兵。
    def test_directory_sentinels(self):
        fixtures = [("root", None), ("root/空目录", None),
                    ("root/中文.bin", b"abc"), ("root/empty", b"")]
        valid = self.file_wire(list(reversed(fixtures)))
        receiver, sender = socket.socketpair()
        with receiver, sender:
            receiver.settimeout(3)
            sender.sendall(valid)
            sender.shutdown(socket.SHUT_WR)
            result = receive_files(receiver, fixtures)
            self.assertEqual(result["directories"], 2)
            self.assertEqual(result["bytes"], 3)
            self.assertTrue(result["emptyFile"])
        for bad in [-2, 0, 1]:
            with self.subTest(sentinel=bad):
                wire = valid.replace(struct.pack("<q", -1), struct.pack("<q", bad), 1)
                receiver, sender = socket.socketpair()
                with receiver, sender:
                    receiver.settimeout(3)
                    sender.sendall(wire)
                    sender.shutdown(socket.SHUT_WR)
                    with self.assertRaises(RuntimeError):
                        receive_files(receiver, fixtures)

    # 日期：2026-11-25；验收工具自身同样有内存上限，拒绝负长度和超限申请。
    def test_bounded_allocation(self):
        for length in [-1, 262145]:
            with self.assertRaises(ValueError):
                receive_exact(None, length)


if __name__ == "__main__":
    unittest.main()

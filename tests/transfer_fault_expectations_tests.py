"""日期：2026-11-07；验证故障拒绝契约，防止完整事件字典误比较或任意完整性错误被放行。"""

import unittest

from transfer_faults_integration import validate_fault_refusal


class FaultExpectationsTests(unittest.TestCase):
    # 日期：2026-11-07；真实错误含event等字段，两个POSIX配置变更故障均须允许精确安全拒绝。
    def test_exact_path_refusal(self):
        for fault in ("revoke", "root-reconfigure"):
            for message in ("源文件路径在读取期间已被替换", "读取期间源文件已变化"):
                with self.subTest(fault=fault, message=message):
                    error = {"event": "error", "eventVersion": 1, "code": 6,
                             "stage": "read", "message": message}
                    stopped = {"state": "failed", "confirmed": 1, "total": 64}
                    self.assertTrue(validate_fault_refusal(error, fault, stopped, "posix"))

    # 日期：2026-11-07；错误阶段、消息、事件、版本与平台不匹配，均不能笼统接受code6。
    def test_unrelated_integrity_refusal_rejected(self):
        original = {"event": "error", "eventVersion": 1, "code": 6,
                    "stage": "read", "message": "源文件路径在读取期间已被替换"}
        stopped = {"state": "failed", "confirmed": 1, "total": 64}
        for change in ({"stage": "write"}, {"message": "摘要不匹配"}, {"event": "other"},
                       {"eventVersion": 2}, {"eventVersion": True}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate_fault_refusal({**original, **change}, "revoke", stopped, "posix")
        with self.assertRaises(AssertionError):
            validate_fault_refusal(original, "revoke", stopped, "nt")

    # 日期：2026-11-07；精确错误也不能掩盖已完成任务、全部确认或非法进度。
    def test_completed_or_invalid_progress_rejected(self):
        error = {"event": "error", "eventVersion": 1, "code": 6,
                 "stage": "read", "message": "读取期间源文件已变化"}
        for stopped in ({"state": "completed", "confirmed": 1, "total": 64},
                        {"state": "failed", "confirmed": 64, "total": 64},
                        {"state": "interrupted", "confirmed": -1, "total": 64}):
            with self.subTest(stopped=stopped), self.assertRaises(AssertionError):
                validate_fault_refusal(error, "root-reconfigure", stopped, "posix")

    # 日期：2026-11-07；原连接/权限拒绝及源变化预期保持可用，不能把成功码或磁盘错误当故障成功。
    def test_existing_refusals(self):
        stopped = {"state": "failed", "confirmed": 1, "total": 64}
        for fault in ("revoke", "root-reconfigure", "same-size-mtime-source-change"):
            for code in ((3, 6) if fault == "same-size-mtime-source-change" else (3, 4)):
                with self.subTest(fault=fault, code=code):
                    self.assertFalse(validate_fault_refusal({"code": code}, fault, stopped, "posix"))
        for code in (0, 1, 2, 5, 7):
            with self.subTest(code=code), self.assertRaises(AssertionError):
                validate_fault_refusal({"code": code}, "revoke", stopped, "posix")


if __name__ == "__main__":
    unittest.main()

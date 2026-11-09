"""日期：2026-11-09；旧Qt注释跳过曾被漏识别，必须通过独立回归后才用于核心验收。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from qt_test_evidence import inspect_qt_report


class QtEvidenceTests(unittest.TestCase):
    # 日期：2026-11-09；真实旧格式允许同一数据函数既有通过行又有注释跳过，不得看result=pass就授予资格。
    def test_legacy_skip_inside_passing_method(self):
        xml = b'''<testsuite tests="1" errors="1" failures="0">
        <testcase name="unsafeObjects" result="pass">
        <!-- tag="symbolic-link" message="unavailable" type="skip" -->
        </testcase></testsuite>'''
        log = b'Totals: 3 passed, 0 failed, 1 skipped, 0 blacklisted, 12ms\n'
        result = inspect_qt_report(xml, log)
        self.assertEqual(result['junitCases'], 1)
        self.assertEqual(result['passedRows'], 3)
        self.assertEqual(result['skips'], ['unsafeObjects'])
        self.assertFalse(result['passed'])

    # 日期：2026-11-09；标准JUnit跳过与旧格式采取相同规则，不能随Qt版本改变资格。
    def test_standard_skip(self):
        result = inspect_qt_report(
            b'<testsuite tests="1"><testcase name="native"><skipped/></testcase></testsuite>',
            b'Totals: 0 passed, 0 failed, 1 skipped, 0 blacklisted, 1ms\n')
        self.assertEqual(result['skippedRows'], 1)
        self.assertFalse(result['passed'])

    # 日期：2026-11-09；文本有跳过而XML丢失凭据时明确拒绝，不取其中较乐观的一份。
    def test_mismatched_reports_are_rejected(self):
        with self.assertRaises(ValueError):
            inspect_qt_report(
                b'<testsuite tests="1"><testcase name="native" result="pass"/></testsuite>',
                b'Totals: 0 passed, 0 failed, 1 skipped, 0 blacklisted, 1ms\n')

    # 日期：2026-11-09；失败/完整通过两种终态分别核对，实际数据行允许多于折叠后的方法条目。
    def test_failure_and_complete_pass(self):
        failed = inspect_qt_report(
            b'<testsuite tests="1"><testcase name="write"><failure/></testcase></testsuite>',
            b'Totals: 0 passed, 1 failed, 0 skipped, 0 blacklisted, 1ms\n')
        self.assertFalse(failed['passed'])
        passed = inspect_qt_report(
            b'<testsuite tests="1"><testcase name="write" result="pass"/></testsuite>',
            b'Totals: 5 passed, 0 failed, 0 skipped, 0 blacklisted, 1ms\n')
        self.assertTrue(passed['passed'])
        self.assertEqual(passed['passedRows'], 5)


if __name__ == '__main__':
    unittest.main()

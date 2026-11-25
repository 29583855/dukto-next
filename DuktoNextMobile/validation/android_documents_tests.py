"""日期：2026-11-26；验证系统记忆多级目录取消不会误关产品，也不会无限返回。"""
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from android_documents import cancel_picker


class PickerCancellationTests(unittest.TestCase):
    # 日期：2026-11-26；只构造系统实际返回的包标识，用于控制导航状态序列。
    def tree(self, package):
        return ET.fromstring('<hierarchy><node package="' + package + '" /></hierarchy>')

    # 日期：2026-11-26；两级记忆目录必须退回两次，看到产品后不能继续发送返回键。
    def test_remembered_subdirectory(self):
        picker = self.tree("com.google.android.documentsui")
        with patch("android_documents.ui_tree", side_effect=[picker, picker, self.tree("org.duktonext.mobile")]), \
                patch("android_documents.adb") as adb_call, patch("android_documents.time.sleep"):
            cancel_picker(None, "cancel")
        self.assertEqual(adb_call.call_count, 2)
        adb_call.assert_called_with("shell", "input", "keyevent", "KEYCODE_BACK")

    # 日期：2026-11-26；产品已经恢复时直接停止，避免关闭应用文件窗口。
    def test_product_already_restored(self):
        with patch("android_documents.ui_tree", return_value=self.tree("org.duktonext.mobile")), \
                patch("android_documents.adb") as adb_call:
            cancel_picker(None, "cancel")
        adb_call.assert_not_called()

    # 日期：2026-11-26；系统主页等未知结果不能当作选择器已正确取消。
    def test_unexpected_window_rejected(self):
        with patch("android_documents.ui_tree", return_value=self.tree("com.google.android.apps.nexuslauncher")), \
                patch("android_documents.adb") as adb_call:
            with self.assertRaisesRegex(RuntimeError, "未返回产品"):
                cancel_picker(None, "cancel")
        adb_call.assert_not_called()

    # 日期：2026-11-26；无响应选择器有界失败，保留现场，不循环发送返回键。
    def test_stuck_picker_is_bounded(self):
        with patch("android_documents.ui_tree", return_value=self.tree("com.google.android.documentsui")), \
                patch("android_documents.adb") as adb_call, patch("android_documents.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "有界返回次数"):
                cancel_picker(None, "cancel")
        self.assertEqual(adb_call.call_count, 10)


if __name__ == "__main__":
    unittest.main()

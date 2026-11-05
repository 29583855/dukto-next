"""日期：2026-11-05；验证卸载状态机的部分卸载/设备重分配边界；不替代原生APFS验收。"""

import importlib.util
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('cleanup', Path(__file__).resolve().parents[1] /
                                            'scripts/macos_disk_cleanup.py')
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    # 日期：2026-11-05；只建立测试私有普通文件，所有hdiutil调用均为明确的状态模拟。
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.image = self.root / 'dukto-test.dmg'
        self.image.write_bytes(b'test')
        self.mount = self.root / 'dukto-mount'
        self.mount.mkdir()

    # 日期：2026-11-05；生成与hdiutil一致的plist结构，可单独模拟已卸载但未退出的设备。
    def state(self, mounted=True, device='/dev/disk7', image=None):
        entities = [{'dev-entry': device}]
        if mounted:
            entities.append({'dev-entry': device + 's1', 'mount-point': str(self.mount)})
        return {'images': [{'image-path': str(image or self.image), 'system-entities': entities}]}

    # 日期：2026-11-05；每次info查询按序返回系统快照，记录全部detach目标以核对没有复用旧路径。
    def run_states(self, states, exits):
        iterator = iter(states)
        exit_iterator = iter(exits)
        mounted = [True]
        targets = []

        # 日期：2026-11-05；模拟命令输入输出，不执行宿主系统磁盘工具。
        def command(arguments, **kwargs):
            if arguments[1] == 'info':
                state = next(iterator)
                mounted[0] = any(entity.get('mount-point') for image in state['images']
                                 for entity in image['system-entities'])
                return subprocess.CompletedProcess(arguments, 0, plistlib.dumps(state), b'')
            self.assertEqual(arguments[:2], ['hdiutil', 'detach'])
            targets.append(arguments[2])
            return subprocess.CompletedProcess(arguments, next(exit_iterator), b'', b'busy')

        with patch.object(cleanup.subprocess, 'run', side_effect=command), \
                patch.object(Path, 'is_mount', side_effect=lambda: mounted[0]), \
                patch.object(cleanup.time, 'sleep'):
            result = cleanup.detach(self.mount, self.image)
        return result, targets

    # 日期：2026-11-05；复现Intel原失败：第一次部分卸载后路径消失，第二次必须使用当前设备并核对退出。
    def test_partial_unmount_retries_device(self):
        attached, unmounted = self.state(), self.state(False)
        result, targets = self.run_states([attached, unmounted, unmounted, {'images': []}], [16, 0])
        self.assertTrue(result['passed'])
        self.assertEqual(targets, ['/dev/disk7', '/dev/disk7'])
        self.assertEqual([item['exitCode'] for item in result['attempts']], [16, 0])

    # 日期：2026-11-05；命令非零后真实映射已退出仍需双重状态证据，不依靠No such file文本猜成功。
    def test_nonzero_requires_actual_absence(self):
        result, targets = self.run_states([self.state(), {'images': []}], [16])
        self.assertTrue(result['passed'])
        self.assertEqual(targets, ['/dev/disk7'])
        self.assertEqual(result['observations'][-1]['attached'], False)

    # 日期：2026-11-05；设备分配变化后仅操作新映射，不对旧设备重复退出。
    def test_reassigned_device_is_not_reused(self):
        first = self.state()
        second = self.state(False, '/dev/disk8')
        result, targets = self.run_states([first, second, second, {'images': []}], [16, 0])
        self.assertTrue(result['passed'])
        self.assertEqual(targets, ['/dev/disk7', '/dev/disk8'])

    # 日期：2026-11-05；detach返回0却仍挂载不能通过；八次用完保持失败。
    def test_success_exit_with_attached_image_is_failure(self):
        result, targets = self.run_states([self.state()] * 16, [0] * 8)
        self.assertFalse(result['passed'])
        self.assertEqual(len(targets), 8)

    # 日期：2026-11-05；别的镜像或不一致挂载不能被视为自有镜像已安全释放。
    def test_absent_image_but_mount_present_refused(self):
        with patch.object(cleanup.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 0, plistlib.dumps({'images': []}), b'')), patch.object(Path, 'is_mount', return_value=True):
            with self.assertRaises(AssertionError):
                cleanup.image_state(self.mount, self.image)

    # 日期：2026-11-05；首次归属检查必须同时匹配临时根、镜像和挂载点。
    def test_initial_ownership_required(self):
        with patch.object(cleanup.sys, 'platform', 'darwin'), \
                patch.object(cleanup, 'image_state', return_value={'attached': False, 'mountPoints': []}):
            with self.assertRaises(AssertionError):
                cleanup.owned_mount(self.mount, self.image, self.root)

    # 日期：2026-11-05；无法读取系统映射必须失败，不能以未观察到镜像当作清理成功。
    def test_info_failure_propagates(self):
        with patch.object(cleanup.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'hdiutil')):
            with self.assertRaises(subprocess.CalledProcessError):
                cleanup.detach(self.mount, self.image)


if __name__ == '__main__':
    unittest.main()

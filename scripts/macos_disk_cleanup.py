"""日期：2026-11-05；仅卸载本轮CI自建镜像，资源忙时有界重试并保留独立清理证据。"""

import argparse
import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time


# 日期：2026-11-05；每次重新查询真实镜像映射，输出仅包含本轮镜像的设备与挂载点。
def image_state(mount, image, timeout=5):
    result = subprocess.run(['hdiutil', 'info', '-plist'], capture_output=True,
                            timeout=timeout, check=True)
    images = plistlib.loads(result.stdout).get('images', [])
    matches = [record for record in images if Path(record.get('image-path', '/')).resolve() == image]
    assert len(matches) <= 1, 'The expected test image is not uniquely attached'
    if not matches:
        assert not mount.is_mount(), 'The mount remains but the owned image is absent'
        return {'attached': False, 'devices': [], 'mountPoints': []}
    entities = matches[0].get('system-entities', [])
    points = [Path(entity['mount-point']).resolve()
              for entity in entities if entity.get('mount-point')]
    assert points in ([], [mount]), 'The image has an unexpected mount point'
    assert bool(points) == mount.is_mount(), 'Image mapping and mount state disagree'
    devices = [entity['dev-entry'] for entity in entities if entity.get('dev-entry')]
    assert devices and len(devices) == len(set(devices))
    assert all(re.fullmatch(r'/dev/disk[0-9]+(?:s[0-9]+)*', device) for device in devices)
    # 日期：2026-11-05；优先整盘设备；路径已卸载时仍可对当前属于自建镜像的设备正常退出。
    devices.sort(key=lambda device: (bool(re.search(r's[0-9]+$', device)), device))
    return {'attached': True, 'devices': devices, 'mountPoints': [str(point) for point in points]}


# 日期：2026-11-05；首次操作要求镜像与挂载同时归属临时根，不允许已有系统卷参与重试。
def owned_mount(mount, image, root):
    assert sys.platform == 'darwin', 'APFS cleanup requires a native macOS runner'
    assert root.is_dir() and mount.is_relative_to(root) and image.is_relative_to(root)
    assert mount != root and image.is_file() and image.suffix == '.dmg'
    assert mount.name.startswith('dukto-') and image.name.startswith('dukto-')
    state = image_state(mount, image)
    assert state['attached'] and state['mountPoints'] == [str(mount)]
    return state


# 日期：2026-11-05；最多20秒/8次普通设备退出；每次用刚核对的映射，避免复用已消失路径或重分配设备。
def detach(mount, image):
    started = time.monotonic()
    deadline = started + 20
    attempts = []
    observations = []
    for number in range(1, 9):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        state = image_state(mount, image, min(5, remaining))
        observations.append(state)
        if not state['attached']:
            return {'passed': True, 'attempts': attempts, 'observations': observations,
                    'completion': 'owned image absent and mount released',
                    'elapsedSeconds': round(time.monotonic() - started, 3)}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        device = state['devices'][0]
        try:
            result = subprocess.run(['hdiutil', 'detach', device], capture_output=True,
                                    timeout=min(5, remaining))
            attempts.append({'attempt': number, 'device': device, 'exitCode': result.returncode,
                             'stdout': result.stdout.decode('utf-8', 'replace')[-2048:],
                             'stderr': result.stderr.decode('utf-8', 'replace')[-2048:]})
        except subprocess.TimeoutExpired:
            attempts.append({'attempt': number, 'device': device, 'timedOut': True})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        state = image_state(mount, image, min(5, remaining))
        observations.append(state)
        if not state['attached']:
            return {'passed': True, 'attempts': attempts, 'observations': observations,
                    'completion': 'owned image absent and mount released',
                    'elapsedSeconds': round(time.monotonic() - started, 3)}
        remaining = deadline - time.monotonic()
        if remaining > 0 and number < 8:
            time.sleep(min(0.5 * number, remaining))
    return {'passed': False, 'attempts': attempts, 'observations': observations,
            'elapsedSeconds': round(time.monotonic() - started, 3)}


# 日期：2026-11-05；清理结果单独归档；调用者负责保留业务非零退出码，不能用清理成功覆盖业务失败。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mount', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    assert not args.report.exists(), 'A prior cleanup report must not be replaced'
    value = {'date': '2026-11-05', 'passed': False, 'scope': 'owned temporary APFS image cleanup',
             'forced': False, 'budgetSeconds': 20, 'maximumAttempts': 8}
    try:
        mount, image, root = args.mount.resolve(), args.image.resolve(), args.root.resolve()
        owned_mount(mount, image, root)
        value.update(ownershipVerified=True, mount=str(mount), image=str(image))
        value.update(detach(mount, image))
    except Exception as error:
        value.update(error=type(error).__name__, message=str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

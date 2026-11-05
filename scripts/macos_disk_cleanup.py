"""日期：2026-11-05；仅卸载本轮CI自建镜像，资源忙时有界重试并保留独立清理证据。"""

import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import time


# 日期：2026-11-05；卸载前同时核对自建镜像与挂载点归属，拒绝系统卷或其它测试镜像。
def owned_mount(mount, image, root):
    assert sys.platform == 'darwin', 'APFS cleanup requires a native macOS runner'
    assert root.is_dir() and mount.is_relative_to(root) and image.is_relative_to(root)
    assert mount != root and image.is_file() and image.suffix == '.dmg'
    assert mount.name.startswith('dukto-') and image.name.startswith('dukto-')
    result = subprocess.run(['hdiutil', 'info', '-plist'], capture_output=True, timeout=5, check=True)
    images = plistlib.loads(result.stdout).get('images', [])
    matches = [record for record in images if Path(record.get('image-path', '/')).resolve() == image]
    assert len(matches) == 1, 'The expected test image is not uniquely attached'
    points = [Path(entity['mount-point']).resolve()
              for entity in matches[0].get('system-entities', []) if entity.get('mount-point')]
    assert points == [mount] and mount.is_mount(), 'The mount belongs to another image'


# 日期：2026-11-05；总计最多20秒/8次普通卸载；不强制、不终止系统进程，失败仍为失败。
def detach(mount):
    started = time.monotonic()
    deadline = started + 20
    attempts = []
    for number in range(1, 9):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = subprocess.run(['hdiutil', 'detach', str(mount)], capture_output=True,
                                    timeout=min(5, remaining))
            attempts.append({'attempt': number, 'exitCode': result.returncode,
                             'stdout': result.stdout.decode('utf-8', 'replace')[-2048:],
                             'stderr': result.stderr.decode('utf-8', 'replace')[-2048:]})
            if result.returncode == 0:
                assert not mount.is_mount(), 'hdiutil succeeded but the test volume is still mounted'
                return {'passed': True, 'attempts': attempts,
                        'elapsedSeconds': round(time.monotonic() - started, 3)}
        except subprocess.TimeoutExpired:
            attempts.append({'attempt': number, 'timedOut': True})
        remaining = deadline - time.monotonic()
        if remaining > 0 and number < 8:
            time.sleep(min(0.5 * number, remaining))
    return {'passed': False, 'attempts': attempts,
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
        value.update(detach(mount))
    except Exception as error:
        value.update(error=type(error).__name__, message=str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False))
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

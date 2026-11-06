"""日期：2026-11-07；复用固定独立慢读协议，对原版发送中止及下一任务保存全新原件。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy


# 日期：2026-11-07；只使用已生成的128MiB与58字节测试输入，所有新结果进入独立目录。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('receive', 'recovery'))
    args = parser.parse_args()
    source = Path('docs/validation/2026-11-07/original-r6-cancel/send-peer-original-driver.py')
    output = Path('docs/validation/2026-11-07/original-r6-send-abort-retry').resolve()
    inputs = Path('.cache/original-r6-cancel-20261107')
    manifest_path = Path('docs/validation/2026-11-07/original-r6-cancel/input-manifest.json')
    manifest = json.loads(manifest_path.read_text('utf-8'))
    for name, size, expected in ((manifest['fileName'], manifest['bytes'], manifest['sha256']),
                                 (manifest['recoveryFileName'], manifest['recoveryBytes'], manifest['recoverySha256'])):
        path = inputs / name
        assert path.stat().st_size == size
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        assert digest.hexdigest() == expected
    output.mkdir(parents=True, exist_ok=True)
    copied = output / 'fixed-peer-source.py'
    if copied.exists():
        assert copied.read_bytes() == source.read_bytes()
    else:
        copied.write_bytes(source.read_bytes())
    module = runpy.run_path(str(source))
    function = module[args.mode]
    function.__globals__['OUTPUT'] = output
    function()


if __name__ == '__main__':
    main()

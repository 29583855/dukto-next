"""日期：2026-11-06；对R94双Mac实际包执行全部载荷、精确源码、原生导航和业务原件核验。"""
import json
from pathlib import Path


# 日期：2026-11-06；绑定已派发的精确提交和全新目录，沿用全部断言，拒绝混用旧包结果。
def main():
    dispatch = json.loads(Path('.cache/r94-run-dispatch.json').read_text('utf-8'))
    run, = [row for row in dispatch['runs'] if row['name'] == 'Native macOS deployed preview packages']
    assert dispatch['sourceCommit'] == 'dec40621cce2d223e46b343e0d3d345a67b80523'
    assert run['head_sha'] == dispatch['sourceCommit']
    source = Path('.cache/verify-client-accounting-r82-packages.py').read_text('utf-8')
    replacements = {
        '8e9077854085a842261abf2b030a83d945545822': dispatch['sourceCommit'],
        '42170433020': str(run['id']),
        'client-accounting-r82-macos-package-terminal': 'text-view-r94-macos-package-terminal',
        'macos-preview-20261106-r82-client-accounting': 'macos-preview-20261106-r94-text-view',
        'client-accounting-r82-package-downloads': 'text-view-r94-package-downloads',
    }
    for before, after in replacements.items():
        assert before in source
        source = source.replace(before, after)
    scope = {'__name__': 'text_view_r94_packages'}
    exec(compile(source, 'text_view_r94_packages', 'exec'), scope)
    scope['main']()


if __name__ == '__main__':
    main()

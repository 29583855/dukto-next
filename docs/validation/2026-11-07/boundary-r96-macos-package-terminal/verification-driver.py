"""日期：2026-11-07；核验精确R96双Mac包全部载荷、源码、Cocoa导航与迁移业务原件。"""
from pathlib import Path


# 日期：2026-11-07；仅绑定本轮提交和新目录，所有原始载荷/链接/架构/依赖与业务断言继续执行。
def main():
    source = Path('.cache/verify-client-history-r80-packages.py').read_text('utf-8')
    mapping = {
        '9ac5ca7a18874a52207bedd7cb440c4867a5bcdf': '88f33b2c83f2950307c362fb64c693f7e9e5929d',
        '42162374097': '42253077233',
        'docs/validation/2026-11-06/client-history-r80-macos-package-terminal': 'docs/validation/2026-11-07/boundary-r96-macos-package-terminal',
        'macos-preview-20261106-r80-client-history': 'macos-preview-20261107-r96-boundary',
        'client-history-r80-package-downloads': 'boundary-r96-package-downloads',
    }
    for old, new in mapping.items():
        assert old in source
        source = source.replace(old, new)
    before = '        proof = payload_proof(payload, architecture)'
    assert source.count(before) == 1
    source = source.replace(before, before + '''
        runtime_parent = json.loads(files['build/package-runtime.json'])
        assert runtime_parent['archiveSha256'] == digest(payload)
        assert runtime_parent['verifiedFiles'] == proof['verifiedPayloadFiles']
        assert runtime_parent['verifiedLinks'] == proof['verifiedLinks'] == 71
        navigation = json.loads(files['build/main-window-navigation.json'])
        assert navigation['sourceCommit'] == COMMIT and navigation['nativePlatform'] == 'cocoa'
        assert navigation['binaryUnchanged']
        assert {case['name'] for case in navigation['cases']} == {'native', 'offscreen-150', 'offscreen-200'}
        for case in navigation['cases']:
            assert case['passed'] and case['exitCode'] == 0 and len(case['frames']) == 2
            for frame in case['frames']:
                assert frame['chineseGlyphCoverage']['passed'] and frame['chineseGlyphCoverage']['missingGlyphs'] == 0
                size = 'x'.join(str(n) for n in frame['requestedSize'])
                picture = 'build/main-window-navigation/' + case['name'] + '/Testing/QtTest/main-server-' + size + '.png'
                assert digest(files[picture]) == frame['pngSha256']''')
    scope = {'__name__': 'boundary_r96_packages'}
    exec(compile(source, 'boundary_r96_packages', 'exec'), scope)
    scope['main']()


if __name__ == '__main__':
    main()

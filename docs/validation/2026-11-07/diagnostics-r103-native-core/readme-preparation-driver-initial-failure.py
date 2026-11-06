"""日期：2026-11-07；使项目入口同步最新已验源码和旧部署包身份，不改构建输入。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；沿用原编码/BOM/换行，补充显式清单并拒绝重复应用，扫描秘密不打印正文。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == 'cd92c43f301e5a60584b7896a450247855f0bdfd'
    update = runpy.run_path('.cache/finalize-skip-items-r84.py')['update']
    # 日期：2026-11-07；最新编译和核心子项与含依赖旧包保持各自明确来源及资格。
    def readme(text):
        assert '最新R103源码cd92c43' not in text
        start = text.index('公开仓库为')
        end = text.index('\n\n', start)
        replacement = '公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。最新R103源码cd92c43的双Mac GUI/独立CLI编译及四原生各23核心/88份Qt原报告已验，新增本地诊断/原子导出核心和GUI方法通过；完整协议与真实CLI诊断原生专项继续。[最新Mac编译产物](docs/macOS独立预览包.md)。含依赖部署包仍为R100精确ed4f5cf：[Windows](docs/Windows独立预览包.md)、[macOS Apple Silicon/Intel](docs/macOS独立预览包.md)、[Linux](docs/Linux独立预览包.md)，均含GUI/独立CLI；其四平台188协议已验，两条精确Darwin端口共享XFAIL披露。真实长期、完整GUI/选择器、物理网络及正式交付继续，见[计划](开发计划与进度.md)和[当前索引](docs/current-validation.json)。'
        return text[:start] + replacement + text[end:]
    update(root / 'README.md', readme)
    public = root / 'docs/validation/2026-11-07/diagnostics-r103-native-core/readme-preparation-driver.py'
    shutil.copyfile(Path(__file__), public)
    manifest = root / '.cache/r103-native-evidence-publish-files.json'
    names = set(json.loads(manifest.read_text('utf-8')))
    names.update(('README.md', public.relative_to(root).as_posix()))
    names = sorted(names)
    for name in names:
        raw = (root / name).read_bytes()
        assert b'-----BEGIN PRIVATE KEY-----' not in raw and b'-----BEGIN RSA PRIVATE KEY-----' not in raw
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    manifest.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r103-native-evidence-stage.nul').write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    inputs = json.loads((root / 'docs/ci-verification-20261107-r103.json').read_text('utf-8'))['buildInputs']
    assert len(inputs) == 213
    for row in inputs:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    print(json.dumps({'explicitFiles': len(names), 'buildInputsUnchanged': 213, 'readmeUpdated': True}))


if __name__ == '__main__':
    main()

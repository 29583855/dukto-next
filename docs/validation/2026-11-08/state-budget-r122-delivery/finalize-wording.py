"""日期：2026-11-08；将R122先前阶段的待办描述更新为当前真实剩余项，避免同页下载版本冲突。"""
from pathlib import Path
import runpy
import shutil


# 日期：2026-11-08；只改当前版本的旧待办说明，保留历史失败与独立Ubuntu/完整协议待验范围。
def main():
    root = Path.cwd()
    update = runpy.run_path(str(root / '.cache/publish-r121-source.py'))['update_document']
    old = '独立Ubuntu和新四原生底层专项/完整回归/双Mac包须按真实原件收验；当前Mac含依赖包保持已验R121。'
    new = '四原生底层专项、四平台完整核心和双Mac包已验；独立Ubuntu构建及R122完整协议终态继续收验。'
    for name in ['开发计划与进度.md', 'docs/执行进度.md']:
        update(name, lambda text: text.replace(old, new, 1))
    update('README.md', lambda text: text.replace('生产预算接入和新原生验证继续。双Mac可用含依赖包保持已验R121；',
           '四原生底层和完整核心已验，生产预算接入继续。双Mac可用含依赖包已更新R122；', 1))
    for base in [root, root / '.cache/github-29583855-dukto-next-r28']:
        shutil.copyfile(Path(__file__), base / 'docs/validation/2026-11-08/state-budget-r122-delivery/finalize-wording.py')


if __name__ == '__main__':
    main()

"""日期：2026-11-08；区分当前下载和历次观察，避免旧进度文字仍指向R124。"""
from pathlib import Path
import runpy
import shutil


# 日期：2026-11-08；使用原有字节保持写回器，只修改本轮说明，不删除历史失败或验证记录。
def main():
    root = Path.cwd()
    update = runpy.run_path(str(root / '.cache/publish-r121-source.py'))['update_document']
    old = ('R125新增持久额度配置及state budget/root CLI，双Windows各33核心/32份Qt XML和16条配置专项通过。'
           '新四原生与双Mac继续，当前可下载Mac包仍为R124；生产总预算、迁移与自动GC未完成。')
    new = ('R125新增持久额度配置及state budget/root CLI，本机及四平台验证、双Mac含依赖包已按上文收验。'
           '生产总预算、迁移与自动GC未完成。')
    assert (root / 'README.md').read_text('utf-8').count(old) == 1
    update('README.md', lambda text: text.replace(old, new, 1).replace(
        '\n\nR124精确424c78b7',
        '\n\n以下为历次验证记录，状态按当时观察保留；当前下载使用上方R125入口。\n\nR124精确424c78b7', 1))
    update('docs/macOS独立预览包.md', lambda text: text.replace(
        '\n\nR124精确424c78b7', '\n\n历史记录：R124精确424c78b7', 1))
    execution = root / '.cache/github-29583855-dukto-next-r28/docs/validation/2026-11-08/budget-configuration-r125-delivery'
    shutil.copyfile(Path(__file__), execution / 'refine-current-documentation.py')
    shutil.copyfile(Path(__file__), root / execution.relative_to(root / '.cache/github-29583855-dukto-next-r28') / 'refine-current-documentation.py')
    print('Current R125 links clarified; historical observations retained.')


if __name__ == '__main__':
    main()

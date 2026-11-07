"""日期：2026-11-08；只读汇总实际状态创建入口，避免用设计文档代替代码位置核对。"""
from pathlib import Path


# 日期：2026-11-08；输出匹配行及少量上下文，检视范围限本项目维护源码。
def main():
    keys = ['QTemporary', 'tempPath()', '.sqlite', 'stateDirectory', 'PrivateStore(', 'PrivateStore ']
    for path in sorted(Path('src').rglob('*.cpp')):
        lines = path.read_text('utf-8-sig').splitlines()
        hits = {j for index, line in enumerate(lines) if any(key in line for key in keys)
                for j in range(max(0, index - 1), min(len(lines), index + 3))}
        if hits:
            print('\nFILE ' + path.as_posix())
            print('\n'.join(str(index + 1) + ':' + lines[index] for index in sorted(hits)))


if __name__ == '__main__':
    main()

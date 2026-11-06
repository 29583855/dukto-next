"""日期：2026-11-07；准备精确Git源码打包副本，防止持续更新的进度文档改变包内来源。"""
import hashlib
import json
from pathlib import Path
import subprocess


# 日期：2026-11-07；只复制对应源码集合，所有字节来自固定Git对象，不复制凭据或测试运行数据。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    commit = 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
    destination = root / '.cache/windows-r98-package-source'
    assert not destination.exists()
    top = {'CMakeLists.txt', '.clang-format', 'LICENSE', 'README.md', '开发计划与进度.md'}
    folders = {'src', 'ui', 'resources', 'scripts', 'tests', '.github', 'docs'}
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '-z', commit], cwd=checkout)
    records = []
    for encoded in names.split(b'\0'):
        if not encoded:
            continue
        name = encoded.decode('utf-8')
        parts = Path(name).parts
        if name not in top and not (parts[0] in folders and 'validation' not in parts and '__pycache__' not in parts):
            continue
        raw = subprocess.check_output(['git', 'show', commit + ':' + name], cwd=checkout)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        assert target.read_bytes() == raw
        records.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest()})
    inputs = json.loads((root / 'docs/ci-verification-20261107-r98.json').read_text('utf-8'))['buildInputs']
    assert len(inputs) == 210
    for row in inputs:
        assert hashlib.sha256((destination / row['path']).read_bytes()).hexdigest() == row['sha256']
        assert (destination / row['path']).read_bytes() == (root / row['path']).read_bytes()
    value = {'sourceCommit': commit, 'sourceFiles': records, 'buildInputsVerified': 210,
             'allSourceFilesFromExactGitBlobs': True, 'sourceRoot': str(destination),
             'releaseQualified': False, 'deliveryComplete': False}
    output = root / '.cache/windows-r98-package-source.json'
    assert not output.exists()
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'sourceCommit': commit, 'sourceFiles': len(records), 'buildInputsVerified': 210}), flush=True)


if __name__ == '__main__':
    main()

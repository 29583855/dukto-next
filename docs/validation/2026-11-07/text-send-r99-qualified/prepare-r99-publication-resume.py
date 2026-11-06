"""日期：2026-11-07；保留首次文档保存失败，从已通过回执继续生成待发布材料。"""
import json
from pathlib import Path


# 日期：2026-11-07；只修正新建文档的保存方式，不重新执行收验、不覆盖原始脚本或结果。
def main():
    root = Path.cwd()
    source = (root / '.cache/verify-and-record-text-send-r99.py').read_text('utf-8')
    assert source.count('    public = {') == 1
    prefix = source[:source.index('# 日期：2026-11-07；只有完整初轮')]
    body = source[source.index('    public = {'):source.index('\n\nif __name__')]
    old = "    helper['save'](root / 'docs/ci-verification-20261107-r99.json', public)"
    assert body.count(old) == 1
    body = body.replace(old, """    public_path = root / 'docs/ci-verification-20261107-r99.json'
    assert not public_path.exists()
    public_path.write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\\n', 'utf-8')""")
    setup = """# 日期：2026-11-07；资格已验，仅从首次新文件保存失败处继续，不重复写入原件或资格回执。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    first = root / 'docs/validation/2026-11-07/text-send-r99-windows'
    final = root / 'docs/validation/2026-11-07/text-send-r99-final-windows'
    output = root / 'docs/validation/2026-11-07/text-send-r99-qualified'
    receipt = output / 'verified-receipt.json'
    value = json.loads(receipt.read_text('utf-8'))
    assert value['passed']
    inputs = value['buildInputs']
    changed = value['changedBuildInputs']
"""
    path = root / '.cache/resume-record-text-send-r99.py'
    assert not path.exists()
    content = prefix + setup + body + "\n\nif __name__ == '__main__':\n    main()\n"
    compile(content, str(path), 'exec')
    path.write_text(content, 'utf-8')
    output = root / 'docs/validation/2026-11-07/text-send-r99-qualified'
    failure = {'date': '2026-11-07', 'type': 'FileNotFoundError',
               'at': 'creation of docs/ci-verification-20261107-r99.json with update-existing helper',
               'qualificationAlreadyPassed': True, 'sourceTestsRerun': False,
               'resumeFromPublicationOnly': True,
               'firstRecoveryCommandShellParsingFailedBeforeExecution': True}
    (output / 'publication-preparation-failure.json').write_text(json.dumps(failure, indent=2) + '\n', 'utf-8')
    print('Prepared publication-only recovery; original qualification and failures retained')


if __name__ == '__main__':
    main()

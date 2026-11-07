"""日期：2026-11-08；以精确本机原件冻结原生占用接口，保留历史失败和未完成整体范围。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = REPO / 'docs/validation/2026-11-08'


# 日期：2026-11-08；按原字节计算固定输入，不将路径或时间戳当作源码一致性证明。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-08；新增证据使用UTF-8，原文档仍保留编码、BOM及换行。
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


# 日期：2026-11-08；唯一确定的当前状态修改才落盘，不改历史失败原件。
def edit(name, callback):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    old = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    text = callback(old)
    assert text != old, name
    path.write_bytes(bom + text.replace('\n', newline).encode('utf-8'))
    shutil.copyfile(path, REPO / name)


# 日期：2026-11-08；完整核心、真实新专项及原归档逐件验收后更新计划与源码清单。
def main():
    local = BASE / 'sqlite-file-info-r120-local'
    assert not local.exists()
    audit = json.loads((ROOT / '.cache/r120-qualified-source-audit.json').read_bytes())
    assert audit['sourceMarkersPassed'] and not audit['findings'] and audit['formatting']['passed']
    assert audit['cxx14Configuration']
    qt = runpy.run_path(str(ROOT / '.cache/collect-r118-native-core.py'))['qt']
    records = []
    for tag in ['msvc', 'ucrt']:
        original = ROOT / ('.cache/r120-qualified-' + tag)
        receipt = json.loads((original / 'receipt.json').read_bytes())
        assert receipt['passed'] and receipt['buildExitCode'] == receipt['ctestExitCode'] == 0
        assert receipt['inputs'] == receipt['inputsAfter'] and receipt['binariesBefore'] == receipt['binariesAfter']
        for name, digest in receipt['inputs'].items():
            assert sha(ROOT / name) == digest, name
        log = (original / 'ctest.log').read_text('utf-8-sig')
        assert re.search(r'100% tests passed(?:, 0 tests failed)? out of 30', log)
        xmls = sorted((original / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 29, len(xmls)
        reports = [qt(path, 'windows-2022') for path in xmls]
        text = (original / 'Testing/QtTest/sqlite-file-info-tests.log').read_text('utf-8-sig')
        assert 'Totals: 11 passed, 0 failed, 0 skipped' in text
        assert 'missing initializer' not in (original / 'build.log').read_text('utf-8-sig')
        shutil.copytree(original, local / tag)
        records.append({'toolchain': tag, 'completeCoreCtestsPassed': 30, 'qtXmlOriginalsVerified': 29,
                        'fileInfoRowsPassed': 11, 'fileInfoSkipped': 0, 'xmlResults': reports})
    # 日期：2026-11-08；保留早期检查及输入变化造成的非资格结果，不将它们重写为最终成功。
    for folder in ['r120-msvc', 'r120-ucrt', 'r120-final-msvc', 'r120-final-ucrt']:
        source = ROOT / '.cache' / folder
        for name in ['receipt.json', 'build.log', 'ctest.log']:
            target = local / 'preliminary-inputs' / folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
    names = ['r120-qualified-source-audit.json', 'r120-source-snapshot-contract.json',
             'r120-frozen-long-observation.json', 'validate-r120-qualified-windows.py']
    for name in names:
        shutil.copyfile(ROOT / '.cache' / name, local / name)
    archive_receipt = json.loads((ROOT / '.cache/r120-qualified-source-archives/receipt.json').read_bytes())
    assert archive_receipt['allRequiredBytesPreserved'] and archive_receipt['upstreamBytesPreserved']
    shutil.copyfile(ROOT / '.cache/r120-qualified-source-archives/receipt.json', local / 'source-archives-before-final-docs.json')
    snapshot = json.loads((ROOT / '.cache/r120-source-snapshot-contract.json').read_bytes())
    assert snapshot['passed']
    baseline = json.loads((REPO / 'docs/ci-verification-20261107-r119.json').read_bytes())
    old = {row['path']: row['sha256'] for row in baseline['qualificationInputs']}
    names = set(old) | {'src/core/sqliteplatform.c', 'src/core/sqlitefileinfo.h',
                        'tests/sqlite_file_info_tests.cpp', 'scripts/ci_sqlite_file_info.py',
                        '.github/workflows/sqlite-file-info-regression.yml'}
    changed, frozen, encoding = [], [], []
    for name in sorted(names):
        raw = (ROOT / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if old.get(name) != digest:
            changed.append(name)
            if name in old:
                original = subprocess.check_output(['git', 'show', baseline['sourceCommit'] + ':' + name], cwd=REPO)
                assert raw.startswith(b'\xef\xbb\xbf') == original.startswith(b'\xef\xbb\xbf')
                assert (b'\r\n' in raw) == (b'\r\n' in original)
            encoding.append({'path': name, 'encoding': 'UTF-8', 'bom': raw.startswith(b'\xef\xbb\xbf'),
                             'lineEnding': 'CRLF' if b'\r\n' in raw else 'LF'})
            target = REPO / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        assert (REPO / name).read_bytes() == raw
        frozen.append({'path': name, 'bytes': len(raw), 'sha256': digest})
    assert len(frozen) == 266
    assert set(changed) == {'CMakeLists.txt', 'src/core/sqlitevfs.cpp', 'src/core/sqlitevfs.h',
                            'src/core/sqliteplatform.c', 'src/core/sqlitefileinfo.h',
                            'tests/sqlite_file_info_tests.cpp', 'scripts/audit.py',
                            'scripts/ci_sqlite_file_info.py', '.github/workflows/sqlite-file-info-regression.yml'}
    info = ROOT / 'docs/SQLite原生占用观察.md'
    raw = info.read_bytes()
    text = raw.decode('utf-8').replace('完整本机及跨平台验证进行中，跨进程预算账本和总配额仍待实施。',
                                     '双Windows各30完整核心、29份Qt原件及新专项各11条全通过；跨平台验证继续，跨进程预算账本和总配额仍待实施。', 1)
    assert text.encode('utf-8') != raw
    info.write_bytes(text.encode('utf-8'))
    shutil.copyfile(info, REPO / info.relative_to(ROOT))
    section = '''## R120 SQLite原生文件身份与占用观察（2026-11-08）

- [x] 固定SQLite同单元适配直接查询已打开文件及WAL共享句柄；POSIX设备/inode与Windows卷/128位ID、64位逻辑长度/系统分配量/链接计数分别返回，不按路径重开或猜测结构偏移。[接口与边界](docs/SQLite原生占用观察.md)。
- [x] 策略在打开完成、写入/截断/大小提示及映射后重查实际占用，失败也不按返回码清零；关闭仅保留关闭前观察，无句柄不证明磁盘对象消失。POSIX共享页分组与u16/native-int边界在原生扩展前核验，拒绝时映射指针归空。
- [x] 双Windows MSVC/UCRT各30完整CTest、29份Qt XML通过，新专项各11条全通过：硬链接/双连接、匿名临时对象、路径换代、超过4GiB稀疏文件、真实底层写入失败、共享文件与实际SQL的journal/WAL/排序溢写。首轮与中间输入原件保留，最终输入及程序前后SHA一致。[本机原件](docs/validation/2026-11-08/sqlite-file-info-r120-local/receipt.json)。
- [x] 230份维护文件含新增C适配的遗留标记/C++14/全量格式审计通过；266份资格输入冻结，上游原件不变，源码快照契约及归档包含新适配。
- [ ] 精确源码公开、四原生完整核心/文件专项、当前实际CLI专项及新双Mac部署包按各自原件继续；当前已验Mac包仍R119，不能继承新产品输入资格。
- [ ] Q02整体与Q03–Q08仍未完成：当前只是原生观察，生产quotaEnforced=false；实际总预算、跨进程账本、原子替换/正文、幂等分类及自动GC继续。完整R6/GUI、物理LAN/3×3、当前各平台24h、最低干净系统、依赖源码重建与正式分发继续。

'''
    def plan(text):
        assert '## R120 ' not in text
        text = text.replace('文档版本：v0.119', '文档版本：v0.120', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R120原生SQLite文件身份/占用观察已通过双Windows各30完整核心及专项11条；266份输入冻结，准备公开和四原生验证。真实总预算/跨进程账本及自动GC继续，已验Mac包仍R119，整体保持未完成。', text, count=1, flags=re.M)
        text = text.replace('v0.119 / SQLite写入前策略基础', 'v0.120 / SQLite原生占用观察基础', 1)
        return text.replace('## R119 固定SQLite运行时与连接VFS', section + '## R119 固定SQLite运行时与连接VFS', 1)
    edit('开发计划与进度.md', plan)
    edit('docs/执行进度.md', lambda text: text.replace('## R119 固定SQLite运行时与连接VFS',
         '## R120 SQLite原生文件身份与占用观察（2026-11-08）\n\n双Windows各30完整CTest/29份Qt XML和新专项各11条全通过。固定上游SQLite同单元适配读取实际主库/旁路/匿名临时/共享句柄，返回原生身份、长度及分配量；失败后的实际占用与关闭前观察明确区分。230份维护文件零遗留标记、C++14/格式与原编码通过，266份输入冻结。四原生/当前CLI及新Mac部署继续，已验Mac包仍R119。生产总预算/跨进程账本与GC未完成。[设计](SQLite原生占用观察.md)、[原件](ci-verification-20261108-r120.json)。\n\n## R119 固定SQLite运行时与连接VFS', 1))
    edit('README.md', lambda text: text.replace('\n\nR119最终夹具',
         '\n\nR120新增固定SQLite原生文件身份/占用观察；双Windows各30核心及专项11条全通过，真实硬链接、匿名临时、超过4GiB稀疏文件、失败后占用和journal/WAL/排序已验。四原生和新Mac包继续，已验Mac下载仍R119；总预算与自动GC未完成。[接口](docs/SQLite原生占用观察.md)、[证据](docs/ci-verification-20261108-r120.json)。\n\nR119最终夹具', 1))
    edit('docs/磁盘总配额实施清单.md', lambda text: text.replace('更新日期：2026-11-07。', '更新日期：2026-11-08。', 1).replace('SQLite运行时/VFS子项已验；实际预算、原子替换和平台分配对账待完成', 'SQLite运行时/VFS及双Windows原生身份/分配量观察已验；跨平台、实际预算、原子替换及完整分配对账待完成', 1) + '\nR120读取固定SQLite实际打开对象的原生身份、逻辑长度及系统分配量，失败后重新观察、匿名文件和共享文件亦覆盖；双Windows新专项各11条通过。[接口](SQLite原生占用观察.md)。此观察不能代替跨进程持久预算，Q02整体仍未完成。\n')
    edit('docs/跨进程磁盘预算设计.md', lambda text: text.replace('状态：待实现。', '状态：分步实施，整体未完成。', 1) + '\nR120已实现第一步的SQLite原生句柄观察和共享文件扩展范围检查，双Windows完整核心及专项已验；实际账本/锁协调和跨平台验证继续。[接口与限制](SQLite原生占用观察.md)。\n')
    write(local / 'receipt.json', {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': True,
          'records': records, 'qualificationInputs': frozen, 'changedInputs': changed,
          'inputCount': len(frozen), 'changedEncoding': encoding, 'allExistingEncodingPreserved': True,
          'upstreamOriginalBytesPreserved': True, 'preliminaryInputsKeptSeparate': True,
          'globalQuotaEnforced': False, 'automaticGcImplemented': False,
          'deliveryComplete': False, 'releaseQualified': False})
    shutil.copyfile(Path(__file__), local / 'preparation-driver.py')
    index = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'planVersion': 'v0.120',
             'baselineSourceCommit': baseline['sourceCommit'], 'qualificationInputs': frozen,
             'inputCount': len(frozen), 'changedInputs': changed, 'localWindowsAllCoreQualified': True,
             'receipts': [{'path': path.relative_to(REPO).as_posix(), 'sha256': sha(path)}
                          for path in [local / 'receipt.json', local / 'r120-qualified-source-audit.json',
                                       local / 'r120-source-snapshot-contract.json', local / 'r120-frozen-long-observation.json']],
             'sourcePublicationPending': True, 'nativeQualificationPending': True,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False}
    write(REPO / 'docs/ci-verification-20261108-r120.json', index)
    shutil.copyfile(REPO / 'docs/ci-verification-20261108-r120.json', ROOT / 'docs/ci-verification-20261108-r120.json')
    shutil.copytree(local, ROOT / local.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({'inputCount': len(frozen), 'changedInputCount': len(changed), 'coreCtestsEach': 30,
                      'newFileInfoRowsEach': 11, 'publicationPending': True}), flush=True)


if __name__ == '__main__':
    main()

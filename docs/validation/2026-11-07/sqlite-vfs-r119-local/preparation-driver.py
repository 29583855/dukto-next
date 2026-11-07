"""日期：2026-11-07；冻结固定SQLite与连接VFS输入，按双Windows原件记录Q02子项而非总配额。"""
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
BASE = REPO / 'docs/validation/2026-11-07'


# 日期：2026-11-07；新JSON按UTF-8写入，已有文档的编码/BOM/换行保持。
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


# 日期：2026-11-07；文档内容只补充有原件的完成范围，原有历史资格和失败不覆盖。
def edit(name, callback):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    old = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    new = callback(old)
    assert new != old, name
    path.write_bytes(bom + new.replace('\n', newline).encode('utf-8'))
    shutil.copyfile(path, REPO / name)


# 日期：2026-11-07；全部测试XML逐项核对，生产及第三方输入按原字节同步到指定公开副本。
def main():
    local = BASE / 'sqlite-vfs-r119-local'
    assert not local.exists()
    audit = json.loads((ROOT / '.cache/r119-source-audit.json').read_bytes())
    assert len(audit['files']) == 226 and not audit['findings'] and audit['formatting']['passed'] and audit['cxx14Configuration']
    qt = runpy.run_path(str(ROOT / '.cache/collect-r118-native-core.py'))['qt']
    records = []
    for tag in ['msvc', 'ucrt']:
        original = ROOT / ('.cache/r119-' + tag)
        receipt = json.loads((original / 'receipt.json').read_bytes())
        assert receipt['passed'] and receipt['buildExitCode'] == receipt['ctestExitCode'] == 0
        assert receipt['inputs'] == receipt['inputsAfter'] and receipt['binariesBefore'] == receipt['binariesAfter']
        for name, digest in receipt['inputs'].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
        log = (original / 'ctest.log').read_text('utf-8-sig')
        assert re.search(r'100% tests passed(?:, 0 tests failed)? out of 29', log)
        xmls = sorted((original / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 28, len(xmls)
        reports = [qt(path, 'windows-2022') for path in xmls]
        text = (original / 'Testing/QtTest/sqlite-vfs-tests.log').read_text('utf-8-sig')
        assert 'Totals: 10 passed, 0 failed, 0 skipped' in text
        shutil.copytree(original, local / tag)
        records.append({'toolchain': tag, 'completeCoreCtestsPassed': 29, 'qtXmlOriginalsVerified': 28,
                        'sqliteVfsRowsPassed': 10, 'sqliteVfsSkipped': 0, 'xmlResults': reports})
    for name in ['r119-first-vfs-failure', 'r119-sort-flag-failure']:
        shutil.copytree(ROOT / '.cache' / name, local / name)
    for name in ['r119-source-audit.json', 'r119-source-snapshot.json', 'validate-r119-windows.py']:
        shutil.copyfile(ROOT / '.cache' / name, local / name)
    shutil.copyfile(Path(__file__), local / 'preparation-driver.py')
    vendor = ROOT / 'third-party/sqlite-runtime'
    provenance = json.loads((vendor / 'provenance.json').read_bytes())
    for row in provenance['files']:
        raw = (vendor / row['path']).read_bytes()
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    previous = json.loads((REPO / 'docs/ci-verification-20261107-r118.json').read_bytes())
    names = {row['path'] for row in previous['qualificationInputs']}
    names.update(['src/core/sqliteruntime.h', 'src/core/sqliteruntime.cpp', 'src/core/sqlitevfs.h',
                  'src/core/sqlitevfs.cpp', 'tests/sqlite_vfs_tests.cpp'])
    names.update(path.relative_to(ROOT).as_posix() for path in vendor.rglob('*') if path.is_file())
    old = {row['path']: row['sha256'] for row in previous['qualificationInputs']}
    changed, frozen = [], []
    for name in sorted(names):
        path = ROOT / name
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if old.get(name) != digest:
            changed.append(name)
            if name in old:
                baseline = subprocess.check_output(['git', 'show', previous['sourceCommit'] + ':' + name], cwd=REPO)
                assert raw.startswith(b'\xef\xbb\xbf') == baseline.startswith(b'\xef\xbb\xbf'), name
                assert (b'\r\n' in raw) == (b'\r\n' in baseline), name
            target = REPO / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        assert (REPO / name).read_bytes() == raw, name
        frozen.append({'path': name, 'bytes': len(raw), 'sha256': digest})
    assert len(frozen) == 259, len(frozen)
    write(local / 'receipt.json', {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': True,
          'records': records, 'qualificationInputs': frozen, 'changedInputs': changed, 'inputCount': len(frozen),
          'allExistingEncodingBomNewlinePreserved': True, 'upstreamBytesAndDigestsVerified': True,
          'firstFixtureFailureOriginalsPreserved': True, 'sqliteVersion': '3.53.4', 'qtDriverSourceVersion': '5.15.2',
          'sqliteVfsDefaultPolicyOnly': True, 'globalQuotaEnforced': False, 'automaticGcImplemented': False,
          'deliveryComplete': False, 'releaseQualified': False})
    index = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'planVersion': 'v0.119',
             'baselineSourceCommit': previous['sourceCommit'], 'qualificationInputs': frozen,
             'inputCount': len(frozen), 'changedInputs': changed,
             'receipts': [{'path': (local / name).relative_to(REPO).as_posix(),
                           'sha256': hashlib.sha256((local / name).read_bytes()).hexdigest()}
                          for name in ['receipt.json', 'r119-source-audit.json', 'r119-source-snapshot.json']],
             'localWindowsAllCoreQualified': True, 'sourcePublicationPending': True, 'nativeQualificationPending': True,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False, 'deliveryComplete': False, 'releaseQualified': False}
    write(REPO / 'docs/ci-verification-20261107-r119.json', index)
    for version, prefix in [(117, 'sqlite-journal'), (118, 'state-storage')]:
        path = REPO / ('docs/ci-verification-20261107-r' + str(version) + '.json')
        value = json.loads(path.read_bytes())
        terminal_path = BASE / (prefix + '-r' + str(version) + '-native-terminal/receipt.json')
        terminal = json.loads(terminal_path.read_bytes())
        value.update(observedUtc=datetime.now(timezone.utc).isoformat(), nativeRun=terminal['run'],
                     fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'])
        for row in value['receipts']:
            row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
        write(path, value)
        shutil.copyfile(path, ROOT / path.relative_to(REPO))
        shutil.copytree(terminal_path.parent, ROOT / terminal_path.parent.relative_to(REPO), dirs_exist_ok=True)
    section = """## R119 固定SQLite运行时与连接VFS（2026-11-07）

- [x] 固定SQLite 3.53.4与Qt官方5.15.2完整驱动原件，CMake编译前/解压后核对SHA256；内部驱动独立注册，13处生产连接及句柄检查统一使用同一引擎。[设计与边界](docs/SQLite运行时与写入拦截.md)。
- [x] 每连接独立VFS策略覆盖打开、写入、截断、大小提示、WAL共享内存请求及删除；正文映射回退读写，原生锁/同步/短读继续转发；默认策略仅转发，实际总预算尚未安装。
- [x] MSVC/UCRT各29完整CTest和28份Qt XML通过；新专项各10条全通过，含旧插件互读、只读/URI/临时库、拒绝前后原摘要、日志拒绝后重试、WAL/排序溢写、32次释放及两连接隔离。Windows非法文件名及排序文件标志的首轮夹具失败原件保留。[本机证据](docs/validation/2026-11-07/sqlite-vfs-r119-local/receipt.json)。
- [x] 226份维护文件零TODO/占位标记、C++14/格式及原编码/BOM/换行通过；259份资格输入冻结。源码快照和三平台共用对应源码归档包含固定依赖与许可，篡改依赖在写入前拒绝，无关third-party目录排除。[索引](docs/ci-verification-20261107-r119.json)。
- [x] R117四原生完整job终态success，Windows51条、三个POSIX各47条通过；R118三个POSIX完整协议各47条已验，Windows继续按精确终态原件收验。
- [ ] R119精确提交公开、四原生完整回归及新双Mac编译/含依赖包继续；现有已验Mac预览为R118。
- [ ] Q02整体及Q03–Q08继续：跨进程持久预算、身份/实际分配对账、所有状态根/原子替换/正文接入、有效幂等保留和自动GC未完成。完整R6 GUI、物理LAN/3×3、当前版本各平台24h、干净系统、依赖源码重建及正式分发继续；整体与正式资格保持false。

"""
    def plan(text):
        assert '## R119 ' not in text
        text = text.replace('文档版本：v0.118', '文档版本：v0.119', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R119固定SQLite与连接VFS已通过双Windows各29核心/28份XML，259份输入冻结，准备公开与原生验证。Q02整体、跨进程总预算与自动GC继续；已验双Mac包仍R118。R117完整四原生终态success，完整项目交付继续。', text, count=1, flags=re.M)
        text = text.replace('v0.118 / 状态根直接占用计量', 'v0.119 / SQLite写入前策略基础', 1)
        text = text.replace('- [ ] R117四原生各27核心已验；ubuntu-22.04、macos-15、macos-15-intel完整协议各47项通过，Windows终态继续，冻结R98不转授当前版本24h资格。', '- [x] R117四原生完整job终态success：Windows51条、Ubuntu/Apple Silicon/Intel各47条协议原件已验，冻结R98不转授当前版本24h资格。')
        return text.replace('## R118 状态根直接占用计量', section + '## R118 状态根直接占用计量', 1)
    edit('开发计划与进度.md', plan)
    edit('docs/执行进度.md', lambda text: text.replace('## R118 状态根直接占用计量',
         '## R119 固定SQLite运行时与连接VFS（2026-11-07）\n\n双Windows各29完整CTest及28份Qt XML通过，新专项各10条全通过；原驱动完整查询/事务功能保留，固定SQLite引擎与每连接VFS提供写入前拒绝接口。226份维护文件审计通过，259份输入冻结；源码快照及对应源码归档含固定依赖/许可，首轮夹具失败保留。Q02整体、跨进程预算与自动GC继续；新四原生与Mac包按精确提交另验。[设计](SQLite运行时与写入拦截.md)、[证据](ci-verification-20261107-r119.json)。R117完整四原生终态success，Windows51/三个POSIX各47条通过；R118三个POSIX完整协议已验。\n\n## R118 状态根直接占用计量', 1))
    edit('README.md', lambda text: text.replace('\n\nR118精确', '\n\nR119固定SQLite 3.53.4与Qt完整驱动，每连接VFS支持写入前策略；双Windows各29完整CTest/28份XML通过，新专项各10条全通过。原件依赖与许可进入源码包；259份输入冻结，新原生构建继续。实际总预算/自动GC仍待接入。[设计](docs/SQLite运行时与写入拦截.md)、[证据](docs/ci-verification-20261107-r119.json)。\n\nR118精确', 1))
    edit('docs/磁盘总配额实施清单.md', lambda text: text.replace('状态：待实现；R118仅完成直接状态根计量基础。', '状态：持续实施；R118完成直接状态根计量，R119完成Q02的固定SQLite/连接VFS子项，Q02整体及其他项尚未完成。', 1).replace('| Q02 | 确定真正覆盖写入的授信接口；在主库增长、回滚日志、WAL/shm、SQLite临时索引和原子替换写入前取得额度。记录Qt驱动/SQLite版本和可用接口的实际探针结果 | 待实现 |', '| Q02 | 确定真正覆盖写入的授信接口；在主库增长、回滚日志、WAL/shm、SQLite临时索引和原子替换写入前取得额度。记录Qt驱动/SQLite版本和可用接口的实际探针结果 | SQLite运行时/VFS子项已验；实际预算、原子替换和平台分配对账待完成 |', 1) + '\n\nR119采用固定SQLite源码与Qt完整驱动，详细接口、已验子项和边界见[SQLite运行时与写入拦截](SQLite运行时与写入拦截.md)。生产默认策略只转发，quotaEnforced=false；本清单不因接口存在而标记总配额完成。\n')
    shutil.copyfile(ROOT / 'docs/SQLite运行时与写入拦截.md', REPO / 'docs/SQLite运行时与写入拦截.md')
    shutil.copyfile(REPO / 'docs/ci-verification-20261107-r119.json', ROOT / 'docs/ci-verification-20261107-r119.json')
    shutil.copytree(local, ROOT / local.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({'inputCount': len(frozen), 'changedInputCount': len(changed), 'coreCtestsEach': 29,
                      'newSqliteVfsRowsEach': 10, 'publicationPending': True}), flush=True)


if __name__ == '__main__':
    main()

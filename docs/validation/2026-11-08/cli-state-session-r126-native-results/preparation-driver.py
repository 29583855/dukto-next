"""日期：2026-11-08；按各平台实际结果记录CLI会话、完整核心和业务回归，未验范围继续保留。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = 'docs/validation/2026-11-08/'


# 日期：2026-11-08；仅复制本轮普通文本证据，不带私有目录、二进制或解释器缓存。
def copy(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.py', '.sha256', '.csv']:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


# 日期：2026-11-08；所有回执冻结后才修改文档；完整协议与含依赖包不由专项成功代替。
def main():
    target = ROOT / '.cache/r126-native-results-prepared.json'
    assert not target.exists()
    source = json.loads((ROOT / '.cache/r126-source-publication.json').read_bytes())['sourceCommit']
    folders = [BASE + 'cli-state-session-r126-' + suffix for suffix in ['native', 'full-native-core', 'macos-compiled', 'native-terminal']]
    reports = [json.loads((REPO / folder / 'receipt.json').read_bytes()) for folder in folders]
    session, core, compiled, terminal = reports
    assert all(value['sourceCommit'] == source for value in reports)
    assert session['allFourNativeSessionQualified'] and session['run']['conclusion'] == 'success'
    assert all(row['rowsPassed'] == 13 and row['warnings'] == row['skipped'] == 0 for row in session['records'])
    assert core['allFourNativeCoreJobsVerified']
    assert all(row['ctestTargetsPassed'] == 34 and row['qtXmlReportsVerified'] == 33 for row in core['records'])
    assert compiled['bothArchitecturesCompiledAndVerified']
    index_path = ROOT / 'docs/ci-verification-20261108-r126.json'
    index = json.loads(index_path.read_bytes())
    assert len(index['qualificationInputs']) == 291
    for row in index['qualificationInputs']:
        assert (ROOT / row['path']).read_bytes() == (REPO / row['path']).read_bytes()
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256']
    output = REPO / (BASE + 'cli-state-session-r126-native-results')
    output.mkdir(exist_ok=False)
    business = []
    for tag in ['msvc', 'ucrt']:
        folder = ROOT / '.cache' / ('r126-cli-business-' + tag)
        actual = json.loads((folder / 'receipt.json').read_bytes())
        assert actual['passed'] and actual['sourceInputCount'] == 291 and actual['sourceInputsUnchanged']
        assert actual['binaryBefore'] == actual['binaryAfter']
        parallel = json.loads((folder / 'parallel_transfer.json').read_bytes())
        assert parallel['passed'] and parallel['channelsTested'] == [1, 2, 4, 8, 16]
        assert len(parallel['cases']) == 10 and all(row['passed'] for row in parallel['cases'])
        assert parallel['binarySha256'] == actual['binaryBefore']
        copy(folder, output / tag)
        business.append({'toolchain': tag, 'servicePassed': True, 'parallelDirectionsAndChannels': 10,
                         'binaryUnchanged': True, 'sourceInputsUnchanged': 291,
                         'physicalLanQualified': False})
    shutil.copyfile(ROOT / '.cache/validate-r126-cli-business.py', output / 'validate-business.py')
    glibc_qualified = False
    glibc_path = ROOT / '.cache/r126-glibc/receipt.json'
    if glibc_path.exists():
        glibc = json.loads(glibc_path.read_bytes())
        assert glibc['passed'] and glibc['rowsPassed'] == 13 and glibc['allInstalledSourceInputsUnchanged']
        installed = json.loads((ROOT / '.cache/r126-glibc/installed-source.json').read_bytes())
        for row in index['qualificationInputs']:
            assert installed['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}, row['path']
        copy(ROOT / '.cache/r126-glibc', output / 'independent-glibc')
        shutil.copyfile(ROOT / '.cache/validate-r126-glibc.py', output / 'validate-glibc.py')
        glibc_qualified = True
    protocol_count = sum(row['qualified'] for row in terminal['records'])
    record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'allFourNativeSessionQualified': True, 'sessionRowsEach': 13,
              'nativeCoreJobsVerified': 4, 'nativeCtestTargetsEach': 34, 'nativeQtXmlEach': 33,
              'bothMacosCompiled': True, 'packagedPreviewRemainsR125': True,
              'localBusiness': business, 'independentGlibcQualified': glibc_qualified,
              'independentGlibcQualificationPending': not glibc_qualified,
              'nativeProtocolJobsVerified': protocol_count,
              'fullNativeProtocolQualified': terminal['allFourNativeProtocolJobsVerified'],
              'cliLifecycleIntegrated': True, 'guiRootsIntegrated': False,
              'productionRootsIntegrated': False, 'globalQuotaEnforced': False,
              'deliveryComplete': False, 'releaseQualified': False}
    if glibc_qualified:
        record['independentGlibcRows'] = 13
        record['independentGlibcQualificationInputsMatched'] = 291
    (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'preparation-driver.py')
    folders.append(output.relative_to(REPO).as_posix())
    for folder in folders:
        copy(REPO / folder, ROOT / folder)
    old_folder = BASE + 'budget-configuration-r125-native-terminal'
    copy(REPO / old_folder, ROOT / old_folder)
    old_terminal = json.loads((ROOT / old_folder / 'receipt.json').read_bytes())
    assert old_terminal['allFourNativeProtocolJobsVerified']
    old_index_path = ROOT / 'docs/ci-verification-20261108-r125.json'
    old_index = json.loads(old_index_path.read_bytes())
    old_index.update(nativeTerminalJobsVerified=4, nativeRun=old_terminal['run'], fullNativeProtocolQualified=True)
    old_index['receipts'] = [{'path': row['path'], 'sha256': hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest()}
                             for row in old_index['receipts']]
    old_index_path.write_text(json.dumps(old_index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(old_index_path, REPO / old_index_path.relative_to(ROOT))
    folders.append(old_folder)
    summary = (f'R126精确{source[:8]}四原生CLI状态会话各13项通过，四平台各34完整核心/33份Qt XML已验；'
               '双Mac GUI/CLI编译归档已核验，双Windows真实服务和1/2/4/8/16通道双向传输通过。'
               + ('独立Ubuntu13项通过。' if glibc_qualified else '独立Ubuntu新目录仍在编译。')
               + '含依赖Mac下载仍R125；GUI映射、历史迁移、实际总预算与自动GC继续。')
    section = f'''## R126四原生CLI会话与完整核心（2026-11-08）

- [x] 精确{source}已公开；[四平台状态会话专项]({session['run']['html_url']})全部终态success，每平台13项、零跳过/警告。实际288份维护构建输入按Git检出规则逐项核对，CLI/测试程序前后保持；本机完整资格清单另含格式/属性/Docker输入共291份。[原件](docs/validation/2026-11-08/cli-state-session-r126-native/receipt.json)。
- [x] Windows、Ubuntu、Apple Silicon、Intel各34完整CTest/33份Qt XML全部收验。原Darwin端口XFAIL、Windows符号链接权限缺口及精确历史诊断保留；核心成功不替代完整协议终态。[核心原件](docs/validation/2026-11-08/cli-state-session-r126-full-native-core/receipt.json)。
- [x] 双Mac真实GUI和独立CLI编译归档已核对官方ZIP、tar摘要、精确提交、Mach-O架构和执行位；归档需要相应Qt5/OpenSSL运行库。可直接使用的含依赖开发预览继续为[R125](docs/macOS独立预览包.md)，本轮没有重发预览或授予正式签名/公证资格。
- [x] 两套Windows程序真实配对/授权/浏览业务、1/2/4/8/16通道上传和下载各10场景通过，程序及291输入前后保持。不同文件检查点实际重叠、双端摘要一致，记录RSS/线程/句柄峰值；测试为本机不透明限速TLS代理，不能据此授予物理LAN或长期无增长资格。[业务原件](docs/validation/2026-11-08/cli-state-session-r126-native-results/receipt.json)。
- [x] R125原完整协议作业现已四平台终态success，Windows51项、三个POSIX各47项均按原件收验。此前进行中记录保留为历史快照。
GLIBC_LINE
- [ ] 本轮完整协议当前已验{protocol_count}/4，其余按原作业继续；GUI旧remote目录与CLI根发现、普通历史安全迁移、实际写前额度、物理分配与跨卷、有效幂等保留、未知项和自动GC继续实施，整体active。

'''
    glibc_line = ('- [x] 独立Ubuntu新目录真实构建及13项专项通过，全部安装源、程序和C++14保持；291资格输入与公开提交全部相同。' if glibc_qualified else '- [ ] 独立Ubuntu新隔离目录真实编译仍在运行，未授予专项或完整核心资格。')
    section = section.replace('GLIBC_LINE', glibc_line)
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace('## R126生产CLI状态会话接入', section + '## R126生产CLI状态会话接入', 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace('## R126生产CLI状态会话接入', section.replace('](docs/', '](') + '## R126生产CLI状态会话接入', 1))
    update('README.md', lambda text: text.replace('R126将CLI服务/客户端状态根', summary + ' [本轮证据](docs/ci-verification-20261108-r126.json)。\n\nR126将CLI服务/客户端状态根', 1))
    update('docs/生产状态会话与CLI接入.md', lambda text: text + '\nR126精确源码四原生各13项会话专项、各34完整核心通过；双Windows真实服务及1/2/4/8/16通道双向业务通过。完整协议、独立环境和剩余生产接入以索引实际状态为准。\n')
    index.update(sourceCommit=source, allFourNativeSessionQualified=True, nativeSessionRun=session['run'],
                 nativeCoreRun=core['run'], nativeCoreJobsVerified=4, bothMacosCompiled=True,
                 nativeQualificationPending=False, independentGlibcQualified=glibc_qualified,
                 independentGlibcQualificationPending=not glibc_qualified,
                 nativeRun=terminal['run'], nativeTerminalJobsVerified=protocol_count,
                 fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'],
                 localRealServiceAndParallelBusinessQualified=True,
                 observedUtc=record['observedUtc'])
    if glibc_qualified:
        index['independentGlibcQualificationInputsMatched'] = 291
    refs = {row['path'] for row in index['receipts']} | {folder + '/receipt.json' for folder in folders}
    index['receipts'] = [{'path': ref, 'sha256': hashlib.sha256((ROOT / ref).read_bytes()).hexdigest()} for ref in sorted(refs)]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(index_path, REPO / index_path.relative_to(ROOT))
    record['evidenceFolders'] = folders
    target.write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()

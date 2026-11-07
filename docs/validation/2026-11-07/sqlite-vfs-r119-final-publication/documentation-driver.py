"""日期：2026-11-08；依据最终精确源码的编译/核心/双Mac部署原件更新计划，不转授完整协议或总配额资格。"""
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import re,shutil,subprocess

ROOT=Path.cwd();REPO=ROOT/'.cache/github-29583855-dukto-next-r28';BASE=REPO/'docs/validation/2026-11-07'


# 日期：2026-11-08；新JSON按UTF-8保存；已有文本保留BOM和换行，源与证据保持同字节。
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n','utf-8')


# 日期：2026-11-08；按实际最终结果更新当前阶段，历史失败继续保留。
def edit(name,callback):
    path=ROOT/name;raw=path.read_bytes();bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'';nl='\r\n' if b'\r\n' in raw else '\n'
    old=raw[len(bom):].decode('utf-8').replace('\r\n','\n');new=callback(old);assert old!=new,name
    path.write_bytes(bom+new.replace('\n',nl).encode('utf-8'));shutil.copyfile(path,REPO/name)


# 日期：2026-11-08；只有四核心/双编译/双部署及四截图实际核验后才更新下载页。
def main():
    source=json.loads((ROOT/'.cache/r119-windows-source-publication.json').read_bytes())
    commit=source['sourceCommit'];app_commit=source['macosApplicationSourceCommit'];assert source['remoteMainVerified'] and source['inputCount']==261
    core=json.loads((BASE/'sqlite-vfs-r119-final-native-core/receipt.json').read_bytes())
    compiled=json.loads((BASE/'sqlite-vfs-r119-final-macos-compiled/receipt.json').read_bytes())
    package=json.loads((BASE/'sqlite-vfs-r119-final-macos-package/receipt.json').read_bytes())
    assert core['sourceCommit']==compiled['sourceCommit']==package['sourceCommit']==app_commit
    assert compiled['bothArchitecturesCompiledAndVerified']
    assert all(row['qualified'] for row in core['records'] if row['runner']!='windows-2022')
    windows=json.loads((BASE/'sqlite-vfs-r119-windows-regression/receipt.json').read_bytes())
    assert windows['sourceCommit']==commit and windows['qualified'] and windows['directoryMutationRepeated']==20
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed']
    for row in source['qualificationInputs']:
        raw=subprocess.check_output(['git','show',commit+':'+row['path']],cwd=REPO)
        assert raw==(ROOT/row['path']).read_bytes() and hashlib.sha256(raw).hexdigest()==row['sha256']
    for row in core['records']:
        if row['runner']!='windows-2022':assert row['ctestTargetsPassed']==29 and row['qtXmlReportsVerified']==28 and row['sqliteVfsRowsPassed']==10
    # 日期：2026-11-08；原Windows完整集只失败计量夹具，其余28目标/27份XML单独核验，原失败永不覆盖。
    original=BASE/'sqlite-vfs-r119-final-native-core/windows-2022'
    ctest,=original.rglob('ctest.log')
    assert '97% tests passed, 1 tests failed out of 29' in ctest.read_text('utf-8-sig')
    import runpy
    qt=runpy.run_path(str(ROOT/'.cache/collect-r118-native-core.py'))['qt']
    xmls=sorted(path for path in (original/'Testing/QtTest').glob('*.xml') if path.name!='state-storage-tests.xml')
    assert len(xmls)==27
    for path in xmls:qt(path,'windows-2022')
    vfs,=original.rglob('sqlite-vfs-tests.log');assert 'Totals: 10 passed, 0 failed, 0 skipped' in vfs.read_text('utf-8-sig')
    assert source['applicationInputsUnchanged'] and source['applicationAndDependencyInputCount']==115
    local=BASE/'sqlite-vfs-r119-final-publication';local.mkdir(exist_ok=False)
    for name in ['r119-source-publication.json','r119-fixed-source-publication.json','r119-observable-source-publication.json','r119-windows-source-publication.json',
                 'r119-initial-native-cancellation.json','r119-checkout-native-cancellation.json','r119-observable-macos-package-dispatch.json','r119-windows-regression-dispatch.json']:
        shutil.copyfile(ROOT/'.cache'/name,local/name)
    shutil.copyfile(Path(__file__),local/'documentation-driver.py')
    index_path=REPO/'docs/ci-verification-20261107-r119.json';index=json.loads(index_path.read_bytes())
    terminal_path=BASE/'sqlite-vfs-r119-native-terminal/receipt.json';terminal=json.loads(terminal_path.read_bytes()) if terminal_path.exists() else None
    full=bool(terminal and terminal['allFourNativeProtocolJobsVerified'])
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(),sourceCommit=commit,
                 sourceTree=subprocess.check_output(['git','rev-parse',commit+'^{tree}'],cwd=REPO).decode().strip(),
                 sourcePublicationPending=False,remoteSourceVerified=True,allNativeCoreQualified=False,allApplicationCoreTargetsVerifiedAcrossRecordedCommits=True,
                 exactAllNativeInputSetsQualified=False,macosApplicationSourceCommit=app_commit,
                 originalWindowsPassingCtestTargets=28,originalWindowsPassingXmlReports=27,
                 originalWindowsVfsRowsPassed=10,originalWindowsFullCoreFailureRetained=True,
                 windowsStorageRegressionQualified=True,windowsStorageRegressionRun=windows['run'],
                 macosCompiledArchitecturesVerified=2,macosDeploymentQualified=True,fullNativeProtocolQualified=full,
                 nativeQualificationPending=not full,nativeRun=terminal['run'] if terminal else core['run'],macosPackageRun=package['run'],
                 localFullCoreInputSourceCommit=json.loads((ROOT/'.cache/r119-source-publication.json').read_bytes())['sourceCommit'],
                 localCurrentStorageTargetQualified=True,globalQuotaEnforced=False,automaticGcImplemented=False,
                 deliveryComplete=False,releaseQualified=False)
    paths={row['path'] for row in index['receipts']}
    for folder in ['sqlite-vfs-r119-final-native-core','sqlite-vfs-r119-final-macos-compiled','sqlite-vfs-r119-final-macos-package','sqlite-vfs-r119-windows-regression']:
        paths.add((BASE/folder/'receipt.json').relative_to(REPO).as_posix())
    if terminal:paths.add(terminal_path.relative_to(REPO).as_posix())
    paths.update(path.relative_to(REPO).as_posix() for path in local.glob('*.json'))
    paths.update((BASE/'sqlite-vfs-r119-local-protocol'/tag/'receipt.json').relative_to(REPO).as_posix() for tag in ['msvc','ucrt'])
    index['receipts']=[{'path':name,'sha256':hashlib.sha256((REPO/name).read_bytes()).hexdigest()} for name in sorted(paths)]
    write(index_path,index);shutil.copyfile(index_path,ROOT/index_path.relative_to(REPO))
    for version,prefix in [(117,'sqlite-journal'),(118,'state-storage')]:
        path=REPO/('docs/ci-verification-20261107-r'+str(version)+'.json');v=json.loads(path.read_bytes());proof=BASE/(prefix+'-r'+str(version)+'-native-terminal/receipt.json');t=json.loads(proof.read_bytes())
        v.update(observedUtc=datetime.now(timezone.utc).isoformat(),nativeRun=t['run'],fullNativeProtocolQualified=t['allFourNativeProtocolJobsVerified'])
        for row in v['receipts']:row['sha256']=hashlib.sha256((REPO/row['path']).read_bytes()).hexdigest()
        write(path,v);shutil.copyfile(path,ROOT/path.relative_to(REPO));shutil.copytree(proof.parent,ROOT/proof.parent.relative_to(REPO),dirs_exist_ok=True)
    section='- [x] 最终夹具精确'+commit+'已非强制公开，261份输入逐blob核对；115份应用/依赖输入与Mac源'+app_commit+'完全相同。三个POSIX在325c60cc各29完整CTest/28份Qt XML/VFS10条通过；Windows原325的28/29及目录夹具失败原件保留。\n'
    section+='- [x] Windows新夹具专项完整计量11条全通过、同一失败方法20轮真实重复通过，CLI/测试SHA前后保持；按d2c8c4f单独授予专项资格，不能将325原完整job改记成功。\n'
    section+='- [x] 双Mac GUI/独立CLI编译归档、含Qt5/OpenSSL预览、对应固定依赖源码/许可、逐件载荷/链接、系统PATH迁移、各五项实际CLI/传输、Cocoa/高DPI及四张截图全部核验。[下载](docs/macOS独立预览包.md)。\n'
    section+='- [x] 当前双Windows各四项实际CLI专项通过：旧版、TLS16通道、覆盖4→8通道故障恢复、上传确认恢复；二进制前后保持。\n'
    section+='- ['+('x' if full else ' ')+'] 最终四原生完整协议'+('已按终态原件全部核验。' if full else '继续运行并按精确终态原件收验；编译/核心/打包通过不替代完整协议。')+'\n'
    def plan(text):
        text=re.sub(r'^当前阶段：.*$','当前阶段：R119夹具'+commit[:8]+'已公开，应用源'+app_commit[:8]+'的三个POSIX各29核心/VFS10条、双Mac编译/含依赖包/迁移与四截图已验；Windows原28/29失败保留，新完整计量11条及20轮专项通过。完整协议、总预算/GC及整体交付继续。',text,count=1,flags=re.M)
        text=text.replace('最后更新：2026-11-07','最后更新：2026-11-08',1)
        text=text.replace('- [ ] 最终应用325c60cc的双Mac含依赖包、Windows时间夹具专项和完整协议继续按各自精确提交验收；整体保持未完成。',section,1)
        text=text.replace('当前已验Mac预览为R118，','当前已验Mac预览为R119，',1)
        text=text.replace('当前双Mac含依赖部署包为R118精确e84f34f','当前双Mac含依赖部署包为R119精确'+app_commit[:8],1)
        text=text.replace('| Windows | R118本机双工具链与原生CI各28核心通过，原生计量11条全通过；部署仍R100 |', '| Windows | R119本机双工具链各29核心及四项CLI专项通过；原生28/29失败保留，新计量11条/20轮专项通过，部署仍R100 |', 1)
        text=text.replace('| Linux | R118原生28核心、计量12条及扫描清理29条通过；完整协议继续 |', '| Linux | R119最终原生29核心/28份Qt原件/VFS10条、计量12条及扫描清理29条通过；完整协议继续 |', 1)
        text=text.replace('| macOS ARM / Intel | R118含Qt5/OpenSSL双架构GUI/CLI预览可下载，各28核心及计量12条通过，迁移运行及截图已验 |', '| macOS ARM / Intel | R119含Qt5/OpenSSL双架构GUI/CLI预览可下载，各29核心/VFS10条及计量12条通过，迁移/传输及截图已验 |', 1)
        return text
    edit('开发计划与进度.md',plan)
    edit('docs/执行进度.md',lambda text:text.replace('## R119 固定SQLite运行时与连接VFS（2026-11-07）\n','## R119 固定SQLite运行时与连接VFS（2026-11-07）\n\n最终夹具'+commit[:8]+'精确261份输入已公开，三个POSIX在325c60cc各29核心/28份Qt原件/VFS10条通过；Windows原28/29失败保留，新计量11条及20轮专项通过；双Mac编译、含Qt5/OpenSSL包、固定依赖源码/许可、迁移、各五项实际CLI/传输及四截图全核验。完整协议按终态继续，总配额与自动GC仍待实施。[Mac下载](macOS独立预览包.md)。\n',1))
    edit('README.md',lambda text:text.replace('\n\nR119固定SQLite','\n\nR119最终夹具'+commit[:8]+'已公开：三个POSIX各29核心/28份Qt XML及VFS10条通过，Windows原28/29失败保留，新计量11条及20轮专项通过；双Mac GUI/CLI编译与含Qt5/OpenSSL预览、迁移/传输和四截图全部核验。[Mac下载](docs/macOS独立预览包.md)、[本轮回执](docs/ci-verification-20261107-r119.json)。完整协议、总配额/自动GC与整体交付继续。\n\nR119固定SQLite',1))
    intro='R119应用精确'+app_commit+'已公开，固定SQLite 3.53.4与Qt完整驱动；三个POSIX各29核心、28份Qt XML及VFS10条通过。Windows原28/29夹具失败保留，后续'+commit[:8]+'完整计量11条及20轮专项通过，115份应用/依赖输入完全相同。双架构GUI/独立CLI、含Qt5/OpenSSL预览、固定依赖源码/许可、迁移运行及四张截图已验。完整协议和正式发布资格继续另验。\n\n'
    package_section='## R119含依赖开发预览\n\n[逐层回执](validation/2026-11-07/sqlite-vfs-r119-final-macos-package/receipt.json)。adhoc开发预览，正式签名/公证、最低干净系统及完整项目继续验收。\n\n| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n'
    for row in package['records']:package_section+='| '+row['architecture']+' | [下载]('+row['artifactUrl']+') | '+row['artifactSha256']+' | '+row['packageSha256']+' |\n'
    package_section+='\n本机副本：dist/macos-preview-20261107-r119-final-sqlite-vfs/。解压与CLI用法见下文。\n\n## R119原生编译归档\n\n[回执](validation/2026-11-07/sqlite-vfs-r119-final-macos-compiled/receipt.json)。仅编译归档需要匹配运行库；上方预览已包含部署依赖。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:package_section+='| '+row['architecture']+' | [下载]('+row['artifactUrl']+') | '+row['sha256']+' |\n'
    package_section+='\n'
    edit('docs/macOS独立预览包.md',lambda text:text.replace('# macOS独立开发预览包\n\n','# macOS独立开发预览包\n\n'+intro,1).replace('## R118含依赖开发预览',package_section+'## R118含依赖开发预览（历史）',1))
    edit('docs/SQLite运行时与写入拦截.md',lambda text:text+'\n2026-11-08补充：应用'+app_commit[:8]+'三个POSIX各29完整CTest/28份Qt原件及新专项10条通过；Windows原28/29失败保留，'+commit[:8]+'完整计量11条及20轮专项通过；双Mac对应源码/许可、含依赖包及迁移运行已验。目录测试显式设置可观测mtime，首次Windows检出摘要失败和Ubuntu夹具失败继续保留；总配额/自动GC仍未完成。\n')
    for folder in ['sqlite-vfs-r119-final-native-core','sqlite-vfs-r119-final-macos-compiled','sqlite-vfs-r119-final-macos-package','sqlite-vfs-r119-local-protocol','sqlite-vfs-r119-final-publication','sqlite-vfs-r119-windows-regression']:
        shutil.copytree(BASE/folder,ROOT/'docs/validation/2026-11-07'/folder,dirs_exist_ok=True)
    print(json.dumps({'sourceCommit':commit,'allNativeCoreQualified':False,'windowsStorageRegressionQualified':True,'macosDeploymentQualified':True,'fullNativeProtocolQualified':full,'deliveryComplete':False}),flush=True)


if __name__=='__main__':main()

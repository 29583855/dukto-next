"""日期：2026-11-07；仅公开R104真实Mac编译和四原生核心原件，应用源码与未完成资格保持。"""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,re,runpy,shutil,subprocess
SOURCE='9c1e9419f7acb9bc3ddf2b8133eb330ead0c3fa6'
LABEL='r104-native-evidence'

# 日期：2026-11-07；原回执/输入核对通过后更新文档，后续暂存、提交和上传仍须各自实际成功。
def main():
 root=Path.cwd();checkout=root/'.cache/github-29583855-dukto-next-r28';base=root/'docs/validation/2026-11-07'
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout).decode().strip()==SOURCE
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=checkout)
 helper=runpy.run_path('.cache/finalize-skip-items-r84.py');update,save,proof=helper['update'],helper['save'],helper['proof']
 compiled_path=base/'state-use-r104-macos-compiled/receipt.json';core_path=base/'state-use-r104-native-core/receipt.json'
 compiled=json.loads(compiled_path.read_text('utf-8'));core=json.loads(core_path.read_text('utf-8'))
 assert compiled['sourceCommit']==core['sourceCommit']==SOURCE and compiled['bothArchitecturesCompiledAndVerified']
 assert core['passed'] and core['coreTargetsEach']==23 and core['originalQtReportsVerified']==88 and core['stateDirectoryUseGuardAllRunnersVerified'] and core['explicitDarwinExpectedFailureCount']==2
 report_path=root/'docs/ci-verification-20261107-r104.json';report=json.loads(report_path.read_text('utf-8'));assert len(report['buildInputs'])==213
 for row in report['buildInputs']:assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256']
 for origin,name in [('.cache/r104-state-use-published-tree-verification.json','source-publication-verification.json'),('.cache/r104-native-run.json','automatic-ci-observation.json')]:
  target=core_path.parent/name;assert not target.exists();shutil.copyfile(root/origin,target)
 report.update(observedUtc=datetime.now(timezone.utc).isoformat(),sourceCommit=SOURCE,nativeCoreQualified=True,nativeEvidence=proof(core_path),macOSCompilationEvidence=proof(compiled_path),sourcePublication=proof(core_path.parent/'source-publication-verification.json'),nativeRun={'runId':42316601470,'runUrl':compiled['run']['html_url'],'reusedAutomaticPushRun':True},nativeCIPending=True,fullProtocolTerminalPending=True,allPlatformCrossProcessGuardQualified=False,entireR04Qualified=False,releaseQualified=False,deliveryComplete=False);save(report_path,report)
 section='## R104最新编译产物（2026-11-07）\n\n精确源码'+SOURCE+'的双Mac GUI/独立CLI已编译、归档并上传；附件及内部tar摘要、源码、Mach-O架构、执行位和许可已逐项核验。\n\n| 架构 | 编译产物 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
 for row in compiled['packages']:section+='| '+row['architecture']+' | [下载]('+row['artifactUrl']+') | '+row['sha256']+' |\n'
 section+='\n[编译回执](validation/2026-11-07/state-use-r104-macos-compiled/receipt.json)。这些编译归档仍需匹配Qt5/OpenSSL运行依赖；含依赖预览仍为顶部R100。R104四runner各23核心/88份Qt原报告已验，新增状态目录共享/独占互斥方法实际通过，两条精确Darwin预期失败保留。[核心回执](validation/2026-11-07/state-use-r104-native-core/receipt.json)。完整协议和POSIX八进程/链接拒绝专项仍待原件收验，过期回收及整个R04继续。\n\n'
 update(root/'docs/macOS独立预览包.md',lambda t:t.replace('## R103最新编译产物（2026-11-07）',section+'## R103编译记录（2026-11-07）',1))
 note='''

## R104双Mac编译及四原生核心收验（2026-11-07）

- [x] 精确9c1e941已公开并独立核对远端main及整树，复用自动CI42316601470。双Mac GUI/CLI附件与内部tar摘要、源码、Mach-O架构、执行位及许可通过，[下载入口](docs/macOS独立预览包.md)已更新；含依赖部署包仍为R100。
- [x] 四runner各23核心及88份Qt原件通过；新增状态目录共享使用/独占维护方法均有真实PASS，原生/150%/200%取消48行继续通过，两条精确Darwin XFAIL保留。[核心原件](docs/validation/2026-11-07/state-use-r104-native-core/receipt.json)。这不代替POSIX真实八进程专项或全局配额验收。
- [x] 双Windows各23核心/真实进程和诊断/服务子项保持原回执；207维护文件零TODO/占位/简化标记、C++14、clang-format、原编码/BOM/换行与213构建输入通过。独立Ubuntu首次同一C++夹具编译失败及收验器误要求不存在LastTest.log的失败原件保留，修正后复验另行执行，不以首次失败授予通过资格。
- [ ] R104完整协议/POSIX多进程、新独立Ubuntu终态和R103 Windows最终协议继续；冻结86400秒尚未真实终止。过期安全回收、所有资源/公平性、完整R6/GUI及原生选择器、物理LAN/3×3、各平台长期、依赖源码重建、最低干净系统与正式发布继续；deliveryComplete=false、releaseQualified=false。
'''
 def plan(t):
  t=re.sub(r'^当前阶段：.*$','当前阶段：R104四原生各23核心/88份Qt及双Mac编译已验，新增维护互斥通过；完整协议、独立Ubuntu与安全回收/长期交付继续。',t,count=1,flags=re.M)
  start=t.index('公开仓库：',t.index('## 当前验收快照'));end=t.index('\n\n| 范围',start)
  t=t[:start]+'公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。精确R104源码9c1e941的四原生各23核心/88份Qt原件和双Mac GUI/CLI编译已验，含状态目录维护互斥；213份输入见[清单](docs/ci-verification-20261107-r104.json)。R102完整终态/188协议与R103已有诊断子项保持各自身份；R104完整协议及独立Ubuntu复验继续，含依赖预览仍为R100，安全回收/整体交付未完成。'+t[end:]
  t=t.replace('R103原生23核心及诊断核心/GUI方法通过；R102独立Ubuntu23核心/十轮取消通过；R100部署另验','R104原生23核心及维护互斥方法通过；R102独立Ubuntu/R100部署另验',1).replace('R103双架构GUI/CLI编译及各23核心/诊断核心/GUI子项通过；R100部署/APFS/完整补跑另验','R104双架构GUI/CLI编译、各23核心/维护互斥通过；R100部署/APFS另验',1)
  return t.rstrip()+note
 update(root/'开发计划与进度.md',plan)
 for name in ['docs/执行进度.md','docs/构建验证摘要.md']:update(root/name,lambda t:t.rstrip()+note.replace('(docs/','('))
 update(root/'README.md',lambda t:t.replace('最新R103源码cd92c43的双Mac GUI/独立CLI编译及四原生各23核心/88份Qt原报告已验，新增本地诊断/原子导出核心和GUI方法通过；完整协议与真实CLI诊断原生专项继续。','最新R104源码9c1e941的双Mac GUI/独立CLI编译及四原生各23核心/88份Qt原报告已验，新增状态目录维护互斥方法通过；完整协议/POSIX多进程、独立Ubuntu及安全回收继续。',1))
 path=root/'docs/current-validation.json';index=json.loads(path.read_text('utf-8'));index.update(observedUtc=report['observedUtc'],currentGuiSourceCommitPending=False,currentGuiSourceCommit=SOURCE,publicVerificationReceipt=report_path.relative_to(root).as_posix(),stateUseR104={'sourceCommit':SOURCE,'windowsEvidence':proof(base/'state-use-r104-qualified/receipt.json'),'nativeCoreEvidence':proof(core_path),'macOSCompilationEvidence':proof(compiled_path),'fullProtocolTerminalPending':True,'expiredCollectionImplemented':False,'entireR04Qualified':False},currentSourceStage='R104 exact source published; all four core targets and dual Mac compilation verified; full protocol, POSIX processes and safe GC pending',releaseQualified=False,deliveryComplete=False);save(path,index)
 path=root/'.cache/execution-current.json';state=json.loads(path.read_text('utf-8'));assert state['currentRepositoryCommit']==SOURCE;state.update(stateUseR104=report,workingSourceStage=index['currentSourceStage'],goalStatus='active',releaseQualified=False,deliveryComplete=False);save(path,state)
 shutil.copyfile(Path(__file__),core_path.parent/'publication-preparation-driver.py')
 names={'开发计划与进度.md','README.md','docs/执行进度.md','docs/构建验证摘要.md','docs/macOS独立预览包.md','docs/current-validation.json','docs/ci-verification-20261107-r104.json','docs/validation/2026-11-06/github-api-push-r104-state-use.json'}
 for folder in ['state-use-r104-native-core','state-use-r104-macos-compiled','state-use-r104-glibc']:
  names.update(p.relative_to(root).as_posix() for p in (base/folder).rglob('*') if p.is_file() and p.suffix not in ('.zip','.gz','.png'))
 names=sorted(names)
 for name in names:
  target=checkout/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target)
 (root/('.cache/'+LABEL+'-publish-files.json')).write_text(json.dumps(names,ensure_ascii=False,indent=2)+'\n','utf-8');(root/('.cache/'+LABEL+'-stage.nul')).write_bytes(b''.join(name.encode('utf-8')+b'\0' for name in names));(root/('.cache/stage-'+LABEL+'.py')).write_bytes((root/'.cache/stage-r104-state-use.py').read_bytes().replace(b'r104-state-use',LABEL.encode()));print(json.dumps({'explicitFiles':len(names),'applicationInputsUnchanged':213,'fullProtocolPending':True}))
if __name__=='__main__':main()

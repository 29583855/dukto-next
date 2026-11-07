"""日期：2026-11-08；发布Windows可观测目录时间夹具及20轮原生专项，产品输入保持325c60cc。"""
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import shutil,subprocess

ROOT=Path.cwd();REPO=ROOT/'.cache/github-29583855-dukto-next-r28';BASE=REPO/'docs/validation/2026-11-07/sqlite-vfs-r119-windows-fixture'


# 日期：2026-11-08；Git操作限定公开副本，原程序及所有失败原件保留。
def git(*args):return subprocess.check_output(['git',*args],cwd=REPO)


# 日期：2026-11-08；只增加明确文档记录并保持原BOM/换行。
def edit(name,callback):
    path=ROOT/name;raw=path.read_bytes();bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'';nl='\r\n' if b'\r\n' in raw else '\n';old=raw[len(bom):].decode('utf-8').replace('\r\n','\n');new=callback(old);assert old!=new;path.write_bytes(bom+new.replace('\n',nl).encode('utf-8'));shutil.copyfile(path,REPO/name)


# 日期：2026-11-08；资格输入只改Windows测试及新增CI，当前Mac应用全部输入与已编译325提交一致。
def main():
    previous=json.loads((ROOT/'.cache/r119-observable-source-publication.json').read_bytes());assert git('rev-parse','HEAD').decode().strip()==previous['sourceCommit'];assert not git('diff','--cached','--name-only')
    BASE.mkdir(exist_ok=False)
    shutil.copytree(REPO/'docs/validation/2026-11-07/sqlite-vfs-r119-final-native-core/windows-2022',BASE/'original-native-failure')
    for tag in ['msvc','ucrt']:
        for suffix in ['log','xml']:
            name='r119-windows-fixture-'+tag+'.'+suffix;shutil.copyfile(ROOT/'.cache'/name,BASE/name)
        assert 'Totals: 10 passed, 0 failed, 1 skipped' in (ROOT/'.cache'/('r119-windows-fixture-'+tag+'.log')).read_text('utf-8-sig')
    shutil.copyfile(ROOT/'.cache/r119-windows-fixture-source-audit.json',BASE/'source-audit.json');shutil.copyfile(Path(__file__),BASE/'publication-driver.py')
    path=ROOT/'docs/ci-verification-20261107-r119.json';index=json.loads(path.read_bytes());frozen=[];changed=[]
    old={row['path']:row['sha256'] for row in index['qualificationInputs']}
    for name in sorted(set(old)|{'.github/workflows/windows-storage-regression.yml'}):
        raw=(ROOT/name).read_bytes();digest=hashlib.sha256(raw).hexdigest();frozen.append({'path':name,'bytes':len(raw),'sha256':digest})
        if old.get(name)!=digest:changed.append(name);target=REPO/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    assert set(changed)=={'tests/state_storage_tests.cpp','.github/workflows/windows-storage-regression.yml'}
    app=[row for row in frozen if row['path'].startswith(('src/','ui/','resources/','third-party/')) or row['path']=='CMakeLists.txt']
    assert len(app)==115 and all(old[row['path']]==row['sha256'] for row in app)
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(),qualificationInputs=frozen,inputCount=261,
                 macosApplicationSourceCommit=previous['sourceCommit'],applicationInputsUnchangedByWindowsFixtureFix=True,
                 applicationAndDependencyInputCount=115,windowsTimestampFixChangedInputs=changed,
                 firstWindowsTimestampFixtureFailureRetained=True,currentWindowsLocalStorageTargetPassedBoth=True,
                 sourcePublicationPending=True,nativeQualificationPending=True)
    for name in ['source-audit.json','r119-windows-fixture-msvc.xml','r119-windows-fixture-ucrt.xml']:
        proof=BASE/name;index['receipts'].append({'path':proof.relative_to(REPO).as_posix(),'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()})
    raw=(json.dumps(index,ensure_ascii=False,indent=2)+'\n').encode();path.write_bytes(raw);(REPO/path.relative_to(ROOT)).write_bytes(raw)
    note='- [x] 325c60cc三个POSIX各29核心/VFS10条通过；Windows VFS10条及其余28核心通过，目录变更测试同样遇到时间戳更新延迟，原失败保留。Windows夹具补原生SetFileTime，仍要求Integrity拒绝；双本机完整计量各10通过/1权限跳过，新增云端完整计量及20轮变更专项继续。115份应用/依赖输入与325c60cc完全一致，新Mac包继续按325原件验收。\n'
    edit('开发计划与进度.md',lambda text:text.replace('- [ ] R119原Windows配置失败及Ubuntu目录夹具失败均保留；新夹具修正提交、四原生回归及双Mac包继续，已验Mac预览仍R118。',note+'- [ ] 最终应用325c60cc的双Mac含依赖包、Windows时间夹具专项和完整协议继续按各自精确提交验收；整体保持未完成。',1))
    edit('docs/执行进度.md',lambda text:text.replace('## R119 固定SQLite运行时与连接VFS（2026-11-07）\n','## R119 固定SQLite运行时与连接VFS（2026-11-07）\n\nWindows原生目录时间更新延迟也导致325c60cc的计量夹具失败；VFS10条/其余28核心通过，原件保留。Windows夹具显式SetFileTime，双本机完整计量各10通过/1权限跳过，云端完整计量及20轮专项继续。115份产品/依赖输入与325c60cc保持一致，Mac包按该精确源验收。\n',1))
    explicit=set(changed)|{'开发计划与进度.md','docs/执行进度.md','docs/ci-verification-20261107-r119.json'}
    explicit.update(p.relative_to(REPO).as_posix() for p in BASE.rglob('*') if p.is_file())
    p=REPO/'docs/ci-verification-20261107-r118.json';v=json.loads(p.read_bytes());terminal=REPO/'docs/validation/2026-11-07/state-storage-r118-native-terminal/receipt.json';t=json.loads(terminal.read_bytes());v.update(nativeRun=t['run'],fullNativeProtocolQualified=t['allFourNativeProtocolJobsVerified'])
    for row in v['receipts']:row['sha256']=hashlib.sha256((REPO/row['path']).read_bytes()).hexdigest()
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n','utf-8');shutil.copyfile(p,ROOT/p.relative_to(REPO));explicit.add(p.relative_to(REPO).as_posix())
    explicit.update(p.relative_to(REPO).as_posix() for p in terminal.parent.rglob('*') if p.is_file())
    dirty={p.decode() for p in git('diff','--name-only','-z').split(b'\0') if p};assert dirty<=explicit,dirty-explicit
    for offset in range(0,len(explicit),40):git('-c','core.autocrlf=false','add','-f','--',*sorted(explicit)[offset:offset+40])
    git('diff','--cached','--check','--','.',':(exclude)docs/validation');git('commit','-qm','Exercise observable Windows directory time changes with native regression [skip ci]')
    commit=git('rev-parse','HEAD').decode().strip();env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0';result=subprocess.run(['git','-c','http.proxy=http://127.0.0.1:10808','-c','http.lowSpeedLimit=1000','-c','http.lowSpeedTime=30','push','origin','main'],cwd=REPO,env=env,capture_output=True,text=True,timeout=120);assert result.returncode==0,result.stderr
    assert git('-c','http.proxy=http://127.0.0.1:10808','ls-remote','origin','refs/heads/main').decode().split()[0]==commit
    for row in frozen:assert hashlib.sha256(git('show',commit+':'+row['path'])).hexdigest()==row['sha256']
    receipt={'observedUtc':datetime.now(timezone.utc).isoformat(),'sourceCommit':commit,'macosApplicationSourceCommit':previous['sourceCommit'],'qualificationInputs':frozen,'inputCount':261,'applicationInputsUnchanged':True,'applicationAndDependencyInputCount':115,'remoteMainVerified':True,'releaseQualified':False,'deliveryComplete':False};p=ROOT/'.cache/r119-windows-source-publication.json';assert not p.exists();p.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8');shutil.copytree(BASE,ROOT/BASE.relative_to(REPO));print(json.dumps({key:receipt[key] for key in ['sourceCommit','macosApplicationSourceCommit','inputCount','applicationInputsUnchanged','remoteMainVerified']}),flush=True)


if __name__=='__main__':main()

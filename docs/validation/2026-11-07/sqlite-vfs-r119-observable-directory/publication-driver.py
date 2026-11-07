"""日期：2026-11-08；只修正可检测目录时间戳夹具，不修改产品代码或放宽拒绝断言。"""
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import shutil,subprocess

ROOT=Path.cwd();REPO=ROOT/'.cache/github-29583855-dukto-next-r28';BASE=REPO/'docs/validation/2026-11-07/sqlite-vfs-r119-observable-directory'


# 日期：2026-11-08；Git操作限已授权公开副本，源文件与诊断按字节保存。
def git(*args):return subprocess.check_output(['git',*args],cwd=REPO)


# 日期：2026-11-08；已有文本按原BOM/换行修改，历史失败和未完成范围始终保留。
def edit(name,callback):
    path=ROOT/name;raw=path.read_bytes();bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'';newline='\r\n' if b'\r\n' in raw else '\n'
    old=raw[len(bom):].decode('utf-8').replace('\r\n','\n');new=callback(old);assert old!=new
    path.write_bytes(bom+new.replace('\n',newline).encode('utf-8'));shutil.copyfile(path,REPO/name)


# 日期：2026-11-08；新资格输入只改测试一件，当前产品全部blob与9af提交保持一致。
def main():
    previous=json.loads((ROOT/'.cache/r119-fixed-source-publication.json').read_bytes());assert git('rev-parse','HEAD').decode().strip()==previous['sourceCommit'];assert not git('diff','--cached','--name-only')
    BASE.mkdir(exist_ok=False)
    failure=REPO/'docs/validation/2026-11-07/sqlite-vfs-r119-native-core/ubuntu-22.04'
    assert (failure/'receipt.json').is_file();value=json.loads((failure/'receipt.json').read_bytes());assert not value['qualified']
    shutil.copytree(failure,BASE/'original-ubuntu-core-failure')
    for name in ['r119-directory-fixture-source-audit.json','r119-directory-fixture-msvc.log','r119-directory-fixture-msvc.xml','r119-directory-fixture-build-msvc.log']:
        shutil.copyfile(ROOT/'.cache'/name,BASE/name)
    shutil.copyfile(Path(__file__),BASE/'publication-driver.py')
    path=ROOT/'docs/ci-verification-20261107-r119.json';index=json.loads(path.read_bytes());frozen=[];changed=[]
    for row in index['qualificationInputs']:
        raw=(ROOT/row['path']).read_bytes();digest=hashlib.sha256(raw).hexdigest();frozen.append({'path':row['path'],'bytes':len(raw),'sha256':digest})
        if digest!=row['sha256']:changed.append(row['path'])
    assert changed==['tests/state_storage_tests.cpp'],changed
    shutil.copyfile(ROOT/changed[0],REPO/changed[0])
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(),qualificationInputs=frozen,
                 gitCheckoutFixedSourceCommit=previous['sourceCommit'],observableDirectoryFixtureChangedInputs=changed,
                 previousUbuntuCoreFailureRetained=True,applicationInputsUnchangedByFixtureFix=True,
                 localFullCoreAtPreviousInputs=True,currentWindowsStorageTargetedPassed=True,
                 sourcePublicationPending=True,nativeQualificationPending=True)
    for name in ['r119-directory-fixture-source-audit.json','r119-directory-fixture-msvc.xml']:
        proof=BASE/name;index['receipts'].append({'path':proof.relative_to(REPO).as_posix(),'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()})
    raw=(json.dumps(index,ensure_ascii=False,indent=2)+'\n').encode();path.write_bytes(raw);(REPO/path.relative_to(ROOT)).write_bytes(raw)
    note='- [x] 9af29ca6的Ubuntu新增VFS10条通过，其余28/29核心通过；原state-storage目录变更断言因同一时钟刻度未观察到mtime变化而失败，原件保留。测试显式设置可观测mtime后仍要求Integrity拒绝，不改产品或放宽门槛；本机Windows完整计量专项10通过/1权限跳过，新原生回归继续。\n'
    edit('开发计划与进度.md',lambda text:text.replace('- [ ] R119首次公开de6f38c9及其Windows配置失败保留；检出修正新提交、四原生回归与双Mac包继续，已验Mac预览仍R118。',note+'- [ ] R119原Windows配置失败及Ubuntu目录夹具失败均保留；新夹具修正提交、四原生回归及双Mac包继续，已验Mac预览仍R118。',1))
    edit('docs/执行进度.md',lambda text:text.replace('## R119 固定SQLite运行时与连接VFS（2026-11-07）\n','## R119 固定SQLite运行时与连接VFS（2026-11-07）\n\n2026-11-08补充：Ubuntu VFS10条通过，计量目录变更测试因同一时钟刻度未产生可见mtime变化失败；原28/29核心和失败原件保留。测试显式产生可观测mtime，仍要求Integrity拒绝；产品输入保持。本机Windows完整计量10通过/1权限跳过，新四原生回归继续。\n',1))
    edit('docs/磁盘总配额实施清单.md',lambda text:text+'\nQ01–Q05的具体入口、预算锁/账本和崩溃核对细化见[跨进程磁盘预算设计](跨进程磁盘预算设计.md)，状态仍为待实现。\n')
    shutil.copyfile(ROOT/'docs/跨进程磁盘预算设计.md',REPO/'docs/跨进程磁盘预算设计.md')
    explicit=set(changed)|{'开发计划与进度.md','docs/执行进度.md','docs/磁盘总配额实施清单.md','docs/跨进程磁盘预算设计.md','docs/ci-verification-20261107-r119.json'}
    explicit.update(p.relative_to(REPO).as_posix() for p in BASE.rglob('*') if p.is_file())
    dirty={x.decode() for x in git('diff','--name-only','-z').split(b'\0') if x};assert dirty<=explicit,dirty-explicit
    for offset in range(0,len(explicit),40):git('-c','core.autocrlf=false','add','-f','--',*sorted(explicit)[offset:offset+40])
    git('diff','--cached','--check','--','.',':(exclude)docs/validation');git('commit','-qm','Make directory mutation fixture observe an explicit POSIX timestamp change')
    commit=git('rev-parse','HEAD').decode().strip();env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0'
    result=subprocess.run(['git','-c','http.proxy=http://127.0.0.1:10808','-c','http.lowSpeedLimit=1000','-c','http.lowSpeedTime=30','push','origin','main'],cwd=REPO,env=env,capture_output=True,text=True,timeout=120);assert result.returncode==0,result.stderr
    assert git('-c','http.proxy=http://127.0.0.1:10808','ls-remote','origin','refs/heads/main').decode().split()[0]==commit
    for row in frozen:assert hashlib.sha256(git('show',commit+':'+row['path'])).hexdigest()==row['sha256']
    receipt={'observedUtc':datetime.now(timezone.utc).isoformat(),'sourceCommit':commit,'previousSourceCommit':previous['sourceCommit'],'qualificationInputs':frozen,'inputCount':260,'applicationInputsUnchanged':True,'remoteMainVerified':True,'deliveryComplete':False,'releaseQualified':False}
    p=ROOT/'.cache/r119-observable-source-publication.json';assert not p.exists();p.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    shutil.copytree(BASE,ROOT/BASE.relative_to(REPO));print(json.dumps({key:receipt[key] for key in ['sourceCommit','inputCount','applicationInputsUnchanged','remoteMainVerified']}),flush=True)


if __name__=='__main__':main()

"""日期：2026-11-07；修正Git自动换行导致的原件摘要拒绝，保留首次原生失败。"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path.cwd()
REPO=ROOT/'.cache/github-29583855-dukto-next-r28'
BASE=REPO/'docs/validation/2026-11-07/sqlite-vfs-r119-checkout'


# 日期：2026-11-07；修改文本保持原编码/BOM/换行，只同步明确文件。
def edit(name, callback):
    path=ROOT/name
    raw=path.read_bytes()
    bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline='\r\n' if b'\r\n' in raw else '\n'
    old=raw[len(bom):].decode('utf-8').replace('\r\n','\n')
    new=callback(old)
    assert new!=old
    path.write_bytes(bom+new.replace('\n',newline).encode('utf-8'))
    shutil.copyfile(path,REPO/name)


# 日期：2026-11-07；Git命令只操作任务已授权的公开副本，不改根目录用户文件。
def git(*args):
    return subprocess.check_output(['git',*args],cwd=REPO)


# 日期：2026-11-07；策略只限定vendor目录；源码包保留属性，真实autocrlf检出原件逐字节相同。
def main():
    initial=json.loads((ROOT/'.cache/r119-source-publication.json').read_bytes())
    assert git('rev-parse','HEAD').decode().strip()==initial['sourceCommit']
    assert not git('status','--porcelain')
    BASE.mkdir(exist_ok=False)
    shutil.copytree(ROOT/'.cache/r119-native-first-failure',BASE/'first-native-failure')
    for name in ['r119-checkout-source-audit.json','r119-checkout-source-snapshot.json']:
        shutil.copyfile(ROOT/'.cache'/name,BASE/name)
    shutil.copyfile(Path(__file__),BASE/'publication-driver.py')
    index_path=ROOT/'docs/ci-verification-20261107-r119.json'
    index=json.loads(index_path.read_bytes())
    frozen=[]
    for name in sorted({row['path'] for row in index['qualificationInputs']}|{'.gitattributes'}):
        raw=(ROOT/name).read_bytes()
        frozen.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    old={row['path']:row['sha256'] for row in initial['qualificationInputs']}
    changed=[row['path'] for row in frozen if old.get(row['path'])!=row['sha256']]
    assert set(changed)=={'.gitattributes','scripts/source_snapshot.py','scripts/package_windows.py','tests/source_snapshot_integration.py'}
    for name in changed:
        shutil.copyfile(ROOT/name,REPO/name)
    input_names={row['path'] for row in frozen}
    assert len(frozen)==260
    for row in frozen:
        assert (ROOT/row['path']).read_bytes()==(REPO/row['path']).read_bytes()
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(),qualificationInputs=frozen,inputCount=260,
                 firstSourceCommit=initial['sourceCommit'],firstWindowsConfigureFailureRetained=True,
                 checkoutFixChangedInputs=changed,sourcePublicationPending=True,nativeQualificationPending=True,
                 completeCoreCxxAndCmakeInputsUnchangedByCheckoutFix=True)
    for name in ['r119-checkout-source-audit.json','r119-checkout-source-snapshot.json']:
        path=BASE/name
        index['receipts'].append({'path':path.relative_to(REPO).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    raw=(json.dumps(index,ensure_ascii=False,indent=2)+'\n').encode()
    index_path.write_bytes(raw);(REPO/index_path.relative_to(ROOT)).write_bytes(raw)
    note='- [x] 首次原生Windows配置因Git autocrlf改写第三方原件而被固定摘要拒绝；原失败保留。新增仅vendor目录的-text属性及源码包/快照保留规则，真实Git autocrlf=true检出逐字节通过；C++/CMake输入保持，资格输入增至260份，新提交重新原生验证。\n'
    edit('开发计划与进度.md',lambda text:text.replace('- [ ] R119精确提交公开、四原生完整回归及新双Mac编译/含依赖包继续；现有已验Mac预览为R118。',note+'- [ ] R119首次公开de6f38c9及其Windows配置失败保留；检出修正新提交、四原生回归与双Mac包继续，已验Mac预览仍R118。',1))
    edit('docs/执行进度.md',lambda text:text.replace('## R119 固定SQLite运行时与连接VFS（2026-11-07）\n','## R119 固定SQLite运行时与连接VFS（2026-11-07）\n\n首次公开de6f38c9的Windows配置被上游源码摘要拒绝，原因是Git自动换行。原失败保留，vendor目录新增保留原字节属性；真实autocrlf=true检出、快照/对应源码包保留属性及依赖均通过。C++/CMake输入不变，260份输入按新提交另验。\n',1))
    edit('README.md',lambda text:text.replace('259份输入冻结，新原生构建继续。','首次259份输入已公开，Windows自动换行导致摘要拒绝的原失败保留；检出修正后260份输入重新原生验证。',1))
    edit('docs/SQLite运行时与写入拦截.md',lambda text:text+'\nGit检出时third-party/sqlite-runtime目录使用-text属性保留原件字节，源码快照和对应源码包均保留.gitattributes。真实Git core.autocrlf=true检出验证通过；首次Windows配置摘要拒绝及原日志继续保留。\n')
    explicit=set(changed)|{'开发计划与进度.md','docs/执行进度.md','README.md','docs/SQLite运行时与写入拦截.md','docs/ci-verification-20261107-r119.json'}
    explicit.update(path.relative_to(REPO).as_posix() for path in BASE.rglob('*') if path.is_file())
    for offset in range(0,len(explicit),40):git('-c','core.autocrlf=false','add','-f','--',*sorted(explicit)[offset:offset+40])
    staged={value.decode() for value in git('diff','--cached','--name-only','-z').split(b'\0') if value}
    assert staged==explicit
    git('diff','--cached','--check','--','.',':(exclude)docs/validation')
    git('commit','-qm','Preserve pinned upstream SQLite driver bytes across Windows Git checkout')
    commit=git('rev-parse','HEAD').decode().strip()
    env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0'
    result=subprocess.run(['git','-c','http.proxy=http://127.0.0.1:10808','-c','http.lowSpeedLimit=1000','-c','http.lowSpeedTime=30','push','origin','main'],cwd=REPO,env=env,capture_output=True,text=True,timeout=120)
    assert result.returncode==0,result.stderr
    assert git('-c','http.proxy=http://127.0.0.1:10808','ls-remote','origin','refs/heads/main').decode().split()[0]==commit
    for row in frozen:
        assert hashlib.sha256(git('show',commit+':'+row['path'])).hexdigest()==row['sha256']
    assert not git('status','--porcelain')
    receipt={'observedUtc':datetime.now(timezone.utc).isoformat(),'sourceCommit':commit,'firstSourceCommit':initial['sourceCommit'],
             'qualificationInputs':frozen,'inputCount':260,'changedInputs':changed,'remoteMainVerified':True,
             'completeCoreCxxAndCmakeInputsUnchanged':True,'firstWindowsConfigureFailureRetained':True,
             'deliveryComplete':False,'releaseQualified':False}
    path=ROOT/'.cache/r119-fixed-source-publication.json';assert not path.exists()
    path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    shutil.copytree(BASE,ROOT/BASE.relative_to(REPO))
    print(json.dumps({key:receipt[key] for key in ['sourceCommit','remoteMainVerified','inputCount','completeCoreCxxAndCmakeInputsUnchanged']}),flush=True)


if __name__=='__main__':
    main()

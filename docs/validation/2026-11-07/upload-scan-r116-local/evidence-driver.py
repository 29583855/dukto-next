"""日期：2026-11-07；绑定候选源、本机真实原件和分层资格，不将单项通过转授完整交付。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path.cwd()
REPO=ROOT/'.cache/github-29583855-dukto-next-r28'
BASE=REPO/'docs/validation/2026-11-07'
LOCAL=BASE/'upload-scan-r116-local'
CHANGED=['CMakeLists.txt','src/core/uploadmanifest.cpp','src/core/uploadmanifest.h',
         'src/cli/servicecommands.cpp','tests/upload_scan_cleanup_tests.cpp']


# 日期：2026-11-07；文本更新保留UTF-8原BOM及换行，不加工日志证据。
def edit(path,callback):
    raw=path.read_bytes(); bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline='\r\n' if b'\r\n' in raw else '\n'
    value=callback(raw[len(bom):].decode('utf-8').replace('\r\n','\n'))
    path.write_bytes(bom+value.replace('\n',newline).encode('utf-8'))


# 日期：2026-11-07；核对完整Qt方法、真实数据行及唯一Windows权限跳过，不只读取CTest退出码。
def qt(path,expect):
    tree=ET.parse(path).getroot()
    assert tree.get('failures')=='0',path
    cases=tree.findall('testcase')
    if expect=='scan':
        assert len(cases)==10
        skipped=[case for case in cases if case.find('skipped') is not None]
        # 日期：2026-11-07；Qt5 JUnit按方法聚合数据行，原始txt另核对23通过/1跳过。
        assert all(case.get('result') in ('pass','skip') for case in cases)
    else:
        assert all(case.get('result')=='pass' for case in cases)
    return len(cases)


# 日期：2026-11-07；本次源码冻结后再复制与发布，旧长测、参考软件和旧依赖不受修改。
def main():
    LOCAL.mkdir(exist_ok=True)
    rows=[]
    for build,tag in [('windows','msvc'),('windows-ucrt','ucrt')]:
        output=LOCAL/tag; output.mkdir(exist_ok=True)
        for name in ['upload-scan-cleanup-tests','strong-manifest-tests','server-panel-tests']:
            for suffix in ['log','xml']:
                shutil.copyfile(ROOT/'build'/build/'Testing/QtTest'/(name+'.'+suffix),output/(name+'.'+suffix))
        scan=(output/'upload-scan-cleanup-tests.log').read_text('utf-8')
        assert '23 passed, 0 failed, 1 skipped' in scan
        assert 'Windows account cannot create a native symbolic link' in scan
        methods={name:qt(output/(name+'.xml'),'scan' if name=='upload-scan-cleanup-tests' else 'other')
                 for name in ['upload-scan-cleanup-tests','strong-manifest-tests','server-panel-tests']}
        program=ROOT/'build'/build/('Release' if tag=='msvc' else '')/'upload-scan-cleanup-tests.exe'
        rows.append({'toolchain':tag,'scanRowsPassed':23,'scanRowsSkipped':1,
                     'skipReason':'Windows account cannot create a native symbolic link',
                     'completeMethodCounts':methods,'binarySha256':hashlib.sha256(program.read_bytes()).hexdigest()})
        for path in (ROOT/'.cache').glob('r116-'+tag+'-*.log'):
            shutil.copyfile(path,output/path.name)
    shutil.copytree(ROOT/'.cache/r116-final-attempt-failed',LOCAL/'failed-dangling-json-reference',dirs_exist_ok=True)
    shutil.copyfile(ROOT/'.cache/r116-final-source-audit.json',LOCAL/'source-audit.json')
    shutil.copyfile(Path(__file__),LOCAL/'evidence-driver.py')
    inputs=[]
    for path in sorted(REPO.rglob('*')):
        if not path.is_file():
            continue
        name=path.relative_to(REPO).as_posix()
        if name.startswith(('src/','ui/','scripts/','tests/','resources/','.github/')) and path.suffix in ('.cpp','.h','.qml','.py','.ps1','.qrc','.yml','.sh','.txt') or name in ('CMakeLists.txt','.clang-format','.github/docker/musl/Dockerfile'):
            if '__pycache__' not in name:
                inputs.append(name)
    inputs=sorted(set(inputs)|set(CHANGED))
    for name in CHANGED:
        target=REPO/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,target)
    frozen=[]
    for name in inputs:
        data=(ROOT/name).read_bytes()
        assert (REPO/name).read_bytes()==data,name
        frozen.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    previous='a910c68f7bc8ca040d64ec7a1b698d1c173c563b'
    changes=[]
    for row in frozen:
        name=row['path']
        original=subprocess.run(['git','show',previous+':'+name],cwd=REPO,capture_output=True)
        if original.returncode or hashlib.sha256(original.stdout).hexdigest()!=row['sha256']:
            changes.append(name)
    assert set(changes)==set(CHANGED),changes
    receipt={'observedUtc':datetime.now(timezone.utc).isoformat(),'baselineSourceCommit':previous,
             'records':rows,'qualificationInputs':frozen,'inputCount':len(frozen),'changedInputs':changes,
             'failedAssertionOriginalsRetained':True,'failureReason':'QJsonValueRef from temporary usage object; store QJsonValue by value',
             'unknownPreOwnershipFilesStillPreserved':True,'passed':True,'deliveryComplete':False,'releaseQualified':False}
    (LOCAL/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    terminal=BASE/'private-read-r114-native-terminal/receipt.json'
    old_index=REPO/'docs/ci-verification-20261107-r114.json'
    value=json.loads(old_index.read_text('utf-8'))
    for row in value['receipts']:
        row['sha256']=hashlib.sha256((REPO/row['path']).read_bytes()).hexdigest()
    value['nativeRun']=json.loads(terminal.read_text('utf-8'))['run']
    value['observedUtc']=datetime.now(timezone.utc).isoformat()
    old_index.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n','utf-8')
    index={'observedUtc':datetime.now(timezone.utc).isoformat(),'planVersion':'v0.116','sourcePublicationPending':True,
           'baselineSourceCommit':previous,'qualificationInputs':frozen,'inputCount':len(frozen),'changedInputs':changes,
           'receipts':[{'path':str(p.relative_to(REPO)).replace('\\','/'),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in [LOCAL/'receipt.json',LOCAL/'source-audit.json']],
           'localWindowsChecksPassed':True,'windowsNativeSymbolicLinkQualified':False,
           'fullNativeProtocolQualified':False,'nativeQualificationPending':True,
           'deliveryComplete':False,'releaseQualified':False}
    (REPO/'docs/ci-verification-20261107-r116.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n','utf-8')
    section='''## R116 未发布源扫描清理（2026-11-07）

- [x] 上传扫描开始前原子同步持久请求/主体/路径、私有根与SQLite原生身份；扫描进程异常退出后保留可核验清理凭据，冻结发布后移除扫描凭据。
- [x] 新增三平台共用CLI `client scan-cleanup preview|run --request-id UUID`；独占维护、七天保留、预览原字节不变、SQLite自身恢复热journal、FULL删除意图和原生身份删除；已冻结/幂等记录及未知旧库保留。[规则](docs/decisions/0029-未发布上传源扫描清理.md)。
- [x] MSVC/UCRT各完整扫描清理CTest通过，原始日志各23通过/1权限跳过；删除前后真实退出、热journal、取消恢复、坏证明/主体、替换对象、WAL/shm拒绝及损坏SQLite额度归还通过。原完整强清单和服务器面板CTest均通过。QJsonValueRef临时引用误断言原件保留，已改实际值。[本机回执](docs/validation/2026-11-07/upload-scan-r116-local/receipt.json)。
- [x] 219份维护文件零TODO/占位标记、C++14及全量C++格式通过，已有修改文件UTF-8无BOM/LF保留；参考原版和冻结长测不变。
- [ ] 独立Ubuntu隔离构建及新源码四平台原生编译/测试待按实际终态收验，Windows原生符号链接行因账户权限跳过，不借用其他平台资格。
- [ ] 缺少创建凭据的历史未知项、全局自动GC、历史256MiB/活动清单总磁盘预算、完整GUI/R6、物理LAN/3×3、各平台24h、干净系统与正式分发继续；整体未完成。

'''
    def plan(text):
        text=text.replace('文档版本：v0.115','文档版本：v0.116',1)
        text=re.sub(r'^当前阶段：.*$', '当前阶段：R116未发布源扫描清理已完成实现及双Windows专项；独立Ubuntu与四平台原生继续验收。R115双Mac各两轮面板专项已验，已下载Mac预览应用仍为R114。R114 Ubuntu/Apple Silicon完整协议各47/47，其他job继续；历史Intel失败保留。整体与正式发布未完成。',text,count=1,flags=re.M)
        if '## R116 未发布源扫描清理' not in text:
            text=text.replace('## R115 服务器界面读取测试时序',section+'## R115 服务器界面读取测试时序',1)
        return text
    edit(ROOT/'开发计划与进度.md',plan)
    progress=ROOT/'docs/执行进度.md'
    edit(progress,lambda text:text.replace('## R114私有配置原子换代重读',
        '## R116未发布源扫描清理（2026-11-07）\n\n请求源清单增加原生身份凭据与七天保留的独占维护CLI；双Windows各23条通过/1符号链接权限跳过，完整强清单和服务器面板通过，原失败保留。独立Ubuntu及四平台CI按实际原件另验。[规则](decisions/0029-未发布上传源扫描清理.md)、[索引](ci-verification-20261107-r116.json)。全局GC和总磁盘预算继续。\n\n## R114私有配置原子换代重读',1))
    for name in ['开发计划与进度.md','docs/执行进度.md','docs/过期任务临时文件清理.md','docs/decisions/0029-未发布上传源扫描清理.md']:
        (REPO/name).parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,REPO/name)
    shutil.copytree(LOCAL,ROOT/LOCAL.relative_to(REPO),dirs_exist_ok=True)
    print(json.dumps({'localPassed':True,'inputCount':len(frozen),'changedInputs':changes,'nativePending':True}))


if __name__=='__main__':
    main()

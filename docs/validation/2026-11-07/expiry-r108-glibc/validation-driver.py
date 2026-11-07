"""日期：2026-11-07；独立Ubuntu重新从精确源码编译，验证过期清理、原幂等和任务租约边界。"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import runpy
import shutil
import subprocess
import tarfile


# 日期：2026-11-07；只使用新的隔离源码/构建目录，不改动旧诊断和冻结长测文件。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/expiry-r108-glibc'
    output.mkdir(exist_ok=False)
    snapshot = runpy.run_path('scripts/source_snapshot.py')
    archive = root / '.cache/source-expiry-r108.tar.gz'
    snapshot['create'](root, archive)
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    for local, remote in [(archive, '/home/dukto/source-expiry-r108.tar.gz'),
                          (root / 'scripts/source_snapshot.py', '/home/dukto/source-install-expiry-r108.py')]:
        with local.open('rb') as data:
            subprocess.run(ssh + ['set -C; cat > ' + remote], stdin=data, check=True, timeout=120)
    program = r'''
from pathlib import Path
import hashlib,json,os,runpy,subprocess,time
root=Path('/home/dukto/expiry-r108');root.mkdir(exist_ok=False)
runpy.run_path('/home/dukto/source-install-expiry-r108.py')['install'](root,Path('/home/dukto/source-expiry-r108.tar.gz'))
output=root/'results';output.mkdir();runtime=root/'runtime';runtime.mkdir(mode=0o700)
env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',XDG_RUNTIME_DIR=str(runtime));rows=[]
# 日期：2026-11-07；实际命令结束即记录，保留原门槛、失败及stderr。
def check(name,args,timeout=1800):
    started=time.monotonic()
    with (output/(name+'.log')).open('xb') as log:
        p=subprocess.run(args,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    rows.append({'name':name,'exitCode':p.returncode,'seconds':round(time.monotonic()-started,3)})
    (output/'exit-codes.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(rows[-1]),flush=True);return p.returncode
assert check('configure',['cmake','-S','.','-B','build','-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DDUKTO_BUILD_GUI=OFF'])==0
assert check('build',['cmake','--build','build','--target','dukto-cli','task-store-tests','task-store-probe','expired-task-cleanup-tests','--parallel','2'])==0
before={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in ('dukto-cli','task-store-tests','expired-task-cleanup-tests')}
check('cleanup-core',['ctest','--test-dir','build','-R','task-store-tests|expired-task-cleanup-tests','--output-on-failure'])
check('task-store-processes',['python3','-X','utf8','tests/task_store_integration.py',str(root/'build/dukto-cli').replace('dukto-cli','task-store-probe'),'--report',str(output/'task-store-processes.json')],600)

import shutil
shutil.copytree(root/'build/Testing',output/'Testing')
after={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in before};assert before==after
value={'cases':rows,'binarySha256':before,'binaryUnchanged':True,'independentFullCoreSuiteRun':False,'passed':all(row['exitCode']==0 for row in rows),'releaseQualified':False,'deliveryComplete':False}
(output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');raise SystemExit(0 if value['passed'] else 1)
'''
    with (output / 'remote-driver.log').open('xb') as log:
        code = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), stdout=log, stderr=subprocess.STDOUT, timeout=7200).returncode
    with (output / 'results.tar.gz').open('xb') as data:
        collected = subprocess.run(ssh + ['tar czf - -C /home/dukto/expiry-r108 results'], stdout=data, stderr=subprocess.PIPE, timeout=120)
    (output / 'collection.stderr').write_bytes(collected.stderr)
    with tarfile.open(output / 'results.tar.gz') as data:
        for member in data:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            assert member.isdir() or member.isfile()
            if member.isfile():
                assert member.size <= 8 * 1024**2
                target = output / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.extractfile(member).read())
    (output / 'remote-driver.py').write_text(program, 'utf-8')
    shutil.copyfile(__file__, output / 'validation-driver.py')
    value = {'remoteExitCode': code, 'collectionExitCode': collected.returncode, 'sourceSnapshotSha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'passed': code == collected.returncode == 0, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'collection-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    return code or collected.returncode


if __name__ == '__main__':
    raise SystemExit(main())

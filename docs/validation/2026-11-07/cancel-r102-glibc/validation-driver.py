"""日期：2026-11-07；在独立Ubuntu目录对照慢端旧夹具与新夹具，不触及现有长测或冻结二进制。"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import tarfile


# 日期：2026-11-07；新目录干净构建旧夹具，再按摘要更新唯一测试输入并执行完整核心和原生三场景。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/cancel-r102-glibc'
    output.mkdir(exist_ok=False)
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    snapshot = runpy.run_path('scripts/source_snapshot.py')
    baseline = root / '.cache/source-cancel-r102-baseline.tar.gz'
    fixed = root / '.cache/source-cancel-r102-fixed.tar.gz'
    snapshot['create'](root, fixed)
    before = snapshot['read_archive'](baseline)[0]['files']
    after = snapshot['read_archive'](fixed)[0]['files']
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    assert changed == ['tests/ui_tests.cpp'], changed
    for path in (baseline, fixed):
        with path.open('rb') as data:
            subprocess.run(ssh + ['set -C; cat > /home/dukto/' + path.name], stdin=data, check=True, timeout=120)
    installer = root / 'scripts/source_snapshot.py'
    with installer.open('rb') as data:
        subprocess.run(ssh + ['set -C; cat > /home/dukto/source-install-cancel-r102.py'], stdin=data, check=True, timeout=30)
    program = r'''
import hashlib,json,os,runpy,subprocess
from pathlib import Path
root=Path('/home/dukto/cancel-r102-fixture')
root.mkdir(exist_ok=False)
output=root/'results'
output.mkdir()
install=runpy.run_path('/home/dukto/source-install-cancel-r102.py')['install']
env=os.environ.copy()
runtime=root/'runtime'
runtime.mkdir(mode=0o700)
env.update(QT_QPA_PLATFORM='offscreen',XDG_RUNTIME_DIR=str(runtime))
rows=[]
# 日期：2026-11-07；每项先保全真实退出码再执行后项，旧失败不会被新夹具结果覆盖。
def check(name,args,timeout=1800):
    with (output/(name+'.log')).open('xb') as log:
        p=subprocess.run(args,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    rows.append({'name':name,'exitCode':p.returncode})
    (output/'exit-codes.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows[-1]),flush=True)
    return p.returncode
install(root,Path('/home/dukto/source-cancel-r102-baseline.tar.gz'))
assert check('baseline-configure',['cmake','-S','.','-B','build','-G','Ninja','-DCMAKE_BUILD_TYPE=Release'])==0
assert check('baseline-build',['cmake','--build','build','--target','ui-tests','--parallel','2'])==0
for i in range(3):
    check('baseline-send-'+str(i),[str(root/'build/ui-tests'),'cancelThenTransferAgainThroughQml:send',
        '-o',str(output/('baseline-send-'+str(i)+'.txt'))+',txt',
        '-o',str(output/('baseline-send-'+str(i)+'.xml'))+',junitxml'],120)
change=install(root,Path('/home/dukto/source-cancel-r102-fixed.tar.gz'))
assert change['updated']==['tests/ui_tests.cpp']
(output/'source-update.json').write_text(json.dumps(change,indent=2)+'\n')
assert check('fixed-build',['cmake','--build','build','--parallel','2'])==0
before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'build/ui-tests',root/'build/dukto-cli')}
check('fixed-ctest',['ctest','--test-dir','build','--output-on-failure'],3600)
check('fixed-native',['xvfb-run','-a','python3','-X','utf8','tests/main_window_navigation_integration.py',
    str(root/'build/ui-tests'),'--platform','xcb','--report',str(output/'native-navigation.json')],300)
for i in range(10):
    check('fixed-cancel-'+str(i),[str(root/'build/ui-tests'),'cancelThenTransferAgainThroughQml',
        '-o',str(output/('fixed-cancel-'+str(i)+'.txt'))+',txt',
        '-o',str(output/('fixed-cancel-'+str(i)+'.xml'))+',junitxml'],120)
after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'build/ui-tests',root/'build/dukto-cli')}
assert before==after
fixed_rows=[row for row in rows if row['name'].startswith('fixed-')]
value={'date':'2026-11-07','actualPlatform':'Ubuntu glibc','baselineCases':rows[2:5],
    'fixedCases':fixed_rows,'binarySha256':before,'binaryUnchanged':True,
    'changedInputs':['tests/ui_tests.cpp'],'productionCoreChanged':False,
    'cancellationAndEofBudgetMilliseconds':5000,
    'passed':all(row['exitCode']==0 for row in fixed_rows),
    'releaseQualified':False,'deliveryComplete':False}
(output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n')
raise SystemExit(0 if value['passed'] else 1)
'''
    with (output / 'remote-driver.log').open('xb') as log:
        code = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), stdout=log,
                              stderr=subprocess.STDOUT, timeout=10800).returncode
    archive = output / 'results.tar.gz'
    with archive.open('xb') as data:
        subprocess.run(ssh + ['tar czf - -C /home/dukto/cancel-r102-fixture results build/Testing/QtTest build/Testing/Temporary/LastTest.log'],
                       stdout=data, check=True, timeout=120)
    with tarfile.open(archive) as data:
        for member in data:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            assert member.isdir() or member.isfile()
            if member.isfile():
                assert member.size <= 32 * 1024**2
                target = output / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data.extractfile(member).read())
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    result = {'remoteExitCode': code, 'changedBuildInputs': changed,
              'baselineSnapshotSha256': hashlib.sha256(baseline.read_bytes()).hexdigest(),
              'fixedSnapshotSha256': hashlib.sha256(fixed.read_bytes()).hexdigest(),
              'passed': code == 0, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'collection-result.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps(result), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

"""日期：2026-11-07；仅修正独立Ubuntu迁移测试夹具，在新目录验证同一原生二进制。"""
from pathlib import Path
import hashlib
import json
import runpy
import subprocess


# 日期：2026-11-07；保留原失败及VM源码不变，仅将已核验新夹具复制到独立重验目录。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/expiry-r108-glibc-migration-v3'
    output.mkdir(exist_ok=False)
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    subprocess.run(ssh + ['mkdir -m 700 /home/dukto/expiry-r108-migration-v3'], check=True, timeout=30)
    fixture = root / 'tests/task_store_integration.py'
    with fixture.open('rb') as data:
        subprocess.run(ssh + ['set -C; cat > /home/dukto/expiry-r108-migration-v3/task_store_integration.py'],
                       stdin=data, check=True, timeout=45)
    program = r'''
from pathlib import Path
import hashlib,json,subprocess,time
root=Path('/home/dukto/expiry-r108'); out=Path('/home/dukto/expiry-r108-migration-v3')
names=['dukto-cli','task-store-tests','expired-task-cleanup-tests','task-store-probe']
before={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in names}
started=time.monotonic()
with (out/'migration.log').open('xb') as log:
    code=subprocess.run(['python3','-X','utf8',str(out/'task_store_integration.py'),str(root/'build/task-store-probe'),'--report',str(out/'migration.json')],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
after={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in names}
assert before==after
result={'exitCode':code,'seconds':round(time.monotonic()-started,3),'binarySha256':before,'binaryUnchanged':True,'fixtureSha256':hashlib.sha256((out/'task_store_integration.py').read_bytes()).hexdigest(),'passed':code==0,'releaseQualified':False,'deliveryComplete':False}
(out/'recheck-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result),flush=True)
raise SystemExit(code)
'''
    with (output / 'driver.log').open('xb') as log:
        process = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), stdout=log,
                                 stderr=subprocess.STDOUT, timeout=700)
    for name in ('migration.json', 'migration.log', 'recheck-result.json', 'task_store_integration.py'):
        result = subprocess.run(ssh + ['cat /home/dukto/expiry-r108-migration-v3/' + name], capture_output=True, timeout=45)
        assert result.returncode == 0 and not result.stderr
        (output / name).write_bytes(result.stdout)
    result = json.loads((output / 'recheck-result.json').read_text('utf-8'))
    assert result['fixtureSha256'] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    (output / 'remote-driver.py').write_text(program, 'utf-8')
    (output / 'validation-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'actualRecheckExitCode': process.returncode, 'binaryUnchanged': result['binaryUnchanged'], 'passed': result['passed']}))
    return process.returncode


if __name__ == '__main__':
    raise SystemExit(main())

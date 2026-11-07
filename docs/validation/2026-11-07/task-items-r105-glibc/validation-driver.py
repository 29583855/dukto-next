"""日期：2026-11-07；隔离复验逐项查询夹具，不修改正在验证的Ubuntu源码或二进制。"""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import runpy
import shutil
import subprocess
import tarfile


# 日期：2026-11-07；全部测试辅助脚本冻结至独立目录；真实退出和前后摘要保留，原失败不覆盖。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/task-items-r105-glibc'
    output.mkdir(exist_ok=False)
    remote = '/home/dukto/task-items-r105'
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    archive = output / 'test-inputs.tar.gz'
    inputs = {}
    with tarfile.open(archive, 'x:gz') as target:
        for path in sorted((root / 'tests').glob('*.py')):
            raw = path.read_bytes()
            name = 'tests/' + path.name
            inputs[name] = hashlib.sha256(raw).hexdigest()
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(raw), 0o644
            target.addfile(member, io.BytesIO(raw))
    (output / 'test-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', 'utf-8')
    with archive.open('rb') as data:
        subprocess.run(ssh + ['set -C; cat > /home/dukto/task-items-r105-inputs.tar.gz'],
                       stdin=data, check=True, timeout=120)
    program = r'''
from pathlib import Path, PurePosixPath
import hashlib,json,os,subprocess,tarfile
root=Path('/home/dukto/task-items-r105');root.mkdir(exist_ok=False)
with tarfile.open('/home/dukto/task-items-r105-inputs.tar.gz') as archive:
 for member in archive:
  path=PurePosixPath(member.name)
  assert member.isfile() and len(path.parts)==2 and path.parts[0]=='tests' and path.suffix=='.py'
  assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name and member.size<=1024**2
  target=root/member.name;target.parent.mkdir(exist_ok=True);target.write_bytes(archive.extractfile(member).read())
binary=Path('/home/dukto/state-use-r104/build/dukto-cli');script=root/'tests/task_items_integration.py'
before=hashlib.sha256(binary.read_bytes()).hexdigest();script_before=hashlib.sha256(script.read_bytes()).hexdigest()
env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen'
with (root/'task-items.log').open('xb') as log:
 code=subprocess.run(['python3','-X','utf8',str(script),str(binary),'--report',str(root/'task-items.json')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
assert hashlib.sha256(binary.read_bytes()).hexdigest()==before and hashlib.sha256(script.read_bytes()).hexdigest()==script_before
value={'exitCode':code,'binarySha256':before,'scriptSha256':script_before,'binaryUnchanged':True,'productionCodeChangedForFixtureCorrection':False,'passed':code==0,'releaseQualified':False,'deliveryComplete':False}
(root/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n');print(json.dumps(value),flush=True);raise SystemExit(code)
'''
    with (output / 'remote-driver.log').open('xb') as log:
        code = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'),
                              stdout=log, stderr=subprocess.STDOUT, timeout=900).returncode
    result = output / 'results.tar.gz'
    with result.open('xb') as data:
        subprocess.run(ssh + ['tar czf - -C ' + remote + ' task-items.log task-items.json driver-result.json'],
                       stdout=data, check=True, timeout=120)
    with tarfile.open(result) as archive_data:
        for member in archive_data:
            path = PurePosixPath(member.name)
            assert member.isfile() and len(path.parts) == 1 and member.size <= 32 * 1024**2
            assert path.name in ('task-items.log', 'task-items.json', 'driver-result.json')
            (output / path.name).write_bytes(archive_data.extractfile(member).read())
    value = json.loads((output / 'driver-result.json').read_text('utf-8'))
    assert value['exitCode'] == code and value['scriptSha256'] == inputs['tests/task_items_integration.py']
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    print(json.dumps(value), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

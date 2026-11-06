"""日期：2026-11-06；原两个发现测试函数逐字节提取，对照旧/新生产源码，完整构建继续独立进行。"""
from pathlib import Path
import base64
import hashlib
import json
import runpy
import subprocess


# 日期：2026-11-06；只提取原测试方法，不修改5000次链、数量、断言或时间门槛。
def main():
    out = Path('docs/validation/2026-11-06/discovery-r92-focused-musl')
    out.mkdir(exist_ok=False)
    original = Path('tests/core_tests.cpp').read_bytes()
    start = original.index(b'    void discoveryYieldsAndRejectsMalformedGoodbye()')
    end = original.index('    // 日期：2026-11-04；取消等待数据的接收任务'.encode('utf-8'), start)
    methods = original[start:end]
    prefix = ('#include "discovery.h"\n#include <QtTest>\n'
              'class CoreTests final : public QObject {\n Q_OBJECT\n private slots:\n'
              ' // 日期：2026-11-06；以下两个方法原字节提取，使用真实UDP与原门槛。\n')
    harness = prefix.encode('utf-8') + methods + b'};\nQTEST_GUILESS_MAIN(CoreTests)\n#include "probe.moc"\n'
    files = {'probe.cpp': harness, 'discovery.h': Path('src/core/discovery.h').read_bytes(),
             'discovery-before.cpp': Path('.cache/discovery-before-r92.cpp').read_bytes(),
             'discovery-after.cpp': Path('src/core/discovery.cpp').read_bytes()}
    for name, value in files.items():
        (out / name).write_bytes(value)
    remote = r'''
from pathlib import Path
import base64,hashlib,json,shlex,subprocess,time
root=Path('/home/dukto/discovery-r92-focused-musl');root.mkdir(exist_ok=False)
for name,value in FILES.items(): (root/name).write_bytes(base64.b64decode(value))
flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','Qt5Test','Qt5Network','Qt5Core'],text=True))
subprocess.run(['moc','probe.cpp','-o','probe.moc'],cwd=root,check=True)
subprocess.run(['moc','discovery.h','-o','moc_discovery.cpp'],cwd=root,check=True)
results=[]
for label in ['before','after']:
 with (root/(label+'-build.log')).open('xb') as log:
  code=subprocess.run(['c++','-std=c++14','-fPIC','probe.cpp','discovery-'+label+'.cpp','moc_discovery.cpp','-o',label,*flags],cwd=root,stdout=log,stderr=subprocess.STDOUT).returncode
 assert code==0,(root/(label+'-build.log')).read_text()
 for attempt in range(1 if label=='before' else 3):
  name=label+'-'+str(attempt+1)
  started=time.monotonic()
  with (root/(name+'.log')).open('xb') as log:
   code=subprocess.run([str(root/label),'-o',str(root/(name+'.xml'))+',junitxml','-o','-,txt'],stdout=log,stderr=subprocess.STDOUT,timeout=120).returncode
  results.append({'label':label,'attempt':attempt+1,'exitCode':code,'seconds':round(time.monotonic()-started,3),'xml':(root/(name+'.xml')).read_text(),'log':(root/(name+'.log')).read_text()})
print(json.dumps({'results':results,'buildLogs':{label:(root/(label+'-build.log')).read_text() for label in ['before','after']}}))
'''.replace('FILES', repr({k: base64.b64encode(v).decode('ascii') for k, v in files.items()}))
    ssh = runpy.run_path('.cache/validate-data-file-r90-musl.py')['SSH']
    result = subprocess.run(ssh + ['python3 -'], input=remote.encode('utf-8'), capture_output=True, timeout=600)
    (out / 'driver.log').write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr.decode()
    value = json.loads(result.stdout)
    for row in value['results']:
        for suffix in ('xml', 'log'):
            (out / (row['label'] + '-' + str(row['attempt']) + '.' + suffix)).write_text(row.pop(suffix), 'utf-8', newline='\n')
    value.update(date='2026-11-06', originalMethodsSha256=hashlib.sha256(methods).hexdigest(),
                 originalTestsFileSha256=hashlib.sha256(original).hexdigest(),
                 originalMethodBytesUnchanged=True, completeCoreSuiteQualified=False,
                 inputs={k: hashlib.sha256(v).hexdigest() for k, v in files.items()}, deliveryComplete=False)
    (out / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()

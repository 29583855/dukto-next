"""日期：2026-11-08；双Windows构建并执行持久配置/真实CLI及故障恢复专项，原失败原件单独保留。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-08；每次新目录记录构建/测试退出码、源码和二进制前后摘要，失败不授予专项资格。
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('tag', choices=['msvc','ucrt'])
    parser.add_argument('--name', default='second')
    args=parser.parse_args()
    root=Path.cwd();out=root/('.cache/r125-'+args.name+'-'+args.tag);out.mkdir(exist_ok=False)
    names={row['path'] for row in json.loads((root/'docs/ci-verification-20261108-r124.json').read_bytes())['qualificationInputs']} | {'src/cli/statecommands.cpp','src/cli/statecommands.h','tests/budget_configuration_tests.cpp'}
    before={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sorted(names)}
    env=os.environ.copy()
    bins=['.tools/Qt/5.15.2/msvc2019_64/bin','.tools/openssl/Library/bin'] if args.tag=='msvc' else ['.tools/msys64/ucrt64/bin']
    env['PATH']=os.pathsep.join(str(root/name) for name in bins)+os.pathsep+env['PATH']
    build=root/('build/windows' if args.tag=='msvc' else 'build/windows-ucrt')
    program=build/('Release' if args.tag=='msvc' else '')
    value={'observedUtc':datetime.now(timezone.utc).isoformat(),'inputs':before,'toolchain':args.tag,'passed':False,'globalQuotaEnforced':False,'deliveryComplete':False,'releaseQualified':False}
    with (out/'build.log').open('xb') as log:
        r=subprocess.run([str(root/'.tools/python/Scripts/cmake.exe'),'--build',str(build),'--config','Release','--target','budget-configuration-tests','state-budget-tests','state-domain-tests','--parallel','3'],env=env,stdout=log,stderr=subprocess.STDOUT)
    value['buildExitCode']=r.returncode
    if r.returncode==0:
        binaries=[program/(name+'.exe') for name in ['dukto-cli','budget-configuration-tests','state-budget-tests','state-domain-tests']]
        value['binariesBefore']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in binaries}
        records=[]
        for path in binaries[1:]:
            with (out/(path.stem+'-driver.log')).open('xb') as log:
                r=subprocess.run([str(path),'-o',str(out/(path.stem+'.xml'))+',xml','-o',str(out/(path.stem+'.log'))+',txt'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
            records.append({'name':path.stem,'exitCode':r.returncode})
        value['tests']=records
        value['binariesAfter']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in binaries}
        value['passed']=all(row['exitCode']==0 for row in records) and value['binariesBefore']==value['binariesAfter']
    value['inputsAfter']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in before}
    value['passed']=value['passed'] and before==value['inputsAfter']
    (out/'receipt.json').write_text(json.dumps(value,indent=2)+'\n','utf-8')
    print(json.dumps({key:value.get(key) for key in ['toolchain','buildExitCode','tests','passed']}),flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__=='__main__':
    main()

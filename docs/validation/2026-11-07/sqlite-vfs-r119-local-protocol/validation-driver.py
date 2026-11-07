"""日期：2026-11-07；固定新引擎实际CLI执行旧版/TLS16通道及覆盖恢复，不替代完整原生协议。"""
import argparse
from datetime import datetime, timezone
import hashlib,json,os
from pathlib import Path
import subprocess,sys,time


# 日期：2026-11-07；分工具链独立原件，固定运行库和二进制，保留各失败并继续独立专项。
def main():
    parser=argparse.ArgumentParser();parser.add_argument('toolchain',choices=['msvc','ucrt']);tag=parser.parse_args().toolchain
    root=Path.cwd();out=root/'.cache'/('r119-protocol-'+tag);out.mkdir()
    cli=root/('build/windows/Release/dukto-cli.exe' if tag=='msvc' else 'build/windows-ucrt/dukto-cli.exe')
    env=os.environ.copy();paths=['.tools/Qt/5.15.2/msvc2019_64/bin','.tools/openssl/Library/bin'] if tag=='msvc' else ['.tools/msys64/ucrt64/bin']
    env['PATH']=os.pathsep.join(str(root/path) for path in paths)+os.pathsep+env['PATH'];env['QT_QPA_PLATFORM']='offscreen'
    initial=hashlib.sha256(cli.read_bytes()).hexdigest();records=[]
    for name,script,args in [('legacy','legacy_integration',[]),('transfer16','transfer_integration',['--threads','16']),
                            ('overwrite-recovery','transfer_recovery_integration',['--on-conflict','overwrite','--threads','4','--resume-threads','8','--files','4','--payload-mib','8','--checkpoint-percent','50']),
                            ('upload-receipt','upload_receipt_integration',[])]:
        report=out/(name+'.json');started=time.monotonic()
        with (out/(name+'.log')).open('wb') as log:
            result=subprocess.run([sys.executable,'-X','utf8','tests/'+script+'.py',str(cli),*args,'--report',str(report)],env=env,stdout=log,stderr=subprocess.STDOUT)
        records.append({'name':name,'exitCode':result.returncode,'reportCreated':report.exists(),'seconds':round(time.monotonic()-started,3),'passed':result.returncode==0 and report.exists()})
        print(json.dumps({'toolchain':tag,**records[-1]}),flush=True)
    value={'observedUtc':datetime.now(timezone.utc).isoformat(),'toolchain':tag,'records':records,'binarySha256':initial,
           'binaryUnchanged':initial==hashlib.sha256(cli.read_bytes()).hexdigest(),'passed':all(row['passed'] for row in records),
           'scope':'selected actual protocol cases; full native CI separately qualified','deliveryComplete':False,'releaseQualified':False}
    (out/'receipt.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n','utf-8')
    raise SystemExit(0 if value['passed'] and value['binaryUnchanged'] else 1)


if __name__=='__main__':main()

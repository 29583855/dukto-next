"""日期：2026-11-07；未重编译程序，定向复验修正的逐项缺失状态夹具并保留旧失败。"""
from pathlib import Path
import hashlib,json,runpy,shutil,subprocess,sys

# 日期：2026-11-07；两工具链各用独立临时根，输入/二进制摘要前后保持，失败不得重用报告。
def main():
 root=Path.cwd();output=root/'docs/validation/2026-11-07/task-items-r105-windows';output.mkdir(exist_ok=False)
 environment=runpy.run_path('.cache/validate-overwrite-r62.py')['environment'];rows=[];script=root/'tests/task_items_integration.py';before=hashlib.sha256(script.read_bytes()).hexdigest()
 for label,folder in [('ucrt','windows-ucrt'),('msvc','windows/Release')]:
  binary=root/'build'/folder/'dukto-cli.exe';digest=hashlib.sha256(binary.read_bytes()).hexdigest();target=output/label;target.mkdir()
  with (target/'task-items.log').open('xb') as log:code=subprocess.run([sys.executable,'-X','utf8',str(script),str(binary),'--report',str(target/'task-items.json')],env=environment(label),stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
  assert hashlib.sha256(binary.read_bytes()).hexdigest()==digest and hashlib.sha256(script.read_bytes()).hexdigest()==before
  row={'toolchain':label,'exitCode':code,'binarySha256':digest,'binaryUnchanged':True,'passed':code==0};rows.append(row);print(json.dumps(row),flush=True)
  (output/'progress.json').write_text(json.dumps(rows,indent=2)+'\n','utf-8')
 value={'cases':rows,'scriptSha256':before,'passed':all(row['passed'] for row in rows),'productionCodeChangedForFixtureCorrection':False,'releaseQualified':False,'deliveryComplete':False};(output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n','utf-8');shutil.copyfile(Path(__file__),output/'validation-driver.py');return 0 if value['passed'] else 1
if __name__=='__main__':raise SystemExit(main())

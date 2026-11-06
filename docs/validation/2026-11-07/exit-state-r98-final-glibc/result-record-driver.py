"""日期：2026-11-07；记录R98独立Ubuntu真实干净构建终态，不把资格移给R100新GUI源码。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import shutil


# 日期：2026-11-07；只有源快照、完整核心和原监听/退出专项的严格回执通过才勾选。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    folder = root / 'docs/validation/2026-11-07/exit-state-r98-final-glibc'
    receipt_path = folder / 'verified-receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['sourceCommit'] == 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
    assert receipt['passed'] and receipt['cleanBuild'] and receipt['allSourcesMatchExactGitBlobs']
    assert receipt['coreTargets'] == 23 and receipt['newExitStateRows'] == 4 and receipt['originalParallelRows'] == 16
    assert receipt['sourceFilesVerified'] == 333 and receipt['buildInputsVerified'] == 210
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': receipt['sourceCommit'],
             'terminalPending': False, 'cleanBuild': True, 'passed': True,
             'coreTargets': 23, 'newExitStateRows': 4, 'originalParallelRows': 16,
             'sourceFiles': 333, 'buildInputs': 210, 'evidence': helper['proof'](receipt_path),
             'entireProtocolSuiteRun': False, 'releaseQualified': False, 'deliveryComplete': False}
    path = root / 'docs/ci-verification-20261107-r98.json'
    report = json.loads(path.read_text('utf-8'))
    report.update(linuxIndependentCleanBuildPending=False, linuxIndependentCleanBuild=value)
    helper['save'](path, report)
    path = root / 'docs/current-validation.json'
    index = json.loads(path.read_text('utf-8'))
    index.update(r98IndependentGlibc=value, nativeRegressionGuardR98=report)
    helper['save'](path, index)
    note = ('\n\n## R98独立Ubuntu干净构建终态（2026-11-07）\n\n'
            '- [x] 新独立目录完成186步干净编译；冻结b2e4659的333源码和210构建输入逐字节匹配Git对象，原始快照摘要已验。\n'
            '- [x] 完整23 CTest与22份Qt XML均通过，另行原监听/双栈/重启、新四退出状态及原16组并行专项通过；四个被测程序前后SHA不变，严格回执及原件保留。\n'
            '- [ ] 结果绑定R98；不授予R99/R100新GUI、整个独立协议、物理网络或长期稳定性资格。Windows 24h及其余计划继续。\n')
    for name in ('开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/Linux独立预览包.md'):
        # 日期：2026-11-07；当前摘要状态更新，历史在途记录继续作为当时观察保留。
        def transform(text):
            if name == '开发计划与进度.md':
                text = text.replace('| R98独立干净构建；R99原生GUI及最新长期 |',
                                    '| R98独立干净构建已通过；R99/R100原生GUI及最新长期 |', 1)
                text = text.replace('独立Ubuntu构建继续，Linux R98包已收验',
                                    '独立Ubuntu R98干净构建及Linux R98包已收验', 1)
            return text + note
        helper['update'](root / name, transform)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state['r98IndependentGlibc'] = value
    helper['save'](state_path, state)
    shutil.copyfile(Path(__file__), folder / 'result-record-driver.py')
    print(json.dumps({'sourceCommit': receipt['sourceCommit'], 'cleanBuildQualified': True,
                      'coreTargets': 23, 'newGuiQualificationTransferred': False}), flush=True)


if __name__ == '__main__':
    main()

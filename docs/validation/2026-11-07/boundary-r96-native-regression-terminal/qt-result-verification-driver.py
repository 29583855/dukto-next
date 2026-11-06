"""日期：2026-11-07；严格补核Qt的xfail聚合状态并发布双Mac焦点终态和后续精确运行身份。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import xml.etree.ElementTree as ET


# 日期：2026-11-07；每份Qt报告只允许精确监听方法的已知xfail，其余用例必须pass，不容许skip或未知结果。
def verify_reports(folder):
    checks = []
    core_folder = folder / 'build/Testing/QtTest'
    assert len(list(core_folder.glob('*.xml'))) == 22
    for path in sorted(core_folder.glob('*.xml')) + sorted((folder / 'evidence').glob('core-*.xml')):
        expected = []
        for case in ET.parse(path).findall('.//testcase'):
            if case.get('result') == 'xfail':
                assert path.name == 'core-tests.xml' or path.name in ['core-' + str(n) + '.xml' for n in range(1, 6)]
                assert case.get('name') == 'exclusiveTcpBinding'
                expected.append(case.get('name'))
            else:
                assert case.get('result') == 'pass', (path, case.attrib)
        assert len(expected) == (1 if path.name == 'core-tests.xml' or path.parent.name == 'evidence' else 0)
        checks.append({'path': path.as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'expectedAggregateMethods': expected, 'allOtherResultsPass': True})
    assert sum(bool(row['expectedAggregateMethods']) for row in checks) == 6
    return checks


# 日期：2026-11-07；只勾选原件通过范围，后续运行全部绑定精确提交，公开文档编码和换行保持。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    commit = '88f33b2c83f2950307c362fb64c693f7e9e5929d'
    output = root / 'docs/validation/2026-11-07/boundary-r96-native-regression-terminal'
    receipt_path = output / 'receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['nativeListenerRegressionQualifiedWithExplicitBoundary']
    supplemental = output / 'qt-result-qualification.json'
    assert not supplemental.exists()
    detailed = []
    for item in receipt['artifacts']:
        assert item['core']['exclusiveBindingPassLines'] == 8
        assert all(row['exclusiveBindingPassLines'] == 8 for row in item['focused'])
        detailed.append({'architecture': item['architecture'], 'reports': verify_reports(output / item['name'])})
    supplemental.write_text(json.dumps({'sourceCommit': commit, 'architectures': detailed,
                                        'allUnknownOrSkippedResultsRejected': True,
                                        'explicitDarwinXfailInstances': 12,
                                        'originalReceipt': helper['proof'](receipt_path), 'passed': True},
                                       ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'qt-result-verification-driver.py')
    runs = {}
    for name, run_id, workflow in [('native', 42252931531, 'build.yml'),
                                    ('musl', 42253012733, 'linux-musl.yml'),
                                    ('macosPackages', 42253077233, 'macos-package.yml')]:
        run = request('/repos/29583855/dukto-next/actions/runs/' + str(run_id))
        assert run['head_sha'] == commit and run['path'] == '.github/workflows/' + workflow
        ledger_path = root / ('.cache/r96-' + workflow.removesuffix('.yml') + '-dispatch.json')
        ledger = json.loads(ledger_path.read_text('utf-8'))
        assert ledger['responseReceived'] and ledger['sourceCommit'] == commit
        ledger['runId'] = run_id
        helper['save'](ledger_path, ledger)
        runs[name] = {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url')}
    frozen_path = root / 'docs/ci-verification-20261107-r96.json'
    frozen = json.loads(frozen_path.read_text('utf-8'))
    frozen.update(nativeMacRegressionPending=False, nativeMacRegressionPassedWithExplicitBoundary=True,
                  nativeMacRegressionEvidence=helper['proof'](receipt_path),
                  nativeQtResultQualification=helper['proof'](supplemental),
                  nativeMacCoreTargetsEach=23, nativeMacFocusedRunsEach=5,
                  nativeMacExpectedFailureInstances=12, nativeMacOriginalParallelExitCases=20,
                  nativeMacOriginalParallelExitFailures=0, entireNativeProtocolPending=True,
                  macosNewPackagesPending=True, observedUtc=datetime.now(timezone.utc).isoformat())
    frozen['runs']['listenerRegression'] = receipt['run']
    frozen['runs'].update(runs)
    helper['save'](frozen_path, frozen)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(nativeBoundaryR96=frozen, observedUtc=frozen['observedUtc'],
                 nativeListenerRegressionR96=dict(receipt['run'], sourceCommit=commit,
                                                   expectedFailurePerCoreExecution=1, originalEvidencePending=False,
                                                   evidence=helper['proof'](receipt_path)),
                 currentSourceStage='R96 dual native Mac focused regression qualified with explicit boundary; full native/Alpine and deployed Mac packages dispatched',
                 releaseQualified=False, deliveryComplete=False)
    index['pendingExactR96Runs'] = runs
    helper['save'](index_path, index)
    note = ('\n\n## R96双Mac焦点终态与完整验证派发（2026-11-07）\n\n'
            '- [x] 精确`88f33b2c83f2950307c362fb64c693f7e9e5929d`的42251051894双架构终态success；全部原件/SHA已验。各23核心和五轮监听/双栈/重启通过；每次核心恰好一条明确Darwin XFAIL，两架构共12次预期失败，其余Qt方法全部pass、无skip。\n'
            '- [x] 两架构原并行退出各十次、共20次通过，原测试/十秒时限不改；只说明本轮未复现，旧超时根因仍未证明。\n'
            '- [x] 同一精确R96已分别派发四原生42252931531、Alpine42253012733和双Mac部署42253077233；已保存单次派发账目，不重复触发。\n'
            '- [ ] 完整协议/新部署包终态、物理网络与长期稳定性仍待；当前下载保持R94开发预览，不能继承R96结果或宣称内核排他。\n')
    for name in ('开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/macOS构建与验收.md'):
        # 日期：2026-11-07；主计划当前入口同步，历史待验段落作为当时记录继续保留。
        def transform(text):
            if name == '开发计划与进度.md':
                text = text.replace('当前阶段：R96明确Darwin外部端口共享边界并修正原生夹具，新双Mac回归待验；R94/R95失败原件保留。完整交付未完成。',
                                    '当前阶段：R96双Mac焦点回归已按明确Darwin边界收验，四原生/Alpine及新Mac包已派发；完整交付未完成。', 1)
                text = text.replace('双Mac[原生回归42251051894](https://github.com/29583855/dukto-next/actions/runs/42251051894)已启动，结果尚待收验。',
                                    '双Mac[原生回归42251051894](https://github.com/29583855/dukto-next/actions/runs/42251051894)已收验success：各23核心、五轮焦点及各十轮原退出通过，每次核心恰有一条明确平台XFAIL。完整原生/Alpine和新部署包继续。', 1)
                text = text.replace('| R96完整核心/五轮监听/十轮原退出终态、新包、完整协议；原退出超时根因和正式分发 |',
                                    '| R96完整协议/新包；原退出超时根因、物理网络与正式分发 |', 1)
            return text + note
        helper['update'](root / name, transform)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state.update(workingSourceStage=index['currentSourceStage'], goalStatus='active', deliveryComplete=False)
    state['activeMacBoundaryR96'].update(terminalPending=False, focusedQualified=True,
                                       originalReceipt=helper['proof'](receipt_path), nextRuns=runs)
    helper['save'](state_path, state)
    names = ['docs/ci-verification-20261107-r96.json', 'docs/current-validation.json',
             '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/macOS构建与验收.md',
             'docs/validation/2026-11-06/github-api-push-r96-boundary.json']
    names.extend(path.relative_to(root).as_posix() for path in output.rglob('*') if path.is_file() and path.suffix != '.zip')
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    names = sorted(set(names))
    (root / '.cache/r96-regression-publish-files.json').write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r96-regression-stage.nul').write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    driver = (root / '.cache/stage-r95-listener.py').read_text('utf-8-sig').replace('r95-listener-publish-files.json', 'r96-regression-publish-files.json').replace('r95-listener-stage.nul', 'r96-regression-stage.nul')
    (root / '.cache/stage-r96-regression.py').write_text(driver, 'utf-8')
    print(json.dumps({'explicitPublishFiles': len(names), 'focusedArchitectures': 2,
                      'explicitExpectedFailureInstances': 12, 'nextRuns': {k:v['id'] for k,v in runs.items()}}), flush=True)


if __name__ == '__main__':
    main()

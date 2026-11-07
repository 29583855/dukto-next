"""日期：2026-11-07；发布原生已完成作业和Ubuntu性能诊断，保留应用版本及未完成资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

PARENT = 'b7375f65f418727fa74af1556a913996c6c6a4e0'
SOURCE = '4652f4dce23b014e18f2db56c6a75e81e76deafa'
LABEL = 'r106-evidence'


# 日期：2026-11-07；先核验真实终态和诊断，再按原编码更新计划；应用构建输入必须全部不变。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    base = root / 'docs/validation/2026-11-07'
    intel_path = base / 'state-use-r104-macos-intel-terminal/subset-verification.json'
    intel = json.loads(intel_path.read_text('utf-8'))
    assert intel['originalJobConclusion'] == 'failure' and intel['originalFailureRetained']
    assert len(intel['verifiedPassedProtocolReports']) == 46 and not intel['fullR104ProtocolQualified']
    diagnostic_path = base / 'task-items-r106-diagnostic-qualified/receipt.json'
    diagnostic = json.loads(diagnostic_path.read_text('utf-8'))
    assert diagnostic['diagnosticEvidenceVerified'] and not diagnostic['originalTimeoutCauseEstablished']
    assert len(diagnostic['diagnostics']) == 2 and all(row['timedOut'] for row in diagnostic['diagnostics'])
    jobs = []
    for runner in ('macos-15', 'ubuntu-22.04'):
        path = base / 'task-items-r105-native-job-terminals' / runner / 'receipt.json'
        value = json.loads(path.read_text('utf-8'))
        assert value['sourceCommit'] == SOURCE and value['thisNativeJobVerified']
        assert value['job']['conclusion'] == 'success' and value['verifiedProtocol']['cases'] == 47
        assert value['taskItemsCorrectedFixturePassed'] and not value['entireRunQualified']
        jobs.append(dict(proof(path), runner=runner, protocolReports=47))
    manifest_path = root / 'docs/ci-verification-20261107-r105.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    assert manifest['sourceCommit'] == SOURCE and len(manifest['buildInputs']) == 213
    for row in manifest['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    source_audit = json.loads((base / 'task-items-r105-source-audit.json').read_text('utf-8'))
    findings = []
    for row in source_audit['files']:
        path = root / row['path']
        for number, line in enumerate(path.read_text('utf-8').splitlines(), 1):
            if re.search(r'\b(TODO|FIXME|HACK|XXX|stub|placeholder)\b|not implemented|简化实现|待实现', line, re.I):
                findings.append({'path': row['path'], 'line': number})
    assert len(source_audit['files']) == 207 and not findings
    authors = ['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
               'docs/current-validation.json', 'docs/ci-verification-20261107-r105.json']
    backup = root / '.cache/evidence-r106-before'
    backup.mkdir(exist_ok=False)
    for name in authors:
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    # 日期：2026-11-07；证据检查点与包内应用提交分别记录，不伪造R106应用构建。
    checkpoint = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'planVersion': 'v0.106',
                  'checkpointOnly': True, 'applicationSourceCommit': SOURCE, 'buildInputs': manifest['buildInputs'],
                  'buildInputsChanged': [], 'verifiedNativeJobTerminals': jobs,
                  'verifiedProtocolReportsThisCheckpoint': 94, 'entireNativeRunQualified': False,
                  'r104IntelOriginalFailure': proof(intel_path), 'independentUbuntuDiagnostic': proof(diagnostic_path),
                  'sourceAuditFiles': 207, 'sourceMarkerFindings': findings,
                  'noMarkerFindingDoesNotQualifyAllPlannedFeatures': True,
                  'originalUbuntuTimeoutCauseEstablished': False, 'releaseQualified': False, 'deliveryComplete': False}
    checkpoint_path = root / 'docs/ci-verification-20261107-r106.json'
    assert not checkpoint_path.exists()
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    diagnostic_doc = '''# Ubuntu小文件超时诊断

更新日期：2026-11-07。此次只做隔离性能诊断，未更改生产代码、冻结二进制、原90秒期限或自动重试。R104二进制SHA-256为`cefa0b54a009461d78f968160ea8bfdd46cf9b1690e52aadfafb76ed06bdd157`。

两个独立样本都从回环服务器以16通道下载201个约500字节文件及3个目录。服务输出持续消费，逐事件记录单调时间戳，每秒采集本次进程/线程等待、CPU和IO指标及系统压力。测试到期后由诊断程序取消自有进程；退出码7来自本次期限触发的取消，不能当作自主崩溃或成功。

| 诊断 | 真实结果 | 证据边界 |
| --- | --- | --- |
| strace跟踪fsync/fdatasync | 90.05秒超时，未发布文件；服务259次、客户端393次已完成同步调用，耗时合计分别约0.91和2.30秒 | ptrace明显改变调度及吞吐，不能作为原超时的基准或据此排除磁盘问题 |
| 去掉strace，仅保留采样/事件时间戳 | 90.08秒超时，实际发布126个文件且逐个外部摘要一致；未完成全部201文件 | CPU PSI some avg10中位86.42%、最大99.13%；事件含15秒和12.8秒的窗口间隔。采样仍有开销，且不能据此认定原两次超时的唯一根因 |

[收验回执](validation/2026-11-07/task-items-r106-diagnostic-qualified/receipt.json)绑定原始时序、进程采样、同步跟踪及驱动。首次跟踪的空文件集合不授予摘要正确性资格；第二次仅给实际发布的126文件子集记摘要一致。两次诊断均为超时，完整task-items仍未通过。

GitHub Ubuntu和Apple Silicon的R105原生作业各47项协议已终态通过；独立单核Ubuntu使用自己的环境及原件，仍单独记录失败。后续须定位CPU热点、调度竞争、每文件持久化成本及窗口等待，再用未增加的原期限验证修复，不能只提高测试时限。
'''
    doc_path = root / 'docs/Ubuntu小文件性能诊断.md'
    assert not doc_path.exists()
    doc_path.write_text(diagnostic_doc, 'utf-8')
    note = '''

## R106证据检查点（2026-11-07，应用仍为R105）

- [x] R105 Apple Silicon与GitHub Ubuntu原生作业各47项完整协议报告、逐份摘要及精确脚本已核对；修正后的204条目/三页、双向4/16通道task-items均通过。维护八进程/诊断及平台附加报告通过；Intel/Windows及整个运行仍分别收验。
- [x] R104 Intel原始failure附件与job.log已保存；47项中46份报告通过，唯一失败为旧task-items空目录夹具，未把该作业改记成功。
- [x] 独立Ubuntu保留90秒期限完成两个隔离诊断：strace影响显著；无strace样本仍超时，已发布126文件摘要一致，CPU压力及窗口等待原时序已保存。原超时根因尚未确定，未声称修复。[诊断与边界](docs/Ubuntu小文件性能诊断.md)。
- [x] 213构建输入保持原摘要；207份维护源码重新扫描，无TODO/FIXME/占位/简化实现标记。这不代替未完成的完整功能验收。
- [ ] 两个冻结86400秒长测仍运行（最近观察Windows84轮/25218秒，Ubuntu60轮/20160秒），不按轮数授予24小时资格；安全GC/全局磁盘预算、完整GUI/R6、物理LAN/3×3、最低干净系统和正式分发继续。整体及正式发布仍为false。
'''
    # 日期：2026-11-07；只更新当前摘要和新增已收验项，历史失败及未完成清单继续保留。
    def plan(text):
        text = text.replace('文档版本：v0.105', '文档版本：v0.106', 1)
        text = text.replace('v0.105 / 逐项查询夹具与真实失败收验', 'v0.106 / 原生作业终态与独立Ubuntu性能诊断', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R105双Mac含依赖包已验，Apple Silicon/GitHub Ubuntu各47协议终态通过；独立Ubuntu小文件超时诊断保留，整体交付继续。', text, count=1, flags=re.M)
        text = text.replace('R104三原生作业和独立Ubuntu继续，R105新原生待验', 'R105 Apple Silicon/GitHub Ubuntu已终态通过，Intel/Windows与长测继续收验', 1)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R105精确4652f4d双Mac GUI/独立CLI含依赖包、每包五项迁移业务已验；Apple Silicon及GitHub Ubuntu原生作业各47项协议报告终态通过，Intel/Windows继续收验。R104三平台原夹具失败和独立Ubuntu90秒超时均保留；新增采样显示高CPU压力，根因未定。[本轮证据](docs/ci-verification-20261107-r106.json)。Windows/Linux含依赖包仍为R100，整体未完成。' + text[end:]
        return text.rstrip() + note
    update(root / '开发计划与进度.md', plan)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(root / name, lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'README.md', lambda text: re.sub(r'^公开仓库为.*$', '公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R105精确4652f4d的[macOS Apple Silicon/Intel GUI与独立CLI](docs/macOS独立预览包.md)已编译、部署Qt5/OpenSSL并通过每包五项迁移业务。Apple Silicon及GitHub Ubuntu各47项原生协议报告终态通过；Intel/Windows继续收验。独立Ubuntu小文件90秒超时已留存性能时序，根因未定；Windows/Linux含依赖预览仍为R100。完整交付进度见[计划](开发计划与进度.md)、[本轮证据](docs/ci-verification-20261107-r106.json)。', text, count=1, flags=re.M))
    manifest.update(verifiedNativeJobTerminals=jobs, r104IntelFailureSubsetEvidence=proof(intel_path),
                    independentUbuntuDiagnosticEvidence=proof(diagnostic_path),
                    fullNativeRegressionQualified=False, nativeCIPending=True)
    save(manifest_path, manifest)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index['taskItemsFixtureR105'].update(manifest=proof(manifest_path), verifiedNativeJobTerminals=jobs,
                                       independentUbuntuDiagnosticEvidence=proof(diagnostic_path))
    index['stateUseR104'].update(intelTerminalEvidence=proof(intel_path), originalIntelJobConclusion='failure')
    index.update(planVersion='v0.106', evidenceCheckpointR106=proof(checkpoint_path),
                 observedUtc=checkpoint['observedUtc'], deliveryComplete=False, releaseQualified=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(taskItemsFixtureR105=manifest, evidenceCheckpointR106=proof(checkpoint_path),
                 goalStatus='active', releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    receipt_folder = base / 'task-items-r106-diagnostic-qualified'
    shutil.copyfile(root / '.cache/r106-inflight-long-observation.json', receipt_folder / 'inflight-long-observation.json')
    shutil.copyfile(root / '.cache/r105-native-run.json', receipt_folder / 'native-inflight-observation.json')
    shutil.copyfile(root / '.cache/r105-delivery-evidence-published-tree-verification.json', receipt_folder / 'parent-publication-verification.json')
    shutil.copyfile(__file__, receipt_folder / 'publication-preparation-driver.py')
    names = set(authors + ['docs/ci-verification-20261107-r106.json', 'docs/Ubuntu小文件性能诊断.md',
                          'docs/validation/2026-11-06/github-api-push-r105-delivery-evidence.json'])
    for folder in ('state-use-r104-macos-intel-terminal', 'task-items-r105-native-job-terminals',
                   'task-items-r106-glibc-diagnostic', 'task-items-r106-glibc-untraced', 'task-items-r106-diagnostic-qualified'):
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*') if path.is_file()
                     and path.suffix in ('.json', '.jsonl', '.xml', '.log', '.txt', '.sha256', '.py', '.png', '.trace', '.stderr'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (root / ('.cache/' + LABEL + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + LABEL + '-stage.nul')).write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    template = (root / '.cache/stage-r105-delivery-evidence.py').read_bytes()
    (root / ('.cache/stage-' + LABEL + '.py')).write_bytes(template.replace(b'r105-delivery-evidence', LABEL.encode()))
    print(json.dumps({'checkpoint': 'v0.106', 'applicationSourceCommit': SOURCE, 'explicitFiles': len(names),
                      'verifiedNativeJobs': 2, 'verifiedProtocolReports': 94, 'unchangedBuildInputs': 213,
                      'sourceAuditFiles': 207, 'sourceMarkerFindings': 0, 'deliveryComplete': False}))


if __name__ == '__main__':
    main()

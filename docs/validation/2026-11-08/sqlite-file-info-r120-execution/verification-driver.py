"""日期：2026-11-08；记录已公开源码、真实CLI专项和已启动原生工作流，未终态保持待验。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-08；保留既有编码和换行，根文档与公开副本同字节。
def edit(name, before, after):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    text = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    assert text.count(before) == 1, (name, before)
    path.write_bytes(bom + text.replace(before, after, 1).replace('\n', newline).encode('utf-8'))
    shutil.copyfile(path, REPO / name)


# 日期：2026-11-08；只在源码及程序身份相符时记录实际CLI协议，原生完整资格仍独立。
def main():
    output = REPO / 'docs/validation/2026-11-08/sqlite-file-info-r120-execution'
    output.mkdir(exist_ok=False)
    publication = json.loads((ROOT / '.cache/r120-source-publication.json').read_bytes())
    runs = json.loads((ROOT / '.cache/r120-ci-runs.json').read_bytes())
    source = publication['sourceCommit']
    assert publication['remoteMainVerified'] and runs['sourceCommit'] == source
    verifier = runpy.run_path(str(ROOT / '.cache/collect-exact-native-r87.py'))['verify_passed']
    records = []
    for tag in ['msvc', 'ucrt']:
        original = ROOT / ('.cache/r120-protocol-' + tag)
        receipt = json.loads((original / 'receipt.json').read_bytes())
        core = json.loads((ROOT / ('.cache/r120-qualified-' + tag + '/receipt.json')).read_bytes())
        assert receipt['passed'] and receipt['binaryUnchanged'] and len(receipt['records']) == 4
        assert core['binariesBefore']['dukto-cli.exe'] == receipt['binarySha256']
        proofs = []
        for row in receipt['records']:
            name = row['name'] + '.json'
            value = json.loads((original / name).read_bytes())
            assert row['passed'] and row['exitCode'] == 0
            verifier(value)
            if isinstance(value, list):
                assert value and all(case['passed'] for case in value)
            else:
                assert value['passed']
            proofs.append({'path': name, 'sha256': hashlib.sha256((original / name).read_bytes()).hexdigest()})
        shutil.copytree(original, output / tag)
        records.append({'toolchain': tag, 'actualCliCases': 4, 'allPassed': True,
                        'binaryMatchesFullCore': True, 'reports': proofs})
    for name in ['r120-source-publication.json', 'r120-ci-runs.json',
                 'r120-dispatch-sqlite-file-info-regression.yml.json', 'r120-dispatch-build.yml.json',
                 'r120-dispatch-macos-package.yml.json']:
        shutil.copyfile(ROOT / '.cache' / name, output / name)
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
               'records': records, 'allLocalCliCasesPassed': True, 'nativeRuns': runs,
               'globalQuotaEnforced': False, 'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    path = REPO / 'docs/ci-verification-20261108-r120.json'
    index = json.loads(path.read_bytes())
    index.update(sourceCommit=source, sourceTree=publication['sourceTree'], sourcePublicationPending=False,
                 remoteSourceVerified=True, localCliCasesEach=4, allLocalCliCasesPassed=True,
                 nativeRunIds=runs, nativeQualificationPending=True)
    for p in [output / 'receipt.json', output / 'r120-source-publication.json', output / 'r120-ci-runs.json']:
        index['receipts'].append({'path': p.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(path, ROOT / path.relative_to(REPO))
    old = '- [ ] 精确源码公开、四原生完整核心/文件专项、当前实际CLI专项及新双Mac部署包按各自原件继续；当前已验Mac包仍R119，不能继承新产品输入资格。'
    new = '- [x] 精确源码' + source + '已非强制公开，266份输入逐blob相同；当前双Windows各四项实际CLI专项通过：旧版、TLS16通道、覆盖4→8通道故障恢复和上传确认恢复，程序SHA与完整核心一致。\n'
    new += '- [ ] [四原生核心/文件专项](https://github.com/29583855/dukto-next/actions/runs/' + str(runs['regressionRunId']) + ')、[完整协议](https://github.com/29583855/dukto-next/actions/runs/' + str(runs['nativeRunId']) + ')及[新双Mac部署](https://github.com/29583855/dukto-next/actions/runs/' + str(runs['packageRunId']) + ')已真实启动，按各自终态原件收验；当前已验Mac包仍R119。'
    edit('开发计划与进度.md', old, new)
    edit('开发计划与进度.md', '266份输入冻结，准备公开和四原生验证。', '精确c9872f72已公开，266份输入核对，四原生及新Mac部署实际运行。')
    edit('docs/执行进度.md', '生产总预算/跨进程账本与GC未完成。[设计](SQLite原生占用观察.md)',
         '精确c9872f72已非强制公开；双Windows各四项真实CLI专项通过，二进制与完整核心一致。四原生核心专项、完整协议与新双Mac部署均已实际启动，当前预览仍R119。生产总预算/跨进程账本与GC未完成。[设计](SQLite原生占用观察.md)')
    shutil.copytree(output, ROOT / output.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({'sourceCommit': source, 'localCliCasesEach': 4, 'nativeRuns': runs}), flush=True)


if __name__ == '__main__':
    main()

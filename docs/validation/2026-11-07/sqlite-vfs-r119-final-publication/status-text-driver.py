"""日期：2026-11-08；核对最终回执后收敛当前状态文字，保持历史失败与原文件格式。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = REPO / 'docs/validation/2026-11-07'


# 日期：2026-11-08；收集文本相对链接，历史附件迁移造成的缺失单独记录。
def links(name):
    path = ROOT / name
    result = set()
    for match in re.finditer(r'\]\(([^)]+)\)', path.read_text('utf-8-sig')):
        href = match.group(1).split('#', 1)[0].strip('<>')
        if href and ':' not in href and not href.startswith('/'):
            result.add(href)
    return result


# 日期：2026-11-08；只在指定文字唯一存在时修改，原编码、BOM与换行保持。
def replace(name, changes):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    text = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    for before, after in changes:
        assert text.count(before) == 1, (name, before)
        text = text.replace(before, after, 1)
    updated = bom + text.replace('\n', newline).encode('utf-8')
    path.write_bytes(updated)
    shutil.copyfile(path, REPO / name)
    return {'path': name, 'encoding': 'UTF-8', 'bomPreserved': updated.startswith(b'\xef\xbb\xbf') == bool(bom),
            'lineEnding': 'CRLF' if newline == '\r\n' else 'LF',
            'beforeSha256': hashlib.sha256(raw).hexdigest(), 'sha256': hashlib.sha256(updated).hexdigest()}


# 日期：2026-11-08；状态由精确提交与已收验终态决定，不将专项资格替代原失败。
def main():
    target = BASE / 'sqlite-vfs-r119-final-publication/status-text-verification.json'
    assert not target.exists()
    names = ['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/macOS独立预览包.md', 'docs/SQLite运行时与写入拦截.md']
    baseline_missing = {(name, href) for name in names for href in links(name) if not (ROOT / name).parent.joinpath(href).exists()}
    for version, prefix in [(117, 'sqlite-journal'), (118, 'state-storage')]:
        receipt = json.loads((BASE / f'{prefix}-r{version}-native-terminal/receipt.json').read_bytes())
        assert receipt['allFourNativeProtocolJobsVerified']
    before = '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。当前已验Mac预览为R119，双架构Qt5/OpenSSL、GUI/独立CLI、迁移运行及截图通过；R115只修正面板读取测试时序，产品输入与R114一致，双Mac各两轮完整面板专项已验。R114 Windows/Ubuntu/Apple Silicon各26核心通过，Intel25/26原失败保留。R113四平台完整协议已验，Windows51/51、其他各47/47。R116扫描清理双Windows各24条/1权限跳过、独立Ubuntu25条全通过。未知身份临时项、通用缓存及全局GC仍待完成。[清理范围](docs/过期任务临时文件清理.md)。历史失败和完整项目资格继续分别保留。'
    after = '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R119双Mac预览包含Qt5/OpenSSL、GUI与独立CLI，迁移运行、实际传输及四张截图已验；[下载与摘要](docs/macOS独立预览包.md)。应用源325c60cc的三个POSIX各29核心通过；Windows原28/29目录时间戳夹具失败保留，后续d2c8c4ff完整计量11条及20轮重复通过，应用与依赖输入保持相同。R117、R118四平台完整协议均已按终态原件核验，Windows各51项、三个POSIX各47项；R119完整协议仍在运行。未知身份临时项、全局磁盘预算/GC及完整项目继续按未完成项执行。[清理范围](docs/过期任务临时文件清理.md)。'
    records = [replace('开发计划与进度.md', [
        ('## 当前验收快照（2026-11-07，v0.119 / SQLite写入前策略基础）', '## 当前验收快照（2026-11-08，v0.119 / SQLite写入前策略基础）'),
        (before, after),
        ('| 原生复验 | R113 Windows51/51、Ubuntu/Apple Silicon/Intel完整job各47/47；R114核心3/4平台通过，Intel原失败独立保留 | 各精确提交完整协议终态和冻结长测 |', '| 原生复验 | R117、R118四平台完整job已验，Windows各51项、三个POSIX各47项；R119三个POSIX29核心与Windows修正专项通过，原失败保留 | R119完整协议终态和当前输入的长期验证 |'),
        ('R118三个POSIX完整协议各47条已验，Windows继续按精确终态原件收验。', 'R118四原生完整job终态success，Windows51条、三个POSIX各47条通过。'),
        ('新增云端完整计量及20轮变更专项继续。115份应用/依赖输入与325c60cc完全一致，新Mac包继续按325原件验收。', '新增云端完整计量11条及20轮变更专项已通过。115份应用/依赖输入与325c60cc完全一致，新Mac包已按325原件验收。'),
        ('R118原生核心：ubuntu-22.04、macos-15、macos-15-intel、windows-2022各28核心已验，双Mac精确Darwin XFAIL继续保留。完整协议仍按终态原件收验。', 'R118原生核心：ubuntu-22.04、macos-15、macos-15-intel、windows-2022各28核心已验，双Mac精确Darwin XFAIL继续保留。四原生完整job已收验success：Windows51条、三个POSIX各47条通过。')
    ])]
    records.append(replace('docs/执行进度.md', [
        ('云端完整计量及20轮专项继续。115份产品/依赖输入与325c60cc保持一致，Mac包按该精确源验收。', '云端完整计量11条及20轮专项已通过。115份产品/依赖输入与325c60cc保持一致，Mac包已按该精确源验收。')
    ]))
    records.append(replace('docs/macOS独立预览包.md', [
        ('[ubuntu-22.04、macos-15、macos-15-intel、windows-2022各28核心已验](ci-verification-20261107-r118.json)；完整协议另按终态核验。', '[四平台各28核心和完整协议终态已验](ci-verification-20261107-r118.json)，Windows51项、三个POSIX各47项通过。'),
        ('[完整CI](https://github.com/29583855/dukto-next/actions/runs/42379391549)继续按终态收验', '[完整CI](https://github.com/29583855/dukto-next/actions/runs/42379391549)四平台终态success且原件已验')
    ]))
    # 日期：2026-11-08；当前新增相对链接必须存在，历史缺失不冒充本轮新增错误或已通过。
    local_links = 0
    missing = set()
    for name in names:
        path = ROOT / name
        assert (REPO / name).read_bytes() == path.read_bytes()
        for href in links(name):
            if not (path.parent / href).exists():
                missing.add((name, href))
                continue
            local_links += 1
    assert missing <= baseline_missing, missing - baseline_missing
    for name, href in [('开发计划与进度.md', 'docs/macOS独立预览包.md'),
                       ('开发计划与进度.md', 'docs/ci-verification-20261107-r119.json'),
                       ('docs/macOS独立预览包.md', 'validation/2026-11-07/sqlite-vfs-r119-final-macos-package/receipt.json'),
                       ('docs/macOS独立预览包.md', 'validation/2026-11-07/sqlite-vfs-r119-final-macos-compiled/receipt.json')]:
        assert (ROOT / name).parent.joinpath(href).is_file()
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'modifiedFiles': records,
               'existingRelativeLinksVerified': local_links, 'currentDownloadAndReceiptLinksVerified': True,
               'noNewBrokenLinks': True, 'historicalMissingLinkTargetsRetained': sorted(missing),
               'allHistoricalLinksQualified': False, 'historyFailuresRetained': True,
               'allNativeCoreQualified': False, 'deliveryComplete': False, 'releaseQualified': False}
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), target.parent / 'status-text-driver.py')
    index_path = REPO / 'docs/ci-verification-20261107-r119.json'
    index = json.loads(index_path.read_bytes())
    index['receipts'].append({'path': target.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(index_path, ROOT / index_path.relative_to(REPO))
    shutil.copytree(target.parent, ROOT / target.parent.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({'relativeLinksVerified': local_links, 'filesUpdated': len(records)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

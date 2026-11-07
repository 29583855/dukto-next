"""日期：2026-11-08；发布两种Mac已核验开发预览，固定精确源码标签，不覆盖既有资产。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path.cwd()
REPOSITORY = '29583855/dukto-next'
TAG = 'preview-r127-20261108'


# 日期：2026-11-08；仅向GitHub本仓库上传端点发送已授权凭据，正文是已核验安装包或摘要。
def upload(identifier, path, token):
    raw = path.read_bytes()
    url = ('https://uploads.github.com/repos/' + REPOSITORY + '/releases/' + str(identifier)
           + '/assets?' + urllib.parse.urlencode({'name': path.name}))
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'Content-Type': 'application/gzip' if path.name.endswith('.tar.gz') else 'text/plain',
               'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Dukto-preview/0.127'}
    request = urllib.request.Request(url, data=raw, headers=headers, method='POST')
    # 日期：2026-11-08；上传不允许重定向到其他主机，秘密不进入回执或日志。
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        # 日期：2026-11-08；拒绝所有上传重定向，不能将Authorization传播给其他服务。
        def redirect_request(self, request, response, code, message, headers, new_url):
            return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError('GitHub asset upload failed: ' + str(error.code)) from None


# 日期：2026-11-08；两架构逐包要求已成功运行和看过截图；同名既有资产仅核对，绝不删除或替换。
def main():
    target = ROOT / '.cache/r127-public-preview.json'
    assert not target.exists()
    repo = ROOT / '.cache/github-29583855-dukto-next-r28'
    evidence = repo / 'docs/validation/2026-11-08/gui-state-session-r127-macos-package'
    package = json.loads((evidence / 'receipt.json').read_bytes())
    source = json.loads((ROOT / '.cache/r127-ci-runs.json').read_bytes())['sourceCommit']
    assert package['sourceCommit'] == source
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed']
    assert package['run']['conclusion'] == 'success'
    helper = runpy.run_path(str(ROOT / '.cache/github-actions-r28.py'))
    request, token = helper['request'], helper['credential']()
    base = '/repos/' + REPOSITORY
    existing = [row for row in request(base + '/releases?per_page=100') if row['tag_name'] == TAG]
    body = ('精确源码：`' + source + '`。\n\n'
            '本轮接入GUI服务器页与CLI同目录状态会话及维护互斥。\n\n提供 Apple Silicon（arm64）与 Intel（x86_64）两份 macOS 开发预览。'
            '每份包含 Dukto Next.app、独立命令行程序及 Qt5/OpenSSL 运行依赖。\n\n'
            '两架构已完成原生编译、Cocoa 窗口/高 DPI 检查、中文空格目录搬迁，'
            '并通过并行传输、覆盖及中断恢复等五项包内实际业务检查。'
            '各文件的 SHA-256 在同名 .sha256 附件中。\n\n'
            '解压对应 tar.gz，打开 Dukto Next.app。命令行入口：'
            '`"Dukto Next.app/Contents/MacOS/dukto-cli" --help`。\n\n'
            '本版本使用开发 adhoc 签名；Developer ID 签名、公证及最低干净系统验证尚未完成。'
            '生产写入的全局磁盘配额、自动历史迁移和自动 GC 尚未接入，'
            '完整项目和长期稳定性验收继续按开发计划执行。\n\n'
            '[打包与实际运行证据](' + package['run']['html_url'] + ') · '
            '[开发计划](https://github.com/' + REPOSITORY + '/blob/main/'
            + urllib.parse.quote('开发计划与进度.md') + ')')
    if existing:
        release, = existing
        assert release['prerelease'] and not release['draft']
        assert release['target_commitish'] == source and release['body'] == body
    else:
        release = request(base + '/releases', method='POST', payload={
            'tag_name': TAG, 'target_commitish': source, 'name': 'Dukto Next R127 macOS 开发预览',
            'body': body, 'draft': False, 'prerelease': True, 'make_latest': 'false'})
    tag = request(base + '/git/ref/tags/' + TAG)
    assert tag['object']['type'] == 'commit' and tag['object']['sha'] == source
    assets = request(base + '/releases/' + str(release['id']) + '/assets?per_page=100')
    records = []
    for row in package['records']:
        assert row['qualified'] and row['screenshotsViewed']
        assert row['package']['signature'] == 'adhoc' and not row['package']['notarized']
        archive = ROOT / 'dist/macos-preview-20261108-r127-gui-state-session' / row['archive']
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == row['packageSha256']
        checksum = Path(str(archive) + '.sha256')
        assert checksum.read_text('ascii').split()[0] == row['packageSha256']
        for path in [archive, checksum]:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            candidates = [asset for asset in assets if asset['name'] == path.name]
            if candidates:
                asset, = candidates
            else:
                asset = upload(release['id'], path, token)
            assert asset['state'] == 'uploaded' and asset['size'] == path.stat().st_size
            assert asset['digest'] == 'sha256:' + digest
            records.append({'architecture': row['architecture'], 'assetId': asset['id'],
                            'name': asset['name'], 'bytes': asset['size'], 'sha256': digest,
                            'downloadUrl': asset['browser_download_url']})
            print(json.dumps({'uploadedOrVerified': path.name, 'bytes': asset['size']}), flush=True)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'releaseId': release['id'], 'tag': TAG, 'releaseUrl': release['html_url'],
             'prerelease': True, 'assets': records, 'allAssetsMatchVerifiedPackages': True,
             'developerIdSigned': False, 'notarized': False,
             'deliveryComplete': False, 'releaseQualified': False}
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'releaseUrl': release['html_url'], 'assets': len(records)}), flush=True)


if __name__ == '__main__':
    main()

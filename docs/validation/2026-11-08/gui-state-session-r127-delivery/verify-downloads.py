"""日期：2026-11-08；匿名实际下载公开预览并流式核对四份附件，禁止使用GitHub凭据。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.request


# 日期：2026-11-08；只访问本仓库公开下载地址，固定缓冲核对长度及SHA，不在本机重复保存包。
def main():
    root = Path.cwd()
    output = root / '.cache/r127-public-download-verification.json'
    assert not output.exists()
    preview = json.loads((root / '.cache/r127-public-preview.json').read_bytes())
    prefix = 'https://github.com/29583855/dukto-next/releases/download/' + preview['tag'] + '/'
    records = []
    for row in preview['assets']:
        url = row['downloadUrl']
        assert url.startswith(prefix) and url == prefix + row['name']
        request = urllib.request.Request(url + '?download_check=' + str(time.time_ns()), headers={
            'User-Agent': 'Dukto-public-preview-check/0.127', 'Cache-Control': 'no-cache'})
        digest = hashlib.sha256()
        length = 0
        with urllib.request.urlopen(request, timeout=120) as response:
            assert response.status == 200
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                length += len(block)
                assert length <= row['bytes']
        assert length == row['bytes'] and digest.hexdigest() == row['sha256']
        records.append({'name': row['name'], 'downloadUrl': url, 'bytes': length,
                        'sha256': digest.hexdigest(), 'anonymousDownloadVerified': True})
        print(json.dumps({'anonymousDownloadVerified': row['name']}), flush=True)
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(),
              'sourceCommit': preview['sourceCommit'], 'releaseUrl': preview['releaseUrl'],
              'assets': records, 'anonymousDownloadsVerified': len(records) == 4,
              'allDownloadedBytesMatchVerifiedPackages': True}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'anonymousDownloadsVerified': True, 'assets': len(records)}), flush=True)


if __name__ == '__main__':
    main()

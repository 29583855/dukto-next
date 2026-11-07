"""日期：2026-11-07；实际查看PNG后按架构保存人工视觉观察，不能由运行通过推定截图已查看。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


# 日期：2026-11-07；只登记调用者本轮已实际查看的两张原图，不扩大为完整R6或系统交互验收。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('architecture', choices=['arm64', 'x86_64'])
    args = parser.parse_args()
    repo = Path.cwd() / '.cache/github-29583855-dukto-next-r28'
    base = repo / 'docs/validation/2026-11-07/upload-scan-r116-macos-package'
    path = base / args.architecture / 'receipt.json'
    receipt = json.loads(path.read_bytes())
    assert receipt['sourceCommit'] == '0a60da9120b6be49d1768fa500d042ff394ac9f7' and receipt['qualified']
    frames = []
    for key in ['screenshot', 'navigationScreenshot']:
        name = receipt['runtime'][key]
        raw = (repo / name).read_bytes()
        assert raw.startswith(b'\x89PNG\r\n\x1a\n')
        frames.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'viewed': True})
    review = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'architecture': args.architecture,
              'frames': frames, 'observations': ['首次运行说明与原生首页文字可读，无明显裁切',
              '服务器主窗口430×700导航、输入框和浏览按钮可读，中文无缺字'],
              'completeR6AndNativeInteractionQualified': False}
    (base / args.architecture / 'visual-review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    receipt['screenshotsViewed'] = True
    receipt['visualReviewSha256'] = hashlib.sha256((base / args.architecture / 'visual-review.json').read_bytes()).hexdigest()
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    top = base / 'receipt.json'
    value = json.loads(top.read_bytes())
    for number, row in enumerate(value['records']):
        if row['architecture'] == args.architecture:
            value['records'][number] = receipt
    value['screenshotsViewed'] = len(value['records']) == 2 and all(row.get('screenshotsViewed', False) for row in value['records'])
    top.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'architecture': args.architecture, 'actualFramesViewed': len(frames), 'bothArchitecturesViewed': value['screenshotsViewed']}))


if __name__ == '__main__':
    main()

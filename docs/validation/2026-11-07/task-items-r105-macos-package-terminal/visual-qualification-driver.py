"""日期：2026-11-07；四张实际原图查看后生成独立视觉收验，不改写原部署回执。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


# 日期：2026-11-07；核对两架构各启动/服务器帧的真实字节，缺图或仅单架构不得授予完整视觉子集资格。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/task-items-r105-macos-package-terminal'
    path = output / 'receipt.json'
    original = json.loads(path.read_text('utf-8'))
    assert original['sourceCommit'] == '4652f4dce23b014e18f2db56c6a75e81e76deafa'
    assert original['bothArchitecturesVerified'] and original['passed'] and not original['screenshotsViewed']
    assert original['run']['status'] == 'completed' and original['run']['conclusion'] == 'success'
    visual_path = root / '.cache/r105-package-visual-reviews.json'
    visual = json.loads(visual_path.read_text('utf-8'))
    assert visual['sourceCommit'] == original['sourceCommit'] and visual['bothArchitecturesVisuallyReviewed']
    expected = set()
    for label in ('ARM64', 'X64'):
        for suffix in ('build/package-runtime.png', 'build/main-window-navigation/native/Testing/QtTest/main-server-430x700.png'):
            expected.add((output / ('macos-preview-' + label) / suffix).relative_to(root).as_posix())
    assert len(visual['images']) == 4 and {row['path'] for row in visual['images']} == expected
    for row in visual['images']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    target = output / 'visual-review.json'
    assert not target.exists()
    shutil.copyfile(visual_path, target)
    qualified = dict(original, qualifiedObservedUtc=datetime.now(timezone.utc).isoformat(),
                     screenshotsViewed=True, screenshotsReviewed=4,
                     originalReceiptSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                     visualReview={'path': target.relative_to(root).as_posix(),
                                   'sha256': hashlib.sha256(target.read_bytes()).hexdigest()},
                     completeGuiInteractionQualified=False, releaseQualified=False, deliveryComplete=False)
    encoded = (json.dumps(qualified, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    target = output / 'qualified-receipt.json'
    assert not target.exists()
    target.write_bytes(encoded)
    target = root / 'dist/macos-preview-20261107-r105-task-items/QUALIFIED-RECEIPT.json'
    assert not target.exists()
    target.write_bytes(encoded)
    shutil.copyfile(Path(__file__), output / 'visual-qualification-driver.py')
    print(json.dumps({'sourceCommit': original['sourceCommit'], 'macArchitectures': 2,
                      'screenshotsReviewed': 4, 'releaseQualified': False}))


if __name__ == '__main__':
    main()

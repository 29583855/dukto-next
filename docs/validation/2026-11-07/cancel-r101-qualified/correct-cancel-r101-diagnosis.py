"""日期：2026-11-07；复查监听器已有起始事件，保留未验证草稿后恢复原核心并记录错误断言。"""
import hashlib
import json
from pathlib import Path


# 日期：2026-11-07；仅恢复本次自有改动，备份核对原SHA，不触碰其他源码或运行中的冻结测试。
def main():
    root = Path.cwd()
    backup = root / '.cache/cancel-r101-before'
    rows = json.loads((backup / 'source-before.json').read_text('utf-8'))
    output = root / '.cache/cancel-r101-rejected-core-draft'
    output.mkdir(exist_ok=False)
    records = []
    for name in ('src/core/legacy.cpp', 'src/core/legacy.h'):
        original = (backup / name).read_bytes()
        row, = [item for item in rows if item['path'] == name]
        assert hashlib.sha256(original).hexdigest() == row['sha256']
        current = (root / name).read_bytes()
        assert current != original
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(current)
        (root / name).write_bytes(original)
        records.append({'path': name, 'restoredSha256': row['sha256'],
                        'rejectedDraftSha256': hashlib.sha256(current).hexdigest()})
    legacy = (root / 'src/core/legacy.cpp').read_text('utf-8')
    listener = legacy[legacy.index('void LegacyListener::incomingConnection('):]
    assert listener.index('emit event(') < listener.index('active_->start();')
    assert '{"stage", "receive"}' in listener and '{"bytes", "0"}' in listener
    value = {'date': '2026-11-07', 'restoredCoreFiles': records,
             'existingListenerReportsReceiveBeforeStartingWorker': True,
             'initialFailure': 'New test incorrectly required nonzero progress before a full 256KiB block',
             'correctedRequirement': 'Visible enabled QML cancel action, bounded completion, cleanup, credit return and later bidirectional transfer',
             'productCancellationBugConfirmed': False, 'correctedRegressionPending': True,
             'releaseQualified': False, 'deliveryComplete': False}
    path = root / 'docs/validation/2026-11-07/cancel-r101-windows/diagnosis-correction.json'
    assert not path.exists()
    path.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value))


if __name__ == '__main__':
    main()

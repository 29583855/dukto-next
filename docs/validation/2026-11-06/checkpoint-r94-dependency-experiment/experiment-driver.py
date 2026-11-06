"""日期：2026-11-06；隔离重现检查点代理跨流依赖饥饿，只论证协调器风险，不认定旧Mac生产根因。"""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'tests'))
from checkpoint_gate import CheckpointGate


class RotatingGate(CheckpointGate):
    # 日期：2026-11-06；实验版只在无确认进展50ms时转给等待流，仍以真实确认达到门槛才返回。
    def checkpoint(self, read_confirmed, minimum, timeout=120):
        deadline = time.monotonic() + timeout
        selected, baseline, granted_at = None, 0, 0
        while time.monotonic() < deadline:
            confirmed = read_confirmed()
            with self.condition:
                if confirmed >= minimum:
                    self.accepting = False
                    return confirmed
                now = time.monotonic()
                if selected is not None and (confirmed > baseline or selected['finished'] or now - granted_at >= 0.05):
                    selected = None
                if selected is None:
                    waiting = [row for row in self.streams if row['waiting'] and not row['finished']]
                    if waiting:
                        selected = min(waiting, key=lambda row: (row['grants'], row['index']))
                        baseline = confirmed
                        selected['limit'] += 4 * 1024**2
                        selected['grants'] += 1
                        granted_at = now
                        self.condition.notify_all()
                self.condition.wait(0.005)
        raise AssertionError(('no durable checkpoint before fault', minimum, self.evidence()))


# 日期：2026-11-06；前一流等待另一流后续数据，模拟TLS业务跨通道依赖，原始流额度仍由实际allowance执行。
def scenario(gate_type):
    gate = gate_type('upload')
    records = [gate.attach('upload'), gate.attach('upload')]
    stopped = threading.Event()
    other_stream_released = threading.Event()
    confirmed = [0]
    errors = []

    # 日期：2026-11-06；只消耗有限密文额度，完成条件由另一流独立设定，不能把额度直接当作确认量。
    def worker(index):
        record = records[index]
        try:
            for _ in range(8):
                amount = gate.allowance(record, stopped)
                assert amount == 16384
                gate.forwarded(record, amount, amount)
            amount = gate.allowance(record, stopped)
            if stopped.is_set():
                return
            gate.forwarded(record, amount, amount)
            if index == 0:
                assert other_stream_released.wait(2)
            else:
                confirmed[0] = 4 * 1024**2
                other_stream_released.set()
        except BaseException as error:
            errors.append(repr(error))
        finally:
            gate.finished(record)

    workers = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in workers:
        thread.start()
    with gate.condition:
        assert gate.condition.wait_for(lambda: all(row['waiting'] for row in records), timeout=2)
    started = time.monotonic()
    failure, reached = None, None
    try:
        reached = gate.checkpoint(lambda: confirmed[0], 4 * 1024**2, timeout=0.75)
    except AssertionError as error:
        failure = repr(error)
    evidence = gate.evidence()
    stopped.set()
    gate.release()
    other_stream_released.set()
    for thread in workers:
        thread.join(2)
    assert not any(thread.is_alive() for thread in workers) and not errors, errors
    return {'gate': gate_type.__name__, 'seconds': round(time.monotonic() - started, 4),
            'timeoutSeconds': 0.75, 'minimumDurableBytes': 4 * 1024**2,
            'confirmedBeforeCleanup': reached, 'failure': failure, 'evidenceBeforeCleanup': evidence}


# 日期：2026-11-06；保存原协调器摘要及两个独立场景，实验不能替代真实TLS、Mac包或正式资格。
def main():
    output = ROOT / 'docs/validation/2026-11-06/checkpoint-r94-dependency-experiment'
    output.mkdir(exist_ok=False)
    original = scenario(CheckpointGate)
    experimental = scenario(RotatingGate)
    assert original['failure'] and original['evidenceBeforeCleanup']['streams'][1]['grants'] == 0
    assert experimental['failure'] is None and experimental['confirmedBeforeCleanup'] == 4 * 1024**2
    value = {'date': '2026-11-06', 'original': original, 'experimental': experimental,
             'originalGateSha256': hashlib.sha256((ROOT / 'tests/checkpoint_gate.py').read_bytes()).hexdigest(),
             'crossStreamDependencyStarvationReproduced': True, 'productionSourceModified': False,
             'syntheticScenarioOnly': True, 'r93MacOSRootCauseProven': False,
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'experiment-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(value, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

"""日期：2026-11-07；收验R98批准测试基线修正后的双Mac原生运行。"""
import argparse
import json
from pathlib import Path


# 日期：2026-11-07；只收单次派发账目所指运行，复用严格原件/XFAIL/新四状态及原16组检查。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=int, required=True)
    args = parser.parse_args()
    ledger = json.loads(Path('.cache/r98-native-regression-dispatch.json').read_text('utf-8'))
    assert ledger['responseReceived'] and args.run == ledger['runId'] == 42264789875
    source = Path('.cache/collect-r97-native-regression.py').read_text('utf-8')
    changes = {
        '38f2384524bfdefa2ffefcc4c737224185a53266': ledger['sourceCommit'],
        'exit-state-r97-native-regression-terminal': 'ci-guard-r98-native-regression-terminal',
    }
    for old, new in changes.items():
        assert old in source
        source = source.replace(old, new)
    scope = {'__name__': 'r98_native_regression', '__file__': str(Path(__file__))}
    exec(compile(source, 'r98_native_regression', 'exec'), scope)
    scope['main']()


if __name__ == '__main__':
    main()

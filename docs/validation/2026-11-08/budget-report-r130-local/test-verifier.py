"""日期：2026-11-08；严格复用既有诊断白名单，只增加本轮真实通过的方法计数。"""
from pathlib import Path
import runpy


# 日期：2026-11-08；6条账本进程就绪信息继续逐字核对，不能通过扩大警告/跳过白名单授予资格。
def qt(path, runner):
    helper = runpy.run_path('.cache/collect-r129-full-native-core.py')
    if path.name != 'state-budget-tests.xml':
        result = helper['qt'](path, runner)
        if path.name == 'server-panel-tests.xml':
            assert result['methods'] == 10 and not result['diagnostics']
            log = path.with_suffix('.log').read_text('utf-8-sig')
            assert 'Totals: 11 passed, 0 failed, 0 skipped' in log
            for name in ['budgetQueryReadOnlyAndFailureClearsSnapshot()', 'budgetQueryThroughQml(compact)', 'budgetQueryThroughQml(default)', 'stateSessionSharedWithCli()']:
                assert 'PASS   : ServerPanelTests::' + name in log
        return result
    text = Path('.cache/prepare-r122-publication.py').read_text('utf-8')
    start = text.index('def budget_junit(')
    end = text.index('\n\n# 日期：', start)
    function = text[start:end].replace("'19'", "'21'").replace('== 19', '== 21').replace("'methods': 19", "'methods': 21").replace("': 23", "': 25")
    namespace = {'ET': __import__('xml.etree.ElementTree', fromlist=['ElementTree'])}
    exec(function, namespace)
    value = namespace['budget_junit'](path, runner == 'windows-2022')
    log = path.with_suffix('.log').read_text('utf-8-sig')
    assert 'Totals: 25 passed, 0 failed, 0 skipped' in log
    for name in ['reportExactAmountsAndHeadroom', 'reportOverdrawnAndCategoryExhaustion']:
        assert 'PASS   : StateBudgetTests::' + name + '()' in log
    return value

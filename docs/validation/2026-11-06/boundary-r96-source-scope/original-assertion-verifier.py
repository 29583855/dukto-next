"""日期：2026-11-07；在本机执行工作流中的精确断言保护代码，避免引号或缩进损坏CI。"""
from pathlib import Path
import subprocess
from unittest.mock import patch

import yaml


# 日期：2026-11-07；仅将工作流Git读取定向发布checkout，其余验证使用真实当前测试原件。
def main():
    value = yaml.safe_load(Path('.github/workflows/macos-listener-regression.yml').read_text('utf-8'))
    script = next(step['run'] for step in value['jobs']['regression']['steps']
                  if step.get('name') == 'Verify original failed assertions remain unchanged')
    marker = "python - <<'PY'"
    start = script.index(marker) + len(marker)
    code = script[start:script.index('\nPY', start)]
    original = subprocess.check_output
    # 日期：2026-11-07；只改变Git命令cwd，确保不会读取根目录的不同Git状态。
    def execute(args, **kwargs):
        kwargs['cwd'] = '.cache/github-29583855-dukto-next-r28'
        return original(args, **kwargs)
    with patch('subprocess.check_output', execute):
        exec(compile(code, 'macos-listener-regression.yml', 'exec'), {})
    print('Original assertions remain exact after removing one explicit Darwin boundary annotation')


if __name__ == '__main__':
    main()

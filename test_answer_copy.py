# -*- coding: utf-8 -*-
"""练习答案原句一键复制前端静态回归测试。"""
from pathlib import Path

html = Path('static/index.html').read_text(encoding='utf-8')
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print('  FAIL:', msg)


check('async function copyVerifiedAnswerSentence(text)' in html,
      '必须有统一的答案原句复制入口')
check("api('/api/grammar/check'" in html,
      '复制前必须调用服务端完整句语法门禁')
check("copyVerifiedAnswerSentence(el&&el.dataset?el.dataset.raw:'')" in html,
      '即时答案必须从 data-raw 复制规范原句，不得复制渲染后的注音/讲解')
check(html.count('复制答案原句') >= 8,
      f'复习、挖空、组句、听力、心理学及成绩回顾均应有复制按钮（实际 {html.count("复制答案原句")}）')
check('复制考察句' not in html,
      '按钮不得继续使用略显生硬的“复制考察句”表述')
check('复制答案中显示的完整日文原句（不含注音、译文和讲解）' in html,
      '按钮应有正式、准确的操作说明')
check("copyText(${jsArg(q.text)},'考察句')" not in html,
      '成绩回顾不得绕过语法门禁直接复制')
check("toast('该原句未通过完整句语法质检，已停止复制')" in html,
      '未通过门禁时必须明确停止复制')

if fails:
    raise SystemExit(f'答案复制回归测试失败：{len(fails)} 项')
print('===== 答案原句复制回归测试: 全部通过 =====')

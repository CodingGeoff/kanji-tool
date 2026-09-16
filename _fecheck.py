# -*- coding: utf-8 -*-
"""前端自检：index.html 中 ① 被 JS 引用的 DOM id 是否存在 ② 内联事件处理函数是否已定义
（防止出现 ragPriority 那类「元素不存在 → 浏览器抛错、功能静默失效」的问题）"""
import io
import re
import sys

LINES = io.open('static/index.html', encoding='utf-8').read().split('\n')
html = '\n'.join(LINES)
script = '\n'.join(LINES[480:])          # 主脚本区（页面结构在前，脚本在后）
ids = set(re.findall(r'id="([^"]+)"', html))
refs = set(re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", script)) | \
       set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", script))
missing_ids = sorted(refs - ids)
defined = set(re.findall(r'^\s*(?:async\s+)?function\s+([A-Za-z0-9_$]+)', script, re.M)) | \
          set(re.findall(r'^\s*(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?\(', script, re.M)) | \
          set(re.findall(r'^\s*(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*function', script, re.M)) | \
          set(re.findall(r'^\s*(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*[A-Za-z0-9_$]+\s*=>', script, re.M))
BROWSER_GLOBALS = {'encodeURIComponent', 'decodeURIComponent', 'setTimeout', 'clearTimeout',
                   'setInterval', 'parseInt', 'parseFloat', 'alert', 'confirm', 'prompt',
                   'requestAnimationFrame', 'speechSynthesis', 'fetch', 'localStorage'}
calls = set()
for attr in re.findall(r'on(?:click|change|input|keydown|submit)="([^"]*)"', html):
    for m in re.finditer(r'(?<![\w.$])([A-Za-z_$][A-Za-z0-9_$]*)\s*\(', attr):
        calls.add(m.group(1))
dynamic_ids = {'bkMenu', 'bkModal', 'gmodal', 'toast'}   # 由 JS 动态创建
missing_ids = [x for x in missing_ids if x not in dynamic_ids]
builtins = {'if', 'for', 'while', 'return', 'event', 'this', 'typeof', 'function', 'catch', 'switch'}
missing_fn = sorted(c for c in calls - defined - builtins - BROWSER_GLOBALS
                    if not c.startswith(('Math', 'JSON', 'Object', 'String')))
dup = sorted(n for n in set(re.findall(r'^\s*(?:async\s+)?function\s+([A-Za-z0-9_$]+)', script, re.M))
             if len(re.findall(r'^\s*(?:async\s+)?function\s+' + n + r'\s*\(', script, re.M)) > 1)
print('JS 引用但不存在的 id :', missing_ids or '无')
print('内联事件未定义函数   :', missing_fn or '无')
print('重复定义的函数       :', dup or '无')
ok = not (missing_ids or missing_fn or dup)
print('== 前端自检', '通过 ==' if ok else '失败 ==')
sys.exit(0 if ok else 1)
# -*- coding: utf-8 -*-
"""从 static/index.html 抽取 <script> 块并做语法检查（node --check）"""
import os
import re
import subprocess
import sys

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'index.html')
src = open(HTML, encoding='utf-8').read()
blocks = re.findall(r'<script[^>]*>(.*?)</script>', src, re.S)
print(f'script 块数: {len(blocks)}')
fail = 0
for i, b in enumerate(blocks):
    if not b.strip():
        continue
    p = os.path.join(os.path.dirname(HTML), f'_jscheck_{i}.js')
    open(p, 'w', encoding='utf-8').write(b)
    r = subprocess.run(['node', '--check', p], capture_output=True, text=True)
    tag = 'OK  ' if r.returncode == 0 else 'FAIL'
    print(f'  [{tag}] block#{i} ({len(b)} chars)')
    if r.returncode != 0:
        fail += 1
        print('    ' + (r.stderr or '').strip()[:600])
    os.remove(p)
print('JS 语法检查:', '全部通过' if not fail else f'{fail} 个块有语法错误')
sys.exit(1 if fail else 0)
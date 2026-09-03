# -*- coding: utf-8 -*-
"""扫描歌曲 tokens：同一行内同一汉字出现多次，但只有部分出现带注音"""
import sqlite3
import json
import re

kanji_re = re.compile(r'[一-鿿]')
c = sqlite3.connect(r'd:\10_Workspace\kanji-tool\kanji.db')
c.row_factory = sqlite3.Row
rows = c.execute('SELECT id, title, lyrics, tokens FROM songs').fetchall()
found = 0
for r in rows:
    toks = json.loads(r['tokens']) if r['tokens'] else []
    lines = r['lyrics'].split('\n')
    for li, (ln, t) in enumerate(zip(lines, toks)):
        if not t or not isinstance(t, list):
            continue
        # 统计每个汉字：出现次数 vs 带注音次数
        cnt, ann = {}, {}
        for tk in t:
            s = tk.get('s') or ''
            has_r = bool(tk.get('r'))
            for ch in s:
                if kanji_re.match(ch):
                    cnt[ch] = cnt.get(ch, 0) + 1
                    if has_r:
                        ann[ch] = ann.get(ch, 0) + 1
        for ch, n in cnt.items():
            a = ann.get(ch, 0)
            if n >= 2 and 0 < a < n:
                found += 1
                if found <= 15:
                    print(f"song {r['id']} line {li}: {ch} x{n} annotated {a} | {ln[:44]}")
                break
print('total:', found)

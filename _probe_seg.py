# -*- coding: utf-8 -*-
"""临时探针：明日への手紙 一行，库内 sp 标记 vs 当前算法 chunk_starts"""
import json
import sqlite3
import sys

sys.path.insert(0, '.')
import db
import ktv

print('db.DB_PATH =', db.DB_PATH)
con = sqlite3.connect('kanji.db')
con.row_factory = sqlite3.Row
row = con.execute("SELECT id,title,lyrics,tokens FROM songs WHERE title LIKE '%明日への手紙%'").fetchone()
lines = (row['lyrics'] or '').split('\n')
toks = json.loads(row['tokens']) if row['tokens'] else []
for i, ln in enumerate(lines):
    if '続く' not in ln or len(ln) > 30:
        continue
    print(f'\n== 行 {i}: {ln!r}')
    if i >= len(toks):
        print('   tokens 缺失')
        continue
    tv = toks[i]
    off = 0
    for t in tv:
        if isinstance(t, dict):
            print(f"   {off:>2} {'SP' if t.get('sp') else '  '} s={t.get('s')!r} w={t.get('w')!r}")
        off += len(t.get('s') or '') if isinstance(t, dict) else 0
    print('   chunk_starts:', sorted(ktv.chunk_starts(ln)))
    for o, w in ktv._offset_words(ln):
        print(f'   mecab {o:>2} {w.surface!r} {w.feature.pos1}')
    tv2 = json.loads(json.dumps(tv))
    print('   seg_mark(copy) would change:', ktv._seg_mark(tv2, ln))
con.close()

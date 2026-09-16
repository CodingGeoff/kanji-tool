# -*- coding: utf-8 -*-
"""调试：当前算法对 INNOCENCE 报告行的分群输出 vs 存储标记"""
import json
import sqlite3
import sys

sys.path.insert(0, '.')
import ktv

c = sqlite3.connect('kanji.db')
c.row_factory = sqlite3.Row
r = c.execute("SELECT id,title,lyrics,tokens FROM songs WHERE title LIKE '%INNOCENCE%'").fetchone()
lines = r['lyrics'].split('\n')
toks = json.loads(r['tokens'])
ln = lines[3]
tk = toks[3]

print('LINE:', repr(ln))
ms = [(off, w.surface, w.feature.pos1, w.feature.pos2) for off, w in ktv._offset_words(ln)]
print('MeCab morphemes:')
for off, s, p1, p2 in ms:
    print(f'   {off:>2} {s!r:<14} {p1}/{p2}')
starts = ktv.chunk_starts(ln)
print('chunk_starts:', sorted(starts))

tokens2 = json.loads(json.dumps(tk))
changed = ktv._seg_mark(tokens2, ln)
print('self-heal changed:', changed)
print('healed sp:', [(t.get('s'), bool(t.get('sp'))) for t in tokens2])
disp = ''.join((' ' if t.get('sp') else '') + t['s'] for t in tokens2)
print('healed display:', disp)

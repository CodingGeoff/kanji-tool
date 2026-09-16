# -*- coding: utf-8 -*-
"""临时探针2：剩余问题行 —— 词内 sp（简体字歌词）与 6 行陈旧标记为何未被 _seg_mark 修复"""
import json
import sqlite3
import sys

sys.path.insert(0, '.')
import ktv

con = sqlite3.connect('kanji.db')
con.row_factory = sqlite3.Row
songs = con.execute("SELECT id,title,lyrics,tokens FROM songs WHERE title IN ('夏恋','遥か','７月の翼')").fetchall()
for s in songs:
    lines = (s['lyrics'] or '').split('\n')
    toks = json.loads(s['tokens']) if s['tokens'] else []
    if len(toks) != len(lines):
        continue
    for ln, tv in zip(lines, toks):
        if not (tv and isinstance(tv, list) and 's' in tv[0]):
            continue
        stored, off = set(), 0
        for t in tv:
            if isinstance(t, dict) and t.get('sp'):
                stored.add(off)
            off += len(t.get('s') or '') if isinstance(t, dict) else 0
        starts = ktv.chunk_starts(ln)
        recon = ''.join(t.get('s') or '' for t in tv if isinstance(t, dict))
        need_fix = stored != starts
        if not need_fix:
            continue
        print(f"\n== {s['title']} | {ln!r}")
        print(f"   stored={sorted(stored)} starts={sorted(starts)} recon==line: {recon == ln}")
        if recon != ln:
            print(f"   recon={recon!r}")
        for o, w in ktv._offset_words(ln):
            print(f"   mecab {o:>2} {w.surface!r} {w.feature.pos1}/{w.feature.pos2}")
con.close()

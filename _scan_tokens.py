# -*- coding: utf-8 -*-
"""定位 song 11 中 上/凉/重/雨 各次出现的注音情况"""
import sqlite3
import json

c = sqlite3.connect(r'd:\10_Workspace\kanji-tool\kanji.db')
c.row_factory = sqlite3.Row
r = c.execute('SELECT * FROM songs WHERE id=11').fetchone()
toks = json.loads(r['tokens'])
lines = r['lyrics'].split('\n')
targets = '上凉重雨'
for li, (ln, t) in enumerate(zip(lines, toks)):
    if not t or not isinstance(t, list):
        continue
    hits = [tk for tk in t if any(ch in targets for ch in (tk.get('s') or ''))]
    if hits:
        desc = ' | '.join(f"{tk['s']}→{tk.get('r')}{('(unk)' if tk.get('unk') else '')}" for tk in hits)
        print(f"line {li}: {ln[:40]}  => {desc}")

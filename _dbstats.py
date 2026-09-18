# -*- coding: utf-8 -*-
"""一次性診断脚本：比較各份 kanji.db 的表行数，判断哪一份是“最新最全”。用完即删。"""
import os
import sqlite3

FILES = [
    r'd:\10_Workspace\kanji-tool\kanji.db',
    r'd:\10_Workspace\kanji-tool\_dbbackup\local\kanji.db',
    r'd:\10_Workspace\kanji-tool\_dbbackup\remote\kanji.db',
    r'd:\10_Workspace\kanji-tool\_dbbackup\merged\kanji.db',
]
TABLES = ['sentences', 'kanji_index', 'songs', 'history', 'srs', 'settings',
          'fav_words', 'fav_sentences', 'books', 'book_lessons',
          'book_sentences', 'book_kanji', 'book_words', 'book_plan',
          'book_progress']

rows = {}
for path in FILES:
    conn = sqlite3.connect('file:%s?mode=ro' % path.replace('\\', '/'), uri=True)
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    stat = {}
    for t in TABLES:
        if t in have:
            stat[t] = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
    stat['_max_ids'] = {}
    for t, col in (('sentences', 'id'), ('songs', 'id'), ('history', 'ts')):
        if t in have:
            v = conn.execute('SELECT MAX(%s) FROM "%s"' % (col, t)).fetchone()[0]
            stat['_max_ids'][t] = v
    rows[path] = stat
    conn.close()

labels = [os.path.relpath(p, r'd:\10_Workspace\kanji-tool') for p in FILES]
print('table'.ljust(18) + ''.join(l.ljust(34) for l in labels))
for t in TABLES:
    line = t.ljust(18)
    for p in FILES:
        line += str(rows[p].get(t, '-')).ljust(34)
    print(line)
print()
for p, l in zip(FILES, labels):
    print(l, '| max ids:', rows[p]['_max_ids'])

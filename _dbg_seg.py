# -*- coding: utf-8 -*-
"""临时调试：INNOCENCE 歌词分词标记诊断"""
import json
import sqlite3

con = sqlite3.connect('kanji.db')
con.row_factory = sqlite3.Row
rows = con.execute("SELECT id,title,artist,lyrics,tokens FROM songs "
                   "WHERE title LIKE '%INNOCENCE%' OR artist LIKE '%藍井%'").fetchall()
print('命中', len(rows), '首')
for r in rows:
    print('==', r['id'], r['title'], r['artist'])
    lines = (r['lyrics'] or '').split('\n')
    toks = json.loads(r['tokens']) if r['tokens'] else []
    for i, (ln, tv) in enumerate(zip(lines, toks + [None] * len(lines))):
        if 'いれば' in ln or '未来' in ln:
            print(' LYRIC line', i, repr(ln))
            if tv:
                print(' TOKENS:', json.dumps(tv, ensure_ascii=False))
con.close()

import ktv
for line in ('ここに いれば 二度と　未来見る事 出来ない',
             'ここに いれば 二度と　未来 見る事 出来ない',
             '未来見る事出来ない', '未来 見る事', '夢を見る事'):
    ms = [(o, w.surface, w.feature.pos1, w.feature.pos2, w.feature.cForm,
           (w.feature.lemma or '').split('-')[0]) for o, w in ktv._offset_words(line)]
    print('\nLINE', repr(line))
    for m in ms:
        print('   ', m)
    print('  chunk_starts ->', sorted(ktv.chunk_starts(line)))

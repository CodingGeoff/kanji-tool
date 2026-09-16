# -*- coding: utf-8 -*-
"""临时诊断：全库歌词分词标记问题扫描
A. 库内标记「词内断开」：sp 出现在同一个 MeCab 词的内部（如 見る → 見|る）
B. 库内标记与当前算法不一致（陈旧标记，打开歌曲时 ensure_seg 可自愈）
C. 当前算法的形式名詞误断（用言连体形 + 事/物/ため… 应与前句同群）
"""
import json
import sqlite3
import sys

sys.path.insert(0, '.')
import ktv

FORMAL = {'事', 'こと', '物', 'もの', '物事', 'ため', '為', 'わけ', '訳', 'はず', '筆',
          'ところ', '所', '時', 'とき', 'つもり', '通り', 'とおり', 'かわり', '代わり',
          'せい', 'おかげ', 'お陰', 'まま', '毎', 'ごと', 'つど', 'たび', '際',
          'あと', '後', 'うち', '内', 'ほか', '他', 'もと', '下', '向こう', '向う'}

con = sqlite3.connect('kanji.db')
con.row_factory = sqlite3.Row
songs = con.execute('SELECT id,title,lyrics,tokens FROM songs').fetchall()
con.close()

n_lines = n_a = n_b = n_c = 0
samples_a, samples_b, samples_c = [], [], []
songs_affected = set()
for s in songs:
    lines = (s['lyrics'] or '').split('\n')
    toks = json.loads(s['tokens']) if s['tokens'] else []
    if len(toks) != len(lines):
        continue
    changed_song = False
    for ln, tv in zip(lines, toks):
        if not (tv and isinstance(tv, list) and tv and 'k' not in tv[0] and 's' in tv[0]):
            continue
        n_lines += 1
        # —— A. 库内词内断开（同一 w 内部出现 sp）——
        prev = None
        for t in tv:
            if not isinstance(t, dict):
                prev = t
                continue
            w = t.get('w')
            if t.get('sp') and prev is not None and isinstance(prev, dict) \
                    and w and prev.get('w') == w and (prev.get('s') or ''):
                n_a += 1
                changed_song = True
                if len(samples_a) < 12:
                    samples_a.append((s['title'][:14], ln[:26], (prev.get('s') or '') + '｜' + (t.get('s') or ''), w))
            prev = t
        # —— B. 陈旧标记（当前算法重算会变化）——
        if ktv._seg_mark(json.loads(json.dumps(tv)), ln):
            n_b += 1
            changed_song = True
            if len(samples_b) < 8:
                samples_b.append((s['title'][:14], ln[:30]))
        # —— C. 当前算法的形式名詞误断 ——
        ms = [(o, w.surface, w.feature.pos1 or '') for o, w in ktv._offset_words(ln)]
        starts = ktv.chunk_starts(ln)
        for k in range(len(ms)):
            off, surf, p1 = ms[k]
            if off in starts and surf in FORMAL and k > 0 and ms[k - 1][2] in (
                    '動詞', '形容詞', '形状詞', '助動詞'):
                n_c += 1
                changed_song = True
                if len(samples_c) < 12:
                    samples_c.append((s['title'][:14], ln[:30], ms[k - 1][1] + '｜' + surf))
    if changed_song:
        songs_affected.add(s['id'])

print(f'歌曲 {len(songs)} 首 / 有效歌词行 {n_lines} 行')
print(f'A 库内词内断开（見る→見|る 类）: {n_a} 处，样例:')
for x in samples_a:
    print('   ', x)
print(f'B 陈旧标记（重算后即变化的行）: {n_b} 行，样例:')
for x in samples_b:
    print('   ', x)
print(f'C 当前算法形式名詞误断: {n_c} 处，样例:')
for x in samples_c:
    print('   ', x)
print(f'受影响歌曲: {len(songs_affected)} 首')

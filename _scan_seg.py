# -*- coding: utf-8 -*-
"""临时诊断 v2：库内 sp 标记 vs 当前算法 精确集合比较
  A. 库内标记「词内断开」：sp 出现在同一个 furigana 词（w）内部（如 続|く）
  B. 库内标记与 chunk_starts 不一致（真正陈旧；_seg_mark pop+re-add 恒 True，不能用）
  C. 当前算法的形式名詞误断（用言 + 事/時/ため… 应与前句同群）
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
        # —— 库内 sp 的字符偏移集合 ——
        off, stored = 0, set()
        prev_dict = None
        for t in tv:
            if isinstance(t, dict):
                if t.get('sp'):
                    stored.add(off)
                    # A. 词内断开：sp token 与前一 token 同属一个 furigana 词
                    if prev_dict is not None and t.get('w') and prev_dict.get('w') == t['w'] \
                            and (prev_dict.get('s') or ''):
                        n_a += 1
                        changed_song = True
                        if len(samples_a) < 12:
                            samples_a.append((s['title'][:14], ln[:26],
                                              (prev_dict.get('s') or '') + '｜' + (t.get('s') or ''), t['w']))
                prev_dict = t
            off += len(t.get('s') or '') if isinstance(t, dict) else 0
        # —— B. 与当前算法精确比较 ——
        starts = ktv.chunk_starts(ln)
        if stored != starts:
            n_b += 1
            changed_song = True
            if len(samples_b) < 8:
                samples_b.append((s['title'][:14], ln[:30], sorted(stored), sorted(starts)))
        # —— C. 当前算法形式名詞误断 ——
        ms = [(o, w.surface, w.feature.pos1 or '') for o, w in ktv._offset_words(ln)]
        for k in range(len(ms)):
            o_, surf, p1 = ms[k]
            if o_ in starts and surf in FORMAL and k > 0 and ms[k - 1][2] in (
                    '動詞', '形容詞', '形状詞', '助動詞'):
                n_c += 1
                changed_song = True
                if len(samples_c) < 12:
                    samples_c.append((s['title'][:14], ln[:30], ms[k - 1][1] + '｜' + surf))
    if changed_song:
        songs_affected.add(s['id'])

print(f'歌曲 {len(songs)} 首 / 有效歌词行 {n_lines} 行')
print(f'A 库内词内断开（続く→続|く 类）: {n_a} 处，样例:')
for x in samples_a:
    print('   ', x)
print(f'B 库内标记 ≠ 当前算法（陈旧/缺失）: {n_b} 行，样例:')
for x in samples_b:
    print('   ', x)
print(f'C 当前算法形式名詞误断: {n_c} 处，样例:')
for x in samples_c:
    print('   ', x)
print(f'受影响歌曲: {len(songs_affected)} 首')


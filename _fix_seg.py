# -*- coding: utf-8 -*-
"""一次性修复：用修正后的算法重算全部歌曲的分词标记（sp）并回写数据库。
只改 sp 标记，不动歌词文本与读音；_seg_mark 自带「重建不一致则放弃」的保护。"""
import json
import sys

sys.path.insert(0, '.')
import db
import ktv

rows = db.list_songs(limit=100000)
fixed_songs = fixed_lines = 0
for s in rows:
    full = db.get_song(s['id'])
    lines = (full['lyrics'] or '').split('\n')
    toks = json.loads(full['tokens']) if full['tokens'] else []
    if len(toks) != len(lines) or not toks:
        continue
    changed_any = False
    for ln, tv in zip(lines, toks):
        if tv and isinstance(tv, list) and tv and 'k' not in tv[0] and 's' in tv[0]:
            changed_any |= ktv._seg_mark(tv, ln)
    if changed_any:
        db.update_song_tokens(full['id'], toks)
        fixed_songs += 1
        fixed_lines += 1
print(f'回写完成：{fixed_songs} 首歌（涉及行已重标）')

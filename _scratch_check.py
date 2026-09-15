# -*- coding: utf-8 -*-
"""临时自检脚本（用完即删）：确认课本拆分/导入/计划管线可用。"""
import json
import time

TEXT = """《東京散策》
作者：テスト
第1課
今日は良い天気ですね。東京タワーへ行きました。

第2課
桜が咲きました。春は美しい季節です。
---
《春の歌》
第1課
花見に行きます。お花見は楽しいです。"""

import textbook

books = textbook.parse_books(TEXT)
print('books:', [(b['title'], b['author'], len(b['lessons']), len(b['sentences'])) for b in books])
for l in books[0]['lessons']:
    print('  lesson:', l['title'], l['sentences'])

k, w = textbook.extract_units(books[0]['sentences'][0])
print('kanji units:', k[:5])
print('word units:', w[:5])

# ---- 写库 + 计划（用真实库，稍后测试会清理） ----
import db
bid = None
try:
    res = textbook.import_book(books[0], deadline='2026-10-15', minutes_per_day=30, target_stage=5)
    print('imported:', res)
    bid = res['id']
    plan = textbook.build_plan([bid])
    print('plan ok:', plan.get('ok'), 'feasible:', plan.get('feasible'),
          'days:', plan.get('days'), 'new_total:', plan.get('new_total'),
          'first_days:', [(d['day'], len(d['new'])) for d in (plan.get('per_day') or [])[:4]])
    lp = textbook.load_plan([bid])
    print('load_plan keys:', sorted(lp.keys()))
    print('today:', {k2: lp.get(k2) for k2 in ('today', 'total_new', 'total_done') if k2 in lp})
    det = textbook.book_detail(bid)
    print('detail:', det['title'], 'lessons:', len(det['lessons_list']),
          'curve:', len(det['curve']), 'plan days:', len(det['plan'].get('per_day') or []))
finally:
    if bid:
        db.delete_book(bid)
    db.log('_scratch', 'done')
print('ALL OK')

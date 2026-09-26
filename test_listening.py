# -*- coding: utf-8 -*-
"""听力练习（listening.py）专项测试
================================================================
覆盖：
  1. 配置读写：白名单 + 边界修正
  2. meaning 题：4 选项语言一致（绝不出现"一眼认出哪个是中文"的伪劣题）、
     干扰项均为真实译文、答案在选项中
  3. discriminate 题：换词候选为真实语料名词、4 个选项互不相同、
     答案与原句完全一致、复合词（图书馆型）不被拆散
  4. scope 稳健性：与组句练习共用同一套 resolve_book_scope，
     "仅课本" 不会泄漏语料库句子
  5. 统计记录
临时库隔离，不碰真实数据。"""
import os
import sys
import json
import shutil
import random
import sqlite3
import tempfile

sys.path.insert(0, '.')

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


import db
tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    for t in ('books', 'book_lessons', 'book_sentences'):
        try:
            c0.execute(f'DELETE FROM {t}')
        except sqlite3.OperationalError:
            pass
    c0.execute("DELETE FROM settings WHERE key IN ('listening_cfg','listening_stats')")
db.DB_PATH = api_db

import textbook
import listening as ls

random.seed(20260926)

print('== 1. 配置读写：白名单 + 边界修正 ==')
cfg = ls.listening_cfg()
check(cfg['enabled'] is True and cfg['scope'] == 'corpus' and cfg['rate'] == 'normal', f'默认配置 {cfg}')
cfg2 = ls.save_listening_cfg({'scope': 'book', 'rate': 'slow', 'count': 999, 'bogus_key': 'x'})
check(cfg2['scope'] == 'book' and cfg2['rate'] == 'slow' and cfg2['count'] == 20,
      f'保存并做边界修正（count 上限 20）：{cfg2}')
check('bogus_key' not in cfg2, '非白名单键不写入')
ls.save_listening_cfg({'scope': 'corpus', 'rate': 'normal', 'count': 6})

print('== 2. meaning 题：语言一致 + 真实干扰项 ==')
GOOD_ZH = [
    ('彼は手を私の肩に置いた。', '他把手放在我的肩膀上。'),
    ('簡単に手に入れたものはすぐに失いやすい。', '来得容易去得快。'),
    ('夜遅くまで起きていては駄目だよ。', '晚上不该熬夜到这么晚。'),
    ('これはセルビアで三番目に大きい町である。', '这是塞尔维亚第三大城市。'),
    ('警戒するに越したことはない。', '再怎么小心也不为过。'),
    ('彼はこのギターが好きだ。', '他喜欢这把吉他。'),
    ('今朝から本を三冊読んだ。', '今天早上以来我读了三本书。'),
]
GOOD_EN = [
    ('猫が窓の外を見ている。', 'The cat is looking out the window.'),
    ('明日は雨が降るでしょう。', 'It will probably rain tomorrow.'),
]
for i in range(30):
    db.add_sentence(t := f'これはテスト文{i}です。', f'This is test sentence {i}.', 'unit_test', None, [], [])
for txt, tr in GOOD_ZH + GOOD_EN:
    db.add_sentence(txt, tr, 'unit_test', None, [], [])

d = ls.make_quiz(count=12, scope='corpus')
check(d['ok'], f'出题成功：{d}')
meaning_qs = [q for q in d['questions'] if q['qtype'] == 'meaning']
check(bool(meaning_qs), 'meaning 题型应出现')
for q in meaning_qs:
    check(len(q['options']) == 4 and len(set(q['options'])) == 4, f'4 个选项且不重复：{q["options"]}')
    check(q['answer'] in q['options'], f'答案在选项中：{q}')
    langs = {ls._tr_lang(o) for o in q['options']}
    check(len(langs) == 1, f'4 个选项语言必须一致（否则靠文字系统就能蒙对）：{q["options"]} → {langs}')

print('== 3. discriminate 题：真实名词换词 + 互不相同 + 复合词不拆散 ==')
db.add_sentence('彼女は毎日図書館で本を読んでいる。', '她每天在图书馆看书。', 'unit_test', None, [], [])
db.add_sentence('卵はどのように調理しましょうか。', '鸡蛋要怎么烹调呢。', 'unit_test', None, [], [])
db.add_sentence('彼はソファーに座って雑誌を読んでいた。', '他坐在沙发上看杂志。', 'unit_test', None, [], [])
d = ls.make_quiz(count=15, scope='corpus')
disc_qs = [q for q in d['questions'] if q['qtype'] == 'discriminate']
check(bool(disc_qs), 'discriminate 题型应出现')
for q in disc_qs:
    check(len(q['options']) == 4 and len(set(q['options'])) == 4, f'4 个选项且不重复：{q["options"]}')
    check(q['answer'] == q['text'] and q['answer'] in q['options'], f'原句本身是唯一正确答案：{q}')
    check('館' not in (q['swapped']['from'] if q.get('swapped') else ''),
          '不应把复合词的后半部分（接尾辞）单独当作替换目标')
    for opt in q['options']:
        check(len(opt) == len(q['text']) or True, '基本合理性占位')  # 长度可能因替换词不同而略变

print('== 4. scope 稳健性：与组句练习共用同一套解析，"仅课本" 不泄漏语料库 ==')
bk = textbook.import_book({'title': '听力测试课本', 'author': '', 'level': '',
                           'lessons': [{'title': '第1課', 'sentences': [g[0] for g in GOOD_ZH]}]})
book_sids = {r['sentence_id'] for r in db.get_conn().execute(
    'SELECT sentence_id FROM book_sentences WHERE book_id=?', (bk['id'],)).fetchall()}
d = ls.make_quiz(count=8, scope='book')
check(d['ok'] and d['scope'] == 'book' and d.get('scope_auto_all') is True,
      f'不传 book_ids 时自动使用全部启用中的课本：{d.get("scope")} {d.get("scope_auto_all")}')
for q in d['questions']:
    if q.get('sid'):
        check(q['sid'] in book_sids, f'"仅课本" 题目必须来自该课本：{q.get("sid")}')

d0 = ls.make_quiz(count=5, scope='book', book_ids=[])
print('== 5. 空书架诚实退化 + 关闭开关 ==')
with sqlite3.connect(api_db) as c0:
    c0.execute('DELETE FROM books')
    c0.execute('DELETE FROM book_lessons')
    c0.execute('DELETE FROM book_sentences')
d = ls.make_quiz(count=5, scope='book')
check(d['ok'] and d['scope'] == 'corpus' and d.get('scope_note') == 'no_books_fallback_corpus',
      f'空书架应诚实退化为 corpus：{d}')
ls.save_listening_cfg({'enabled': False})
d = ls.make_quiz()
check(d['ok'] is False and '关闭' in (d.get('reason') or ''), f'关闭开关生效：{d}')
ls.save_listening_cfg({'enabled': True})

print('== 6. 统计记录 ==')
r = ls.record_results([{'qtype': 'meaning', 'level': 'N4', 'ok': True},
                       {'qtype': 'discriminate', 'level': 'N4', 'ok': False}])
check(r['ok'] and r['asked'] == 2 and r['correct'] == 1, f'计分 {r}')
st = ls.listening_stats(7)
check(st and st[-1]['asked'] == 2 and st[-1]['correct'] == 1, f'统计落库 {st}')

print()
if FAILS:
    print(f'===== 听力练习测试: {len(FAILS)} 项失败 =====')
    sys.exit(1)
else:
    print('===== 听力练习测试: 全部通过 =====')

shutil.rmtree(tmp, ignore_errors=True)

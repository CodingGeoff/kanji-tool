# -*- coding: utf-8 -*-
"""组句练习 · 题源 scope 端到端回归测试
================================================================
复现并锁死用户实测到的问题：「组句配置里选『仅课本』，出的却还是很多
语料库的句子」。根因是 sentence_builder.make_quiz 在 scope='book' 但调用方
（前端）没有传 book_ids 时，静默把候选池换成全库 sentences 表，且返回的
scope 字段仍然写 'book'，用户无法在界面上察觉题源被偷换。

本测试直接打 HTTP API（与真实前端调用路径一致：POST /api/builder/quiz，
不带 book_ids），验证：
  1. 用户一本课本都没有 → 诚实返回 scope='corpus'（不是挂着 book 的牌子卖 corpus）；
  2. 用户导入课本后 → 不传 book_ids 也能自动只用课本例句出题，
     且返回的每一题 origin 都指向课本，sid 都在该课本的 book_sentences 里；
  3. 语料库里同时存在大量其他（非课本）语料句子时，"仅课本" 配置依然
     不会混入这些语料库句子。
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
    for t in ('books', 'book_lessons', 'book_sentences', 'book_kanji', 'book_words',
              'book_plan', 'book_progress', 'srs', 'fav_sentences'):
        try:
            c0.execute(f'DELETE FROM {t}')
        except sqlite3.OperationalError:
            pass
    c0.execute("DELETE FROM settings WHERE key IN "
               "('sentence_builder_cfg','sentence_builder_stats')")
db.DB_PATH = api_db

import grammar
import textbook
import sentence_builder as sb
import app as appmod
client = appmod.app.test_client()

random.seed(20260926)

GOOD = [
    '雨が降っているので、試合は中止になりました。',
    '彼女は毎日図書館で本を読んでいる。',
    'この薬を飲めば、すぐによくなるでしょう。',
    '彼は来ないかもしれないと言っていた。',
    '日本語が上手になるために、毎日練習している。',
    '母に心配をかけないように、早く帰ることにした。',
    '私は昨日図書館で本を読みました。',
    '明日は雨が降るかもしれません。',
]

print('== 1. 一本课本都没有：POST scope=book 不传 book_ids → 诚实退化为 corpus ==')
r = client.post('/api/builder/cfg', json={'scope': 'book'})
check(r.get_json()['ok'], '保存组句配置 scope=book')
r = client.post('/api/builder/quiz', json={})
d = r.get_json()
check(d['ok'] and d['scope'] == 'corpus' and d.get('scope_note') == 'no_books_fallback_corpus',
      f'空书架应诚实报告 scope=corpus（而不是挂 book 的牌子卖 corpus）：{d.get("scope")} {d.get("scope_note")}')

print('== 2. 导入课本后：不传 book_ids，"仅课本" 也应自动只用课本例句 ==')
bk = textbook.import_book({'title': '组句测试课本', 'author': '', 'level': '',
                           'lessons': [{'title': '第1課', 'sentences': GOOD}]})
book_sids = {r['sentence_id'] for r in db.get_conn().execute(
    'SELECT sentence_id FROM book_sentences WHERE book_id=?', (bk['id'],)).fetchall()}
check(len(book_sids) >= 6, f'课本应有若干句子入库：{book_sids}')

r = client.post('/api/builder/quiz', json={'count': 8})
d = r.get_json()
check(d['ok'] and d['scope'] == 'book' and d.get('scope_auto_all') is True,
      f'不传 book_ids 时应自动使用全部启用中的课本，scope 仍为 book：{d.get("scope")} {d.get("scope_auto_all")}')
check(set(d.get('book_ids') or []) == {bk['id']}, f'自动解析出的课本 id 应为该书：{d.get("book_ids")}')
arrange_qs = [q for q in d['questions'] if q['qtype'] == 'arrange']
check(bool(arrange_qs), f'应出到组句题：{d["questions"]}')
for q in arrange_qs:
    check(q.get('sid') in book_sids, f'"仅课本" 题目的 sid 必须来自该课本：{q.get("sid")} not in {book_sids}')
    check('组句测试课本' in (q.get('origin') or ''), f'出处应标注课本名：{q.get("origin")}')

print('== 3. 语料库里另有海量非课本语料时，"仅课本" 配置依然不应混入 ==')
# 语料库里插入一批与课本无关、纯语料库来源的句子（模拟真实场景：Tatoeba/Wikipedia 等）
extra_sids = set()
for i in range(200):
    sid = db.add_sentence(f'今日は天気がとても良いですね{i}。', None, 'tatoeba', None, [], [])
    if sid:
        extra_sids.add(sid)
check(len(extra_sids) > 0, '应成功插入语料库对照句')

r = client.post('/api/builder/quiz', json={'count': 10})
d = r.get_json()
check(d['ok'] and d['scope'] == 'book', f'scope 仍应保持 book：{d.get("scope")}')
leaked = [q for q in d['questions'] if q.get('qtype') == 'arrange' and q.get('sid') in extra_sids]
check(leaked == [], f'"仅课本" 绝不应该混入语料库对照句，但检测到泄漏：{leaked}')

print('== 4. scope=corpus 时，语料库句子应能正常出现（确认没有把语料库堵死）==')
r = client.post('/api/builder/quiz', json={'count': 10, 'scope': 'corpus'})
d = r.get_json()
check(d['ok'] and d['scope'] == 'corpus', f'显式 corpus 应保持 corpus：{d.get("scope")}')

print()
if FAILS:
    print(f'===== 组句题源 scope 回归测试: {len(FAILS)} 项失败 =====')
    sys.exit(1)
else:
    print('===== 组句题源 scope 回归测试: 全部通过 =====')

shutil.rmtree(tmp, ignore_errors=True)

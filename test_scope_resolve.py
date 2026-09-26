# -*- coding: utf-8 -*-
"""题源解析（textbook.resolve_book_scope / fetch_book_sentence_rows）专项测试
================================================================
覆盖此前「组句练习配置选『仅课本』，出的却还是全库语料句子」的根因缺陷：

  旧代码：scope=='book' 但调用方没传 book_ids 时，sentence_builder._fetch_pool
  会静默改跑「SELECT * FROM sentences」这条全库语料查询，但返回给前端的
  scope 字段仍然写死是 'book'——用户在界面上完全看不出题源已经被偷换。

本测试验证修复后的统一规则（textbook.resolve_book_scope）：
  1. 没有任何课本时，scope='book' 诚实退化为 'corpus' 并标注原因；
  2. 有课本但调用方未指定 book_ids 时，自动使用「书架里全部启用中的课本」，
     而不是退化为语料库；
  3. 已停用（active=0）的课本不会被自动纳入；
  4. 显式传入的 book_ids 会先校验存在性，非法 id 被丢弃；
  5. fetch_book_sentence_rows 对多本课本做分层抽样，句子基数悬殊的课本
     也能公平出现在候选池里（不会被大课本的 ORDER BY RANDOM() 全局压过）。

临时库隔离，不碰真实数据。"""
import os
import sys
import shutil
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
    for t in ('books', 'book_lessons', 'book_sentences', 'sentences', 'kanji_index'):
        try:
            c0.execute(f'DELETE FROM {t}')
        except sqlite3.OperationalError:
            pass
db.DB_PATH = api_db

import textbook


def add_plain_sentence(text):
    return db.add_sentence(text, None, 'unit_test', None, [], [])


print('== 1. 一本课本都没有：scope=book 诚实退化为 corpus ==')
r = textbook.resolve_book_scope('book', None)
check(r['scope'] == 'corpus' and r['note'] == 'no_books_fallback_corpus' and r['ids'] == [],
      f'空书架应诚实标注退化原因：{r}')
r2 = textbook.resolve_book_scope('corpus', None)
check(r2['scope'] == 'corpus' and r2['note'] is None, f'scope=corpus 不受影响：{r2}')
r3 = textbook.resolve_book_scope('lyric', None)
check(r3['scope'] == 'lyric', f'scope=lyric 不受课本解析影响：{r3}')

print('== 2. 有课本、未指定 book_ids：自动使用全部启用中的课本（而非语料库）==')
bidA = db.add_book('课本A', active=1)
bidB = db.add_book('课本B', active=1)
bidC = db.add_book('课本C（已停用）', active=0)
r = textbook.resolve_book_scope('book', None)
check(r['scope'] == 'book' and r['auto_all'] is True, f'scope 应保持 book：{r}')
check(set(r['ids']) == {bidA, bidB}, f'应自动纳入全部启用中的课本，排除停用课本：{r["ids"]}')
r = textbook.resolve_book_scope('mixed', [])
check(set(r['ids']) == {bidA, bidB} and r['scope'] == 'mixed', f'mixed 同理：{r}')

print('== 3. 显式 book_ids：校验存在性，非法 id 被丢弃 ==')
r = textbook.resolve_book_scope('book', [bidA, 999999, 'not-a-number'])
check(r['ids'] == [bidA] and r['auto_all'] is False, f'非法/不存在 id 应被丢弃：{r}')

print('== 4. 多课本分层抽样：句子基数悬殊也要公平出场 ==')
lidA = db.add_lesson(bidA, 1, '第1課')
lidB = db.add_lesson(bidB, 1, '第1課')
# 课本 A：400 句（大课本）；课本 B：3 句（小课本）
for i in range(400):
    sid = add_plain_sentence(f'これはA課本の文{i}です。')
    db.add_book_sentence(bidA, lidA, i, sid)
for i in range(3):
    sid = add_plain_sentence(f'これはB課本の文{i}です。')
    db.add_book_sentence(bidB, lidB, i, sid)

hit_b = 0
trials = 25
for _ in range(trials):
    rows = textbook.fetch_book_sentence_rows([bidA, bidB], need=10)
    if any(r['book_id'] == bidB for r in rows):
        hit_b += 1
check(hit_b >= trials * 0.6,
      f'小课本（3句）应在多数抽样里都出现，而不是被 40 句的大课本淹没：命中 {hit_b}/{trials}')

# 对照组：如果直接退化为「不分层、全局 ORDER BY RANDOM 单条 SQL」，
# 小课本几乎不可能进 need=10 的候选池 —— 用它验证我们的分层策略确实起作用，
# 而不是恰好总能抽到。
with db.get_conn() as c:
    naive_hits = 0
    for _ in range(trials):
        rows = c.execute(
            'SELECT bs.book_id book_id FROM book_sentences bs '
            'WHERE bs.book_id IN (?,?) ORDER BY RANDOM() LIMIT 10', (bidA, bidB)).fetchall()
        if any(r['book_id'] == bidB for r in rows):
            naive_hits += 1
print(f'  （对照：未分层的全局随机 LIMIT 10 命中小课本 {naive_hits}/{trials} 次，'
      f'分层抽样命中 {hit_b}/{trials} 次）')

print('== 5. scope=book 且课本内容为空课本（无 book_sentences）也不该假装有题 ==')
bidEmpty = db.add_book('空课本', active=1)
rows = textbook.fetch_book_sentence_rows([bidEmpty], need=10)
check(rows == [], f'空课本不应凭空产生候选句：{rows}')

print()
if FAILS:
    print(f'===== 题源解析测试: {len(FAILS)} 项失败 =====')
    sys.exit(1)
else:
    print('===== 题源解析测试: 全部通过 =====')

shutil.rmtree(tmp, ignore_errors=True)

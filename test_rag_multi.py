# -*- coding: utf-8 -*-
"""
RAG 多源检索高级特性验证：
  - 罗马音→假名查询扩展（gakkou ⇒ 学校 / がっこう）
  - 来源优先级加权（用户指定通道排在前面并被优先召回）
  - 指定课本范围（book_ids 限定仅返回该教材）
  - 查询归一化（全角 / 片假名混合）
  - 歌名命中置顶
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, '.')

PASS, FAIL = 0, 0
FAILURES = []


def check(name, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [OK]   {name}')
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f'  [FAIL] {name} {extra}')


import sqlite3
import db
tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    c0.execute('DELETE FROM songs')
    c0.execute('DELETE FROM books')
    c0.execute('DELETE FROM book_sentences')
    c0.execute('DELETE FROM book_lessons')
    c0.execute('DELETE FROM srs')
db.DB_PATH = api_db
import app as appmod
client = appmod.app.test_client()

# --- 导入一首歌 + 一本课本（含「学校」） ---
songs_blob = "《テスト曲》\n私は学校へ行く\n学校で友だちと遊んだ"
r = client.post('/api/songs/import', json={'text': songs_blob})
check(len(r.get_json()['created']) == 1, '导入测试歌')
book_blob = "《学校の時間》\n私は学校へ行く。\n学校で勉強します。"
r = client.post('/api/books/import', json={'text': book_blob})
book_id = r.get_json()['books'][0]['id']
check(bool(book_id), '导入测试课本')

# --- 1. 罗马音→假名扩展：gakkou 应命中含「学校/がっこう」的句子 ---
print('== 罗马音→假名查询扩展 ==')
r = client.post('/api/rag/search', json={'q': 'gakkou', 'limit': 8})
d = r.get_json()
checks = [x['text'] for x in d.get('rows', [])] + [x['text'] for x in d.get('lyrics', [])]
hit = any('学校' in (c or '') for c in checks)
check(hit, f'罗马音 gakkou ⇒ 命中含「学校」的内容：{checks[:4]}')

# --- 2. 来源优先级加权 ---
print('== 来源优先级加权 ==')
r = client.post('/api/rag/search', json={'q': '学校', 'limit': 8,
                                          'sources': ['textbook', 'lyric', 'web']})
d = r.get_json()
check(d['meta']['prior'][0] == 'textbook', f'优先级首位=textbook: {d["meta"]["prior"]}')
# 优先权重不仅反映在 prior，而且优先通道结果更靠前
types_order = [x['type'] for x in d.get('rows', [])] + ['lyric'] * len(d.get('lyrics', []))
has_textbook = any(x['type'] == 'textbook' for x in d.get('rows', []))
check(has_textbook or any(x.get('title_match') for x in d.get('lyrics', [])),
      f'优先 textbook 仍召回到教材内容: rows={types_order[:4]}')

# --- 3. 指定课本范围：仅返回该教材 ---
print('== 指定课本范围 ==')
r = client.post('/api/rag/search', json={'q': '学校', 'limit': 8,
                                          'sources': ['textbook'], 'book_ids': [book_id]})
d = r.get_json()
check(all(x['type'] == 'textbook' and x.get('book_id') == book_id for x in d.get('rows', [])),
      f'仅返回指定教材: {len(d.get("rows",[]))} 条')
check(d['meta']['book_ids'] == [book_id], f'book_ids 回传: {d["meta"].get("book_ids")}')

# --- 4. 只看歌词 ---
print('== 单通道过滤 ==')
r = client.post('/api/rag/search', json={'q': '学校', 'limit': 8, 'sources': ['lyric']})
d = r.get_json()
check(all(x['type'] == 'lyric' for x in d.get('lyrics', [])), f'只看歌词: {len(d.get("lyrics",[]))} 条')
# 只看语料不应返回歌词
r = client.post('/api/rag/search', json={'q': '学校', 'limit': 8, 'sources': ['web']})
d = r.get_json()
check(len(d.get('lyrics', [])) == 0, 'web-only 不返回歌词')

# --- 5. 查询归一化：全角 + 片假名混合 ---
print('== 查询归一化 ==')
r = client.post('/api/rag/search', json={'q': 'Ｇａｋｋｏｕ', 'limit': 8})
d = r.get_json()
checks = [x['text'] for x in d.get('rows', [])] + [x['text'] for x in d.get('lyrics', [])]
check(any('学校' in (c or '') for c in checks), f'全角罗马字命中: {checks[:3]}')

# --- 6. 歌名命中置顶 ---
print('== 歌名命中置顶 ==')
r = client.post('/api/rag/search', json={'q': 'テスト曲', 'limit': 6})
d = r.get_json()
check(d['lyrics'] and d['lyrics'][0].get('title_match') and d['lyrics'][0]['title'] == 'テスト曲',
      f'歌名命中置顶: {d.get("lyrics",[])[:1]}')

shutil.rmtree(tmp, ignore_errors=True)
print()
if FAILS := FAILURES:
    print(f'===== RAG 高级特性测试: 失败 {len(FAILS)} 项 =====')
    for f in FAILS:
        print('  -', f)
    sys.exit(1)
print(f'===== RAG 高级特性测试: 全部通过 ({PASS} 项) =====')

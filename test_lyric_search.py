# -*- coding: utf-8 -*-
"""歌词检索深度测试：去重 / 每首上限可调 / 歌名匹配 / 阈值过滤 / 结构检索参数"""
import os
import sys
import shutil
import tempfile
from collections import Counter

sys.path.insert(0, '.')

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


import sqlite3
import db
tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    c0.execute('DELETE FROM songs')
db.DB_PATH = api_db
import structsim
import app as appmod
client = appmod.app.test_client()

# ============ 导入 8 首测试歌（含重复副歌=用户实际遇到的场景） ============
SONGS = """《星屑ビーナス》
一つぶの出会い
次の出会いならすぐそこに
一つぶの出会い
きらめく方が勝ちだね

---

《Departures ～あなたにおくるアイの歌～》
あなたの腕の中にいたい
もう二度とは会えないってことを知ってたの?
かけがえのない家族を連れて
あなたの腕の中にいたい

---

《Lemon》
夢ならばどれほどよかったでしょう
それでも僕は君を想う
そのすべてを愛してた
そのすべてを愛してた
淋しさの中にいるなら

---

《时の流れに身をまかせ》
あなたの色に染められ
はじまりの音に変わるように
あなたの色に染められ

---

《茜さす》
返事のない呼ぶ声は
季節を見てたかった
消えない影 見てた

---

《僕にできること》
答えのない日々に溜息漏らす度
小さな祈りを込めて
答えのない日々に溜息漏らす度

---

《secret base～君がくれたもの～》
また出会えるのを信じて
出会いはふっとした瞬間
また出会えるのを信じて

---

《ユメセカイ》
目の前に開かれた果てない世界
次の出会いならすぐそこに"""
r = client.post('/api/songs/import', json={'text': SONGS})
check(len(r.get_json()['created']) == 8, f"导入 8 首（实际 {len(r.get_json().get('created', []))}）")

print('== 1. 歌词命中去重（副歌重复行只留一条） ==')
# 用户实际案例：搜「出会い」曾出现 一つぶの出会い ×2
r = client.post('/api/rag/search', json={'q': '出会い', 'limit': 12, 'per_song': 0})
d = r.get_json()
texts = [x['text'] for x in d.get('lyrics', []) if x['text']]
check(len(texts) == len(set(texts)), f'歌词命中无重复行：{texts}')
check(texts.count('一つぶの出会い') <= 1, '一つぶの出会い 只出现一次（用户报告的重复）')
print(f'  命中 {len(texts)} 行：', ' | '.join(t[:12] for t in texts[:8]))

print('== 2. 每首上限可调（用户自主调节） ==')
for ps, expect_max in ((1, 1), (3, 3)):
    r = client.post('/api/rag/search', json={'q': '出会い', 'limit': 20, 'per_song': ps})
    d = r.get_json()
    cnt = Counter(x['title'] for x in d.get('lyrics', []) if x['text'])
    check(all(v <= expect_max for v in cnt.values()),
          f'per_song={ps} 生效：{dict(cnt)}')
# per_song=0 不限时：星屑ビーナス 有 3 行含 出会い（去重后）
r = client.post('/api/rag/search', json={'q': '出会い', 'limit': 20, 'per_song': 0})
cnt0 = Counter(x['title'] for x in r.get_json().get('lyrics', []) if x['text'])
check(cnt0.get('星屑ビーナス', 0) >= 2, f'per_song=0 不限：{dict(cnt0)}')

print('== 3. 歌名匹配置顶 ==')
r = client.post('/api/rag/search', json={'q': 'Lemon', 'limit': 8})
lyr = r.get_json().get('lyrics', [])
check(lyr and lyr[0].get('title_match') and lyr[0]['title'] == 'Lemon',
      f'歌名匹配置顶：{lyr[:1]}')
check(all(not x.get('title_match') or x['title'] == 'Lemon' for x in lyr), '无其他歌名误匹配')

print('== 4. 阈值过滤 ==')
r1 = client.post('/api/rag/search', json={'q': '出会い', 'min_affinity': 0.4})
a1 = [x['affinity'] for x in r1.get_json().get('lyrics', []) if x['text']]
check(all(a >= 0.4 for a in a1) or not a1, f'歌词最低匹配过滤：{a1}')
r2 = client.post('/api/rag/search', json={'q': '出会い', 'min_score': 0.3})
rows = r2.get_json().get('rows', [])
check(all(x.get('score', 0) >= 0.3 for x in rows) or not rows, '语料相似阈值过滤')

print('== 5. 结构检索：去重 + per_song 参数 ==')
r = client.post('/api/rag/search', json={'q': '答えのない日々に溜息漏らす度', 'per_song': 1})
st = r.get_json().get('struct')
check(st is not None, '整句触发结构分析')
if st:
    texts = [x['text'] for x in st['rows']]
    check(len(texts) == len(set(texts)), f'结构结果无重复：{texts}')
    cnt = Counter(x['title'] for x in st['rows'] if x['type'] == 'lyric')
    check(all(v <= 1 for v in cnt.values()), f'结构检索 per_song=1：{dict(cnt)}')
    check(st['components'].get('template'), '结构模板存在')
r = client.post('/api/rag/search', json={'q': '答えのない日々に溜息漏らす度', 'per_song': 0})
cnt0 = Counter(x['title'] for x in r.get_json()['struct']['rows'] if x['type'] == 'lyric')
check(any(v >= 2 for v in cnt0.values()) or sum(cnt0.values()) <= 1,
      f'结构检索 per_song=0 放开：{dict(cnt0)}')

print('== 6. 混合查询质量抽查 ==')
for q in ['あなたの色に染められ', '会いたい', '君に会いたい', '消えない影']:
    r = client.post('/api/rag/search', json={'q': q, 'limit': 6, 'per_song': 2})
    d = r.get_json()
    lyr = [f"{(x['title'] or '?')[:8]}:{(x['text'] or '整首')[:10]}" for x in d.get('lyrics', [])]
    has_struct = 'struct' in d
    print(f'  「{q}」→ 歌词{len(lyr)}条{" + 结构分析" if has_struct else ""}: {" | ".join(lyr[:4])}')
    check(len(set(lyr)) == len(lyr), f'「{q}」结果无重复')

shutil.rmtree(tmp, ignore_errors=True)
print()
if FAILS:
    print(f'===== 歌词检索深度测试: 失败 {len(FAILS)} 项 =====')
    sys.exit(1)
print('===== 歌词检索深度测试: 全部通过 =====')
sys.exit(0)

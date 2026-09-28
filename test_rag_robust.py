# -*- coding: utf-8 -*-
"""RAG 检索健壮性回归测试（v26）

覆盖用户实际报障的两个现象，以及它们背后的三类根因：

  现象①「检索失败：SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON」
     根因 A：查询命中**课名**时 rag.py 直取 m['author'] / m['level'] → KeyError
             → Flask 返回 HTML 500 页 → 前端 JSON.parse 炸在第一个 '<'。
     根因 B：/api/* 的 400/404/405/415/500 一律是 HTML 错误页，前端只会解析 JSON。

  现象②「没有找到相关内容」但歌词库里明明有那一行
     根因 C：索引首次构建期间进来的检索直接用**空索引**查（ensure() 遇
             _building 就 return False），稳定返回 0 条。
     根因 D：BM25/Dice 双路召回都有 topk 截断，加上来源优先级分档与每首歌配额，
             整句精确命中会被泛泛相关的结果挤出 limit。

跑法：python3 test_rag_robust.py
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILS = []
PASSED = 0


def check(cond, msg, extra=''):
    global PASSED
    if cond:
        PASSED += 1
        print(f'  [OK]   {msg}')
        return True
    FAILS.append(msg)
    print(f'  [FAIL] {msg} {extra}')
    return False


# ---------------------------------------------------------------- 测试数据
LYRIC = """《打上花火》
あの日見渡した渚を
今も思い出すんだ
砂の上に刻んだ言葉
君の後ろ姿
寄り返す波が
足元をよぎり何かを攫う
"""
BOOK = """《海の教科書》
波の音が聞こえる。
砂浜を歩いた。
"""

tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    c0.execute('DELETE FROM songs')
    c0.execute('DELETE FROM books')
    c0.execute('DELETE FROM book_sentences')
    c0.execute('DELETE FROM book_lessons')

import db                                                          # noqa: E402
db.DB_PATH = api_db
# 换临时库后必须补跑一次迁移（与 test_lyric_search.py / test_search.py 一致）。
db._migrate()

import rag                                                         # noqa: E402
import app as appmod                                               # noqa: E402

client = appmod.app.test_client()

r = client.post('/api/songs/import', json={'text': LYRIC})
assert r.status_code == 200, r.data[:200]
r = client.post('/api/books/import', json={'text': BOOK})
BOOK_ID = r.get_json()['books'][0]['id']

# 造一个「课名与查询词重叠」的场景：这正是 500 HTML 的触发条件。
with sqlite3.connect(api_db) as c0:
    c0.execute("UPDATE book_lessons SET title=? WHERE book_id=?", ('第1課 寄り返す波', BOOK_ID))

TARGET = '寄り返す波が'


def search(q, **kw):
    body = {'q': q, 'limit': 10, 'sources': ['lyric', 'textbook', 'web'],
            'sort': 'priority', 'per_song': 3, 'per_book': 4, 'book_ids': []}
    body.update(kw)
    return client.post('/api/rag/search', json=body)


def texts(d):
    out = []
    for key in ('results', 'lyrics', 'rows'):
        out += [x.get('text') or '' for x in (d.get(key) or [])]
    for v in (d.get('groups') or {}).values():
        out += [x.get('text') or '' for x in v]
    return out


# ============================================================ 1. 不再返回 HTML
print('== 1. /api/rag/search 永远是 JSON（课名命中曾抛 KeyError → HTML 500）==')
for q in ['寄り返す波が', '寄り 返す 波', '寄り 返す 波が', '波', '第1課']:
    r = search(q)
    ok = check(r.status_code == 200, f'「{q}」→ HTTP 200',
               f'实际 {r.status_code}: {r.data[:80]!r}')
    check((r.headers.get('Content-Type') or '').startswith('application/json'),
          f'「{q}」→ Content-Type 是 JSON', r.headers.get('Content-Type'))
    check(not r.data.lstrip().startswith(b'<'), f'「{q}」→ 响应体不是 HTML')
    if ok:
        r.get_json()          # 能被 JSON.parse 解析（解析失败会直接抛）

print('== 1b. 各类出错路径也必须是 JSON（前端只会 JSON.parse）==')
cases = [
    ('未知接口', client.post('/api/rag/searchh', json={'q': 'x'}), 404),
    ('方法不对', client.get('/api/rag/search'), 405),
    ('请求体不是 JSON', client.post('/api/rag/search', data='{oops',
                                content_type='application/json'), 400),
    ('Content-Type 不对', client.post('/api/rag/search', data='{}',
                                    content_type='text/plain'), 400),
    ('空查询', client.post('/api/rag/search', json={'q': '   '}), 400),
]
for name, resp, code in cases:
    check(resp.status_code == code, f'{name} → HTTP {code}', f'实际 {resp.status_code}')
    check(not resp.data.lstrip().startswith(b'<'), f'{name} → 不是 HTML 错误页',
          resp.data[:60])
    body = resp.get_json(silent=True)
    check(isinstance(body, dict) and body.get('error'), f'{name} → JSON 里有中文说明',
          str(body)[:80])

print('== 1c. 接口内部真出异常时，仍然回 JSON 500 而不是 HTML ==')
_orig = rag.MULTI.search
try:
    rag.MULTI.search = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
    r = search(TARGET)
    check(r.status_code == 500, '内部异常 → HTTP 500', str(r.status_code))
    check(not r.data.lstrip().startswith(b'<'), '内部异常 → 不是 HTML 错误页', r.data[:60])
    j = r.get_json(silent=True)
    check(isinstance(j, dict) and '服务器内部错误' in (j.get('error') or ''),
          '内部异常 → JSON 里有可读说明', str(j)[:100])
finally:
    rag.MULTI.search = _orig

# ============================================================ 2. 一定搜得到
print('== 2. 歌词里有这一行，就一定要搜得到（各种写法/参数组合）==')
variants = ['寄り返す波が', '寄り返す波', '寄り 返す 波が', '寄り　返す　波が',
            ' 寄り返す波が ', '寄リ返す波が'.replace('リ', 'り'), '寄り返す波が\n']
for q in variants:
    d = search(q).get_json()
    check(TARGET in texts(d), f'「{q.strip()}」命中目标行',
          f"top={[x.get('text') for x in (d.get('results') or [])][:3]}")

print('== 2b. 任意来源优先级 / 排序 / 配额下，整句命中都排在第一条 ==')
for srcs in (['lyric', 'textbook', 'web'], ['web', 'lyric', 'textbook'],
             ['web', 'textbook', 'lyric'], ['textbook', 'web', 'lyric']):
    for sort in ('priority', 'score'):
        for per_song in (0, 1, 3):
            d = search(TARGET, sources=srcs, sort=sort, per_song=per_song).get_json()
            top = (d.get('results') or [{}])[0]
            check(top.get('text') == TARGET,
                  f"{'/'.join(srcs)} · {sort} · per_song={per_song} → 首条即精确命中",
                  f"实际 {top.get('title')}:{top.get('text')}")
            check(top.get('exact') is True, '首条带 exact 标记', str(top.get('exact')))

print('== 2c. 小 limit 也不能把精确命中挤掉 ==')
for limit in (1, 2, 3):
    d = search(TARGET, limit=limit, sources=['web', 'textbook', 'lyric']).get_json()
    check(TARGET in [x.get('text') for x in (d.get('results') or [])],
          f'limit={limit} 时精确命中仍在结果里',
          str([x.get('text') for x in (d.get('results') or [])]))

# ============================================================ 3. 冷启动竞态
print('== 3. 索引构建期间的检索：要么等到真结果，绝不谎报「没有找到」==')
mi = rag.MultiIndex()
got = {}


def _builder():
    mi.ensure()


def _searcher():
    time.sleep(0.05)                       # 确保撞在构建过程中
    res = mi.search(TARGET, limit=10)
    got['n'] = len(res['results'])
    got['hit'] = any(x.get('text') == TARGET for x in res['results'])
    got['warming'] = res['meta'].get('warming')


t1, t2 = threading.Thread(target=_builder), threading.Thread(target=_searcher)
t1.start(); t2.start(); t1.join(); t2.join()
check(got.get('hit') is True, '构建期间并发检索 → 仍然拿到目标行',
      f"results={got.get('n')} warming={got.get('warming')}")

print('== 3b. 真的等不到时，如实标记 meta.warming（前端提示「索引建立中」）==')
mi2 = rag.MultiIndex()
mi2._build_lock.acquire()                  # 假装另一线程正占着构建锁
try:
    res = mi2.search(TARGET, limit=5, )
finally:
    mi2._build_lock.release()
check(res['meta'].get('warming') is True, '等不到索引 → meta.warming=True',
      str(res['meta'].get('index')))
check(res['meta'].get('index', {}).get('ready') is False, 'meta.index.ready=False')

print('== 3c. 索引未就绪的空结果不得进查询缓存（否则错误答案会粘住）==')
mi3 = rag.MultiIndex()
mi3.FIRST_BUILD_WAIT_S = 0.2               # 等一下下就放弃
mi3._build_lock.acquire()                  # 占住构建锁 = 等待必然超时
try:
    first = mi3.search(TARGET, limit=5)
finally:
    mi3._build_lock.release()
check(not first['results'] and first['meta'].get('warming'),
      '等不到索引时如实返回空 + warming 标记',
      f"results={len(first['results'])} warming={first['meta'].get('warming')}")
mi3.FIRST_BUILD_WAIT_S = 20
second = mi3.search(TARGET, limit=5)       # 同一个查询、同一套参数
check(any(x.get('text') == TARGET for x in second['results']),
      '索引就绪后同一查询立刻能查到（没有被空结果缓存粘住）',
      str([x.get('text') for x in second['results']][:3]))
check(not second['meta'].get('warming'), '就绪后不再标记 warming')

print('== 3d. 数据变化时用旧索引先答，不阻塞、也不返回空 ==')
rag.MULTI.ensure()
rag.MULTI._stamp = ('stale', 'stale', 'stale')      # 制造「签名已变」
holder = threading.Thread(target=lambda: None)
rag.MULTI._build_lock.acquire()                     # 假装重建正在进行
try:
    t0 = time.time()
    res = rag.MULTI.search(TARGET, limit=5)
    dt = time.time() - t0
finally:
    rag.MULTI._build_lock.release()
check(any(x.get('text') == TARGET for x in res['results']),
      '重建进行中 → 用旧索引照样给出结果', str(len(res['results'])))
check(dt < 2.0, f'重建进行中 → 不阻塞（{dt * 1000:.0f}ms）')
rag.MULTI.ensure()

# ============================================================ 4. 空结果要说人话
print('== 4. 被自己的筛选挡住时，要说清楚原因 ==')
d = search(TARGET, sources=['textbook']).get_json()
ex = (d.get('meta') or {}).get('excluded') or {}
check(ex.get('lyric', {}).get('hits', 0) >= 1,
      '排除歌词来源后，meta.excluded 指出歌词里其实有命中', str(ex))
check(ex.get('lyric', {}).get('exact') is True, 'meta.excluded 标明那是精确命中', str(ex))
check(TARGET in (ex.get('lyric', {}).get('sample') or ''), 'meta.excluded 带样例原文', str(ex))

d = search('存在しないはずの語句です', sources=['lyric']).get_json()
check(not ((d.get('meta') or {}).get('excluded') or {}).get('lyric'),
      '真的没有的内容 → 不瞎报「被排除了」', str((d.get('meta') or {}).get('excluded')))

print('== 4b. meta.index 始终回传索引状态 ==')
d = search(TARGET).get_json()
idx = (d.get('meta') or {}).get('index') or {}
check(idx.get('ready') is True, 'meta.index.ready=True', str(idx))
check(idx.get('docs', 0) > 0, 'meta.index.docs > 0', str(idx))

print('== 4c. 1~2 字的短查询不触发「精确置顶」，仍按来源优先级分档 ==')
d = search('波', sources=['textbook', 'lyric', 'web']).get_json()
res = d.get('results') or []
check(not any(x.get('exact') for x in res), '单字查询不打 exact 标记（满库都字面包含，没有区分度）',
      str([(x.get('type'), x.get('text')) for x in res[:3]]))
check(res and res[0].get('type') == 'textbook', '单字查询仍尊重来源优先级（课本置顶）',
      str([(x.get('type'), x.get('text')) for x in res[:3]]))

# ============================================================ 5. 不回退旧能力
print('== 5. 既有能力不回退 ==')
d = search('打上花火').get_json()
check(any(x.get('title_match') for x in (d.get('lyrics') or [])), '歌名命中仍然置顶',
      str([(x.get('title'), x.get('title_match')) for x in (d.get('lyrics') or [])][:3]))

d = search('波', sources=['textbook'], book_ids=[BOOK_ID]).get_json()
check(all(x.get('book_id') in (BOOK_ID, None) for x in (d.get('rows') or [])),
      '限定课本仍然生效', str([(x.get('book_id'), x.get('text')) for x in (d.get('rows') or [])][:3]))

d = search(TARGET, per_song=1).get_json()
from collections import Counter                                     # noqa: E402
cnt = Counter(x['title'] for x in (d.get('lyrics') or []) if x.get('text'))
check(all(v <= 1 for v in cnt.values()), 'per_song 配额仍然生效', str(dict(cnt)))

lines = [x.get('text') for x in (d.get('lyrics') or []) if x.get('text')]
check(len(lines) == len(set(lines)), '结果去重仍然生效', str(lines))

d = search('波の音が聞こえる。').get_json()
check('struct' in d, '整句输入仍触发结构分析', str(list(d.keys())))

shutil.rmtree(tmp, ignore_errors=True)
print()
if FAILS:
    print(f'===== RAG 健壮性回归测试：失败 {len(FAILS)} 项 / 共 {PASSED + len(FAILS)} 项 =====')
    for f in FAILS:
        print('  -', f)
    sys.exit(1)
print(f'===== RAG 健壮性回归测试：全部通过（{PASSED} 项）=====')
sys.exit(0)

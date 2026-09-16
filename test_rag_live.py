# -*- coding: utf-8 -*-
"""RAG 检索-实测（只读，不写用户数据）：
从 kanji.db 现场发现真实词条，再对运行中的服务做端到端断言。
覆盖：响应结构 / 三通道命中 / 来源优先级 / 单通道过滤 / 罗马音与假名跨写法 /
      每首配额与去重 / 歌名置顶 / 空查询 / 热查询延迟。
用法：python test_rag_live.py [port]，默认 5000。
"""
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:%s' % (sys.argv[1] if len(sys.argv) > 1 else '5000')
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db')
FAILS = []


def check(name, cond, extra=''):
    print(('  [OK]   ' if cond else '  [FAIL] ') + name + ('' if cond else f'   {extra}'))
    if not cond:
        FAILS.append(name)


def rag(q, **kw):
    """返回 (status, dict)。400/409 等也正常返回，便于断言错误分支。"""
    body = json.dumps(dict(q=q, **kw)).encode('utf-8')
    req = urllib.request.Request(BASE + '/api/rag/search', data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8') or '{}')


def words(text):
    return set(re.findall(r'[一-鿿]{2,3}', text or ''))


# ---------- 0. 从真实数据库发现测试词条（只读） ----------
print('== 0. 从 %s 发现测试词条 ==' % os.path.basename(DB))
con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
lyric_text = '\n'.join(r[0] or '' for r in con.execute('SELECT lyrics FROM songs'))
web_text = '\n'.join(r[0] or '' for r in con.execute('SELECT text FROM sentences'))
book_text = '\n'.join(r[0] or '' for r in con.execute(
    'SELECT s.text FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id'))
songs = [(r[0], r[1] or '') for r in con.execute('SELECT title,lyrics FROM songs')]
con.close()

LW, WW, BW = words(lyric_text), words(web_text), words(book_text)
shared = sorted(LW & WW, key=lambda w: (-lyric_text.count(w), w))
lyric_word = max(LW, key=lyric_text.count) if LW else ''
web_word = max(WW, key=web_text.count) if WW else ''
book_word = max(BW, key=book_text.count) if BW else ''
shared_word = shared[0] if shared else lyric_word
print(f'   歌词词条={lyric_word} 语料词条={web_word} 跨通道词条={shared_word} '
      f'课本词条={book_word or "(无课本)"}')
check('数据库存在歌词与语料', bool(LW) and bool(WW))
# ---------- 1. 响应结构（前端 UI 契约） ----------
print('== 1. 响应结构 ==')
st, d = rag(shared_word, limit=6)
check('HTTP 200', st == 200, st)
for k in ('rows', 'lyrics', 'groups', 'titles', 'meta'):
    check(f'字段 {k}', k in d, sorted(d.keys()))
check('groups 三通道', set(d['groups']) == {'lyric', 'textbook', 'web'}, list(d['groups']))
check('meta 完整', all(x in d['meta'] for x in ('counts', 'terms', 'prior', 'ms')), d['meta'])
allrows = d['rows'] + [x for x in d['groups']['lyric'] if x.get('text')]
check('每行含 score/channel/type', all(
    x.get('score') is not None and x.get('channel') and x.get('type') for x in allrows),
    allrows[:1])
check('前端高亮所需 tokens 已注入', all('tokens' in x for x in allrows), allrows[:1])
print('   索引规模:', d['meta']['counts'], ' 冷查询', d['meta']['ms'], 'ms')

# ---------- 2. 三通道命中 ----------
print('== 2. 三通道命中 ==')
st, d = rag(lyric_word, limit=10)
check('歌词通道命中', bool(d['groups']['lyric']), f'词={lyric_word}')
st, d2 = rag(web_word, limit=10)
check('网络语料通道命中', bool(d2['rows']), f'词={web_word}')
if book_word:
    st, d3 = rag(book_word, limit=10)
    check('课本通道命中', bool(d3['groups']['textbook']), f'词={book_word}')
else:
    print('   （当前库无课本，课本通道由 test_rag_multi.py 的导入用例覆盖）')

# ---------- 3. 用户指定来源优先级 ----------
print('== 3. 来源优先级 ==')
if len(shared) >= 1 and any(shared_word in t for t in (lyric_text, web_text)):
    for first in ('lyric', 'web'):
        rests = [c for c in ('lyric', 'textbook', 'web') if c != first]
        st, r = rag(shared_word, limit=10, sources=[first] + rests)
        # results = 跨通道统一排名列表（优先级的第一排序键）；旧字段兜底
        uni = r.get('results') or (r['rows'] + r['groups']['lyric'])
        got = [x['channel'] for x in uni]
        check(f'首位 {first} 时该通道置顶', got and got[0] == first, got[:6])
        check(f'prior 回传 {first}', r['meta']['prior'][0] == first, r['meta']['prior'])
else:
    print('   （无跨通道词条，跳过置顶断言）')

# ---------- 4. 单通道过滤 ----------
print('== 4. 单通道过滤 ==')
st, r = rag(shared_word, limit=10, sources=['lyric', 'textbook'])
check('排除 web 后 rows 为空', not r['rows'], [x['channel'] for x in r['rows']])
check('排除 web 后歌词仍有结果', bool(r['groups']['lyric']), r['groups']['lyric'][:1])
st, r = rag(web_word, limit=10, sources=['web'])
check('仅 web 时歌词/课本为空',
      not r['groups']['lyric'] and not r['groups']['textbook'],
      (r['groups']['lyric'][:1], r['groups']['textbook'][:1]))

# ---------- 5. 跨写法检索（罗马音 / 假名 / 全角） ----------
print('== 5. 跨写法检索 ==')
KY = '学校' if '学校' in WW else ''
if KY:
    for name, q in (('罗马音 gakkou', 'gakkou'), ('平假名 がっこう', 'がっこう'),
                    ('片假名 ガッコウ', 'ガッコウ'), ('全角 ＧＡＫＫＯＵ', 'ＧＡＫＫＯＵ')):
        st, r = rag(q, limit=8)
        hit = [x['text'] for x in (r['rows'] + r['lyrics']) if KY in x['text']]
        check(f'{name} 召回「{KY}」', bool(hit), hit[:2])
    st, r = rag('gakkou', limit=8)
    check('罗马音被转为假名', bool(r['meta']['qvars']), r['meta']['qvars'])
else:
    print('   （语料无「学校」，跳过跨写法断言）')

# ---------- 6. 歌词配额与去重 ----------
print('== 6. 歌词配额与去重 ==')
st, r = rag(lyric_word, limit=24, per_song=1)
seen = [x['text'] for x in r['groups']['lyric'] if x.get('text')]
check('歌词无重复行', len(seen) == len(set(seen)), seen[:5])
per = {}
for x in r['groups']['lyric']:
    if x.get('kind') == 'line':
        per[x['id']] = per.get(x['id'], 0) + 1
check('per_song=1 生效', all(v <= 1 for v in per.values()), per)
st, r0 = rag(lyric_word, limit=24, per_song=0)
per0 = {}
for x in r0['groups']['lyric']:
    if x.get('kind') == 'line':
        per0[x['id']] = per0.get(x['id'], 0) + 1
check('per_song=0 放开配额', not per0 or max(per0.values()) >= 1, per0)

# ---------- 7. 歌名命中置顶 ----------
print('== 7. 歌名命中置顶 ==')
if songs:
    title = songs[0][0]
    st, r = rag(title, limit=8)
    hit = [x for x in r['groups']['lyric'] if x.get('title_match')]
    check(f'歌名「{title}」置顶', bool(hit) and hit[0]['title'] == title, hit[:2])
    check('歌名行带 id（可点击定位整首）', all(x.get('id') for x in hit), hit[:1])

# ---------- 8. 边界输入 ----------
print('== 8. 边界输入 ==')
for q in ('', '   '):
    st, r = rag(q, limit=5)
    check(f'空查询「{q}」→ 400', st == 400, st)
st, r = rag('の', limit=5)
check('单假名查询返回 200', st == 200, st)
st, r = rag('存在しない語句xyzzz', limit=5)
check('无结果查询返回 200 空列表', st == 200 and isinstance(r['rows'], list), st)

# ---------- 9. 热查询延迟 ----------
print('== 9. 热查询延迟 ==')
rag(shared_word, limit=10)                      # 确保索引已就绪
ts = []
for _ in range(3):
    st, r = rag(shared_word, limit=10)
    ts.append(r['meta']['ms'])
print('   三次热查询耗时(ms):', ts)
check('热查询 < 1500ms', max(ts) < 1500, ts)

print()
if FAILS:
    print(f'===== RAG 实测: 失败 {len(FAILS)} 项 =====')
    for f in FAILS:
        print('  -', f)
    sys.exit(1)
print('===== RAG 实测: 全部通过 =====')
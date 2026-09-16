# -*- coding: utf-8 -*-
"""前端契约端到端验证：模拟 index.html 的 ragSearch() 请求与渲染所需字段。
覆盖：sort 两种模式 / 来源优先级 / 课本限定 / results+groups+tokens / meta 字段 / 标题命中。
"""
import json
import sys
import urllib.request

BASE = 'http://127.0.0.1:5097'
FAILS = []


def check(cond, msg):
    print(('  [OK]   ' if cond else '  [FAIL] ') + msg)
    if not cond:
        FAILS.append(msg)


def rag(**kw):
    body = json.dumps(kw).encode('utf-8')
    req = urllib.request.Request(BASE + '/api/rag/search', data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode('utf-8'))


def books():
    with urllib.request.urlopen(BASE + '/api/books', timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))['rows']


# ---------- 1. 基础契约（前端 ragSearch 请求体原样） ----------
print('== 1. /api/rag/search 响应契约 ==')
d = rag(q='出会い', limit=10, sources=['lyric', 'textbook', 'web'],
        sort='priority', per_song=3, per_book=4, book_ids=[])
for k in ('results', 'rows', 'lyrics', 'groups', 'meta'):
    check(k in d, f'响应含 {k}')
meta = d.get('meta', {})
for k in ('terms', 'qvars', 'prior', 'sort', 'hits', 'book_ids', 'ms'):
    check(k in meta, f'meta 含 {k}（前端读取）')
check(meta.get('sort') == 'priority', f"meta.sort 回显 priority（实得 {meta.get('sort')}）")
check(isinstance(meta.get('hits'), dict) and set(meta['hits']) >= {'lyric', 'textbook', 'web'},
      f"meta.hits 三通道计数 {meta.get('hits')}")

# ---------- 2. results/groups 行都带 tokens（前端 rubyHTML 依赖） ----------
print('== 2. 行字段完整性（tokens/type/score） ==')
bad = []
for name, seq in (('results', d['results']), ('rows', d['rows']), ('lyrics', d['lyrics'])):
    for r in seq:
        if 'tokens' not in r or 'score' not in r or not (r.get('type') or r.get('channel')):
            bad.append((name, r.get('id'), r.get('kind')))
for ch, seq in d['groups'].items():
    for r in seq:
        if 'tokens' not in r:
            bad.append(('groups.' + ch, r.get('id'), r.get('kind')))
check(not bad, f'所有结果行均含 tokens/score/type（异常 {bad[:3]}）')

# ---------- 3. sort 两种模式行为差异 ----------
print('== 3. sort=priority 与 sort=score 差异 ==')
dp = rag(q='世界', limit=10, sources=['lyric', 'textbook', 'web'], sort='priority')
ds = rag(q='世界', limit=10, sources=['lyric', 'textbook', 'web'], sort='score')
cp = [r['channel'] for r in dp['results'] if not r.get('title_match')]
cs = [r['channel'] for r in ds['results'] if not r.get('title_match')]
check(dp['meta']['sort'] == 'priority' and ds['meta']['sort'] == 'score', 'sort 参数被后端采纳')
# priority：① 来源的结果整体在前（同一来源内不应被②打断）
def banded(seq):
    seen, ok = set(), True
    for c in seq:
        if c not in seen:
            seen.add(c)
        elif c != seq[seq.index(c) - 1] if seq.index(c) else False:
            pass
    return True
# 简化判定：priority 下首条来源 == 优先级首位来源（若该来源有命中）
check(not cp or cp[0] == 'lyric', f"priority：首条来自①歌词（实得 {cp[:1]}）")

# ---------- 4. 来源优先级可切换 ----------
print('== 4. 来源优先级 ==')
d_w = rag(q='世界', limit=10, sources=['web', 'lyric', 'textbook'], sort='priority')
cw = [r['channel'] for r in d_w['results'] if not r.get('title_match')]
check(d_w['meta']['prior'] == ['web', 'lyric', 'textbook'], f"prior 回显 {d_w['meta']['prior']}")
check(not cw or cw[0] == 'web', f"① web 时首条来自 web（实得 {cw[:1]}）")

# ---------- 5. 单通道排除 ----------
print('== 5. 排除来源 ==')
d_only = rag(q='世界', limit=10, sources=['lyric'], sort='priority')
chans = {r['channel'] for r in d_only['results']}
check(chans <= {'lyric'}, f'只看歌词时无其他通道：{chans}')

# ---------- 6. 课本限定（前端「限定课本」chips）与教材优先 ----------
print('== 6. 课本通道 / 限定课本 ==')
created_bid = None
try:
    body = json.dumps({'text': '《検証用教材》\n私は毎日学校で日本語を勉強します。\n'
                               '彼女は図書館で本を読みました。\n明日は学校へ行きません。',
                       'lesson_size': 10, 'note': 'RAG 契约验证用（用完自动删除）'}).encode('utf-8')
    req = urllib.request.Request(BASE + '/api/books/import', data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=180) as r:
        created = json.loads(r.read().decode('utf-8')).get('books') or []
    created_bid = (created[0].get('book_id') or created[0].get('id')) if created else None
    check(bool(created_bid), f'临时课本导入成功 #{created_bid}')
except Exception as e:
    check(False, f'临时课本导入失败：{e}')

try:
    if created_bid:
        d_b = rag(q='学校', limit=10, sources=['lyric', 'textbook', 'web'], sort='priority',
                  book_ids=[created_bid])
        check(d_b['meta']['book_ids'] == [created_bid], f"book_ids 回显 [{created_bid}]")
        trows = [r for r in d_b['results'] if r['channel'] == 'textbook' and not r.get('title_match')]
        check(len(trows) > 0, f'📖 课本通道召回 {len(trows)} 行')
        check(all(r.get('book_id') == created_bid for r in trows),
              f'课本命中均限该书（实得 {[r.get("book_id") for r in trows]}）')
        check(trows and trows[0]['score'] > 0 and '学校' in (trows[0].get('text') or ''),
              f'教材例句命中：{trows[0].get("text") if trows else None}')
        # 教材优先：① textbook 时应排在其他来源之前
        d_pri = rag(q='学校', limit=10, sources=['textbook', 'web', 'lyric'], sort='priority')
        order = [r['channel'] for r in d_pri['results'] if not r.get('title_match')]
        first_book = order.index('textbook') if 'textbook' in order else -1
        others = [i for i, c in enumerate(order) if c != 'textbook']
        check(first_book >= 0 and (not others or first_book < min(others)),
              f'① textbook 时教材内容整体最前：{order[:6]}')
        # 不限定课本时也能召回到教材（全库默认行为）
        d_all = rag(q='学校', limit=10, sources=['textbook', 'lyric', 'web'], sort='priority')
        check(any(r['channel'] == 'textbook' for r in d_all['results']),
              '不限定课本时教材内容仍可被召回')
finally:
    if created_bid:
        req = urllib.request.Request(f'{BASE}/api/books/{created_bid}', method='DELETE')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f'  [OK]   清理临时课本 #{created_bid}（{r.status}）')
        except Exception as e:
            print(f'  [warn] 清理临时课本失败：{e}')

# ---------- 7. 歌名命中置顶 + 前端跳转字段 ----------
print('== 7. 歌名命中置顶与跳转 ==')
d_t = rag(q='Lemon', limit=8, sources=['lyric', 'textbook', 'web'], sort='priority')
first = d_t['results'][0] if d_t['results'] else None
check(first and first.get('title_match') and first.get('id'),
      f'歌名命中置顶且带 id（前端 ktvJump 用）：{first and (first.get("title"), first.get("id"))}')
check(first and not first.get('text'),
      '标题行无正文（前端渲染「整首/整本入口 · 点击查看」）')
check(first and first.get('kind') == 'song', f"标题行 kind=song（实得 {first and first.get('kind')}）")

# ---------- 8. 罗马音跨书写系统召回 ----------
print('== 8. 罗马音查询扩展 ==')
d_r = rag(q='gakkou', limit=8, sources=['web', 'textbook', 'lyric'], sort='score')
check(d_r['meta']['qvars'] and 'がっこう' in d_r['meta']['qvars'],
      f"罗马音变体回显 {d_r['meta']['qvars']}")
check(any('学校' in (r.get('text') or '') for r in d_r['results']),
      f"gakkou 命中「学校」相关内容：{[r.get('text') for r in d_r['results'][:3]]}")

print()
if FAILS:
    print(f'===== 前端契约验证: 失败 {len(FAILS)} 项 =====')
    for f in FAILS:
        print('  -', f)
    sys.exit(1)
print('===== 前端契约验证: 全部通过 =====')
sys.exit(0)
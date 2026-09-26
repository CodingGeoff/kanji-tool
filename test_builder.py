# -*- coding: utf-8 -*-
"""组句练习（sentence_builder）专项测试
================================================================
覆盖面：
  1. 文节切块正确性（依存焊死：连体修饰/属格/补助动词/程度副词）
  2. 多解稳健判卷 —— 所有语法正确语序判对；谓语错位/跨区/干扰块/缺块判错
  3. 全排列语法质检（strict_check 白名单）
  4. 初级换词变体：语料共现 + 换词后必过语法质检
  5. 高级干扰块安全性：等价助词对绝不生成、干扰块不与所需块撞面
  6. 配置读写：白名单、边界修正、深合并、mode 与 level 两轴独立
  7. API 全链路：cfg / quiz / check / answer / stats
  8. 统计记录：按日 + 题型/模式/级别细分
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


# ---------- 临时库 ----------
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
import sentence_builder as sb
import app as appmod
client = appmod.app.test_client()

random.seed(20260926)

# ================================================================
print('== 1. 文节切块正确性')
# ================================================================
CHUNK_CASES = [
    ('私は昨日図書館で本を読みました。',
     ['私は', '昨日', '図書館で', '本を', '読みました']),
    ('彼女は毎日図書館で本を読んでいる。',
     ['彼女は', '毎日', '図書館で', '本を', '読んでいる']),
    ('雨が降っているので、試合は中止になりました。',
     ['雨が', '降っているので', '試合は', '中止になりました']),
    ('彼は来ないかもしれないと言っていた。',
     ['彼は', '来ないかもしれないと', '言っていた']),
    ('母に心配をかけないように、早く帰ることにした。',
     ['母に', '心配を', 'かけないように', '早く帰ることにした']),
    ('日本語が上手になるために、毎日練習している。',
     ['日本語が', '上手になるために', '毎日', '練習している']),
]
for text, want in CHUNK_CASES:
    p = sb.parse_sentence(text)
    got = [c['surface'] for c in p['chunks']] if p else None
    check(got == want, f'切块 {text} → {got}（期望 {want}）')

# 依存焊死检查：连体修饰/程度副词绝不独立成块
p = sb.parse_sentence('昨日買ったばかりのカメラをなくしてしまった。')
check(p is not None and '昨日買ったばかりのカメラを' in [c['surface'] for c in p['chunks']],
      '连体从句应吸收前置时间词（昨日買ったばかりのカメラを 一体）')
p = sb.parse_sentence('とても高い山に登った。')
if p:
    check(all('とても' != c['surface'] for c in p['chunks']),
          '程度副词とても必须并入形容词块')

# 重建不变式：随机语料 300 句，凡能解析必可逐字拼回
import re as _re
with db.get_conn() as c:
    rows = [r['text'] for r in c.execute(
        'SELECT text FROM sentences ORDER BY RANDOM() LIMIT 300')]
n_parse = 0
for t in rows:
    p = sb.parse_sentence(t)
    if not p:
        continue
    n_parse += 1
    rebuilt = ''.join(ch['surface'] for ch in p['chunks'])
    stripped = _re.sub('[、。！？!?，, 　]', '', t)
    check(rebuilt == stripped, f'重建失真：{t} → {rebuilt}')
check(n_parse >= 100, f'300 句语料至少 100 句可解析（实际 {n_parse}）')

# ================================================================
print('== 2. 多解稳健判卷')
# ================================================================
def _spec_of(text):
    p = sb.parse_sentence(text)
    acc = sb.enumerate_accepted(p)
    n = len(p['chunks'])
    return p, {'chunks': [c['surface'] for c in p['chunks']], 'zones': p['zones'],
               'punct': p['punct'], 'tile_map': {f't{i}': i for i in range(n)},
               'accepted': acc, 'alt_count': len(acc) if acc else sb.order_count(p['zones'])}

p, spec = _spec_of('私は昨日図書館で本を読みました。')
check(spec['alt_count'] == 24, f'私は…読みました 应有 24 种合法语序（{spec["alt_count"]}）')
# 全部 24 种语序均判对
import itertools
n_ok = 0
for perm in itertools.permutations(['t0', 't1', 't2', 't3']):
    r = sb.check_arrangement(spec, list(perm) + ['t4'])
    n_ok += 1 if r['ok'] else 0
check(n_ok == 24, f'24 种自由语序应全部判对（{n_ok}）')
# 谓语不在句尾 → 判错且反馈明确
r = sb.check_arrangement(spec, ['t4', 't0', 't1', 't2', 't3'])
check(not r['ok'] and '谓语' in r['feedback'], f'谓语错位应判错并提示（{r["feedback"]}）')
# 缺块
r = sb.check_arrangement(spec, ['t0', 't1', 't2', 't4'])
check(not r['ok'] and '少用' in r['feedback'], '缺块应判错并指出缺了什么')
# 重复块
r = sb.check_arrangement(spec, ['t0', 't0', 't1', 't2', 't3', 't4'])
check(not r['ok'], '重复用块应判错')
# 干扰块
spec2 = dict(spec)
spec2['tile_map'] = dict(spec['tile_map'], d0=-1)
r = sb.check_arrangement(spec2, ['t0', 't1', 't2', 'd0', 't4'])
check(not r['ok'] and '干扰' in r['feedback'], '使用干扰块应判错并提示')
# 未知块 / 空输入 / 脏 spec —— 不崩溃
r = sb.check_arrangement(spec, ['zzz'])
check(not r['ok'], '未知词块应判错')
r = sb.check_arrangement(spec, [])
check(not r['ok'], '空作答应判错')
r = sb.check_arrangement({}, ['t0'])
check(isinstance(r, dict) and not r['ok'], '空 spec 不崩溃')
r = sb.check_arrangement({'chunks': 'x', 'tile_map': 'y'}, None)
check(isinstance(r, dict) and not r['ok'], '脏 spec 不崩溃')

# 跨区（从句边界）判错
p2, specB = _spec_of('雨が降っているので、試合は中止になりました。')
r = sb.check_arrangement(specB, ['t2', 't1', 't0', 't3'])
check(not r['ok'] and ('分句' in r['feedback'] or '谓语' in r['feedback']),
      f'跨区移动应判错（{r["feedback"]}）')
r = sb.check_arrangement(specB, ['t0', 't1', 't2', 't3'])
check(r['ok'], '原序应判对')

# 引用と句：两种语序均判对
p3, specC = _spec_of('彼は来ないかもしれないと言っていた。')
check(sb.check_arrangement(specC, ['t0', 't1', 't2'])['ok'], '彼は…と言っていた 原序判对')
check(sb.check_arrangement(specC, ['t1', 't0', 't2'])['ok'], '引用と句前置也判对（多解）')

# ================================================================
print('== 3. 全排列语法质检（strict 白名单）')
# ================================================================
p = sb.parse_sentence('私は昨日図書館で本を読みました。')
acc = sb.enumerate_accepted(p, strict=True)
check(acc is not None and len(acc) >= 1, '白名单枚举成功')
for o in (acc or [])[:30]:
    s = sb.assemble(p['chunks'], o, p['punct'])
    check(grammar.is_sentence_grammatically_sound(s), f'白名单语序必须过语法质检：{s}')
check(list(range(len(p['chunks']))) in (acc or []), '原句语序必须在白名单中')
# 组合数超限 → 返回 None（退化为约束判卷）
acc2 = sb.enumerate_accepted(p, perm_limit=2)
check(acc2 is None, '超过 perm_limit 应返回 None（约束判卷兜底）')
spec3 = {'chunks': [c['surface'] for c in p['chunks']], 'zones': p['zones'],
         'punct': p['punct'], 'tile_map': {f't{i}': i for i in range(5)},
         'accepted': None, 'alt_count': 24}
check(sb.check_arrangement(spec3, ['t3', 't2', 't1', 't0', 't4'])['ok'],
      '约束判卷：自由换序判对')
check(not sb.check_arrangement(spec3, ['t4', 't0', 't1', 't2', 't3'])['ok'],
      '约束判卷：谓语错位判错')

# ================================================================
print('== 4. 初级换词变体（语料共现）')
# ================================================================
nouns = sb._colloc_nouns('を', '読む')
check(len(nouns) >= 1, f'语料共现挖掘（を+読む）应有结果：{nouns}')
check(all(isinstance(w, str) and w and isinstance(n, int) and n >= 1
          for w, n in nouns), '共现结果为 (名词, 频次≥1) 对')
found_swap = 0
for _ in range(12):
    text = '彼女は毎日図書館で本を読んでいる。'
    got = sb._swap_variant(text, sb.parse_sentence(text))
    if not got:
        continue
    found_swap += 1
    new_text, info = got
    check(info['from'] + info['particle'] in text and info['to'] != info['from'],
          f'换词信息正确（原词在原句中、新词不同）：{info}')
    check(info['to'] + info['particle'] in new_text, '替换词已进入新句')
    check(grammar.is_sentence_grammatically_sound(new_text),
          f'换词后必须语法正确：{new_text}')
    check(sb.parse_sentence(new_text) is not None, '换词后仍可正常切块')
check(found_swap >= 1, '12 次尝试至少产出 1 个换词变体')

# —— 语义安全闸门 ——
# 1) 斜格在场（塀に…掛けた：に格收窄动词义项）→ 整句禁用换词槽位
_pg = sb.parse_sentence('彼は塀に梯子を掛けた。')
check(sb._case_slots(_pg, '彼は塀に梯子を掛けた。') == [],
      '斜格闸门：塀に 在场时禁用换词/多答案槽位')
check(sb._swap_variant('彼は塀に梯子を掛けた。', _pg) is None,
      '斜格闸门：换词直接返回 None')
# 2) に 格本身绝不做槽位（语义角色过宽）
check('に' not in sb.SWAP_PARTICLES and set(sb.SWAP_PARTICLES) == {'を', 'が', 'で'},
      '槽位只认选择限制强的 を/が/で')
# 3) 候选词终审：形式名词碎片/数字头/复合词残片一律拒绝
check(sb._noun_candidate_ok('小説') and sb._noun_candidate_ok('注意事項'),
      '正常实义名词通过终审')
check(not sb._noun_candidate_ok('こと煙草') and not sb._noun_candidate_ok('２人')
      and not sb._noun_candidate_ok('一箱'), '形式名词头/数字头拒绝')

# ================================================================
print('== 5. 高级干扰块安全性')
# ================================================================
# 等价助词对绝不生成（は↔が、に↔へ 等意义保持型替换）
for a, b in [('は', 'が'), ('に', 'へ'), ('は', 'も'), ('が', 'も')]:
    check((a, b) in sb._EQUIV_PAIRS and (b, a) in sb._EQUIV_PAIRS,
          f'等价对 {a}↔{b} 应在禁用表中')
cfg = sb.builder_cfg()
cfg['distractors'] = 4
n_d = 0
for text in ['私は昨日図書館で本を読みました。', '彼女は毎日図書館で本を読んでいる。']:
    p = sb.parse_sentence(text)
    ds = sb.make_distractors(p, text, cfg)
    n_d += len(ds)
    required = {c['surface'] for c in p['chunks']}
    for d in ds:
        check(d not in required, f'干扰块不得与所需块撞面：{d}')
        check(d not in text, f'干扰块不得是句内子串：{d}')
    # 换助词干扰：绝不出现 が/は/も/へ 结尾的名词块（等价风险）
    for d in ds:
        if any(d == c['surface'][:-1] + x for c in p['chunks']
               for x in ('が', 'は', 'も', 'へ')):
            check(False, f'出现等价助词干扰块：{d}')
check(n_d >= 2, f'两句应产出若干干扰块（{n_d}）')
# 时态变形干扰
p = sb.parse_sentence('私は昨日図書館で本を読みました。')
vf = sb._verb_form_variants(p['chunks'][-1])
check('読みます' in vf and '読みません' in vf, f'ました→ます/ません 变形：{vf}')
tail = sb.parse_sentence('彼は学校へ行った。')
if tail:
    vf2 = sb._verb_form_variants(tail['chunks'][-1])
    check('行く' in vf2, f'タ形→辞书形变形：{vf2}')

# —— 公平性铁律：无译文的句子 advanced 也不得放干扰块（译文=语义预言机）——
_row_tr = {'sid': 90001, 'text': '彼女は毎日図書館で本を読んでいる。',
           'translation': '她每天在图书馆看书。', 'source': 'tatoeba'}
_row_no = dict(_row_tr, translation='')
cfgA = sb.builder_cfg()
qtr = sb._build_arrange(_row_tr, cfgA, 'advanced', None)
qno = sb._build_arrange(_row_no, cfgA, 'advanced', None)
check(qtr and any(v == -1 for v in qtr['spec']['tile_map'].values()),
      '有译文 → advanced 可带干扰块')
check(qno and not any(v == -1 for v in qno['spec']['tile_map'].values()),
      '无译文 → advanced 零干扰块（公平性铁律）')

# —— 多答案（可互换名词槽位）——
found_group = None
for _ in range(8):
    qg = sb._build_arrange(_row_tr, cfgA, 'advanced', None)
    if qg and qg.get('alt_group'):
        found_group = qg
        break
if check(found_group is not None, '高频搭配句应能产出多答案组'):
    qg = found_group
    tm = qg['spec']['tile_map']
    alt_ids = [t for t in tm if t.startswith('a')]
    req_ids = sorted([t for t in tm if t.startswith('t')], key=lambda t: tm[t])
    ci = tm[alt_ids[0]]
    surfs = {t['id']: t['s'] for t in qg['tiles']}
    for a in alt_ids:
        # 换入整句独立复验语法
        s = ''.join(qg['spec']['chunks'][:ci]) + surfs[a] \
            + ''.join(qg['spec']['chunks'][ci + 1:]) + '。'
        check(grammar.is_sentence_grammatically_sound(s),
              f'可互换块换入整句必过语法质检：{s}')
        # 任选其一判对
        order = [a if tm[t] == ci else t for t in req_ids]
        check(sb.check_arrangement(qg['spec'], order)['ok'],
              f'可互换块 {surfs[a]} 作答判对')
    # 同槽双用必错
    r = sb.check_arrangement(qg['spec'], [alt_ids[0]] + req_ids)
    check(not r['ok'] and '互换' in r['feedback'], '同槽双用判错并明示原因')
    # 复合名词完整性：可互换名词不得是被截半的复合词碎片
    for o in qg['alt_group']['options']:
        check(len(o) >= 1 and not o.startswith(('々',)), f'互换名词合法：{o}')

# ================================================================
print('== 6. 配置：白名单 + 边界修正 + 两轴独立')
# ================================================================
c0 = sb.builder_cfg()
check(c0['mode'] in ('basic', 'advanced') and c0['level'] in ['any'] + sb.LEVELS,
      '默认配置合法')
c1 = sb.save_builder_cfg({'mode': 'advanced', 'level': 'N3', 'count': 99,
                          'max_tiles': 999, 'swap_prob': 7,
                          'types': {'arrange': 0, 'pairs': 0},
                          'distractor_kinds': {'vocab': False, 'bogus': True},
                          'evil_key': 'x'})
check(c1['mode'] == 'advanced' and c1['level'] == 'N3', 'mode 与 level 独立保存')
check(c1['count'] == 20, f'count 上限修正为 20（{c1["count"]}）')
check(c1['max_tiles'] <= 14, f'max_tiles 上限修正（{c1["max_tiles"]}）')
check(c1['swap_prob'] <= 1.0, f'swap_prob 修正到 0-1（{c1["swap_prob"]}）')
check(sum(c1['types'].values()) > 0, '题型占比全 0 时回落默认')
check('evil_key' not in c1 and 'bogus' not in c1['distractor_kinds'],
      '白名单过滤未知键')
check(c1['distractor_kinds']['vocab'] is False
      and c1['distractor_kinds']['verb_form'] is True, '字典键深合并')
# mode 改回 basic，level 不受影响（两轴独立）
c2 = sb.save_builder_cfg({'mode': 'basic'})
check(c2['mode'] == 'basic' and c2['level'] == 'N3', '改 mode 不动 level（两轴独立）')
c3 = sb.save_builder_cfg({'level': 'any'})
check(c3['mode'] == 'basic' and c3['level'] == 'any', '改 level 不动 mode（两轴独立）')
sb.save_builder_cfg({'mode': 'basic', 'level': 'any', 'count': 6,
                     'types': {'arrange': 80, 'pairs': 20}, 'max_tiles': 9})

# ================================================================
print('== 7. 出题主流程（basic / advanced / level 过滤 / 题型占比）')
# ================================================================
q = sb.make_quiz(count=6, mode='basic', level='any')
check(q['ok'] and q['count'] >= 1, f'basic 出题成功（{q["count"]} 题）')
for x in q['questions']:
    if x['qtype'] != 'arrange':
        check(len(x['pairs']) >= 2, '配对题至少 2 对')
        ws = [pp['w'] for pp in x['pairs']]
        rs = [pp['wr'] for pp in x['pairs']]
        check(len(set(ws)) == len(ws) and len(set(rs)) == len(rs),
              '配对题词形/读音均唯一（无歧义可配）')
        continue
    # basic 模式：无干扰块，tiles 恰好等于所需块
    fakes = [t for t in x['tiles'] if x['spec']['tile_map'][t['id']] == -1]
    check(not fakes, 'basic 模式不得有干扰块')
    check(len(x['tiles']) == x['n_required'], 'basic tiles 数 == 所需块数')
    check(x['alt_count'] >= 1, 'alt_count ≥ 1')
    # 判卷自洽：按原序作答必判对
    order = sorted([t['id'] for t in x['tiles'] if x['spec']['tile_map'][t['id']] >= 0],
                   key=lambda tid: x['spec']['tile_map'][tid])
    r = sb.check_arrangement(x['spec'], order)
    check(r['ok'], f'原序作答必判对：{x["text"]} → {r["feedback"]}')
    # 白名单存在时，逐个语序判对且过语法质检
    if x['spec'].get('accepted'):
        for o in x['spec']['accepted'][:10]:
            ids = [tid for i in o for tid, ci in x['spec']['tile_map'].items() if ci == i]
            check(sb.check_arrangement(x['spec'], ids)['ok'],
                  f'白名单语序必判对：{x["text"]}')
qa = sb.make_quiz(count=4, mode='advanced', level='any')
check(qa['ok'] and qa['count'] >= 1, f'advanced 出题成功（{qa["count"]} 题）')
adv_has_fake = False
for x in qa['questions']:
    if x['qtype'] != 'arrange':
        continue
    fakes = [t for t in x['tiles'] if x['spec']['tile_map'][t['id']] == -1]
    adv_has_fake = adv_has_fake or bool(fakes)
    # 干扰块用上必判错
    if fakes:
        real = sorted([t['id'] for t in x['tiles'] if x['spec']['tile_map'][t['id']] >= 0],
                      key=lambda tid: x['spec']['tile_map'][tid])
        bad = real[:-1] + [fakes[0]['id']] + real[-1:]
        r = sb.check_arrangement(x['spec'], bad)
        check(not r['ok'], '掺入干扰块必判错')
check(adv_has_fake, 'advanced 模式至少一题带干扰块')
# level 过滤：N5 专项 → 所有未放宽题目 level == N5
q5 = sb.make_quiz(count=4, mode='basic', level='N5')
for x in q5['questions']:
    if x['qtype'] == 'arrange' and not x.get('level_relaxed'):
        check(x['level'] == 'N5', f'level=N5 时选句应为 N5（{x["level"]}）')
# mode 与 level 自由组合
q53 = sb.make_quiz(count=2, mode='advanced', level='N4')
check(q53['ok'] and q53['mode'] == 'advanced' and q53['level'] == 'N4',
      'mode=advanced × level=N4 自由组合')

# ================================================================
print('== 8. API 全链路')
# ================================================================
r = client.get('/api/builder/cfg')
check(r.status_code == 200 and r.get_json()['ok'], 'GET /api/builder/cfg')
r = client.post('/api/builder/cfg', json={'mode': 'advanced', 'level': 'N5'})
j = r.get_json()
check(j['ok'] and j['cfg']['mode'] == 'advanced' and j['cfg']['level'] == 'N5',
      'POST /api/builder/cfg 两轴独立保存')
r = client.post('/api/builder/quiz', json={'count': 3, 'mode': 'basic', 'level': 'any'})
j = r.get_json()
check(j['ok'] and j['count'] >= 1, f'POST /api/builder/quiz（{j.get("count")} 题）')
arr = [x for x in j['questions'] if x['qtype'] == 'arrange']
if arr:
    x = arr[0]
    order = sorted([t['id'] for t in x['tiles'] if x['spec']['tile_map'][t['id']] >= 0],
                   key=lambda tid: x['spec']['tile_map'][tid])
    r = client.post('/api/builder/check', json={'spec': x['spec'], 'order': order})
    check(r.get_json()['ok'], 'POST /api/builder/check 原序判对')
    r = client.post('/api/builder/check', json={'spec': x['spec'], 'order': order[:1]})
    check(not r.get_json()['ok'], 'POST /api/builder/check 缺块判错')
r = client.post('/api/builder/check', json={})
check(r.status_code == 200 and not r.get_json()['ok'], 'check 空请求不崩')
r = client.post('/api/builder/answer', json={'results': [
    {'qtype': 'arrange', 'mode': 'basic', 'level': 'N5', 'ok': True},
    {'qtype': 'arrange', 'mode': 'advanced', 'level': 'N4', 'ok': False},
    {'qtype': 'pairs', 'mode': 'basic', 'level': '-', 'ok': True}]})
j = r.get_json()
check(j['ok'] and j['asked'] == 3 and j['correct'] == 2, 'POST /api/builder/answer')
r = client.get('/api/builder/stats')
j = r.get_json()
check(j['ok'] and len(j['stats']) >= 1, 'GET /api/builder/stats')
day = j['stats'][-1]
check(day['asked'] >= 3 and day['by_mode'].get('basic', {}).get('asked', 0) >= 2
      and day['by_type'].get('pairs', {}).get('asked', 0) >= 1,
      '统计按 题型/模式/级别 细分')
# enabled=False 时出题应拒绝
client.post('/api/builder/cfg', json={'enabled': False})
r = client.post('/api/builder/quiz', json={})
check(not r.get_json()['ok'], 'enabled=False 时拒绝出题')
client.post('/api/builder/cfg', json={'enabled': True})

# ================================================================
print('== 9. 大规模稳健性抽查（真实语料 × 全排列质检）')
# ================================================================
qs = sb.make_quiz(count=8, mode='basic', level='any')
for x in qs['questions']:
    if x['qtype'] != 'arrange' or not x['spec'].get('accepted'):
        continue
    for o in x['spec']['accepted']:
        s = sb.assemble([{'surface': ss} for ss in x['spec']['chunks']], o,
                        x['spec']['punct'] or '。')
        check(grammar.is_sentence_grammatically_sound(s),
              f'出题白名单语序必过语法质检：{s}')

print()
if FAILS:
    print(f'✗ {len(FAILS)} 项失败：')
    for f in FAILS:
        print(' -', f)
    sys.exit(1)
print('✓ 全部测试通过')

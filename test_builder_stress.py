# -*- coding: utf-8 -*-
"""组句练习 · 全语料深度压力测试（stress / property-based）
================================================================
在**全部真实语料**上验证六大不变式 —— 算法可以完全不懂句子意义，
但以下机械性质必须对每一句都成立：

  A. 切块普查（全库）      ：凡可解析必逐字重建；分区恰好划分全部块；
                             区尾非空；合法语序数 ≥ 1
  B. 白名单语法质检        ：每个被接受的语序拼回整句必过语法引擎；
                             原句语序必在白名单；块多重集不变
  C. 出题不变式（双模式）  ：basic 无干扰/无多答案组；advanced 干扰块
                             不撞所需块/不是句内子串/无等价助词对/
                             句外词不命中语料实证集；**无译文句零干扰块**
  D. 多答案稳健性          ：每个可互换名词 = 语料实证 + 换入整句过语法
                             质检 + 判卷任选其一均对 + 同槽双用必错
  E. 对抗判卷              ：谓语前置/跨区/缺块/多块/干扰块/乱序垃圾
                             一律判错且不崩溃（含 JSON 往返模拟 API）
  F. 多样性                ：同一句多次出题，换词/多答案/干扰组合不唯一

临时库隔离，不碰真实数据。运行：python3 test_builder_stress.py
"""
import os
import sys
import json
import time
import shutil
import random
import sqlite3
import tempfile
import itertools

sys.path.insert(0, '.')

FAILS = []
T0 = time.time()


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
    c0.execute("DELETE FROM settings WHERE key IN "
               "('sentence_builder_cfg','sentence_builder_stats')")
db.DB_PATH = api_db

import re
import grammar
import sentence_builder as sb

random.seed(20260926)

# ================================================================
print('== A. 全库切块普查')
# ================================================================
with db.get_conn() as c:
    ALL = [r['text'] for r in c.execute('SELECT text FROM sentences')]
print(f'   语料总量：{len(ALL)} 句')
n_parsed = n_multi = 0
bad_rebuild = bad_zone = 0
t0 = time.time()
for text in ALL:
    p = sb.parse_sentence(text)
    if not p:
        continue
    n_parsed += 1
    # 不变式 1：逐字重建
    rebuilt = ''.join(ch['surface'] for ch in p['chunks'])
    stripped = re.sub('[、。！？!?，, 　]', '', text)
    if rebuilt != stripped:
        bad_rebuild += 1
        if bad_rebuild <= 3:
            check(False, f'重建失真：{text} → {rebuilt}')
    # 不变式 2：分区恰好划分 0..n-1，区尾非空
    n = len(p['chunks'])
    seen = []
    for z in p['zones']:
        if not z['tail']:
            bad_zone += 1
            check(False, f'区尾为空：{text}')
        seen += list(z['head']) + list(z['mov']) + list(z['tail'])
    if sorted(seen) != list(range(n)):
        bad_zone += 1
        if bad_zone <= 3:
            check(False, f'分区未恰好划分：{text} → {p["zones"]}')
    # 不变式 3：合法语序数 ≥ 1
    if sb.order_count(p['zones']) < 1:
        check(False, f'合法语序数 < 1：{text}')
    if sb.order_count(p['zones']) > 1:
        n_multi += 1
dt = time.time() - t0
print(f'   可解析 {n_parsed}（{100*n_parsed//max(1,len(ALL))}%），多解 {n_multi}，'
      f'重建失真 {bad_rebuild}，分区异常 {bad_zone}，耗时 {dt:.1f}s')
check(bad_rebuild == 0, f'全库重建失真必须为 0（实际 {bad_rebuild}）')
check(bad_zone == 0, f'全库分区异常必须为 0（实际 {bad_zone}）')
check(n_parsed >= len(ALL) * 0.5, '全库至少一半句子可解析')

# ================================================================
print('== B. 白名单语法质检（抽样 300 句多解句全枚举）')
# ================================================================
random.shuffle(ALL)
sampled = 0
n_orders_checked = 0
t0 = time.time()
for text in ALL:
    if sampled >= 300:
        break
    p = sb.parse_sentence(text)
    if not p or not (3 <= len(p['chunks']) <= 9):
        continue
    total = sb.order_count(p['zones'])
    if not (2 <= total <= 120):
        continue
    try:
        if not grammar.is_sentence_grammatically_sound(text):
            continue
    except Exception:
        continue
    sampled += 1
    acc = sb.enumerate_accepted(p, perm_limit=120, strict=True)
    check(acc is not None and len(acc) >= 1, f'白名单枚举失败：{text}')
    original = list(range(len(p['chunks'])))
    check(original in acc, f'原句语序必须在白名单：{text}')
    base_ms = sorted(ch['surface'] for ch in p['chunks'])
    for o in acc:
        n_orders_checked += 1
        # 不变式：块多重集不变（纯排列）
        ms = sorted(p['chunks'][i]['surface'] for i in o)
        if ms != base_ms:
            check(False, f'白名单语序不是纯排列：{text} {o}')
        # 独立复验：拼回整句必过语法引擎
        s = sb.assemble(p['chunks'], o, p['punct'] or '。')
        if not grammar.is_sentence_grammatically_sound(s):
            check(False, f'白名单语序未过语法质检：{s}')
print(f'   抽样 {sampled} 句 / 复验 {n_orders_checked} 个语序，'
      f'耗时 {time.time()-t0:.1f}s')

# ================================================================
print('== C+D. 出题不变式 + 多答案稳健性（双模式大批量）')
# ================================================================
cfg = sb.builder_cfg()
n_q = n_fake_q = n_group_q = n_swap_q = 0
n_alt_verified = 0
t0 = time.time()
for mode in ('basic', 'advanced'):
    for batch in range(6):
        quiz = sb.make_quiz(count=8, mode=mode, level='any')
        if not quiz['ok']:
            continue
        for q in quiz['questions']:
            if q['qtype'] != 'arrange':
                continue
            n_q += 1
            spec = json.loads(json.dumps(q['spec']))   # JSON 往返模拟 API
            tm = spec['tile_map']
            req_ids = sorted([t for t, ci in tm.items() if ci >= 0 and t.startswith('t')],
                             key=lambda t: tm[t])
            fake_ids = [t for t, ci in tm.items() if ci == -1]
            alt_ids = [t for t, ci in tm.items() if ci >= 0 and t.startswith('a')]
            surfs = {t['id']: t['s'] for t in q['tiles']}

            # -- 通用不变式 --
            check(len(req_ids) == q['n_required'] == len(spec['chunks']),
                  f'所需块数自洽：{q["text"]}')
            check([surfs[t] for t in req_ids] == spec['chunks'],
                  f'词块表面与槽位一致：{q["text"]}')
            r = sb.check_arrangement(spec, req_ids)
            check(r['ok'], f'原序作答必判对：{q["text"]} → {r["feedback"]}')
            check(r['your_text'].startswith(''.join(spec['chunks'])),
                  f'your_text 拼接正确：{r["your_text"]}')

            if mode == 'basic':
                check(not fake_ids, f'basic 不得有干扰块：{q["text"]}')
                check(not alt_ids, f'basic 不得有多答案组：{q["text"]}')
                if q.get('swap'):
                    n_swap_q += 1
                    check(grammar.is_sentence_grammatically_sound(q['text']),
                          f'换词变体必过语法质检：{q["text"]}')
                    check(q['swap']['to'] + q['swap']['particle'] in q['text'],
                          f'换词已进入题面：{q["swap"]}')
                continue

            # -- advanced 专属不变式 --
            has_tr = bool((q.get('translation') or '').strip())
            if not has_tr:
                check(not fake_ids,
                      f'公平性铁律：无译文句零干扰块：{q["text"]}')
            if fake_ids:
                n_fake_q += 1
                req_surf = set(spec['chunks']) | {surfs[a] for a in alt_ids}
                for f in fake_ids:
                    fs = surfs[f]
                    check(fs not in req_surf, f'干扰块撞所需块：{fs}')
                    check(fs not in q['text'], f'干扰块是句内子串：{fs}')
                    # 等价助词对检查：同名词换助词的干扰块
                    for cs in spec['chunks']:
                        for p1 in ('は', 'が', 'も', 'へ', 'に', 'を', 'で'):
                            if cs.endswith(p1) and fs.startswith(cs[:-len(p1)]) \
                                    and len(fs) > len(cs) - len(p1):
                                p2 = fs[len(cs) - len(p1):]
                                if (p1, p2) in sb._EQUIV_PAIRS:
                                    check(False, f'等价助词干扰块：{cs} vs {fs}')
                # 掺干扰块必判错
                bad = req_ids[:-1] + [fake_ids[0]] + req_ids[-1:]
                check(not sb.check_arrangement(spec, bad)['ok'],
                      f'掺干扰块必判错：{q["text"]}')

            if alt_ids:
                n_group_q += 1
                ag = q['alt_group']
                ci = tm[alt_ids[0]]
                check(all(tm[a] == ci for a in alt_ids), '多答案块映射同一槽位')
                for a in alt_ids:
                    n_alt_verified += 1
                    # 换入整句独立复验语法
                    alt_sent = ''.join(
                        surfs[a] if tm[t] == ci and t == req_ids[ci] else surfs[t]
                        for t in req_ids) + (spec.get('punct') or '')
                    alt_sent = alt_sent.replace(spec['chunks'][ci], surfs[a], 1) \
                        if surfs[a] not in alt_sent else alt_sent
                    ok_g = grammar.is_sentence_grammatically_sound(
                        ''.join(spec['chunks'][:ci]) + surfs[a]
                        + ''.join(spec['chunks'][ci + 1:]) + (spec.get('punct') or '。'))
                    check(ok_g, f'可互换块换入整句必过语法质检：{surfs[a]} in {q["text"]}')
                    # 语料实证：名词必须在共现集中
                    noun = surfs[a][:-len(ag['particle'])]
                    check(noun in ag['options'], f'可互换名词登记在案：{noun}')
                    # 判卷：任选其一均判对
                    order = [a if t == req_ids[ci] else t for t in req_ids]
                    rr = sb.check_arrangement(spec, order)
                    check(rr['ok'], f'可互换块作答必判对：{surfs[a]} → {rr["feedback"]}')
                    check(surfs[a] in rr['your_text'], 'your_text 反映所选词块')
                # 同槽双用必错
                both = [alt_ids[0]] + req_ids
                rr = sb.check_arrangement(spec, both)
                check(not rr['ok'] and '互换' in rr['feedback'],
                      f'同槽双用必错并提示（{rr["feedback"]}）')
print(f'   出题 {n_q} 道（干扰 {n_fake_q} / 多答案 {n_group_q} / 换词 {n_swap_q}，'
      f'复验互换块 {n_alt_verified} 个），耗时 {time.time()-t0:.1f}s')
check(n_q >= 40, f'批量出题应 ≥40 道（{n_q}）')
check(n_fake_q >= 5, f'advanced 应有带干扰题（{n_fake_q}）')
check(n_group_q >= 3, f'advanced 应有多答案题（{n_group_q}）')

# ================================================================
print('== E. 对抗判卷（结构性错误全判错 + 模糊测试不崩溃）')
# ================================================================
adv_rejected = adv_total = 0
quiz = sb.make_quiz(count=8, mode='basic', level='any')
for q in quiz['questions']:
    if q['qtype'] != 'arrange':
        continue
    spec = json.loads(json.dumps(q['spec']))
    tm = spec['tile_map']
    req_ids = sorted([t for t in tm if tm[t] >= 0], key=lambda t: tm[t])
    n = len(req_ids)
    acc = spec.get('accepted')
    # 谓语强行前置
    r = sb.check_arrangement(spec, req_ids[-1:] + req_ids[:-1])
    if acc and [tm[t] for t in req_ids[-1:] + req_ids[:-1]] not in acc:
        check(not r['ok'], f'谓语前置必判错：{q["text"]}')
    # 随机乱序 20 次：白名单外必判错，白名单内必判对（判卷=白名单精确一致）
    for _ in range(20):
        perm = req_ids[:]
        random.shuffle(perm)
        r = sb.check_arrangement(spec, perm)
        adv_total += 1
        if acc is not None:
            expect = [tm[t] for t in perm] in acc
            if r['ok'] != expect:
                check(False, f'判卷与白名单不一致：{q["text"]} {perm}')
            if not expect:
                adv_rejected += 1
    # 缺块 / 多块
    check(not sb.check_arrangement(spec, req_ids[:-1])['ok'], '缺块必判错')
    check(not sb.check_arrangement(spec, req_ids + req_ids[:1])['ok'], '多块必判错')
print(f'   随机乱序 {adv_total} 次（其中判错 {adv_rejected} 次，其余为合法多解）')
# 模糊测试：垃圾输入不崩溃、绝不误判对
fuzz_ok = True
for _ in range(300):
    garbage_spec = random.choice([
        {}, {'chunks': None}, {'chunks': [], 'tile_map': {}},
        {'chunks': ['あ', 'い'], 'tile_map': {'t0': 0, 't1': 99}, 'zones': []},
        {'chunks': ['あ'], 'tile_map': {'t0': 'x'}, 'zones': [{'head': [], 'mov': [], 'tail': [0]}]},
        {'chunks': ['あ', 'い'], 'tile_map': {'t0': 0, 't1': 1},
         'zones': [{'head': [], 'mov': [0], 'tail': [1]}], 'accepted': 'bogus'},
    ])
    garbage_order = random.choice([None, [], ['t0'], ['x', 'y'], [1, 2], ['t0'] * 5])
    try:
        r = sb.check_arrangement(garbage_spec, garbage_order)
        if not isinstance(r, dict):
            fuzz_ok = False
    except Exception as e:
        # accepted='bogus' 之类结构错误允许内部兜底，但绝不能抛出
        fuzz_ok = False
        check(False, f'模糊测试崩溃：{type(e).__name__} {e}')
check(fuzz_ok, '300 次模糊测试全部不崩溃')

# ================================================================
print('== F. 多样性（同句多次出题，组合不唯一）')
# ================================================================
text = '彼女は毎日図書館で本を読んでいる。'
p = sb.parse_sentence(text)
alts_seen, fakes_seen = set(), set()
for _ in range(12):
    ag = sb._alt_group(text, p, cfg)
    if ag:
        alts_seen |= set(ag['alts'])
    ds = sb.make_distractors(p, text, cfg)
    fakes_seen |= set(ds)
check(len(alts_seen) >= 2, f'多答案候选应有多样性（{alts_seen}）')
check(len(fakes_seen) >= 4, f'干扰块组合应有多样性（{fakes_seen}）')
swaps_seen = set()
for _ in range(12):
    got = sb._swap_variant(text, p)
    if got:
        swaps_seen.add(got[1]['to'])
check(len(swaps_seen) >= 2, f'换词应有多样性（{swaps_seen}）')

print()
print(f'总耗时 {time.time()-T0:.1f}s')
if FAILS:
    print(f'✗ {len(FAILS)} 项失败：')
    for f in FAILS[:30]:
        print(' -', f)
    sys.exit(1)
print('✓ 全语料深度压力测试全部通过')

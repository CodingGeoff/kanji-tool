# -*- coding: utf-8 -*-
"""KTV 歌词注音质量回归测试（v20 审计固化）

审计发现并修复的三类问题，全部固化为不变式，防止回归：
  1. furigana alt 候选混入非纯假名（啄 alt=['啄']、にわとり(とり)）
  2. ktv._S2J 简体转换表缺字（诱访梦阑标见响鸣仅岚…）→ 整词 unk
  3. 双路择优平手误选未转换路径 → 风铃/鸣 有词典读音却标 unk

以及结构不变式（存量审计全绿项，永远不许破）：
  行对齐 0 错 / 逐字重建 0 失真 / 假读音（读音含汉字）0
"""
import re
import json

import db
import ktv
import furigana

KANJI = re.compile(r'[一-鿿]')
PURE_KANA = re.compile(r'^[ぁ-ゖァ-ヺーゝゞヽヾ]+$')

_PASS = _FAIL = 0


def check(name, cond, detail=''):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f'  ✓ {name}')
    else:
        _FAIL += 1
        print(f'  ✗ {name}  {detail}')


# ----------------------------------------------------------------
print('== 1. 简体转换表：审计缺字必须全部在表 ==')
for pair in ('诱誘', '访訪', '梦夢', '阑闌', '标標', '见見',
             '响響', '鸣鳴', '仅僅', '岚嵐'):
    sc, jc = pair[0], pair[1]
    check(f'{sc} → {jc}', ktv._S2J.get(sc) == jc, f'got {ktv._S2J.get(sc)}')

print('== 2. 双路择优：简体行整词注音（曾整词 unk 的实例） ==')
toks, _ = ktv.annotate_lyrics('近づくように风薫り风铃鸣らし')
line = toks[0]
check('逐字重建原文', ''.join(t['s'] for t in line) == '近づくように风薫り风铃鸣らし')
by_s = {t['s']: t for t in line}
check('风铃 → ふうりん', by_s.get('风铃', {}).get('r') == 'ふうりん',
      str(by_s.get('风铃')))
check('鸣 → な', by_s.get('鸣', {}).get('r') == 'な', str(by_s.get('鸣')))
check('无 unk', not any(t.get('unk') for t in line))

print('== 3. alt 纯假名门禁（两条产生路径都堵死） ==')
t = furigana.annotate('鶏(とり)と共に')          # 复合词仲裁路径
bad = [a for x in t for a in (x.get('alt') or []) if not PURE_KANA.match(a)]
check('括号脏字符 alt 被过滤', not bad, str(bad))
t = furigana.annotate('小鳥が朝を啄ばむ')          # nbest/sudachi 路径
bad = [a for x in t for a in (x.get('alt') or []) if not PURE_KANA.match(a)]
check('未収録字表面形 alt 被过滤', not bad, str(bad))

print('== 4. 全曲库结构不变式（fresh 重注） ==')
with db.get_conn() as c:
    rows = [dict(r) for r in c.execute('SELECT * FROM songs').fetchall()]
if not rows:
    print('  （曲库为空，跳过）')
else:
    mis = rebuild = fake = 0
    unk, bad_alt = [], []
    for r in rows:
        toks, kc = ktv.annotate_lyrics(r['lyrics'])
        lines = r['lyrics'].split('\n')
        if len(toks) != len(lines):
            mis += 1
        for ln, tk in zip(lines, toks):
            if tk is None:
                continue
            if len(tk) == 1 and ('k' in tk[0] or 'en' in tk[0]):
                continue
            if ''.join(x['s'] for x in tk) != ln:
                rebuild += 1
            for x in tk:
                if x.get('unk'):
                    unk.append(x['s'])
                if x.get('r') and KANJI.search(x['r']):
                    fake += 1
                for a in x.get('alt') or []:
                    if not PURE_KANA.match(a):
                        bad_alt.append((x['s'], a))
    check(f'行对齐 0 错（{len(rows)} 首）', mis == 0, f'{mis} 首错位')
    check('逐字重建 0 失真', rebuild == 0, f'{rebuild} 行失真')
    check('假读音（读音含汉字）= 0', fake == 0, f'{fake} 个')
    check('alt 全部纯假名', not bad_alt, str(bad_alt[:5]))
    # 残余 unk 只允许是真中文词（简转后仍非日语词），不允许爆炸
    check(f'unk ≤ 6（当前 {len(unk)}：真中文词诚实标记）', len(unk) <= 6,
          str(unk[:10]))

print('== 5. 引擎版本自动对齐（惰性重注） ==')
if rows:
    sid = rows[0]['id']
    with db._lock, db.get_conn() as c:
        c.execute('UPDATE songs SET anno_ver=0 WHERE id=?', (sid,))
    row = db.get_song(sid)
    toks, ver = ktv.ensure_fresh(row)
    check('重注后返回当前版本', ver == ktv.ANNO_VER, f'got {ver}')
    check('版本号已回写', db.get_song(sid).get('anno_ver') == ktv.ANNO_VER)
    check('重注 tokens 行对齐', len(toks) == len(row['lyrics'].split('\n')))

print('== 6. 歌曲学习档案 ==')
if rows:
    st = ktv.song_study(db.get_song(rows[0]['id']))
    check('结构完整', all(k in st for k in ('kanji', 'words'))
          and all(k in st['kanji'] for k in ('total', 'learned', 'coverage', 'new', 'known')))
    check('生字按频次降序', all(
        st['kanji']['new'][i]['song_freq'] >= st['kanji']['new'][i + 1]['song_freq']
        for i in range(len(st['kanji']['new']) - 1)))
    check('learned + new = total（截断前）',
          st['kanji']['learned'] + len(st['kanji']['new']) == st['kanji']['total']
          or len(st['kanji']['new']) == 60)
    allk = [x['k'] for x in st['kanji']['new']] + [x['k'] for x in st['kanji']['known']]
    check('档案条目全是汉字', all(KANJI.match(k) for k in allk))

print('== 7. 组句歌词域（公平铁律：无译文 ⇒ 零干扰） ==')
import sentence_builder as sb
pool = sb._lyric_pool(300)
check(f'歌词题源非空（{len(pool)} 行）', len(pool) > 50)
check('题源行全部含假名、无拉丁', all(
    sb._LYRIC_KANA_RE.search(p['text']) and not sb._LYRIC_LATIN_RE.search(p['text'])
    for p in pool))
q = sb.make_quiz(count=6, scope='lyric', mode='advanced')
arr = [x for x in q.get('questions', []) if x.get('qtype') == 'arrange']
check(f'出题成功（{len(arr)} 道组句）', q.get('ok') and len(arr) >= 3)
check('advanced 下歌词题零干扰', all(
    not any(t.get('d') for t in x['tiles']) for x in arr))
check('sid 为空（不在 sentences 表，前端不显示收藏）',
      all(x.get('sid') is None for x in arr))
check('origin 带歌名', all((x.get('origin') or '').startswith('🎵') for x in arr))
# 正确答案必须判对
ok_all = True
for x in arr:
    ans = sb.check_arrangement(x['spec'], [f't{i}' for i in range(x['n_required'])])
    if not ans.get('ok'):
        ok_all = False
        print('    判卷失败:', x['text'])
check('原始语序判对', ok_all)

print()
print(f'PASS {_PASS}  FAIL {_FAIL}')
raise SystemExit(1 if _FAIL else 0)

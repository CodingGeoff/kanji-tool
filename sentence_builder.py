# -*- coding: utf-8 -*-
"""多邻国式「组句练习」引擎（sentence builder）
================================================================
根据现有语料（sentences / book_sentences / 歌词句子）自动生成
Duolingo 风格的拼句题，并保证判卷稳健：

一、题型
  1. arrange —— 组句题（核心）：把句子按「文节（bunsetsu）」拆成词块，
     打乱后让用户重新排序。
  2. pairs  —— 配对题：从语料注音中抽词，词形 ↔ 读音连线。

二、两条完全独立的难度轴
  * mode（初级 basic / 高级 advanced）—— 决定「题目形态」：
      - basic：词块=恰好所需，无干扰项；默认开启「同位换词」——
        依语料共现（同一助词+同一谓语动词下的宾语/主语分布）把原句
        某个名词替换成语料中真实搭配过的另一个名词，替换后的整句
        必须通过语法质检，保证语法正确（题目不一定是原句）。
      - advanced：在 basic 词块基础上加入混淆干扰块（同一动词的不同
        时态/礼貌体变形、语料随机高频词、换助词的同名词块），干扰块
        经过等价性检查，绝不会与译文语义相同（は↔が、に↔へ 等
        意义保持型替换一律不生成）。
  * level（N5..N1 / any）—— 决定「句子选材」：按语法引擎解析出的
    句内最高级别语法点过滤选句，与 mode 互不影响、自由组合。

三、多解稳健性（关键设计）
  日语是格标记语言，谓语句尾、其余格成分（〜は/〜が/〜を/〜に/〜で、
  时间词、副词）在小句内可自由换序（scrambling）。判卷绝不能只认原句
  一种语序。做法：
    1. 文节切块：内容词+其后附属功能词为一块；连体修饰（この/连体形
       从句+名词/〜の+名词）、样态补助（〜ている/〜てしまう/かもしれ
       ない/〜になる）、程度副词+形容词 一律并入同块 —— 依存关系被
       "焊死"在块内，块间就只剩自由格成分。
    2. 分区（zone）：读点、接续助词（〜ば/〜ので/〜て、）处切区，
       区序固定、区内自由 —— 从句成分不允许越过逗号漂移。
    3. 每区最后一块（谓语）固定区尾；句首接续词/感叹词固定区头；
       无格助词又非副词性的块出现时整区锁死（宁可少给自由度，
       绝不误判对错）。
    4. 合法排列 = 各区自由块的全排列组合。生成时若组合数 ≤ 上限，
       逐一拼回整句过 `grammar.check_sentence_grammar` 质检，通过的
       排列显式写入题面（accepted 白名单）；组合过多时退化为约束
       判卷。两条路径都保证：所有语法正确的语序都判对。
    5. 判卷（check_arrangement）给出结构化反馈：用了干扰块 / 少块 /
       谓语没在句尾 / 跨区移动 / 固定语序错位，并返回规范答案与
       合法语序总数。

四、质检链（出题前逐句过滤）
  单句完整（grammar.check_sentence_grammar）→ 无引号括号 → 文节数
  在配置区间 → 词块拼回去必须与原句逐字一致（去标点比对）→
  （strict_check）全部合法排列语法质检。
"""
import functools
import itertools
import json
import math
import random
import re
from datetime import date

import fugashi

import db
import furigana
import grammar

_tagger = fugashi.Tagger()

LEVEL_ORDER = {'N5': 0, 'N4': 1, 'N3': 2, 'N2': 3, 'N1': 4}
LEVELS = ['N5', 'N4', 'N3', 'N2', 'N1']

# ================================================================
# 配置（与挖空的 study_cfg 相互独立；mode 与 level 是两条独立轴）
# ================================================================
DEFAULT_BUILDER_CFG = {
    'enabled': True,
    'mode': 'basic',            # basic=初级(无干扰) | advanced=高级(带混淆)
    'level': 'any',             # any | N5..N1  —— 句子选材难度，独立于 mode
    'scope': 'corpus',          # corpus=全库语料 | book=仅课本 | mixed=课本优先
    'count': 6,                 # 每组题数 (1-20)
    'types': {'arrange': 80, 'pairs': 20},   # 题型占比（自动归一）
    'min_tiles': 3,             # 组句题最少词块数
    'max_tiles': 9,             # 组句题最多词块数
    'distractors': 3,           # advanced 干扰块数 (0-6)
    'distractor_kinds': {'verb_form': True, 'vocab': True, 'particle': True},
    'swap': True,               # basic 语料同位换词
    'swap_prob': 0.35,          # 每题换词概率
    'strict_check': True,       # 出题时对全部合法排列做语法质检
    'perm_limit': 120,          # 全排列质检上限（组合数超过则用约束判卷）
    'show_furigana': 'basic',   # basic=仅初级显示注音 | always | never
}

_CFG_KEY = 'sentence_builder_cfg'
_STATS_KEY = 'sentence_builder_stats'


def builder_cfg():
    """读取组句练习配置（settings JSON，白名单键 + 字典键深合并）"""
    cfg = json.loads(json.dumps(DEFAULT_BUILDER_CFG))
    try:
        raw = db.get_setting(_CFG_KEY, '')
        if raw:
            saved = json.loads(raw)
            for k, v in saved.items():
                if k not in DEFAULT_BUILDER_CFG:
                    continue
                if isinstance(DEFAULT_BUILDER_CFG[k], dict) and isinstance(v, dict):
                    cfg[k].update({kk: vv for kk, vv in v.items()
                                   if kk in DEFAULT_BUILDER_CFG[k]})
                else:
                    cfg[k] = v
    except Exception:
        pass
    return _sanitize_cfg(cfg)


def _sanitize_cfg(cfg):
    """配置边界修正：非法值全部回落到安全默认，保证任何输入都不崩"""
    if cfg.get('mode') not in ('basic', 'advanced'):
        cfg['mode'] = 'basic'
    if cfg.get('level') not in (['any'] + LEVELS):
        cfg['level'] = 'any'
    if cfg.get('scope') not in ('corpus', 'book', 'mixed'):
        cfg['scope'] = 'corpus'
    try:
        cfg['count'] = max(1, min(int(cfg.get('count', 6)), 20))
    except Exception:
        cfg['count'] = 6
    try:
        cfg['min_tiles'] = max(2, min(int(cfg.get('min_tiles', 3)), 6))
    except Exception:
        cfg['min_tiles'] = 3
    try:
        cfg['max_tiles'] = max(cfg['min_tiles'], min(int(cfg.get('max_tiles', 9)), 14))
    except Exception:
        cfg['max_tiles'] = 9
    try:
        cfg['distractors'] = max(0, min(int(cfg.get('distractors', 3)), 6))
    except Exception:
        cfg['distractors'] = 3
    try:
        cfg['swap_prob'] = max(0.0, min(float(cfg.get('swap_prob', 0.35)), 1.0))
    except Exception:
        cfg['swap_prob'] = 0.35
    try:
        cfg['perm_limit'] = max(1, min(int(cfg.get('perm_limit', 120)), 720))
    except Exception:
        cfg['perm_limit'] = 120
    t = cfg.get('types') or {}
    a = max(0, int(t.get('arrange', 80) or 0))
    p = max(0, int(t.get('pairs', 20) or 0))
    if a + p == 0:
        a, p = 80, 20
    cfg['types'] = {'arrange': a, 'pairs': p}
    if cfg.get('show_furigana') not in ('basic', 'always', 'never'):
        cfg['show_furigana'] = 'basic'
    return cfg


def save_builder_cfg(patch):
    """增量保存（白名单键），返回合并后的完整配置"""
    cfg = builder_cfg()
    for k, v in (patch or {}).items():
        if k not in DEFAULT_BUILDER_CFG:
            continue
        if isinstance(DEFAULT_BUILDER_CFG[k], dict) and isinstance(v, dict):
            cfg[k].update({kk: vv for kk, vv in v.items()
                           if kk in DEFAULT_BUILDER_CFG[k]})
        else:
            cfg[k] = v
    cfg = _sanitize_cfg(cfg)
    db.set_setting(_CFG_KEY, json.dumps(cfg, ensure_ascii=False))
    db.log('builder', '更新组句练习配置：' + ', '.join(
        f'{k}={v}' for k, v in (patch or {}).items() if k in DEFAULT_BUILDER_CFG))
    return cfg


# ================================================================
# 1. 形态素 → 文节切块
# ================================================================
_SENT_END = ('。', '！', '？', '!', '?')
_DROP_CHARS = '、。！？!?，, 　'
_BAD_TEXT_RE = re.compile(r'[「」『』（）()\[\]【】〈〉《》…‥・〜~"\'";:：；]')

_CONTENT_POS = {'名詞', '代名詞', '動詞', '形容詞', '形状詞', '副詞',
                '連体詞', '接続詞', '感動詞', '接頭辞', '記号'}
_CASE_P = {'が', 'を', 'に', 'で', 'へ', 'と', 'から', 'まで', 'より'}
# 意义保持型助词替换对（生成干扰块时禁用：换了句意几乎不变，判错不公平）
_EQUIV_PAIRS = {('は', 'が'), ('が', 'は'), ('に', 'へ'), ('へ', 'に'),
                ('は', 'も'), ('も', 'は'), ('が', 'も'), ('も', 'が')}


def _tok(w):
    f = w.feature
    return {'s': w.surface, 'p1': f.pos1, 'p2': f.pos2 or '', 'p3': f.pos3 or '',
            'lemma': f.lemma or w.surface, 'cf': f.cForm or '',
            'ob': getattr(f, 'orthBase', None) or f.lemma or w.surface}


def _tag(text):
    return [_tok(w) for w in _tagger(text)]


def _chunk_has_te(cur):
    return any(t['p2'] == '接続助詞' and t['s'] in ('て', 'で') for t in cur)


def _attach(cur, tok):
    """tok 是否附着到当前文节（不开新块）"""
    if not cur:
        return True
    last = cur[-1]
    p1 = tok['p1']
    # 功能词一律附着
    if p1 in ('助詞', '助動詞', '接尾辞', '補助記号'):
        return True
    # 形状詞-助動詞語幹（よう/そう/みたい）附着：〜ないように
    if p1 == '形状詞' and tok['p2'] == '助動詞語幹':
        return True
    # 接头辞后的内容词附着
    if last['p1'] == '接頭辞':
        return True
    # かもしれない：か+も 之后的动词附着
    if len(cur) >= 2 and cur[-2]['s'] == 'か' and last['s'] == 'も' and p1 == '動詞':
        return True
    # 复合名词：名詞+名詞 合并（但时间词「昨日/毎日」等副詞可能名词不吞后词）
    if p1 in ('名詞',) and last['p1'] in ('名詞', '接尾辞') and last['p3'] != '副詞可能':
        return True
    # サ变名词 + する（勉強する/練習している）
    if (p1 == '動詞' and tok['lemma'] == '為る' and last['p1'] == '名詞'
            and 'サ変' in last['p3']):
        return True
    # 非自立动词/形容词（ている/てしまう/ておく/てもいい/になる/にする/よくなる）
    if p1 in ('動詞', '形容詞') and tok['p2'] == '非自立可能':
        if last['p2'] == '接続助詞' and last['s'] in ('て', 'で'):
            return True
        if last['s'] in ('は', 'も') and _chunk_has_te(cur):
            return True
        if last['p1'] == '助動詞' and last['cf'].startswith('連用形'):
            return True
        if last['p1'] in ('動詞', '形容詞') and last['cf'].startswith('連用形'):
            return True
        if last['s'] == 'に' and last['p2'] == '格助詞' and tok['lemma'] in ('成る', '為る'):
            return True
    return False


def _raw_chunks(toks):
    """第一遍：线性切文节。返回 (chunks, punct)；chunk={'toks','comma_after'}"""
    chunks, cur, punct = [], [], ''
    for t in toks:
        if t['p1'] == '補助記号':
            if t['s'] in _SENT_END:
                punct = t['s']
                continue
            if t['p2'] == '読点' or t['s'] in ('、', '，', ','):
                if cur:
                    chunks.append({'toks': cur, 'comma_after': True})
                    cur = []
                elif chunks:
                    chunks[-1]['comma_after'] = True
                continue
            # 其余补助记号附着
            if cur:
                cur.append(t)
            continue
        if cur and not _attach(cur, t):
            chunks.append({'toks': cur, 'comma_after': False})
            cur = [t]
        else:
            cur.append(t)
    if cur:
        chunks.append({'toks': cur, 'comma_after': False})
    return chunks, punct


def _c_surface(c):
    return ''.join(t['s'] for t in c['toks'])


def _c_last(c):
    return c['toks'][-1]


def _c_head(c):
    return c['toks'][0]


def _ends_rentai(c):
    """块尾是否连体形（后面必须紧跟被修饰名词）"""
    return _c_last(c)['cf'].startswith('連体形')


def _is_adverbial(c):
    """块是否副词性（时间词/副词/形容词连用形，可自由移位）"""
    toks = c['toks']
    h = toks[0]
    if h['p1'] == '副詞':
        return all(t['p1'] in ('副詞', '助詞') for t in toks)
    if h['p1'] == '名詞' and h['p3'] == '副詞可能' and len(toks) == 1:
        return True
    if h['p1'] == '形容詞' and h['cf'].startswith('連用形') and len(toks) == 1:
        return True
    return False


def _merge_chunks(chunks):
    """第二遍：把固定依存焊进同一块（连体修饰/属格/程度副词/从句前副词）。
    合并只会减少自由度，绝不会放行错误语序 —— 稳健性优先。"""
    changed = True
    while changed and len(chunks) > 1:
        changed = False
        for i in range(len(chunks) - 1):
            a, b = chunks[i], chunks[i + 1]
            if a['comma_after']:
                continue                      # 逗号是区界，绝不跨界合并
            merge = False
            # 连体词（この/その/あの/どの/大きな…）→ 并入后块
            if _c_head(a)['p1'] == '連体詞' and len(a['toks']) == 1:
                merge = True
            # 属格「〜の」→ 并入后块（ばかりの/だけの 同理，块尾是の即合）；
            # 若の前含动词/形容词（買ったばかりの…）实为连体从句 → 打 clause 标，
            # 让前置时间副词一并吸入，避免「昨日」漂移改变修饰对象
            elif (_c_last(a)['s'] == 'の' and _c_last(a)['p1'] == '助詞'
                  and _c_last(a)['p2'] in ('格助詞', '準体助詞')
                  and _c_head(b)['p1'] in ('名詞', '代名詞', '接頭辞')):
                merge = True
                if any(t['p1'] in ('動詞', '形容詞') for t in a['toks']):
                    b['clause'] = True
            # 连体形从句 + 名词（買った+カメラ / 帰る+こと / なる+ため）
            elif _ends_rentai(a) and _c_head(b)['p1'] in ('名詞', '代名詞', '接頭辞'):
                merge = True
                b['clause'] = True
            # 程度副词/连用形容词 + 形容词系块 or 从句块（とても高い / 早く帰ること）
            elif _is_adverbial(a) and (
                    _c_head(b)['p1'] in ('形容詞', '形状詞') or b.get('clause')):
                merge = True
            if merge:
                merged = {'toks': a['toks'] + b['toks'],
                          'comma_after': b['comma_after'],
                          'clause': a.get('clause') or b.get('clause', False)}
                chunks[i:i + 2] = [merged]
                changed = True
                break
    return chunks


def _zone_boundary_after(c):
    """块后是否切区：读点 / 块尾接续助词（ば/て/ので/から/のに/たら…）"""
    if c['comma_after']:
        return True
    last = _c_last(c)
    if last['p2'] == '接続助詞':
        return True
    # ので/のに：準体助詞の + 助動詞だ(で/に)
    toks = c['toks']
    if (len(toks) >= 2 and last['p1'] == '助動詞' and last['lemma'] == 'だ'
            and toks[-2]['s'] == 'の' and toks[-2]['p2'] == '準体助詞'):
        return True
    return False


def _is_movable(c):
    """区内可自由换序：带格/系/副助词的成分，或副词性成分"""
    last = _c_last(c)
    if last['p1'] == '助詞' and last['p2'] in ('格助詞', '係助詞', '副助詞'):
        return True
    return _is_adverbial(c)


def _is_predicative(c):
    """块内含谓语性成分（动/形/助动/终助词收尾）→ 可作区尾"""
    if any(t['p1'] in ('動詞', '形容詞', '助動詞') for t in c['toks']):
        return True
    return _c_last(c)['p2'] == '終助詞'


def parse_sentence(text):
    """整句 → {chunks:[{surface,toks}], zones:[{head,mov,tail}], punct}
    返回 None 表示此句不适合出组句题（质检不过/切块失真/结构过险）。"""
    text = (text or '').strip()
    if not text or _BAD_TEXT_RE.search(text):
        return None
    toks = _tag(text)
    chunks, punct = _raw_chunks(toks)
    if len(chunks) < 2:
        return None
    chunks = _merge_chunks(chunks)
    # 逐字重建校验：所有块拼起来必须等于原句去标点 —— 切块失真直接弃句
    rebuilt = ''.join(_c_surface(c) for c in chunks)
    stripped = re.sub('[' + re.escape(_DROP_CHARS) + ']', '', text)
    if rebuilt != stripped:
        return None

    # 分区
    zones, zc = [], []
    for c in chunks:
        zc.append(c)
        if _zone_boundary_after(c):
            zones.append(zc)
            zc = []
    if zc:
        zones.append(zc)

    out_zones, gi = [], 0
    for zi, zcs in enumerate(zones):
        idxs = list(range(gi, gi + len(zcs)))
        gi += len(zcs)
        head, mov, tail = [], [], [idxs[-1]]
        locked = False
        # 区尾必须谓语性；末区（主句）不谓语则整句弃掉，从区不谓语则锁区
        if not _is_predicative(zcs[-1]):
            if zi == len(zones) - 1:
                return None
            locked = True
        for j, c in zip(idxs[:-1], zcs[:-1]):
            h = _c_head(c)
            if h['p1'] in ('接続詞', '感動詞') and j == idxs[0]:
                head.append(j)                # 接续词/感叹词固定区头
            elif _is_movable(c):
                mov.append(j)
            else:
                locked = True                 # 出现无法归类的块 → 整区锁死
        if locked:
            head, mov, tail = [], [], idxs    # 锁死区：全部按原序固定
        out_zones.append({'head': head, 'mov': mov, 'tail': tail})

    return {'chunks': [{'surface': _c_surface(c), 'toks': c['toks']} for c in chunks],
            'zones': out_zones, 'punct': punct}


# ================================================================
# 2. 合法语序：计数 / 枚举 / 判卷
# ================================================================
def order_count(zones):
    n = 1
    for z in zones:
        n *= math.factorial(len(z['mov']))
    return n


def iter_orders(zones):
    """按区生成全部合法语序（块下标序列）"""
    per_zone = []
    for z in zones:
        base = []
        for perm in itertools.permutations(z['mov']):
            seq = list(z['head'])
            rest = list(perm)
            # tail 若含多块（锁死区）按原序
            base.append(seq + rest + list(z['tail']))
        per_zone.append(base)
    for combo in itertools.product(*per_zone):
        yield [i for zz in combo for i in zz]


def assemble(chunks, order, punct='', comma_zones=None):
    """按语序拼回整句字符串（供语法质检/展示）"""
    return ''.join(chunks[i]['surface'] for i in order) + (punct or '')


def enumerate_accepted(parsed, perm_limit=120, strict=True):
    """枚举合法语序；strict 时逐一整句语法质检，剔除质检不过的排列。
    组合数超限返回 None（判卷退化为约束模式）。原句语序永远保留。"""
    zones, chunks, punct = parsed['zones'], parsed['chunks'], parsed['punct']
    total = order_count(zones)
    if total > perm_limit:
        return None
    original = list(range(len(chunks)))
    accepted = []
    for order in iter_orders(zones):
        if order == original:
            accepted.append(order)
            continue
        if strict:
            s = assemble(chunks, order, punct or '。')
            try:
                if not grammar.is_sentence_grammatically_sound(s):
                    continue
            except Exception:
                continue
        accepted.append(order)
    if original not in accepted:
        accepted.insert(0, original)
    return accepted


def check_arrangement(spec, order_tile_ids):
    """稳健判卷。spec 为出题时生成的判卷规格：
      {chunks:[surface...], zones, punct, tile_map:{tile_id:chunk_idx|-1},
       accepted:[[idx...]]|None, alt_count}
    返回 {ok, feedback, canonical, canonical_surfaces, alt_count, your_text}"""
    try:
        tile_map = {str(k): int(v) for k, v in (spec.get('tile_map') or {}).items()}
        surfaces = list(spec.get('chunks') or [])
        zones = spec.get('zones') or []
        n = len(surfaces)
        order_tile_ids = [str(t) for t in (order_tile_ids or [])]
    except Exception:
        return {'ok': False, 'feedback': '判卷数据无效', 'alt_count': 0,
                'canonical': [], 'canonical_surfaces': [], 'your_text': ''}

    canonical = list(range(n))
    canonical_surf = [surfaces[i] for i in canonical]
    alt = spec.get('alt_count') or order_count(zones)
    base = {'canonical': canonical, 'canonical_surfaces': canonical_surf,
            'alt_count': alt}

    # 0) 空题面/空作答一律判错（防御脏请求）
    if n == 0 or not order_tile_ids:
        return {'ok': False, 'feedback': '作答为空或题面无效', 'your_text': '', **base}

    # 1) 词块存在性
    unknown = [t for t in order_tile_ids if t not in tile_map]
    if unknown:
        return {'ok': False, 'feedback': '包含未知词块', 'your_text': '', **base}
    # 2) 干扰块
    used_fake = [t for t in order_tile_ids if tile_map[t] == -1]
    if used_fake:
        return {'ok': False, 'feedback': '用到了干扰词块（这些词不属于本句）',
                'your_text': '', **base}
    idx_order = [tile_map[t] for t in order_tile_ids]
    your_text = ''.join(surfaces[i] for i in idx_order if 0 <= i < n) + (spec.get('punct') or '')
    base['your_text'] = your_text
    # 3) 完整性（多用/少用/重复）
    if sorted(idx_order) != list(range(n)):
        missing = [surfaces[i] for i in range(n) if i not in idx_order]
        if missing:
            return {'ok': False,
                    'feedback': '少用了词块：' + '、'.join(missing[:3]), **base}
        return {'ok': False, 'feedback': '词块重复或多余', **base}
    # 4) 白名单判卷（生成时已全排列语法质检）
    accepted = spec.get('accepted')
    if accepted:
        acc = [list(map(int, a)) for a in accepted]
        if idx_order in acc:
            return {'ok': True, 'feedback': '', **base}
        return {'ok': False, 'feedback': _order_feedback(idx_order, zones, surfaces), **base}
    # 5) 约束判卷（组合数过大时）
    ok, fb = _constraint_check(idx_order, zones, surfaces)
    return {'ok': ok, 'feedback': '' if ok else fb, **base}


def _constraint_check(idx_order, zones, surfaces):
    pos = 0
    for z in zones:
        members = set(z['head']) | set(z['mov']) | set(z['tail'])
        seg = idx_order[pos:pos + len(members)]
        if set(seg) != members:
            return False, _order_feedback(idx_order, zones, surfaces)
        k = len(z['head'])
        if seg[:k] != list(z['head']):
            return False, '接续词要放在分句开头'
        t = len(z['tail'])
        if t and seg[len(seg) - t:] != list(z['tail']):
            return False, '谓语部分必须放在分句末尾'
        pos += len(members)
    return True, ''


def _order_feedback(idx_order, zones, surfaces):
    """针对性反馈：谓语位置 / 跨区 / 固定语序"""
    pos = 0
    for zi, z in enumerate(zones):
        members = set(z['head']) | set(z['mov']) | set(z['tail'])
        seg = idx_order[pos:pos + len(members)]
        if set(seg) != members:
            return ('分句成分越过了逗号/接续边界：'
                    '每个分句内部的词块不能移到其他分句里')
        t = len(z['tail'])
        if t and seg[len(seg) - t:] != list(z['tail']):
            tail_surf = surfaces[z['tail'][-1]]
            return f'「{tail_surf}」是谓语部分，必须放在分句末尾'
        k = len(z['head'])
        if k and seg[:k] != list(z['head']):
            return '接续词要放在分句开头'
        pos += len(members)
    return '语序不对：此句这些成分的顺序是固定的'


# ================================================================
# 3. 注音切分（词块 ruby）
# ================================================================
def _tiles_tokens(text, chunks):
    """整句注音一次，按块的字符跨度切给各块；跨度切不开则单块独立注音"""
    try:
        toks = furigana.annotate(text)
    except Exception:
        toks = []
    spans, pos = [], 0
    for c in chunks:
        s = c['surface']
        start = text.find(s, pos)
        if start < 0:
            spans.append(None)
        else:
            spans.append((start, start + len(s)))
            pos = start + len(s)
    # token 跨度
    tk_spans, p = [], 0
    for t in toks:
        tk_spans.append((p, p + len(t['s'])))
        p += len(t['s'])
    out = []
    for c, sp in zip(chunks, spans):
        got = None
        if sp:
            seg = [t for t, (a, b) in zip(toks, tk_spans) if a >= sp[0] and b <= sp[1]]
            if ''.join(t['s'] for t in seg) == c['surface']:
                got = seg
        if got is None:
            try:
                got = furigana.annotate(c['surface'])
            except Exception:
                got = [{'s': c['surface'], 'r': None, 'w': None, 'wr': None}]
        out.append(got)
    return out


# ================================================================
# 4. 语料同位换词（basic 变体题）
# ================================================================
def _pred_key(toks, j):
    """谓语搭配键：サ变结构（発揮した）用「名词+する」做键，
    避免所有「〜をする」互相污染搭配统计；其余用动词词元。"""
    t = toks[j]
    if t['lemma'] == '為る' and j > 0 and toks[j - 1]['p1'] == '名詞' \
            and 'サ変' in toks[j - 1]['p3']:
        return toks[j - 1]['s'] + 'する'
    return t['lemma']


# 过于泛化的动词：任何名词都能搭 → 共现统计无意义，禁止作为换词依据
_GENERIC_PREDS = {'為る', '居る', '有る', '成る', '仕舞う', '行く', '来る'}


@functools.lru_cache(maxsize=256)
def _colloc_nouns(particle, pred_key):
    """语料共现挖掘：与谓语 pred_key 搭配、经 particle 标记的名词分布。
    只信语料里真实出现过的搭配 —— 换词后语义搭配天然成立。"""
    try:
        with db.get_conn() as c:
            rows = c.execute(
                'SELECT text FROM sentences WHERE text LIKE ? '
                'ORDER BY RANDOM() LIMIT 700', (f'%{particle}%',)).fetchall()
    except Exception:
        return ()
    counter = {}
    for r in rows:
        try:
            toks = _tag(r[0] if not hasattr(r, 'keys') else r['text'])
        except Exception:
            continue
        for i, t in enumerate(toks):
            if t['s'] != particle or t['p2'] != '格助詞' or i == 0:
                continue
            prev = toks[i - 1]
            if (prev['p1'] != '名詞' or prev['p2'] != '普通名詞'
                    or prev['p3'] in ('助数詞可能', '副詞可能')):
                continue
            # particle 之后 4 个形态素内找到目标谓语
            for j in range(i + 1, min(i + 5, len(toks))):
                if toks[j]['p1'] == '動詞':
                    if _pred_key(toks, j) == pred_key:
                        counter[prev['s']] = counter.get(prev['s'], 0) + 1
                    break
    return tuple(w for w, _ in sorted(counter.items(), key=lambda kv: -kv[1])[:20])


def _swap_variant(text, parsed):
    """挑一个「名词+格助词」自由块，用语料共现名词替换。
    返回 (new_text, {'from','to','particle'}) 或 None。替换句必须过语法质检。"""
    chunks, zones = parsed['chunks'], parsed['zones']
    mov_idx = [i for z in zones for i in z['mov']]
    random.shuffle(mov_idx)
    for ci in mov_idx:
        toks = chunks[ci]['toks']
        if len(toks) < 2:
            continue
        last = toks[-1]
        if last['p2'] != '格助詞' or last['s'] not in ('を', 'が', 'に', 'で'):
            continue
        noun_toks = toks[:-1]
        if not all(t['p1'] in ('名詞', '接頭辞', '接尾辞') for t in noun_toks):
            continue
        noun = ''.join(t['s'] for t in noun_toks)
        if len(noun) < 1 or noun not in text:
            continue
        # 支配谓语：本块之后第一个含动词的块（泛化动词不做换词依据）
        pred = None
        for cj in range(ci + 1, len(chunks)):
            ctoks = chunks[cj]['toks']
            for j, t in enumerate(ctoks):
                if t['p1'] == '動詞':
                    key = _pred_key(ctoks, j)
                    if key not in _GENERIC_PREDS:
                        pred = key
                    break
            if pred is not None or any(t['p1'] == '動詞' for t in ctoks):
                break
        if not pred:
            continue
        cands = [w for w in _colloc_nouns(last['s'], pred)
                 if w != noun and w not in text and 1 < len(w) <= 6]
        random.shuffle(cands)
        for repl in cands[:5]:
            new_text = text.replace(noun + last['s'], repl + last['s'], 1)
            if new_text == text:
                continue
            try:
                if grammar.is_sentence_grammatically_sound(new_text):
                    return new_text, {'from': noun, 'to': repl, 'particle': last['s']}
            except Exception:
                continue
    return None


# ================================================================
# 5. 干扰块生成（advanced 混淆）
# ================================================================
def _verb_form_variants(chunk):
    """谓语块的时态/礼貌体/极性变形（surface 变换，语义必然偏离译文）"""
    s = chunk['surface']
    out = []
    if s.endswith('ました'):
        out += [s[:-3] + 'ます', s[:-3] + 'ません']
    elif s.endswith('ません'):
        out += [s[:-3] + 'ました', s[:-3] + 'ます']
    elif s.endswith('ます'):
        out += [s[:-2] + 'ました', s[:-2] + 'ません']
    elif s.endswith('でした'):
        out += [s[:-2] + 'す']
    elif s.endswith('です'):
        out += [s[:-2] + 'でした']
    elif s.endswith(('た', 'だ')):
        toks = chunk['toks']
        # 平体タ形 → 辞书形：定位最后一个动词，用 orthBase 重建
        for k in range(len(toks) - 1, -1, -1):
            if toks[k]['p1'] == '動詞':
                prefix = ''.join(t['s'] for t in toks[:k])
                base = toks[k]['ob']
                if base and re.search(r'[うくぐすつぬぶむる]$', base):
                    out.append(prefix + base)
                break
    return [v for v in out if v and v != s]


def _particle_variants(chunk):
    """自由块换助词（禁用意义保持对：は↔が、に↔へ 等绝不生成）"""
    toks = chunk['toks']
    last = toks[-1]
    if last['p2'] != '格助詞' or last['s'] not in _CASE_P:
        return []
    if not all(t['p1'] in ('名詞', '代名詞', '接頭辞', '接尾辞') for t in toks[:-1]):
        return []
    noun = ''.join(t['s'] for t in toks[:-1])
    outs = []
    for alt in ('を', 'に', 'で', 'から', 'まで'):
        if alt == last['s'] or (last['s'], alt) in _EQUIV_PAIRS:
            continue
        outs.append(noun + alt)
    random.shuffle(outs)
    return outs[:2]


def _vocab_distractors(n, exclude_text):
    """语料随机高频实词（不在本句中出现）"""
    out = []
    try:
        with db.get_conn() as c:
            rows = c.execute('SELECT tokens FROM sentences '
                             'ORDER BY RANDOM() LIMIT 30').fetchall()
    except Exception:
        return out
    seen = set()
    for r in rows:
        try:
            toks = json.loads(r[0] if not hasattr(r, 'keys') else r['tokens'])
        except Exception:
            continue
        for t in toks:
            w = t.get('w')
            if (w and w not in seen and w not in exclude_text
                    and 1 < len(w) <= 5 and re.search(r'[一-龥]', w)):
                seen.add(w)
                out.append(w)
        if len(out) >= n * 3:
            break
    random.shuffle(out)
    return out[:n]


def make_distractors(parsed, text, cfg):
    """生成混淆干扰块列表（surface 字符串）。安全保证：
    1. 判卷要求「所需词块恰好全用」，用任一干扰块必错 —— 而干扰块的
       语义均偏离译文（时态/极性变形、句外词、非等价助词），判错公平；
    2. 干扰块 surface 与任何所需块都不同（避免 UI 无法区分）。"""
    kinds = cfg.get('distractor_kinds') or {}
    want = int(cfg.get('distractors', 3))
    if want <= 0:
        return []
    chunks, zones = parsed['chunks'], parsed['zones']
    required = {c['surface'] for c in chunks}
    out = []

    def _push(s):
        if s and s not in required and s not in out and s not in text:
            out.append(s)

    if kinds.get('verb_form', True):
        tail_idx = zones[-1]['tail'][-1] if zones else len(chunks) - 1
        for v in _verb_form_variants(chunks[tail_idx]):
            _push(v)
    if kinds.get('particle', True) and len(out) < want:
        mov = [i for z in zones for i in z['mov']]
        random.shuffle(mov)
        for i in mov:
            for v in _particle_variants(chunks[i]):
                # 换助词后的整句若与原句等价则弃（双保险，理论上等价对已禁）
                _push(v)
            if len(out) >= want:
                break
    if kinds.get('vocab', True) and len(out) < want:
        for v in _vocab_distractors(want - len(out), text + ''.join(out)):
            _push(v)
    random.shuffle(out)
    return out[:want]


# ================================================================
# 6. 选材：按 scope 取句 + 按 level 过滤
# ================================================================
def _sentence_level(text):
    """句子难度 = 句内最高级别语法点（无语法点视为 N5）"""
    try:
        gs = grammar.analyze(text)
    except Exception:
        return 'N5', []
    lv = 'N5'
    for g in gs:
        if LEVEL_ORDER.get(g.get('level'), 0) > LEVEL_ORDER[lv]:
            lv = g['level']
    return lv, gs


def _fetch_pool(scope, book_ids, need):
    rows = []
    ids = [int(b) for b in (book_ids or [])]
    if scope in ('book', 'mixed') and ids:
        ph = ','.join('?' * len(ids))
        try:
            with db.get_conn() as c:
                rows += [dict(r) for r in c.execute(
                    f'SELECT s.id sid, s.text text, s.translation translation, '
                    f's.source source, b.title book_title, l.title lesson_title '
                    f'FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id '
                    f'JOIN books b ON b.id=bs.book_id '
                    f'LEFT JOIN book_lessons l ON l.id=bs.lesson_id '
                    f'WHERE bs.book_id IN ({ph}) ORDER BY RANDOM() LIMIT ?',
                    ids + [need]).fetchall()]
        except Exception:
            pass
    if scope == 'corpus' or scope == 'mixed' or (scope == 'book' and not ids):
        try:
            with db.get_conn() as c:
                rows += [dict(r) for r in c.execute(
                    'SELECT id sid, text text, translation translation, source source '
                    'FROM sentences ORDER BY RANDOM() LIMIT ?', (need,)).fetchall()]
        except Exception:
            pass
    return rows


def _origin(row):
    try:
        import textbook
        return textbook.origin_label(row.get('source'), row.get('book_title'),
                                     row.get('lesson_title'))
    except Exception:
        return row.get('source') or '语料库'


# ================================================================
# 7. 出题主流程
# ================================================================
def _build_arrange(row, cfg, mode, want_level):
    """单句 → 组句题；不合适返回 None"""
    text = (row.get('text') or '').strip()
    if not (6 <= len(text) <= 60):
        return None
    try:
        if not grammar.is_sentence_grammatically_sound(text):
            return None
    except Exception:
        return None
    level, gpoints = _sentence_level(text)
    if want_level and want_level != 'any' and level != want_level:
        return None, level  # 让调用方做放宽二选
    parsed = parse_sentence(text)
    if not parsed:
        return None
    n_chunks = len(parsed['chunks'])
    if not (cfg['min_tiles'] <= n_chunks <= cfg['max_tiles']):
        return None

    swap_info = None
    if (mode == 'basic' and cfg.get('swap', True)
            and random.random() < cfg.get('swap_prob', 0.35)):
        got = _swap_variant(text, parsed)
        if got:
            new_text, swap_info = got
            new_parsed = parse_sentence(new_text)
            # 换词后必须结构等价（块数一致），否则放弃换词
            if new_parsed and len(new_parsed['chunks']) == n_chunks:
                text, parsed = new_text, new_parsed
            else:
                swap_info = None

    accepted = enumerate_accepted(parsed, perm_limit=cfg.get('perm_limit', 120),
                                  strict=cfg.get('strict_check', True))
    alt_count = len(accepted) if accepted is not None else order_count(parsed['zones'])

    chunk_tokens = _tiles_tokens(text, parsed['chunks'])
    tiles, tile_map = [], {}
    for i, (c, tk) in enumerate(zip(parsed['chunks'], chunk_tokens)):
        tid = f't{i}'
        tiles.append({'id': tid, 's': c['surface'], 'tokens': tk})
        tile_map[tid] = i
    if mode == 'advanced':
        for k, ds in enumerate(make_distractors(parsed, text, cfg)):
            tid = f'd{k}'
            try:
                dtk = furigana.annotate(ds)
            except Exception:
                dtk = [{'s': ds, 'r': None, 'w': None, 'wr': None}]
            tiles.append({'id': tid, 's': ds, 'tokens': dtk})
            tile_map[tid] = -1
    random.shuffle(tiles)

    spec = {'chunks': [c['surface'] for c in parsed['chunks']],
            'zones': parsed['zones'], 'punct': parsed['punct'],
            'tile_map': tile_map,
            'accepted': accepted, 'alt_count': alt_count}
    try:
        full_tokens = furigana.annotate(text)
    except Exception:
        full_tokens = []
    gtop = sorted(gpoints, key=lambda g: -LEVEL_ORDER.get(g.get('level'), 0))[:3]
    return {'qtype': 'arrange', 'mode': mode, 'level': level,
            'sid': row.get('sid'), 'text': text, 'punct': parsed['punct'],
            'translation': row.get('translation'),
            'origin': _origin(row), 'source': row.get('source'),
            'swap': swap_info,
            'tiles': tiles, 'n_required': n_chunks,
            'alt_count': alt_count, 'tokens': full_tokens,
            'grammar': [{'name': g.get('name'), 'level': g.get('level'),
                         'explain': g.get('explain') or g.get('meaning') or '',
                         'structure': g.get('structure') or ''} for g in gtop],
            'spec': spec}


def _build_pairs(n_pairs=5):
    """配对题：词形↔读音（来自语料注音 token，读音唯一才入选）"""
    try:
        with db.get_conn() as c:
            rows = [dict(r) for r in c.execute(
                'SELECT tokens FROM sentences ORDER BY RANDOM() LIMIT 40').fetchall()]
    except Exception:
        rows = []
    pool, seen_w, seen_r = [], set(), set()
    for r in rows:
        try:
            toks = json.loads(r.get('tokens') or '[]')
        except Exception:
            continue
        for t in toks:
            w, wr = t.get('w'), t.get('wr')
            if (w and wr and w != wr and w not in seen_w and wr not in seen_r
                    and re.search(r'[一-龥]', w) and 1 < len(w) <= 6):
                seen_w.add(w)
                seen_r.add(wr)
                pool.append({'w': w, 'wr': wr})
    if len(pool) < n_pairs:
        return None
    random.shuffle(pool)
    pairs = pool[:n_pairs]
    return {'qtype': 'pairs', 'pairs': pairs, 'n': len(pairs)}


def make_quiz(book_ids=None, count=None, mode=None, level=None, scope=None):
    """生成一组题。mode / level 可临时覆盖配置（两轴独立）。"""
    cfg = builder_cfg()
    if not cfg.get('enabled', True):
        return {'ok': False, 'reason': '组句练习已在配置中关闭',
                'count': 0, 'questions': []}
    mode = mode if mode in ('basic', 'advanced') else cfg['mode']
    level = level if level in (['any'] + LEVELS) else cfg['level']
    scope = scope if scope in ('corpus', 'book', 'mixed') else cfg['scope']
    try:
        count = max(1, min(int(count), 20)) if count else cfg['count']
    except Exception:
        count = cfg['count']

    t = cfg['types']
    ts = t['arrange'] + t['pairs']
    n_pairs = int(round(count * t['pairs'] / ts)) if ts else 0
    n_arr = count - n_pairs

    rows = _fetch_pool(scope, book_ids, need=min(max(n_arr * 30, 120), 500))
    questions, used_sid = [], set()
    relax_note = False

    for relax in (False, True):
        want = None if relax else level      # 第二遍放宽 level 限制
        for row in rows:
            if len(questions) >= n_arr:
                break
            if row.get('sid') in used_sid:
                continue
            got = _build_arrange(row, cfg, mode, want)
            if isinstance(got, tuple):       # level 不匹配（供放宽重试）
                continue
            if not got:
                continue
            if relax and level != 'any':
                got['level_relaxed'] = True
                relax_note = True
            used_sid.add(row['sid'])
            questions.append(got)
        if len(questions) >= n_arr or level == 'any':
            break

    # 配对题
    made_pairs = 0
    for _ in range(n_pairs):
        q = _build_pairs()
        if not q:
            break
        questions.append(q)
        made_pairs += 1

    random.shuffle(questions)
    for i, q in enumerate(questions):
        q['qid'] = f'q{i}'
    return {'ok': True, 'mode': mode, 'level': level, 'scope': scope,
            'count': len(questions), 'questions': questions,
            'n_arrange': len(questions) - made_pairs, 'n_pairs': made_pairs,
            'level_relaxed': relax_note,
            'short': len(questions) < count}


# ================================================================
# 8. 成绩记录 / 统计
# ================================================================
def record_results(results):
    """记录一组答题结果：按日累计 + 按 题型/模式/级别 细分"""
    results = [r for r in (results or []) if isinstance(r, dict)]
    n_ok = sum(1 for r in results if r.get('ok'))
    today = date.today().isoformat()
    try:
        stats = json.loads(db.get_setting(_STATS_KEY, '') or '{}')
    except Exception:
        stats = {}
    d = stats.setdefault(today, {'asked': 0, 'correct': 0, 'by_type': {},
                                 'by_mode': {}, 'by_level': {}})
    d['asked'] += len(results)
    d['correct'] += n_ok
    for r in results:
        for key, field in (('by_type', 'qtype'), ('by_mode', 'mode'),
                           ('by_level', 'level')):
            v = str(r.get(field) or '?')
            slot = d.setdefault(key, {}).setdefault(v, {'asked': 0, 'correct': 0})
            slot['asked'] += 1
            slot['correct'] += 1 if r.get('ok') else 0
    db.set_setting(_STATS_KEY, json.dumps(stats, ensure_ascii=False))
    db.log('builder', f'组句练习：{n_ok}/{len(results)} 正确')
    return {'ok': True, 'asked': len(results), 'correct': n_ok}


def builder_stats(days=14):
    try:
        stats = json.loads(db.get_setting(_STATS_KEY, '') or '{}')
    except Exception:
        stats = {}
    return [{'day': day, **stats[day]} for day in sorted(stats)[-max(1, int(days)):]]

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
    'scope': 'corpus',          # corpus=全库语料 | book=仅课本 | mixed=课本优先 | lyric=KTV歌词
    'count': 6,                 # 每组题数 (1-20)
    'types': {'arrange': 80, 'pairs': 20},   # 题型占比（自动归一）
    'min_tiles': 3,             # 组句题最少词块数
    'max_tiles': 9,             # 组句题最多词块数
    'distractors': 3,           # advanced 干扰块数 (0-6)
    'distractor_kinds': {'verb_form': True, 'vocab': True, 'particle': True},
    'alt_answers': True,        # advanced 多答案：槽位放可互换名词块（任选其一均判对）
    'alt_max': 2,               # 每题最多追加的可互换名词数 (1-4)
    'alt_min_freq': 1,          # 可互换名词的语料共现次数下限
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
    if cfg.get('scope') not in ('corpus', 'book', 'mixed', 'lyric'):
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
    cfg['alt_answers'] = bool(cfg.get('alt_answers', True))
    try:
        cfg['alt_max'] = max(1, min(int(cfg.get('alt_max', 2)), 4))
    except Exception:
        cfg['alt_max'] = 2
    try:
        cfg['alt_min_freq'] = max(1, min(int(cfg.get('alt_min_freq', 1)), 5))
    except Exception:
        cfg['alt_min_freq'] = 1
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
    # 2) 干扰块（指名道姓 + 保留用户拼出的句子，反馈可核查）
    tsurf = {str(k): v for k, v in (spec.get('tile_surface') or {}).items()}
    used_fake = [t for t in order_tile_ids if tile_map[t] == -1]
    if used_fake:
        fakes = [s for s in (tsurf.get(t, '') for t in used_fake) if s]
        your_text = ''.join(tsurf.get(t, surfaces[tile_map[t]]
                                      if 0 <= tile_map[t] < n else '')
                            for t in order_tile_ids) + (spec.get('punct') or '')
        return {'ok': False,
                'feedback': '用到了干扰词块' +
                            ('：' + '、'.join(fakes[:3]) if fakes else '') +
                            '（这些词不属于本句）',
                'your_text': your_text, **base}
    idx_order = [tile_map[t] for t in order_tile_ids]
    # 拼出用户句子：优先用词块自身表面（可互换名词块与槽位原块表面不同）
    your_text = ''.join(tsurf.get(t, surfaces[tile_map[t]] if 0 <= tile_map[t] < n else '')
                        for t in order_tile_ids) + (spec.get('punct') or '')
    base['your_text'] = your_text
    # 3) 完整性（多用/少用/重复；可互换块映射同一槽位 → 天然支持多答案）
    if sorted(idx_order) != list(range(n)):
        dup = sorted({i for i in idx_order if idx_order.count(i) > 1})
        if dup and spec.get('has_groups'):
            return {'ok': False,
                    'feedback': '同一槽位的可互换词块只能选用一个', **base}
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

# 形式名词/轻名词（こと/もの/ところ…）：不是实义搭配词，
# 挖掘左扩绝不吸收、候选词绝不采用
_FORMAL_NOUNS = {'事', '物', '所', '為', '筈', '訳', '方', '風', '積もり', '儘', '内', '中'}


def _noun_candidate_ok(w):
    """换词/多答案候选词终审：纯实义名词（可含复合），无数字、
    无形式名词头、无助数词，且整词可完整分词为名词序列。"""
    if not w or not (1 < len(w) <= 6) or re.search(r'[0-9０-９〇一二三四五六七八九十]', w[:1]):
        return False
    try:
        toks = _tag(w)
    except Exception:
        return False
    if not toks or not all(t['p1'] in ('名詞', '接頭辞', '接尾辞') for t in toks):
        return False
    for t in toks:
        if t['lemma'] in _FORMAL_NOUNS or t['p3'] in ('助数詞可能',):
            return False
    return True


@functools.lru_cache(maxsize=256)
def _colloc_nouns(particle, pred_key):
    """语料共现挖掘：与谓语 pred_key 搭配、经 particle 标记的名词分布。
    返回 ((名词, 出现次数), ...) 按频次降序。只信语料里真实出现过的搭配 ——
    「语料是语义预言机」：算法不懂句义，但语料中出现过 = 有人写过 = 搭配成立。"""
    try:
        with db.get_conn() as c:
            rows = c.execute(
                'SELECT text FROM sentences WHERE text LIKE ? '
                'ORDER BY RANDOM() LIMIT 1000', (f'%{particle}%',)).fetchall()
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
            # 左扩收取完整复合名词（注意事項→注意事項，绝不截半个复合词）；
            # 形式名词（こと/もの…）/助数词/时间词是独立文节成分，绝不吸收
            j0 = i - 1
            while (j0 - 1 >= 0 and toks[j0 - 1]['p1'] in ('名詞', '接頭辞')
                   and toks[j0 - 1]['p3'] not in ('助数詞可能', '副詞可能')
                   and toks[j0 - 1]['lemma'] not in _FORMAL_NOUNS
                   and toks[j0 - 1]['p2'] in ('普通名詞', '固有名詞', '')):
                j0 -= 1
            noun_surf = ''.join(x['s'] for x in toks[j0:i])
            if not (1 <= len(noun_surf) <= 8):
                continue
            # particle 之后 4 个形态素内找到目标谓语
            for j in range(i + 1, min(i + 5, len(toks))):
                if toks[j]['p1'] == '動詞':
                    if _pred_key(toks, j) == pred_key:
                        counter[noun_surf] = counter.get(noun_surf, 0) + 1
                    break
    return tuple(sorted(counter.items(), key=lambda kv: -kv[1])[:20])


SWAP_PARTICLES = ('を', 'が', 'で')
# 换词/多答案槽位只认选择限制强的格：を(宾语)/が(主语)/で(场所·手段)。
# に 格语义角色过宽（方向/目标/场所/时间/惯用），共现证据容易跨语境
# 误配（「文頭に持ってくる」≠「手もとに持っている」），一律不做换词槽位。

OBLIQUE_PARTICLES = ('に', 'へ', 'と', 'から', 'まで')
# 语义收窄闸门：句中若存在「名词+斜格助词」成分（塀に/駅へ/友達と…），
# 该斜格会收窄谓语义项（「塀に掛ける」＝搭靠 ≠「電話を掛ける」＝拨打），
# 跨语境共现证据可能错配 —— 整句禁用换词/多答案槽位（宁可少出，绝不出错）。


def _has_oblique(chunks):
    for c in chunks:
        toks = c['toks']
        if (len(toks) >= 2 and toks[-1]['p2'] == '格助詞'
                and toks[-1]['s'] in OBLIQUE_PARTICLES
                and all(t['p1'] in ('名詞', '代名詞', '接頭辞', '接尾辞')
                        for t in toks[:-1])):
            return True
    return False


def _case_slots(parsed, text):
    """枚举可换词槽位：「名词+格助词(を/が/で)」块且能定位支配谓语。
    槽位不必是自由块 —— 换词只改名词表面、不影响语序判卷，
    锁死区内的名词块同样可换。返回 [(ci, noun, particle, pred_key), ...]。"""
    chunks, zones = parsed['chunks'], parsed['zones']
    if _has_oblique(chunks):
        return []                      # 语义收窄闸门：斜格在场，整句不换词
    mov_idx = list(range(len(chunks)))
    random.shuffle(mov_idx)
    out = []
    for ci in mov_idx:
        toks = chunks[ci]['toks']
        if len(toks) < 2:
            continue
        last = toks[-1]
        if last['p2'] != '格助詞' or last['s'] not in SWAP_PARTICLES:
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
        if pred:
            out.append((ci, noun, last['s'], pred))
    return out


def _vet_substitution(text, parsed, noun, particle, repl):
    """换词双保险：整句语法质检 + 换词后结构等价（块数不变）。
    返回替换后的整句或 None。"""
    new_text = text.replace(noun + particle, repl + particle, 1)
    if new_text == text:
        return None
    try:
        if not grammar.is_sentence_grammatically_sound(new_text):
            return None
    except Exception:
        return None
    np_ = parse_sentence(new_text)
    if not np_ or len(np_['chunks']) != len(parsed['chunks']):
        return None
    return new_text


def _swap_variant(text, parsed):
    """初级变体：挑一个「名词+格助词」自由块，用语料共现名词替换。
    返回 (new_text, {'from','to','particle'}) 或 None。替换句必须过语法质检。"""
    for ci, noun, particle, pred in _case_slots(parsed, text):
        cands = [w for w, _n in _colloc_nouns(particle, pred)
                 if w != noun and w not in text and _noun_candidate_ok(w)]
        random.shuffle(cands)
        for repl in cands[:5]:
            new_text = _vet_substitution(text, parsed, noun, particle, repl)
            if new_text:
                return new_text, {'from': noun, 'to': repl, 'particle': particle}
    return None


def _alt_group(text, parsed, cfg):
    """高级多答案：为一个槽位挖掘可互换名词（语料实证 + 语法质检 + 结构等价）。
    任选其一均判对 —— 判卷只看槽位是否恰好被填一次，与选词无关。
    返回 {'ci', 'noun', 'particle', 'alts': [...]} 或 None。"""
    max_alts = max(1, min(int(cfg.get('alt_max', 2) or 2), 4))
    min_freq = max(1, int(cfg.get('alt_min_freq', 1) or 1))
    for ci, noun, particle, pred in _case_slots(parsed, text):
        pool = [(w, n) for w, n in _colloc_nouns(particle, pred)
                if w != noun and w not in text and n >= min_freq
                and _noun_candidate_ok(w)]
        random.shuffle(pool)
        alts = []
        for repl, _n in pool:
            if _vet_substitution(text, parsed, noun, particle, repl):
                alts.append(repl)
            if len(alts) >= max_alts:
                break
        if alts:
            return {'ci': ci, 'noun': noun, 'particle': particle, 'alts': alts}
    return None


def _attested_words(parsed, text):
    """本句各槽位的语料实证搭配词全集 —— 句外词干扰块绝不允许命中该集合
    （否则该词其实能合法替入某槽位，判错会不公平）。"""
    out = set()
    for _ci, _noun, particle, pred in _case_slots(parsed, text):
        out |= {w for w, _n in _colloc_nouns(particle, pred)}
    return out


# ================================================================
# 5. 干扰块生成（advanced 混淆）
# ================================================================
# 可自由插入句中的词类：插入后句子通常依然合法、语义与译文不冲突，
# 拿来当干扰块会冤枉正确的日语（如否定句 + 「全然」）。
# 形状詞也整类拦截：其中「大変/結構」等有副词用法（大変＋形容词＝とても），
# 与「好き/静か」等无法靠词性细分 —— 宁可过严弃用候选，绝不冒冤案风险。
_INSERTABLE_P1 = {'副詞', '接続詞', '感動詞', '連体詞', '形状詞', '助詞', '助動詞'}


def _freely_insertable(w):
    """判断词 w 是否属于「可自由插入」词类（副词/接续词/連体詞/副詞可能名词等）。

    这类词是状语性修饰成分，几乎可以插进任何句子的区边界而不破坏语法，
    且语义增量往往与译文兼容（全然→加强否定、今日→补时间、決して→加强禁止），
    译文这个「语义预言机」钉不死它们 —— 一律不得做句外词干扰块。
    注意 UniDic 的「副詞可能」标在 pos2 或 pos3（今日/結局/絶対/全部…），两层都查。
    解析失败时按可插入处理（宁可弃用候选，绝不冒判错冤案的风险）。"""
    try:
        toks = _tag(w)
    except Exception:
        return True
    if not toks:
        return True
    for t in toks:
        if t['p1'] in _INSERTABLE_P1:
            return True
        if t['p1'] == '名詞' and ('副詞可能' in (t['p2'], t['p3'])
                                  or '数詞' in (t['p2'], t['p3'])):
            return True
    return False


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
        # 平体タ形 → 辞书形。判据必须用 token 层：句尾须是过去助动词
        # （lemma='た'，浊音便「だ」也归并到它）且直接前驱是动词 ——
        # 名词谓语的断定「だ」（lemma='だ'，如「仕事だ」）绝不能误入此分支，
        # 否则会从块中间拽出动词拼成病态残缺块（わくわくさせる仕事だ→わくわくする）。
        if (len(toks) >= 2 and toks[-1]['p1'] == '助動詞'
                and toks[-1]['lemma'] == 'た' and toks[-2]['p1'] == '動詞'):
            prefix = ''.join(t['s'] for t in toks[:-2])
            base = toks[-2]['ob']
            if base and re.search(r'[うくぐすつぬぶむる]$', base):
                out.append(prefix + base)
    return [v for v in out if v and v != s]


# 移动/离脱动词：格助词兼容性极强（家を出る＝家から出る、電車を降りる＝
# 電車から降りる、駅に行く＝駅まで行く…），换助词后往往仍是合法等义句，
# 而语料实证反查覆盖有限（语料没有 ≠ 搭配不成立）—— 这类谓语一律放弃换助词干扰。
_MOTION_PREDS = {'出る', '飛び出す', '飛び出る', '出かける', '出発する', '帰る',
                 '戻る', '向かう', '着く', '到着する', '移る', '移動する',
                 '逃げる', '逃げ出す', '離れる', '渡る', '通る', '通う', '進む',
                 '登る', '上る', '下る', '降りる', '走る', '歩く', '泳ぐ', '飛ぶ',
                 '引っ越す', '旅立つ', '抜ける', '抜け出す', '去る', '発つ',
                 '駆ける', '駆け出す', '卒業する', '出場する', '退く'}


def _chunk_pred_key(parsed, ci):
    """定位名词块 ci 的支配谓语键（换助词干扰的实证反查用）。

    返回 None 表示「不可依赖」：谓语是泛化动词（行く/来る/する…与多数
    「名词+助词」都能合法搭配）或移动/离脱动词（を↔から↔まで 常等义），
    或后续找不到动词谓语 —— 调用方应放弃该块的换助词干扰，宁缺毋滥。"""
    chunks = parsed['chunks']
    for cj in range(ci + 1, len(chunks)):
        ctoks = chunks[cj]['toks']
        for j, t in enumerate(ctoks):
            if t['p1'] == '動詞':
                key = _pred_key(ctoks, j)
                # lemma 与 orthBase 双查：UniDic 会把异表记归并到同一 lemma
                # （降りる→下りる），只查一层会漏拦移动动词
                forms = {key, t['lemma'], t['ob']}
                if forms & _GENERIC_PREDS or forms & _MOTION_PREDS:
                    return None
                return key
    return None


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
    """语料随机高频实词（不在本句中出现）。

    公平性关键过滤 —— 「可自由插入」的词类一律不得做句外词干扰块：
    副词（全然/決して/突然…）、副詞可能名词（今日/絶対/結局…）、接続詞、
    連体詞等插进句子后往往**依然语法成立、语义与译文不冲突**
    （典型冤案：否定句里插「全然」只是加强否定，与译文完全兼容却被判错）。
    只保留裸插必然破坏语法或明显偏离译文语义的实词（普通名词/动词/形容词）。"""
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
                    and 1 < len(w) <= 5 and re.search(r'[一-龥]', w)
                    and not _freely_insertable(w)):
                seen.add(w)
                out.append(w)
        if len(out) >= n * 3:
            break
    random.shuffle(out)
    return out[:n]


def make_distractors(parsed, text, cfg, extra_exclude=()):
    """生成混淆干扰块列表（surface 字符串）。

    公平性铁律（调用方保证）：只有**有人工译文**的句子才会调用本函数 ——
    译文是语义预言机，钉死了唯一正确语义；干扰块三类的语义均偏离译文：
      verb_form  时态/礼貌体/极性变形 —— 与译文时态/极性必然不符；
      particle   非等价换助词 —— 意义保持对（は↔が、に↔へ…）已在源头禁用；
      vocab      句外词 —— 双重防线：①**词类防线**：副词/副詞可能名词/
                 接続詞/連体詞等「可自由插入」词类一律不选（插入后句子仍
                 合法且语义与译文兼容，如否定句+「全然」，判错是冤案）；
                 ②**语料实证反查**：凡是与本句任一槽位（同助词+同谓语）
                 在语料中真实共现过的词一律不做干扰块，
                 因为它其实能合法替入槽位（多答案领域），判错会不公平。
    结构性保证：判卷要求所需词块恰好全用，用任一干扰块必错；
    干扰块 surface 与所需块/可互换块均不同、不是句内子串。"""
    kinds = cfg.get('distractor_kinds') or {}
    want = int(cfg.get('distractors', 3))
    if want <= 0:
        return []
    chunks, zones = parsed['chunks'], parsed['zones']
    required = {c['surface'] for c in chunks} | set(extra_exclude)
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
            variants = _particle_variants(chunks[i])
            if not variants:
                continue
            # 公平性防线：支配谓语泛化（駅に/から/まで行く 均合法）或无法定位
            # → 换任何助词都可能拼出合法句，整块放弃换助词干扰，宁缺毋滥
            pred = _chunk_pred_key(parsed, i)
            if pred is None:
                continue
            noun = ''.join(t['s'] for t in chunks[i]['toks'][:-1])
            for v in variants:
                alt = v[len(noun):]
                # 语料实证反查：「名词+新助词」与本句谓语真实共现过
                # （如 家から+飛び出す）→ 换后其实是合法搭配，判错不公平，弃用
                if noun and alt and any(w == noun for w, _n in _colloc_nouns(alt, pred)):
                    continue
                _push(v)
            if len(out) >= want:
                break
    if kinds.get('vocab', True) and len(out) < want:
        attested = _attested_words(parsed, text)   # 语料实证反查：可替入词禁用
        for v in _vocab_distractors(want - len(out), text + ''.join(out)):
            if v in attested or _freely_insertable(v):   # 双保险：可插入词绝不放行
                continue
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


def _fetch_pool(scope, ids, need):
    """按（已解析好的）scope + book id 列表取候选句子池。

    注意：scope/ids 必须先经过 textbook.resolve_book_scope() 解析——本函数不再
    自己判断“book_ids 为空就悄悄改用全库语料”，避免题源被静默替换却不回报真实
    scope 的问题（v20 修复：见 make_quiz 与 QUESTION_SOURCE_POLICY.md）。
    """
    import textbook
    rows = []
    if scope in ('book', 'mixed') and ids:
        rows += textbook.fetch_book_sentence_rows(ids, need)
    if scope == 'lyric':
        rows += _lyric_pool(need)
    if scope == 'corpus' or scope == 'mixed':
        try:
            with db.get_conn() as c:
                rows += [dict(r) for r in c.execute(
                    'SELECT id sid, text text, translation translation, source source '
                    'FROM sentences ORDER BY RANDOM() LIMIT ?', (need,)).fetchall()]
        except Exception:
            pass
    return rows


_LYRIC_KANA_RE = re.compile(r'[ぁ-ゖ]')
_LYRIC_LATIN_RE = re.compile(r'[A-Za-z]')


def _lyric_pool(need):
    """v20 歌词语料域：KTV 歌曲的日文行 → 组句题源。

    公平性自动成立：歌词行没有人工译文 → advanced 也零干扰（铁律兜底），
    只考语序与多答案；语法门禁照常把关（歌词碎片行会被自然过滤）。
    sid 置 None（歌词行不在 sentences 表，前端不显示收藏按钮），
    去重用独立键 dedup，不与语料句混淆。
    """
    rows, seen = [], set()
    try:
        with db.get_conn() as c:
            songs = c.execute('SELECT id, title, lyrics FROM songs').fetchall()
    except Exception:
        return rows
    for s_ in songs:
        for i, ln in enumerate((s_['lyrics'] or '').split('\n')):
            t = ln.strip()
            if (not t or not (6 <= len(t) <= 60)
                    or not _LYRIC_KANA_RE.search(t)
                    or _LYRIC_LATIN_RE.search(t)
                    or t in seen):
                continue
            seen.add(t)
            rows.append({'sid': None, 'dedup': f'L{s_["id"]}:{i}',
                         'text': t, 'translation': None, 'source': 'lyric',
                         'song_title': s_['title'], 'artist': ''})
    random.shuffle(rows)
    return rows[:need]


def _origin(row):
    if row.get('source') == 'lyric':
        return f"🎵 《{row.get('song_title') or '歌词'}》"
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
    has_translation = bool((row.get('translation') or '').strip())

    chunk_tokens = _tiles_tokens(text, parsed['chunks'])
    tiles, tile_map, tile_surface = [], {}, {}
    for i, (c, tk) in enumerate(zip(parsed['chunks'], chunk_tokens)):
        tid = f't{i}'
        tiles.append({'id': tid, 's': c['surface'], 'tokens': tk})
        tile_map[tid] = i
        tile_surface[tid] = c['surface']

    # 高级多答案：一个槽位放入可互换名词块（语料实证 + 语法质检），任选其一均判对
    group_info = None
    if mode == 'advanced' and cfg.get('alt_answers', True):
        ag = _alt_group(text, parsed, cfg)
        if ag:
            group_info = {'slot': parsed['chunks'][ag['ci']]['surface'],
                          'options': [ag['noun']] + ag['alts'],
                          'particle': ag['particle']}
            for k, alt in enumerate(ag['alts']):
                surf = alt + ag['particle']
                tid = f'a{k}'
                try:
                    atk = furigana.annotate(surf)
                except Exception:
                    atk = [{'s': surf, 'r': None, 'w': None, 'wr': None}]
                tiles.append({'id': tid, 's': surf, 'tokens': atk})
                tile_map[tid] = ag['ci']          # 与原块映射同一槽位
                tile_surface[tid] = surf

    # 干扰块公平性铁律：只有存在人工译文（语义预言机）的句子才放混淆项；
    # 无译文时题面要求「语法正确即可」，任何语法上可行的块都不该被判错。
    if mode == 'advanced' and has_translation:
        exclude = set(tile_surface.values())
        for k, ds in enumerate(make_distractors(parsed, text, cfg,
                                                extra_exclude=exclude)):
            tid = f'd{k}'
            try:
                dtk = furigana.annotate(ds)
            except Exception:
                dtk = [{'s': ds, 'r': None, 'w': None, 'wr': None}]
            tiles.append({'id': tid, 's': ds, 'tokens': dtk})
            tile_map[tid] = -1
            tile_surface[tid] = ds
    random.shuffle(tiles)

    spec = {'chunks': [c['surface'] for c in parsed['chunks']],
            'zones': parsed['zones'], 'punct': parsed['punct'],
            'tile_map': tile_map, 'tile_surface': tile_surface,
            'has_groups': bool(group_info),
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
            'swap': swap_info, 'alt_group': group_info,
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
    scope = scope if scope in ('corpus', 'book', 'mixed', 'lyric') else cfg['scope']
    try:
        count = max(1, min(int(count), 20)) if count else cfg['count']
    except Exception:
        count = cfg['count']

    t = cfg['types']
    ts = t['arrange'] + t['pairs']
    n_pairs = int(round(count * t['pairs'] / ts)) if ts else 0
    n_arr = count - n_pairs

    import textbook
    resolved = textbook.resolve_book_scope(scope, book_ids)
    scope, resolved_ids = resolved['scope'], resolved['ids']
    rows = _fetch_pool(scope, resolved_ids, need=min(max(n_arr * 30, 120), 500))
    questions, used_sid = [], set()
    relax_note = False

    for relax in (False, True):
        want = None if relax else level      # 第二遍放宽 level 限制
        for row in rows:
            if len(questions) >= n_arr:
                break
            if (row.get('sid') or row.get('dedup')) in used_sid:
                continue
            got = _build_arrange(row, cfg, mode, want)
            if isinstance(got, tuple):       # level 不匹配（供放宽重试）
                continue
            if not got:
                continue
            if relax and level != 'any':
                got['level_relaxed'] = True
                relax_note = True
            used_sid.add(row.get('sid') or row.get('dedup'))
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
            'book_ids': resolved_ids, 'scope_auto_all': resolved['auto_all'],
            'scope_note': resolved['note'],
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

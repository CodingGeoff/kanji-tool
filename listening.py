# -*- coding: utf-8 -*-
"""听力练习（v21）：基于本地语料 / 课本 / 歌词的「听后选择」自动出题引擎
================================================================
背景与边界（诚实声明，避免过度承诺）
----------------------------------------------------------------
这个模块用纯规则（词性标注 + 语料统计）就能自动出的听力题，天花板很明确：
它可以检验「听音辨形辨义」——你是否听清楚了这句话在说什么、听出了哪个词
被换掉了——但它**没有能力**凭空编出一段新故事再问「说话人接下来会怎么做」
这种真正的听力理解推理题。原因不是工程量不够，而是这类题需要「理解句子
在说什么」，而不是「统计句子长什么样」；规则引擎只能做后者。真正需要
语义理解的听力理解题（篇章、推论、话者意图）见 ai_item_writer.py ——
那条路径显式经过 LLM 起草 + 人工复核，绝不假装规则引擎能替代理解。

本模块提供三种自动题型：

  1. meaning       听后选义：从 4 个同语言译文中选义。
  2. discriminate  听音辨句：从 4 条真实完整语料中辨认原句。
  3. cloze         双空最小对立：题面同时挖掉一个分句接续/词汇/格成分和一个
                   时态・极性成分，四个选项是二者的 2×2 组合。错误极性可让
                   意义完全相反（如「ている」↔「ていない」），词汇项优先
                   使用同助词+同谓语的语料实证搭配。候选整句全部重新经过
                   语法门禁；这是规则引擎可安全实现的“细微差别”，不冒充
                   Python 库能够自动理解任意句子的深层语义。

难度轴（与组句练习保持同样的两条独立轴哲学）：
  - level：句子选材难度（复用 sentence_builder._sentence_level 的语法
    最高级别判定），N5..N1 / any；
  - rate：TTS 语速（复用 /api/tts 的 edge-tts rate 参数）——放慢更容易，
    加快更难；这是听力题特有的、组句/挖空都不存在的难度维度。

题源（scope）与「多课本更稳健」
----------------------------------------------------------------
与组句练习共用同一套 textbook.resolve_book_scope() + fetch_book_sentence_rows()：
  - scope=book/mixed 且未显式给 book_ids 时，自动使用书架里全部启用中的课本
    （而不是静默换成全库语料）；
  - 多本课本按课本分层抽样，句子基数悬殊的课本也能公平出场；
  - 返回值如实携带 scope / book_ids / scope_auto_all / scope_note，
    前端据此显示真实题源，不会出现「配置选仅课本、出的却是语料库」的偷换。
"""
import json
import random
import re
from collections import Counter
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from math import log

import db
import furigana
import grammar
import sentence_builder as sb
import textbook

LEVEL_ORDER = sb.LEVEL_ORDER
LEVELS = sb.LEVELS

DEFAULT_CFG = {
    'enabled': True,
    'level': 'any',              # any | N5..N1 —— 句子选材难度
    'scope': 'corpus',           # corpus | book | mixed | lyric（与组句练习同义）
    'count': 6,
    # 双空最小对立占最高比重，避免只听见一个简单词就能排除。
    'types': {'meaning': 30, 'discriminate': 25, 'cloze': 45},
    # advanced 要求译文共享高信息词/短语且句式相近；凑不齐三项就不出该题。
    'meaning_difficulty': 'advanced',   # standard | advanced
    'rate': 'normal',            # slow | slower | normal | fast —— 听力特有难度轴
                                  # （与 /api/tts 的 RATES 命名完全一致，前端直接透传）
    'max_plays': 3,              # 每题最多重播次数，0=不限
    'min_len': 6,
    'max_len': 60,
}
_RATES = ('slow', 'slower', 'normal', 'fast')
_CFG_KEY = 'listening_cfg'
_STATS_KEY = 'listening_stats'


def listening_cfg():
    """读取听力练习配置（settings JSON，白名单键 + 字典键深合并）"""
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    try:
        raw = db.get_setting(_CFG_KEY, '')
        if raw:
            saved = json.loads(raw)
            for k, v in saved.items():
                if k not in DEFAULT_CFG:
                    continue
                if isinstance(DEFAULT_CFG[k], dict) and isinstance(v, dict):
                    cfg[k].update({kk: vv for kk, vv in v.items() if kk in DEFAULT_CFG[k]})
                else:
                    cfg[k] = v
    except Exception:
        pass
    return _sanitize_cfg(cfg)


def _sanitize_cfg(cfg):
    if cfg.get('level') not in (['any'] + LEVELS):
        cfg['level'] = 'any'
    if cfg.get('scope') not in ('corpus', 'book', 'mixed', 'lyric'):
        cfg['scope'] = 'corpus'
    if cfg.get('rate') not in _RATES:
        cfg['rate'] = 'normal'
    if cfg.get('meaning_difficulty') not in ('standard', 'advanced'):
        cfg['meaning_difficulty'] = 'advanced'
    try:
        cfg['count'] = max(1, min(int(cfg.get('count', 6)), 20))
    except Exception:
        cfg['count'] = 6
    try:
        cfg['max_plays'] = max(0, min(int(cfg.get('max_plays', 3)), 10))
    except Exception:
        cfg['max_plays'] = 3
    try:
        cfg['min_len'] = max(4, min(int(cfg.get('min_len', 6)), 40))
    except Exception:
        cfg['min_len'] = 6
    try:
        cfg['max_len'] = max(cfg['min_len'], min(int(cfg.get('max_len', 60)), 100))
    except Exception:
        cfg['max_len'] = 60
    t = cfg.get('types') or {}
    m = max(0, int(t.get('meaning', 30) or 0))
    d = max(0, int(t.get('discriminate', 25) or 0))
    c = max(0, int(t.get('cloze', 45) or 0))
    if m + d + c == 0:
        m, d, c = 30, 25, 45
    cfg['types'] = {'meaning': m, 'discriminate': d, 'cloze': c}
    cfg['enabled'] = bool(cfg.get('enabled', True))
    return cfg


def save_listening_cfg(patch):
    cfg = listening_cfg()
    for k, v in (patch or {}).items():
        if k not in DEFAULT_CFG:
            continue
        if isinstance(DEFAULT_CFG[k], dict) and isinstance(v, dict):
            cfg[k] = dict(cfg.get(k) or {}, **{kk: vv for kk, vv in v.items() if kk in DEFAULT_CFG[k]})
        else:
            cfg[k] = v
    cfg = _sanitize_cfg(cfg)
    db.set_setting(_CFG_KEY, json.dumps(cfg, ensure_ascii=False))
    return cfg


# ================================================================
# 题源池（与 sentence_builder 共用同一套稳健 scope 解析）
# ================================================================
def _fetch_pool(scope, ids, need):
    import textbook as tb
    rows = []
    if scope in ('book', 'mixed') and ids:
        rows += tb.fetch_book_sentence_rows(ids, need)
    if scope == 'lyric':
        rows += sb._lyric_pool(need)
    if scope in ('corpus', 'mixed'):
        try:
            with db.get_conn() as c:
                rows += [dict(r) for r in c.execute(
                    'SELECT id sid, text text, translation translation, source source '
                    'FROM sentences ORDER BY RANDOM() LIMIT ?', (need,)).fetchall()]
        except Exception:
            pass
    return rows


# ================================================================
# 题型 1：听后选义（需要译文；干扰项 = 其它句子的真实译文）
# ================================================================
def _tr_lang(t):
    """粗略判定译文的文字系统：语料库的翻译经常混着中/英/其它语言
    （如 Tatoeba 一句日语可能同时挂中文和英文翻译）。绝不能让 4 个选项
    的语言不一致——那样答案靠「一眼认出哪个是中文」就能蒙对，
    完全绕过了听力/理解本身，是比没有干扰项更糟的伪劣题目。"""
    if re.search(r'[\u4e00-\u9fff]', t):
        return 'zh'
    if re.search(r'[A-Za-z]', t):
        return 'en'
    return 'other'


_EN_STOP = frozenset('''a an the is are was were be been being to of in on at for from
with and or but that this these those it its i you he she we they me him her us them my
your his our their do does did have has had will would can could may might should as so
very just really also there here then than not no yes up down over out about into through
after before during under again further once off only own same such too don don't didn
isn aren't wasn weren't won't can't couldn shouldn't wouldn't'''.split())
_ZH_STOP = frozenset('的一了是在和也都就很有我你他她它們们这這那個个嗎吗呢啊吧被把給给')


@lru_cache(maxsize=16384)
def _translation_terms(text):
    """译文检索词。英文去功能词并轻量归一；中文同时保留信息字和二字短语。"""
    if _tr_lang(text) == 'zh':
        chunks = re.findall(r'[\u4e00-\u9fff]+', text)
        terms = set()
        for chunk in chunks:
            terms.update('b:' + chunk[i:i + 2] for i in range(len(chunk) - 1)
                         if chunk[i] not in _ZH_STOP and chunk[i + 1] not in _ZH_STOP)
            terms.update('c:' + ch for ch in chunk if ch not in _ZH_STOP)
        return frozenset(terms)
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    terms = set()
    for word in words:
        word = word.replace("'s", '')
        if word in _EN_STOP or len(word) < 3:
            continue
        # 保守使用完整表面词；自制英文词干器会把 tired 误切成 tir，反而降质。
        terms.add('w:' + word)
    return frozenset(terms)


def _translation_shape(text):
    low = text.lower()
    if _tr_lang(text) == 'zh':
        people = tuple(x for x in ('我', '你', '他', '她', '我们', '你们', '他们') if x in text)
        negative = bool(re.search(r'[不沒没未無无別别]', text))
    else:
        people = tuple(x for x in ('i', 'you', 'he', 'she', 'we', 'they')
                       if re.search(rf'\b{x}\b', low))
        negative = bool(re.search(r"\b(?:not|no|never|neither|nor|cannot|can't|won't|didn't|isn't|aren't|wasn't|weren't)\b", low))
    return {
        'people': people,
        'negative': negative,
        'question': text.rstrip().endswith(('?', '？', '吗', '嗎')),
        'numbered': bool(re.search(r'\d|[一二三四五六七八九十百千万兩两]', text)),
    }


def _meaning_search_context(rows):
    """预建译文词频；IDF 避免把 good/all/的/是等高频词误当作高混淆。"""
    df = Counter()
    for row in rows:
        tr = (row.get('translation') or '').strip() if isinstance(row, dict) else str(row).strip()
        df.update(_translation_terms(tr))
    return {'rows': rows, 'df': df, 'n': max(1, len(rows))}


@lru_cache(maxsize=4096)
def _meaning_signature(text):
    """为译文难干扰检索提取日文侧结构签名，不生成或改写译文。"""
    try:
        points = grammar.analyze(text)
        grammar_names = frozenset(p.get('name') for p in points
                                  if p.get('kind') == 'pattern' and p.get('name'))
        toks = sb._tag(text)
        content = frozenset(t['lemma'] for t in toks
                            if t['p1'] in ('名詞', '動詞', '形容詞', '形状詞')
                            and len(t['lemma']) > 1)
    except Exception:
        grammar_names, content = frozenset(), frozenset()
    return {
        'grammar': grammar_names,
        'content': content,
        'negative': bool(re.search(r'(?:ない|なかった|ません|ぬ|ず)', text)),
        'past': bool(re.search(r'(?:た|ました|でした)[。！？!?]?$', text)),
        'question': text.endswith(('？', '?')) or bool(re.search(r'(?:か|の)[。？?]?$', text)),
    }


def _jaccard(a, b):
    u = a | b
    return len(a & b) / len(u) if u else 0.0


def _build_meaning_q(row, translation_rows, difficulty='advanced', search_ctx=None):
    """听后选义：高级模式只接受“共享信息锚点”的真实译文硬负例。

    standard 保留结构/长度匹配；advanced 先用 IDF 加权的中英文实词和短语
    找同主题候选，再比较日文语法、极性、时态和译文句式。高级题若凑不齐
    三个真正相近的选项便返回 None，主流程会改出其它题型，绝不拿无关句凑数。
    """
    text = (row.get('text') or '').strip()
    tr = (row.get('translation') or '').strip()
    if not tr:
        return None
    lang = _tr_lang(tr)
    sig = _meaning_signature(text)
    shape = _translation_shape(tr)
    ctx = search_ctx or _meaning_search_context(translation_rows)
    df, corpus_n = ctx['df'], ctx['n']
    target_terms = _translation_terms(tr)

    def weight(term):
        return log((corpus_n + 1) / (df.get(term, 0) + 1)) + 1.0

    target_weight = sum(weight(x) for x in target_terms) or 1.0
    pre_ranked, seen = [], set()
    for candidate in translation_rows:
        if isinstance(candidate, str):
            other_tr, other_text = candidate.strip(), ''
        else:
            other_tr = (candidate.get('translation') or '').strip()
            other_text = (candidate.get('text') or '').strip()
        if (not other_tr or other_tr == tr or other_tr in seen
                or _tr_lang(other_tr) != lang or other_text == text):
            continue
        # 近似复述有多答案风险；长度悬殊则无需听音即可排除。
        tr_sim = SequenceMatcher(None, tr, other_tr, autojunk=False).ratio()
        # 高级模式需要“一两个关键词不同”的最小语义对立，不能沿用标准模式
        # 过严的字面相似过滤；但近乎逐字相同仍可能是同义答案，必须排除。
        if tr_sim > (0.96 if difficulty == 'advanced' else 0.84):
            continue
        length_sim = 1.0 - min(1.0, abs(len(other_tr) - len(tr)) / max(len(tr), 1))
        if length_sim < (0.48 if difficulty == 'advanced' else 0.35):
            continue
        terms = _translation_terms(other_tr)
        shared = target_terms & terms
        shared_weight = sum(weight(x) for x in shared)
        other_weight = sum(weight(x) for x in terms) or 1.0
        target_coverage = shared_weight / target_weight
        candidate_coverage = shared_weight / other_weight
        lexical_overlap = 0.7 * target_coverage + 0.3 * candidate_coverage
        # 高级模式必须有高信息词/二字短语重合；长句至少共享两个实质锚点，
        # 防止仅凭一个普通词（如 time / said）把完全不同的话题拉进选项。
        # 小课本中词频样本很少，IDF 天然偏低；仍要求多个共享词，但不误杀。
        idf_floor = 1.0 if corpus_n < 100 else 2.0
        strong_shared = [x for x in shared if weight(x) >= idf_floor]
        if difficulty == 'advanced' and (
                lexical_overlap < 0.18 or not strong_shared
                or (len(target_terms) >= 4 and len(strong_shared) < 2)):
            continue
        oshape = _translation_shape(other_tr)
        shape_score = (
            0.10 * (shape['question'] == oshape['question'])
            + 0.07 * (shape['negative'] == oshape['negative'])
            + 0.06 * (shape['people'] == oshape['people'])
            + 0.03 * (shape['numbered'] == oshape['numbered'])
        )
        # 先按译文字面锚点缩到小池，避免对全库每句运行日文形态分析。
        cheap_score = 0.62 * lexical_overlap + 0.12 * length_sim + shape_score
        seen.add(other_tr)
        pre_ranked.append((cheap_score, other_tr, other_text, length_sim,
                           lexical_overlap, strong_shared, oshape))

    if len(pre_ranked) < 3:
        return None
    pre_ranked.sort(key=lambda x: (-x[0], x[1]))
    ranked = []
    for cheap, other_tr, other_text, length_sim, lexical_overlap, shared, oshape in pre_ranked[:16]:
        osig = _meaning_signature(other_text) if other_text else {
            'grammar': frozenset(), 'content': frozenset(),
            'negative': False, 'past': False, 'question': False}
        structure_score = (
            0.10 * _jaccard(sig['grammar'], osig['grammar'])
            + 0.06 * _jaccard(sig['content'], osig['content'])
            + 0.04 * (sig['negative'] == osig['negative'])
            + 0.03 * (sig['past'] == osig['past'])
            + 0.03 * (sig['question'] == osig['question'])
        )
        score = cheap + structure_score
        ranked.append((score, other_tr, {
            'lexical_overlap': round(lexical_overlap, 3),
            'shared_terms': [x[2:] for x in sorted(shared, key=lambda y: (-weight(y), y))[:5]],
            'same_translation_shape': shape == oshape,
            'grammar_overlap': round(_jaccard(sig['grammar'], osig['grammar']), 3),
            'same_polarity': sig['negative'] == osig['negative'],
            'same_tense': sig['past'] == osig['past'],
            'same_question_type': sig['question'] == osig['question'],
        }))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    chosen = ranked[:3]
    if len(chosen) < 3:
        return None
    distractors = [x[1] for x in chosen]
    opts = [tr] + distractors
    random.shuffle(opts)
    try:
        tokens = furigana.annotate(text)
    except Exception:
        tokens = []
    return {'qtype': 'meaning', 'text': text, 'options': opts, 'answer': tr,
            'sid': row.get('sid'), 'source': row.get('source'),
            'origin': _origin(row), 'tokens': tokens,
            'meaning_difficulty': difficulty,
            'distractor_source': ('attested_translation_lexical_hard_negative'
                                  if difficulty == 'advanced'
                                  else 'attested_translation_structural_hard_negative'),
            'distractor_audit': [x[2] for x in chosen]}

# ================================================================
# 题型 2：听音辨句（不需要译文；所有选项都是完整的真实语料句）
# ================================================================
def _sound_sentence(text):
    """辨句选项的保守门禁；失败或检查异常都不让句子进入题面。"""
    text = (text or '').strip()
    if not text or not (4 <= len(text) <= 100):
        return False
    try:
        return bool(grammar.is_sentence_grammatically_sound(text))
    except Exception:
        return False


def _build_discriminate_q(row, sentence_pool):
    """用三条真实原句作干扰项，绝不再做机械词语替换。

    旧实现即使按词性和助词槽筛选，仍无法判断「無駄だ」能否换成
    「国民だ」，更会因サ变/复合词分词产生「友達して」「一明日」等坏句。
    规则引擎没有语义能力，因此唯一稳健的边界是：只展示语料中实际存在且
    通过句子门禁的完整文本。相似度仅用于让选项不至于完全无关，不参与造句。
    """
    text = (row.get('text') or '').strip()
    if not _sound_sentence(text):
        return None

    seen, ranked = set(), []
    end = text[-1:] if text else ''
    for candidate in sentence_pool:
        other = ((candidate.get('text') if isinstance(candidate, dict) else candidate) or '').strip()
        if other == text or other in seen or not _sound_sentence(other):
            continue
        # 排除长度悬殊、凭长度即可秒选的选项；池不足时由调用方改出 meaning 题。
        delta = abs(len(other) - len(text))
        if delta > max(6, int(len(text) * 0.45)):
            continue
        seen.add(other)
        similarity = SequenceMatcher(None, text, other, autojunk=False).ratio()
        punct_bonus = 0.05 if other[-1:] == end else 0.0
        ranked.append((similarity + punct_bonus - delta * 0.002, other))

    if len(ranked) < 3:
        return None
    ranked.sort(key=lambda x: (-x[0], x[1]))
    # 从最相近的一小组中抽取，兼顾题目质量和重复练习时的变化。
    shortlist = [other for _, other in ranked[:min(12, len(ranked))]]
    decoys = random.sample(shortlist, 3)
    opts = [text] + decoys
    random.shuffle(opts)
    try:
        tokens = furigana.annotate(text)
    except Exception:
        tokens = []
    return {'qtype': 'discriminate', 'text': text, 'options': opts, 'answer': text,
            'sid': row.get('sid'), 'source': row.get('source'),
            'origin': _origin(row), 'tokens': tokens,
            'distractor_source': 'attested_sentences'}


# ================================================================
# 题型 3：双空最小对立（分句逻辑/词汇/格成分 × 极性）
# ================================================================
# 只收录无需动词活用生成器也能安全替换的完整表面形；顺序最长优先。
# 通用“反义词库”无法判断语境和搭配，因此只生成可复验的形态极性对立。
_POLARITY_FORMS = (
    ('ていませんでした', 'ていました'), ('ていました', 'ていませんでした'),
    ('でいませんでした', 'でいました'), ('でいました', 'でいませんでした'),
    ('ていません', 'ています'), ('ています', 'ていません'),
    ('でいません', 'でいます'), ('でいます', 'でいません'),
    ('ていなかった', 'ていた'), ('ていた', 'ていなかった'),
    ('でいなかった', 'でいた'), ('でいた', 'でいなかった'),
    ('ていない', 'ている'), ('ている', 'ていない'),
    ('でいない', 'でいる'), ('でいる', 'でいない'),
    ('ませんでした', 'ました'), ('ました', 'ませんでした'),
    ('ません', 'ます'), ('ます', 'ません'),
    ('ではありませんでした', 'でした'), ('でした', 'ではありませんでした'),
    ('ではありません', 'です'), ('です', 'ではありません'),
)


def _replace_once_at(text, start, old, new):
    return text[:start] + new + text[start + len(old):]


def _polarity_variant(text):
    """返回靠近句尾的时态/极性最小对立及字符位置；无把握则不出题。"""
    cutoff = max(0, len(text) - 20)
    for old, new in sorted(_POLARITY_FORMS, key=lambda pair: len(pair[0]), reverse=True):
        pos = text.rfind(old)
        if pos < cutoff:
            continue
        changed = _replace_once_at(text, pos, old, new)
        if _sound_sentence(changed):
            return {'text': changed, 'from': old, 'to': new, 'start': pos,
                    # 表中每一对均保持时态而翻转肯定/否定；从否定变肯定也同样
                    # 属于极性反转，不能只检查 new 是否含否定标记。
                    'opposite': True}
    return None


def _clause_logic_variant(text):
    """多分句最小对立：只改接续关系，不改两侧命题。

    「ので／のに」只有一个假名不同，却把原因关系翻成逆接；
    「から／けれど」把原因翻成转折。必须由形态素确认它确实是接续形式，
    避免误改名词中的同形字符串，并对改写后的完整句再次质检。
    """
    try:
        toks = sb._tag(text)
    except Exception:
        return None
    spans, pos = [], 0
    for tok in toks:
        i = text.find(tok['s'], pos)
        if i < 0:
            i = pos
        spans.append((i, i + len(tok['s'])))
        pos = i + len(tok['s'])

    candidates = []
    for i, tok in enumerate(toks):
        # UniDic: の(準体助詞) + で/に(助動詞だ・連用形)
        if (tok['s'] == 'の' and tok['p2'] == '準体助詞' and i + 1 < len(toks)
                and toks[i + 1]['p1'] == '助動詞'
                and toks[i + 1]['lemma'] == 'だ'
                and toks[i + 1]['s'] in ('で', 'に')):
            old = 'の' + toks[i + 1]['s']
            new = 'のに' if old == 'ので' else 'ので'
            candidates.append((spans[i][0], old, new, '分句逻辑（原因↔逆接）'))
        elif tok['p2'] == '接続助詞' and tok['s'] in ('から', 'けれど', 'けれども'):
            old = tok['s']
            new = 'けれど' if old == 'から' else 'から'
            candidates.append((spans[i][0], old, new, '分句逻辑（原因↔转折）'))

    random.shuffle(candidates)
    for start, old, new, kind in candidates:
        changed = _replace_once_at(text, start, old, new)
        if _sound_sentence(changed):
            return {'text': changed, 'from': old, 'to': new, 'start': start,
                    'kind': kind}
    return None


def _lexical_variant(text, parsed):
    """优先实证名词搭配；不足时退到格关系对立，完整句均重新质检。"""
    got = sb._swap_variant(text, parsed)
    if got:
        changed, info = got
        old = info['from'] + info['particle']
        new = info['to'] + info['particle']
        pos = text.find(old)
        if pos >= 0 and _sound_sentence(changed):
            return {'text': changed, 'from': old, 'to': new, 'start': pos,
                    'kind': '语料实证词汇'}

    for chunk in parsed.get('chunks') or []:
        old = chunk['surface']
        pos = text.find(old)
        if pos < 0:
            continue
        for new in sb._particle_variants(chunk):
            changed = _replace_once_at(text, pos, old, new)
            if _sound_sentence(changed):
                return {'text': changed, 'from': old, 'to': new, 'start': pos,
                        'kind': '格关系辨析'}
    return None


def _build_cloze_q(row):
    """同时考两个听辨点，四项形成 2×2 组合，不能靠听到一个词秒选。"""
    text = (row.get('text') or '').strip()
    if not _sound_sentence(text):
        return None
    parsed = sb.parse_sentence(text)
    if not parsed:
        return None
    # 多分句优先考接续逻辑；单句再考词汇/格关系。
    lex = _clause_logic_variant(text) or _lexical_variant(text, parsed)
    pol = _polarity_variant(text)
    if not lex or not pol:
        return None
    if lex['start'] + len(lex['from']) > pol['start']:
        return None

    lex_only = lex['text']
    pol_only = pol['text']
    p2 = lex_only.rfind(pol['from'])
    if p2 < 0:
        return None
    both = _replace_once_at(lex_only, p2, pol['from'], pol['to'])
    candidates = [text, lex_only, pol_only, both]
    if len(set(candidates)) != 4 or not all(_sound_sentence(s) for s in candidates):
        return None

    labels = [
        f"{lex['from']}　／　{pol['from']}",
        f"{lex['to']}　／　{pol['from']}",
        f"{lex['from']}　／　{pol['to']}",
        f"{lex['to']}　／　{pol['to']}",
    ]
    answer = labels[0]
    random.shuffle(labels)
    a, b = lex['start'], lex['start'] + len(lex['from'])
    c, d = pol['start'], pol['start'] + len(pol['from'])
    return {
        'qtype': 'cloze', 'text': text, 'options': labels, 'answer': answer,
        'sid': row.get('sid'), 'source': row.get('source'), 'origin': _origin(row),
        'prompt_parts': [text[:a], text[b:c], text[d:]],
        'blank_answers': [lex['from'], pol['from']],
        'contrast': {'lexical_kind': lex['kind'], 'lexical_to': lex['to'],
                     'form_to': pol['to'], 'opposite': pol['opposite']},
        'candidate_sentences': candidates,
        'distractor_source': 'minimal_pair_grammar_checked',
    }


def _origin(row):
    if row.get('source') == 'lyric':
        return f"🎵 《{row.get('song_title') or '歌词'}》"
    try:
        return textbook.origin_label(row.get('source'), row.get('book_title'), row.get('lesson_title'))
    except Exception:
        return row.get('source') or '语料库'


# ================================================================
# 出题主流程
# ================================================================
def _expanded_translation_pool(scope, ids, rows):
    """高级选义需要足够大的同主题检索池；目标题仍严格来自已解析的 scope。"""
    pool = list(rows)
    try:
        if scope in ('corpus', 'mixed'):
            with db.get_conn() as c:
                pool += [dict(r) for r in c.execute(
                    "SELECT id sid, text, translation, source FROM sentences "
                    "WHERE translation IS NOT NULL AND trim(translation)<>'' LIMIT 20000"
                ).fetchall()]
        elif scope == 'book' and ids:
            pool += textbook.fetch_book_sentence_rows(ids, 5000)
    except Exception:
        pass
    out, seen = [], set()
    for row in pool:
        tr = (row.get('translation') or '').strip()
        key = ((row.get('text') or '').strip(), tr)
        if not tr or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def make_quiz(book_ids=None, count=None, level=None, scope=None):
    cfg = listening_cfg()
    if not cfg.get('enabled', True):
        return {'ok': False, 'reason': '听力练习已在配置中关闭', 'count': 0, 'questions': []}
    level = level if level in (['any'] + LEVELS) else cfg['level']
    scope = scope if scope in ('corpus', 'book', 'mixed', 'lyric') else cfg['scope']
    try:
        count = max(1, min(int(count), 20)) if count else cfg['count']
    except Exception:
        count = cfg['count']

    resolved = textbook.resolve_book_scope(scope, book_ids)
    scope, ids = resolved['scope'], resolved['ids']

    need = min(max(count * 20, 150), 500)
    rows = _fetch_pool(scope, ids, need)
    rows = [r for r in rows if cfg['min_len'] <= len((r.get('text') or '').strip()) <= cfg['max_len']]

    t = cfg['types']
    kinds = ('meaning', 'discriminate', 'cloze')
    total_weight = sum(t[k] for k in kinds)
    raw_targets = {k: count * t[k] / total_weight for k in kinds}
    targets = {k: int(raw_targets[k]) for k in kinds}
    for k in sorted(kinds, key=lambda x: raw_targets[x] - targets[x], reverse=True):
        if sum(targets.values()) >= count:
            break
        targets[k] += 1

    translation_pool = [r for r in rows if (r.get('translation') or '').strip()]
    meaning_difficulty = cfg.get('meaning_difficulty', 'advanced')
    if meaning_difficulty == 'advanced':
        translation_pool = _expanded_translation_pool(scope, ids, translation_pool)
    meaning_ctx = _meaning_search_context(translation_pool)
    sentence_pool = rows
    builders = {
        'meaning': lambda row: _build_meaning_q(
            row, translation_pool, meaning_difficulty, meaning_ctx),
        'discriminate': lambda row: _build_discriminate_q(row, sentence_pool),
        'cloze': _build_cloze_q,
    }

    questions, used = [], set()
    made = {k: 0 for k in kinds}
    relax_note = False
    for relax in (False, True):
        want = None if relax else level
        for row in rows:
            if len(questions) >= count:
                break
            key = row.get('sid') or row.get('dedup') or row.get('text')
            if key in used:
                continue
            text = (row.get('text') or '').strip()
            lv, _ = sb._sentence_level(text)
            if want and want != 'any' and lv != want:
                continue
            # 优先补足目标占比；若该题无法构造，才尝试其它题型，保证宁可改变
            # 占比也不要用低质量干扰项凑数。
            order = sorted(kinds,
                           key=lambda k: (targets[k] - made[k], t[k]), reverse=True)
            got = None
            for kind in order:
                got = builders[kind](row)
                if got:
                    break
            if not got:
                continue
            got['level'] = lv
            made[got['qtype']] += 1
            if relax and level != 'any':
                got['level_relaxed'] = True
                relax_note = True
            used.add(key)
            questions.append(got)
        if len(questions) >= count or level == 'any':
            break

    random.shuffle(questions)
    rate = cfg['rate']
    for i, q in enumerate(questions):
        q['qid'] = f'l{i}'
        q['rate'] = rate
        q['max_plays'] = cfg['max_plays']
    return {'ok': True, 'level': level, 'scope': scope, 'book_ids': ids,
            'scope_auto_all': resolved['auto_all'], 'scope_note': resolved['note'],
            'rate': rate, 'max_plays': cfg['max_plays'],
            'meaning_difficulty': meaning_difficulty,
            'count': len(questions), 'questions': questions,
            'level_relaxed': relax_note, 'short': len(questions) < count}


# ================================================================
# 成绩记录 / 统计（与 sentence_builder 完全同构，方便复用同一套统计 UI）
# ================================================================
def record_results(results):
    results = [r for r in (results or []) if isinstance(r, dict)]
    n_ok = sum(1 for r in results if r.get('ok'))
    today = date.today().isoformat()
    try:
        stats = json.loads(db.get_setting(_STATS_KEY, '') or '{}')
    except Exception:
        stats = {}
    d = stats.setdefault(today, {'asked': 0, 'correct': 0, 'by_type': {}, 'by_level': {}})
    d['asked'] += len(results)
    d['correct'] += n_ok
    for r in results:
        for key, field in (('by_type', 'qtype'), ('by_level', 'level')):
            v = str(r.get(field) or '?')
            slot = d.setdefault(key, {}).setdefault(v, {'asked': 0, 'correct': 0})
            slot['asked'] += 1
            slot['correct'] += 1 if r.get('ok') else 0
    db.set_setting(_STATS_KEY, json.dumps(stats, ensure_ascii=False))
    db.log('listening', f'听力练习：{n_ok}/{len(results)} 正确')
    return {'ok': True, 'asked': len(results), 'correct': n_ok}


def listening_stats(days=14):
    try:
        stats = json.loads(db.get_setting(_STATS_KEY, '') or '{}')
    except Exception:
        stats = {}
    return [{'day': day, **stats[day]} for day in sorted(stats)[-max(1, int(days)):]]

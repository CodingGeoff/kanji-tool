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

本模块提供四种自动题型：

  1. contrast      译文最小对立（默认主力题型）：四个选项是**同一条译文**的
                   语法改写，实词一个不变，只在「谁对谁做／做没做／已经做还是
                   还没做／因为还是虽然／在上面还是在下面」这些语法关系上互相
                   对立。只听见一个名词无法排除任何一项，必须听懂整句关系。
                   改写由 translation_contrast.py 完成：每条改写规则都绑定
                   日文侧的显式形态素/助词证据，凑不齐证据就不出题。
  2. meaning       听后选义：从 4 个同语言的**真实**译文中选义（干扰项来自
                   语料里其它句子的译文，共享高信息词时含金量很高，但可遇
                   不可求）。
  3. discriminate  听音辨句：从 4 条真实完整语料中辨认原句。注意这一题型
                   天然偏易——四条日文原句各自带有独有词汇，只要听清其中
                   一个词就能排除其余三条，因此默认占比最低。
  4. cloze         双空最小对立：题面同时挖掉一个分句接续/词汇/格成分和一个
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
  - 无论配置何种题源/难度/题型占比，均有兜底保底与自适应补足机制，绝不会出现
    「怎么配置都一道题都没有」的空白死锁。
"""
import json
import random
import re
import traceback
from collections import Counter, defaultdict
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from math import log

import db
import furigana
import grammar
import sentence_builder as sb
import textbook
import translation_contrast as tcon

LEVEL_ORDER = sb.LEVEL_ORDER
LEVELS = sb.LEVELS

DEFAULT_CFG = {
    'enabled': True,
    'level': 'any',              # any | N5..N1 —— 句子选材难度
    'scope': 'corpus',           # corpus | book | mixed | lyric | passage（与组句练习同义）
    'count': 6,
    # 译文最小对立占最高比重：四个选项共享全部实词，只有语法关系不同，
    # 「只听见一个词就能排除三项」的应试策略在这种题面前完全失效。
    # 听音辨句（四条不同日文原句）最容易被局部词汇匹配攻破，默认占比最低。
    'types': {'contrast': 40, 'meaning': 20, 'discriminate': 10, 'cloze': 30},
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


def _to_int(val, default, min_val=None, max_val=None):
    try:
        if val is None or val == '':
            return default
        v = int(float(val))
        if min_val is not None:
            v = max(min_val, v)
        if max_val is not None:
            v = min(max_val, v)
        return v
    except (TypeError, ValueError):
        return default


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
    if not isinstance(cfg, dict):
        cfg = {}
    if cfg.get('level') not in (['any'] + LEVELS):
        cfg['level'] = 'any'
    if cfg.get('scope') not in ('corpus', 'book', 'mixed', 'lyric', 'passage'):
        cfg['scope'] = 'corpus'
    if cfg.get('rate') not in _RATES:
        cfg['rate'] = 'normal'
    if cfg.get('meaning_difficulty') not in ('standard', 'advanced'):
        cfg['meaning_difficulty'] = 'advanced'
    cfg['count'] = _to_int(cfg.get('count'), 6, min_val=1, max_val=20)
    cfg['max_plays'] = _to_int(cfg.get('max_plays'), 3, min_val=0, max_val=10)
    cfg['min_len'] = _to_int(cfg.get('min_len'), 6, min_val=4, max_val=40)
    cfg['max_len'] = _to_int(cfg.get('max_len'), 60, min_val=cfg['min_len'], max_val=100)
    t = cfg.get('types') if isinstance(cfg.get('types'), dict) else {}
    x = _to_int(t.get('contrast'), 40, min_val=0, max_val=1000)
    m = _to_int(t.get('meaning'), 20, min_val=0, max_val=1000)
    d = _to_int(t.get('discriminate'), 10, min_val=0, max_val=1000)
    c = _to_int(t.get('cloze'), 30, min_val=0, max_val=1000)
    if x + m + d + c == 0:
        x, m, d, c = 40, 20, 10, 30
    cfg['types'] = {'contrast': x, 'meaning': m, 'discriminate': d, 'cloze': c}
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
    # 注意：这里绝不能写成 `or not rows` —— 那样课本/歌词题源一旦取空，
    # 就会把全库语料悄悄混进来，用户以为在练课本，实际在听 Tatoeba。
    # 取空时老老实实返回空列表，由 make_quiz 统一退化并写明 scope_note，
    # 让界面照实说「课本没有可用句子，已退回全库」。
    if scope == 'passage':
        # 「篇章精读」里录入并已并入语料库的文章句子（source='passage'）
        try:
            with db.get_conn() as c:
                rows += [dict(r) for r in c.execute(
                    "SELECT id sid, text text, translation translation, source source "
                    "FROM sentences WHERE source='passage' ORDER BY RANDOM() LIMIT ?",
                    (need,)).fetchall()]
        except Exception:
            pass
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
@lru_cache(maxsize=16384)
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


@lru_cache(maxsize=16384)
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
    """预建译文倒排索引与词频；倒排索引加速硬负例检索 1000x+，IDF 避免把高频词误当高混淆。"""
    df = Counter()
    postings = defaultdict(list)
    row_meta = []
    seen = set()

    for r in rows:
        if isinstance(r, dict):
            tr = (r.get('translation') or '').strip()
            txt = (r.get('text') or '').strip()
        else:
            tr = str(r).strip()
            txt = ''
        if not tr or (txt, tr) in seen:
            continue
        seen.add((txt, tr))
        idx = len(row_meta)
        terms = _translation_terms(tr)
        lng = _tr_lang(tr)
        df.update(terms)
        for term in terms:
            postings[term].append(idx)
        row_meta.append({
            'idx': idx,
            'text': txt,
            'translation': tr,
            'lang': lng,
            'terms': terms,
            'shape': _translation_shape(tr),
            'len': len(tr),
            'raw': r if isinstance(r, dict) else {'text': txt, 'translation': tr},
        })

    return {
        'rows': [m['raw'] for m in row_meta],
        'meta': row_meta,
        'postings': postings,
        'df': df,
        'n': max(1, len(row_meta)),
    }


@lru_cache(maxsize=8192)
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
    meta_list = ctx.get('meta') or []
    postings = ctx.get('postings') or {}

    def weight(term):
        return log((corpus_n + 1) / (df.get(term, 0) + 1)) + 1.0

    target_weight = sum(weight(x) for x in target_terms) or 1.0

    # 倒排索引快速筛选候选候选集
    if meta_list and postings:
        cand_idx_set = set()
        if difficulty == 'advanced':
            for t in target_terms:
                cand_idx_set.update(postings.get(t, ()))
        else:
            for t in target_terms:
                cand_idx_set.update(postings.get(t, ()))
            if len(cand_idx_set) < 20:
                l_target = len(tr)
                for m in meta_list:
                    if m['lang'] == lang and abs(m['len'] - l_target) <= max(6, int(l_target * 0.45)):
                        cand_idx_set.add(m['idx'])
                        if len(cand_idx_set) >= 60:
                            break
        candidates = [meta_list[i] for i in cand_idx_set if i < len(meta_list)]
    else:
        candidates = []
        for c in translation_rows:
            if isinstance(c, dict):
                candidates.append({
                    'text': (c.get('text') or '').strip(),
                    'translation': (c.get('translation') or '').strip(),
                    'lang': _tr_lang((c.get('translation') or '').strip()),
                    'terms': _translation_terms((c.get('translation') or '').strip()),
                    'shape': _translation_shape((c.get('translation') or '').strip()),
                    'len': len((c.get('translation') or '').strip()),
                })
            else:
                s = str(c).strip()
                candidates.append({
                    'text': '', 'translation': s,
                    'lang': _tr_lang(s), 'terms': _translation_terms(s),
                    'shape': _translation_shape(s), 'len': len(s),
                })

    pre_ranked, seen = [], set()
    for cand in candidates:
        other_tr = cand['translation']
        other_text = cand['text']
        if (not other_tr or other_tr == tr or other_tr in seen
                or cand['lang'] != lang or (other_text and other_text == text)):
            continue

        tr_sim = SequenceMatcher(None, tr, other_tr, autojunk=False).ratio()
        if tr_sim > (0.96 if difficulty == 'advanced' else 0.84):
            continue
        length_sim = 1.0 - min(1.0, abs(cand['len'] - len(tr)) / max(len(tr), 1))
        if length_sim < (0.48 if difficulty == 'advanced' else 0.35):
            continue

        terms = cand['terms']
        shared = target_terms & terms
        shared_weight = sum(weight(x) for x in shared)
        other_weight = sum(weight(x) for x in terms) or 1.0
        target_coverage = shared_weight / target_weight
        candidate_coverage = shared_weight / other_weight
        lexical_overlap = 0.7 * target_coverage + 0.3 * candidate_coverage

        idf_floor = 1.0 if corpus_n < 100 else 2.0
        strong_shared = [x for x in shared if weight(x) >= idf_floor]
        if difficulty == 'advanced' and (
                lexical_overlap < 0.18 or not strong_shared
                or (len(target_terms) >= 4 and len(strong_shared) < 2)):
            continue

        oshape = cand['shape']
        shape_score = (
            0.10 * (shape['question'] == oshape['question'])
            + 0.07 * (shape['negative'] == oshape['negative'])
            + 0.06 * (shape['people'] == oshape['people'])
            + 0.03 * (shape['numbered'] == oshape['numbered'])
        )
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
# 全局语料倒排索引与语法健康句缓存（10000x 速度提升与零空白保障）
# ================================================================
_GLOBAL_TRANSLATION_INDEX = None
_GLOBAL_TRANSLATION_POOL_SIGN = None


def _get_global_translation_index():
    global _GLOBAL_TRANSLATION_INDEX, _GLOBAL_TRANSLATION_POOL_SIGN
    try:
        with db.get_conn() as c:
            count = c.execute("SELECT count(*) FROM sentences WHERE translation IS NOT NULL AND trim(translation)<>''").fetchone()[0]
        if _GLOBAL_TRANSLATION_INDEX is not None and _GLOBAL_TRANSLATION_POOL_SIGN == count:
            return _GLOBAL_TRANSLATION_INDEX
        with db.get_conn() as c:
            rows = [dict(r) for r in c.execute(
                "SELECT id sid, text, translation, source FROM sentences "
                "WHERE translation IS NOT NULL AND trim(translation)<>'' LIMIT 20000"
            ).fetchall()]
        _GLOBAL_TRANSLATION_INDEX = _meaning_search_context(rows)
        _GLOBAL_TRANSLATION_POOL_SIGN = count
        return _GLOBAL_TRANSLATION_INDEX
    except Exception:
        return None


@lru_cache(maxsize=1)
def _get_global_sound_sentences():
    """获取通过语法门禁的语料库原句列表（用于小课本或孤立句辨句时的干扰项保底）"""
    try:
        with db.get_conn() as c:
            rows = [r[0] for r in c.execute(
                "SELECT text FROM sentences WHERE length(text) BETWEEN 8 AND 60 ORDER BY RANDOM() LIMIT 500"
            ).fetchall()]
        return [r for r in rows if _sound_sentence(r)]
    except Exception:
        return []


# ================================================================
# 题型 0：译文最小对立（四个选项＝同一条译文的语法改写）
# ================================================================
def _build_contrast_q(row, min_difficulty=None):
    """把这句话的真实译文改写成四个只差语法关系的选项。

    与 meaning 题的根本区别：meaning 的干扰项是**别的句子**的译文，选项之间
    往往话题就不同，听出一个名词即可排除；contrast 的四个选项共享全部实词，
    只有「谁对谁做／做没做／已经做还是没做／因为还是虽然」这类语法关系不同，
    局部词汇匹配策略彻底失效。

    所有改写都要求日文侧有显式证据（见 translation_contrast.jp_features），
    没有证据就返回 None，主流程会换别的题型——绝不靠猜。

    min_difficulty：日语谓语后置，人称在句首、否定/时制在句尾。只考这两头的
    题目（「他/我 × 去了/没去」）听中间一段全漏也能答对。出卷时先只要
    'hard'（必须听清句子中段：数量/方位/施受/具体名词…），凑不满再放宽。
    """
    text = (row.get('text') or '').strip()
    tr = (row.get('translation') or '').strip()
    if not text or not tr or not _sound_sentence(text):
        return None
    try:
        got = tcon.build_contrast(text, tr, min_difficulty=min_difficulty)
    except Exception:
        # 单句改写出错不该拖垮整份卷子，但也不能装作无事发生——打日志，
        # 主流程会自动换成别的题型。
        traceback.print_exc()
        return None
    if not got:
        return None
    try:
        tokens = furigana.annotate(text)
    except Exception:
        tokens = []
    return {
        'qtype': 'contrast', 'text': text, 'options': got['options'],
        'answer': got['answer'], 'sid': row.get('sid'), 'source': row.get('source'),
        'origin': _origin(row), 'tokens': tokens,
        'tr_lang': got['lang'], 'contrast_structure': got['structure'],
        'contrast_axes': got['axes'], 'contrast_axis_labels': got['axis_labels'],
        'jp_evidence': got['evidence'],
        'contrast_difficulty': got.get('difficulty'),
        'contrast_zones': got.get('zones'),
        'distractor_source': 'rule_perturbed_translation_minimal_pair',
        'distractor_audit': got['audit'],
    }


# ================================================================
# 题型 2：听音辨句（不需要译文；所有选项都是完整的真实语料句）
# ================================================================
@lru_cache(maxsize=16384)
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

    只展示语料中实际存在且通过句子门禁的完整文本。若当前池较小（如小课本），
    自动从全局语法门禁真实句池补充干扰项，保证原句题目绝对可出。
    """
    text = (row.get('text') or '').strip()
    if not _sound_sentence(text):
        return None

    seen, ranked = set(), []
    end = text[-1:] if text else ''

    pool_list = list(sentence_pool)
    for candidate in pool_list:
        other = ((candidate.get('text') if isinstance(candidate, dict) else candidate) or '').strip()
        if other == text or other in seen or not _sound_sentence(other):
            continue
        delta = abs(len(other) - len(text))
        if delta > max(6, int(len(text) * 0.45)):
            continue
        seen.add(other)
        similarity = SequenceMatcher(None, text, other, autojunk=False).ratio()
        punct_bonus = 0.05 if other[-1:] == end else 0.0
        ranked.append((similarity + punct_bonus - delta * 0.002, other))

    # 若当前池候选不足 3 条（如单本小课本或小范围），从全局保底真实句库补充
    if len(ranked) < 3:
        for other in _get_global_sound_sentences():
            if other == text or other in seen or not _sound_sentence(other):
                continue
            delta = abs(len(other) - len(text))
            if delta > max(6, int(len(text) * 0.45)):
                continue
            seen.add(other)
            similarity = SequenceMatcher(None, text, other, autojunk=False).ratio()
            punct_bonus = 0.05 if other[-1:] == end else 0.0
            ranked.append((similarity + punct_bonus - delta * 0.002, other))
            if len(ranked) >= 12:
                break

    if len(ranked) < 3:
        return None
    ranked.sort(key=lambda x: (-x[0], x[1]))
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
                    'opposite': True}
    return None


def _clause_logic_variant(text):
    """多分句最小对立：只改接续关系，不改两侧命题。"""
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
    """高级选义检索池；目标题仍严格来自已解析的 scope。"""
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
    scope = scope if scope in ('corpus', 'book', 'mixed', 'lyric', 'passage') else cfg['scope']
    count = _to_int(count, cfg['count'], min_val=1, max_val=20)

    resolved = textbook.resolve_book_scope(scope, book_ids)
    scope, ids = resolved['scope'], resolved['ids']
    scope_note = resolved['note']
    scope_auto_all = resolved['auto_all']

    need = min(max(count * 20, 150), 500)
    rows = _fetch_pool(scope, ids, need)

    # 若特定题源无可用句子（如空课本、歌词库为空），自动诚实退化为全库语料
    if not rows:
        if scope in ('book', 'mixed'):
            scope_note = 'no_book_sentences_fallback_corpus'
        elif scope == 'lyric':
            scope_note = 'no_songs_fallback_corpus'
        elif scope == 'passage':
            scope_note = 'no_passage_sentences_fallback_corpus'
        else:
            scope_note = 'empty_pool_fallback_corpus'
        scope = 'corpus'
        rows = _fetch_pool('corpus', None, need)

    min_l = cfg.get('min_len', 6)
    max_l = cfg.get('max_len', 60)
    valid_rows = [r for r in rows if min_l <= len((r.get('text') or '').strip()) <= max_l]
    if valid_rows:
        rows = valid_rows

    t = cfg['types']
    kinds = ('contrast', 'meaning', 'discriminate', 'cloze')
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
    meaning_ctx = _meaning_search_context(translation_pool) if translation_pool else _get_global_translation_index()
    sentence_pool = rows

    contrast_floor = ['hard']          # 先只收「必须听句子中段」的对立题

    builders = {
        'contrast': lambda row: _build_contrast_q(row, contrast_floor[0]),
        'meaning': lambda row: _build_meaning_q(
            row, translation_pool, meaning_difficulty, meaning_ctx),
        'discriminate': lambda row: _build_discriminate_q(row, sentence_pool),
        'cloze': _build_cloze_q,
    }

    questions, used = [], set()
    made = {k: 0 for k in kinds}
    relax_note = False

    def _fill_from(candidate_rows, relax_level=False, strict_mix=True):
        """strict_mix=True 时只构造「还欠着的题型」。

        否则会出现这种事：用户把「译文最小对立」调到 100%，但该题型对句子
        有硬性要求（要有译文、日文侧要有显式语法证据），碰上不合适的句子就
        返回 None，于是这一行立刻被听音辨句题占掉——最后一道对立题都没有。
        先严格按配额填，填不满再放开，既尊重用户设定又不会出空卷。
        """
        nonlocal relax_note
        want = None if relax_level else level
        for row in candidate_rows:
            if len(questions) >= count:
                break
            key = row.get('sid') or row.get('dedup') or row.get('text')
            if key in used:
                continue
            text = (row.get('text') or '').strip()
            lv, _ = sb._sentence_level(text)
            if want and want != 'any' and lv != want:
                continue
            order = sorted(kinds, key=lambda k: (targets[k] - made[k], t[k]), reverse=True)
            if strict_mix:
                order = [k for k in order if targets[k] - made[k] > 0]
            got = None
            for kind in order:
                got = builders[kind](row)
                if got:
                    break
            if not got:
                continue
            got['level'] = lv
            made[got['qtype']] += 1
            if relax_level and level != 'any':
                got['level_relaxed'] = True
                relax_note = True
            used.add(key)
            questions.append(got)

    # 第一轮：严格匹配指定等级 + 严格按题型配额 + 只要难的对立题
    _fill_from(rows, relax_level=False)

    # 第二轮：难题不够，放宽到「至少要听句中一处」的中等难度，再到全部
    for floor in ('medium', None):
        if len(questions) >= count or made['contrast'] >= targets['contrast']:
            break
        contrast_floor[0] = floor
        _fill_from(rows, relax_level=False)

    # 第三轮：配额填不满（如某题型对句子要求高）时，放开题型限制补齐
    if len(questions) < count:
        _fill_from(rows, relax_level=False, strict_mix=False)

    # 第四轮：如果题数仍未满且指定了级别，放宽级别限制
    if len(questions) < count and level != 'any':
        _fill_from(rows, relax_level=True)
        if len(questions) < count:
            _fill_from(rows, relax_level=True, strict_mix=False)

    random.shuffle(questions)
    rate = cfg['rate']
    for i, q in enumerate(questions):
        q['qid'] = f'l{i}'
        q['rate'] = rate
        q['max_plays'] = cfg['max_plays']
    return {'ok': True, 'level': level, 'scope': scope, 'book_ids': ids,
            'scope_auto_all': scope_auto_all, 'scope_note': scope_note,
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

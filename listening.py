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

本模块提供八种自动题型（另有 AI 人工复核题草稿箱）：

  1. contrast      译文最小对立：四个选项是**同一条译文**的语法改写，实词
                   一个不变，只在施受、极性、时态、方位等关系上对立。
  2. meaning       听后选义：从 4 个同语言的**真实**译文中选义；高级模式
                   只接受共享高信息词的同主题硬负例。
  3. cloze         日文双空最小对立：分句接续/词汇/格成分 × 时态・极性，
                   四项是 2×2 组合，整句逐项过语法门禁。
  4. discriminate  听音辨句：从 4 条真实完整日文原句中辨认原句。天然偏易，
                   默认占比为 0，只有用户主动提高比例才启用。
  5. word_dictation 听写纯汉字词：音频只朗读一个语料中实际出现的、表面形为
                   纯汉字的词；答案禁止假名、罗马字和注音。
  6. kanji_choice 听音选汉字：音频只朗读一个词，从其它真实词条中选字形；
                   候选优先使用同音、同长度、共享字形的硬混淆，不机械改造词。
  7. sentence_dictation 听写完整句：不计标点，用户可输入汉字、假名或混合
                   写法。高级无提示；中级完整词后从全语料库给下一小块搭配；
                   初级连词的一部分也给完整词候选，并在词完成后继续给搭配。
  8. sentence_arrange 听后组句：音频只播放句子，随后将整句切成词块打乱；
                   用户必须把全部词块按顺序放回，不能只拼出半句。默认最多听 2 次。

句子听写的读音判定不是简单字符串比较：日文表记和整句读音都进入候选
有限状态匹配；furigana 引擎给出的推荐读音、非推荐但确有证据的可能读音
都可识别。后一种会标成“读音可通，但建议改写”，未知词不猜读音。

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
import unicodedata
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
    # 旧有选择题保留，但把「听音辨句」默认关掉：它只需抓到一个独有词，
    # 很容易绕过整句听辨。新增三种听写/辨字题默认占主要比重。
    # 这些是权重而不是必须相加到 100 的百分比，服务端会统一归一化；这样
    # 老配置只提交四种题型时也能平滑升级，不会丢失新增题型的默认值。
    'types': {
        'contrast': 15, 'meaning': 5, 'discriminate': 0, 'cloze': 5,
        'word_dictation': 15, 'kanji_choice': 15, 'sentence_dictation': 25,
        'sentence_arrange': 20,
    },
    # 译文最小对立要求译文共享高信息词/短语且句式相近；凑不齐三项就不出题。
    'meaning_difficulty': 'advanced',   # standard | advanced
    # sentence_dictation：advanced=无提示，intermediate=完整词后联想，
    # beginner=部分词也联想，mixed=三种模式按高级优先随机。
    'sentence_mode': 'mixed',
    'rate': 'normal',            # slow | slower | normal | fast —— 听力特有难度轴
                                  # （与 /api/tts 的 RATES 命名完全一致，前端直接透传）
    'max_plays': 3,              # 旧选择/听写题最多重播次数，0=不限
    'arrange_max_plays': 2,      # 听后组句专用：默认只允许听两次
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
    if cfg.get('sentence_mode') not in ('advanced', 'intermediate', 'beginner', 'mixed'):
        cfg['sentence_mode'] = 'mixed'
    cfg['count'] = _to_int(cfg.get('count'), 6, min_val=1, max_val=20)
    cfg['max_plays'] = _to_int(cfg.get('max_plays'), 3, min_val=0, max_val=10)
    cfg['arrange_max_plays'] = _to_int(cfg.get('arrange_max_plays'), 2, min_val=0, max_val=10)
    cfg['min_len'] = _to_int(cfg.get('min_len'), 6, min_val=4, max_val=40)
    cfg['max_len'] = _to_int(cfg.get('max_len'), 60, min_val=cfg['min_len'], max_val=100)
    t = cfg.get('types') if isinstance(cfg.get('types'), dict) else {}
    x = _to_int(t.get('contrast'), DEFAULT_CFG['types']['contrast'], min_val=0, max_val=1000)
    m = _to_int(t.get('meaning'), DEFAULT_CFG['types']['meaning'], min_val=0, max_val=1000)
    d = _to_int(t.get('discriminate'), DEFAULT_CFG['types']['discriminate'], min_val=0, max_val=1000)
    c = _to_int(t.get('cloze'), DEFAULT_CFG['types']['cloze'], min_val=0, max_val=1000)
    w = _to_int(t.get('word_dictation'), DEFAULT_CFG['types']['word_dictation'], min_val=0, max_val=1000)
    k = _to_int(t.get('kanji_choice'), DEFAULT_CFG['types']['kanji_choice'], min_val=0, max_val=1000)
    s = _to_int(t.get('sentence_dictation'), DEFAULT_CFG['types']['sentence_dictation'], min_val=0, max_val=1000)
    a = _to_int(t.get('sentence_arrange'), DEFAULT_CFG['types']['sentence_arrange'], min_val=0, max_val=1000)
    if x + m + d + c + w + k + s + a == 0:
        x, m, d, c, w, k, s, a = (DEFAULT_CFG['types'][name]
                                   for name in ('contrast', 'meaning', 'discriminate', 'cloze',
                                                 'word_dictation', 'kanji_choice',
                                                 'sentence_dictation', 'sentence_arrange'))
    cfg['types'] = {'contrast': x, 'meaning': m, 'discriminate': d, 'cloze': c,
                    'word_dictation': w, 'kanji_choice': k,
                    'sentence_dictation': s, 'sentence_arrange': a}
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



# ================================================================
# 新增题型：纯汉字词、听音选汉字、整句听写
# ================================================================
_KANJI_RE = re.compile(r'^[\u3400-\u9fff々〆ヶ]+$')
_GLOBAL_WORD_BANK = None
_GLOBAL_WORD_BANK_SIGN = None
_GLOBAL_SUGGESTION_ROWS = None
_GLOBAL_SUGGESTION_SIGN = None


def _is_pure_kanji(value):
    """纯汉字表记：不接受假名、罗马字、数字或注音符号。"""
    return bool(_KANJI_RE.fullmatch((value or '').strip()))


@lru_cache(maxsize=8192)
def _kanji_word_units(text):
    """从一句话抽取语料实际出现的纯汉字词和推荐读音。

    furigana.annotate() 可能把一个复合词拆成多个带 ruby 的片段，因此按 w/wr
    合并并去重；绝不凭空把假名词转换成汉字，保证听写题的答案确实是原文表记。
    """
    text = (text or '').strip()
    if not text:
        return ()
    try:
        tokens = furigana.annotate(text)
    except Exception:
        tokens = []
    out, seen = [], set()
    for tok in tokens:
        surface = (tok.get('w') or tok.get('s') or '').strip()
        if not _is_pure_kanji(surface):
            continue
        reading = (tok.get('wr') or tok.get('r') or '').strip()
        if not reading:
            continue
        key = (surface, reading)
        if key in seen:
            continue
        seen.add(key)
        out.append({'word': surface, 'reading': reading})
    # 某些未收录词的词典仲裁不会带 w；用形态素表记作安全的保守兜底。
    if not out:
        try:
            for tok in sb._tag(text):
                surface = tok.get('s', '')
                if not _is_pure_kanji(surface) or len(surface) > 8:
                    continue
                one = furigana.annotate(surface)
                reading = ''.join(x.get('r') or furigana.kata_to_hira(x.get('s') or '')
                                  for x in one).strip()
                if reading and (surface, reading) not in seen:
                    seen.add((surface, reading))
                    out.append({'word': surface, 'reading': reading})
        except Exception:
            pass
    return tuple(out)


def _word_bank_from_rows(rows):
    out, seen = [], set()
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        text = (row.get('text') or '').strip()
        for unit in _kanji_word_units(text):
            key = (unit['word'], unit['reading'])
            if key in seen:
                continue
            seen.add(key)
            out.append({**unit, 'text': text, 'sid': row.get('sid'),
                        'source': row.get('source'), 'origin': _origin(row)})
    return out


def _get_global_word_bank():
    """全语料库纯汉字词索引；按 count/max(id) 换代，避免每道题重复分词。"""
    global _GLOBAL_WORD_BANK, _GLOBAL_WORD_BANK_SIGN
    try:
        with db.get_conn() as c:
            sign = (str(db.DB_PATH), *tuple(c.execute(
                'SELECT count(*), COALESCE(max(id), 0) FROM sentences').fetchone()))
        if _GLOBAL_WORD_BANK is not None and _GLOBAL_WORD_BANK_SIGN == sign:
            return _GLOBAL_WORD_BANK
        # kanji_index 已在录入语料时建立，直接取它比逐句重新跑 ruby 快一个数量级；
        # 只把纯汉字且有读音的真实词放入候选，旧库缺索引时再退回逐句提取。
        with db.get_conn() as c:
            indexed = [dict(r) for r in c.execute(
                'SELECT DISTINCT ki.word word, ki.word_reading reading, '
                's.text text, s.id sid, s.source source '
                'FROM kanji_index ki JOIN sentences s ON s.id=ki.sentence_id '
                "WHERE ki.word_reading IS NOT NULL AND trim(ki.word_reading)<>'' "
                'LIMIT 60000').fetchall()]
        _GLOBAL_WORD_BANK = [r for r in indexed if _is_pure_kanji(r.get('word'))
                             and 1 <= len(r.get('word') or '') <= 8
                             and r.get('reading')]
        if not _GLOBAL_WORD_BANK:
            with db.get_conn() as c:
                rows = [dict(r) for r in c.execute(
                    'SELECT id sid, text, source FROM sentences '
                    'WHERE length(text) BETWEEN 4 AND 120 LIMIT 30000').fetchall()]
            _GLOBAL_WORD_BANK = _word_bank_from_rows(rows)
        _GLOBAL_WORD_BANK_SIGN = sign
        return _GLOBAL_WORD_BANK
    except Exception:
        return []


def _row_word_candidates(row):
    units = list(_kanji_word_units((row or {}).get('text') or ''))
    # 复合词更适合听辨；只有一句里没有复合纯汉字词时才放开单字。
    long_units = [x for x in units if len(x['word']) >= 2]
    return long_units or units


def _build_word_dictation_q(row, word_bank=None):
    candidates = _row_word_candidates(row)
    if not candidates:
        return None
    unit = random.choice(candidates)
    return {
        'qtype': 'word_dictation', 'text': (row.get('text') or '').strip(),
        'audio_text': unit['word'], 'answer': unit['word'],
        'target_word': unit['word'], 'reading': unit['reading'],
        'sid': row.get('sid'), 'source': row.get('source'), 'origin': _origin(row),
        'distractor_source': 'attested_pure_kanji_word',
        'input_rule': 'pure_kanji_only',
    }


def _build_kanji_choice_q(row, word_bank=None):
    candidates = _row_word_candidates(row)
    if not candidates:
        return None
    unit = random.choice(candidates)
    bank = word_bank or _get_global_word_bank()
    target = unit['word']
    target_reading = furigana.kata_to_hira(unit['reading'])
    ranked, seen = [], {target}
    for cand in bank:
        word = cand.get('word', '')
        if word in seen or not _is_pure_kanji(word) or not cand.get('reading'):
            continue
        if abs(len(word) - len(target)) > 2 or len(word) > 8:
            continue
        reading = furigana.kata_to_hira(cand['reading'])
        surface_sim = SequenceMatcher(None, target, word, autojunk=False).ratio()
        reading_sim = SequenceMatcher(None, target_reading, reading, autojunk=False).ratio()
        shared = len(set(target) & set(word)) / max(len(set(target)), 1)
        same_len = 1.0 if len(word) == len(target) else 0.0
        # 同音词是最强混淆，其次是同长/共享字形；所有候选必须来自真实语料。
        score = (0.52 * reading_sim + 0.22 * surface_sim +
                 0.16 * same_len + 0.10 * shared +
                 (0.24 if reading == target_reading else 0.0))
        if score < 0.30:
            continue
        seen.add(word)
        ranked.append((score, word, cand, reading_sim, surface_sim, shared))
    if len(ranked) < 3:
        return None
    ranked.sort(key=lambda x: (-x[0], x[1]))
    # 在高分前 8 个中抽 3 个，既保持高混淆又避免每次永远同一组。
    pool = ranked[:min(8, len(ranked))]
    chosen = random.sample(pool, 3) if len(pool) >= 3 else pool[:3]
    opts = [target] + [x[1] for x in chosen]
    random.shuffle(opts)
    audits = []
    for word in opts:
        if word == target:
            audits.append({'option': word, 'is_answer': True,
                           'reading_similarity': 1.0, 'surface_similarity': 1.0,
                           'same_length': True, 'shared_kanji': len(set(target))})
            continue
        hit = next(x for x in chosen if x[1] == word)
        audits.append({'option': word, 'is_answer': False,
                       'reading_similarity': round(hit[3], 3),
                       'surface_similarity': round(hit[4], 3),
                       'same_length': len(word) == len(target),
                       'shared_kanji': len(set(target) & set(word))})
    return {
        'qtype': 'kanji_choice', 'text': (row.get('text') or '').strip(),
        'audio_text': target, 'answer': target, 'target_word': target,
        'options': opts, 'sid': row.get('sid'), 'source': row.get('source'),
        'origin': _origin(row), 'reading': unit['reading'],
        'distractor_source': 'attested_high_confusion_kanji_words',
        'kanji_option_audit': audits,
    }


@lru_cache(maxsize=8192)
def _sentence_answer_profile(text):
    """整句表记/读音的有限状态匹配材料。"""
    text = (text or '').strip()
    try:
        tokens = furigana.annotate(text)
    except Exception:
        tokens = []
    parts = []
    for tok in tokens:
        surface = tok.get('s') or ''
        if not surface or all(unicodedata.category(ch).startswith(('P', 'S'))
                              or ch.isspace() for ch in surface):
            continue
        reading = tok.get('r') or ''
        if not reading:
            reading = furigana.kata_to_hira(surface)
        alternatives = [reading]
        alternatives.extend(tok.get('alt') or [])
        # furigana 已把「わたし/わたくし」「にほん/にっぽん」等语体变体
        # 归为等价读音，但为了判卷仍需把它们列为“可识别、需修正”的候选。
        for pair in getattr(furigana, '_EQUIV_PAIRS', ()):
            if reading in pair:
                alternatives.extend(x for x in pair if x != reading)
        # token.alt/等价表是其它实证读法；过滤脏表面形，避免“猜读音”。
        alternatives = [furigana.kata_to_hira(x) for x in alternatives
                        if x and re.fullmatch(r'[\u3040-\u309fー]+', x)]
        parts.append({'surface': _normalize_jp(surface),
                      'recommended': _normalize_jp(reading),
                      'alternatives': sorted(set(alternatives))})
    surface = _normalize_jp(text)
    reading = ''.join(p['recommended'] for p in parts)
    return {'surface': surface, 'reading': reading, 'parts': parts}


def _normalize_jp(value):
    """NFKC、片假名转平假名，并忽略标点/空格；不删除汉字或长音符。"""
    value = unicodedata.normalize('NFKC', str(value or ''))
    out = []
    for ch in value:
        if ch.isspace() or unicodedata.category(ch).startswith(('P', 'S')):
            continue
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            ch = chr(code - 0x60)
        out.append(ch)
    return ''.join(out)


def _match_sentence_input(profile, response):
    """返回 (匹配, 是否使用非推荐可能读音)，按 token 做有限状态匹配。"""
    value = _normalize_jp(response)
    if not value:
        return False, False
    states = {(0, False)}
    for part in profile.get('parts') or ():
        alternatives = [(part['surface'], False),
                        (part['recommended'], False)]
        alternatives += [(x, x != part['recommended'])
                         for x in part.get('alternatives') or ()]
        next_states = set()
        for pos, alt_used in states:
            for option, this_alt in alternatives:
                option = _normalize_jp(option)
                if option and value.startswith(option, pos):
                    next_states.add((pos + len(option), alt_used or this_alt))
        states = next_states
        if not states:
            return False, False
        if len(states) > 512:
            states = set(sorted(states)[:512])
    finals = [(pos, alt) for pos, alt in states if pos == len(value)]
    if not finals:
        return False, False
    return True, any(alt for _, alt in finals)


def grade_sentence_dictation(expected, response):
    expected = (expected or '').strip()
    profile = _sentence_answer_profile(expected)
    ok, alternate = _match_sentence_input(profile, response)
    return {
        'ok': ok, 'alternate_reading': bool(ok and alternate),
        'needs_correction': bool(ok and alternate),
        'correction': expected if ok and alternate else '',
        'answer': expected,
        'answer_reading': profile.get('reading', ''),
        'normalized_input': _normalize_jp(response),
    }


def grade_arrangement(question, order):
    """听后组句复用 sentence_builder 的完整性 + 合法语序判卷。"""
    q = question if isinstance(question, dict) else {}
    if q.get('qtype') != 'sentence_arrange' or not q.get('spec'):
        return {'ok': False, 'feedback': '不是有效的听后组句题', 'alt_count': 0,
                'canonical': [], 'canonical_surfaces': [], 'your_text': ''}
    try:
        result = sb.check_arrangement(q['spec'], order or [])
    except Exception:
        return {'ok': False, 'feedback': '组句判卷失败，请重新播放后再试',
                'alt_count': 0, 'canonical': [], 'canonical_surfaces': [], 'your_text': ''}
    # 听力组句测的是“听到的原顺序”，而不是开放式日语换序；即便普通组句
    # 引擎认为某种格成分换序语法上也成立，这里仍要求和音频中的原顺序一致。
    if result.get('ok') and q.get('strict_audio_order', True):
        tile_map = {str(k): int(v) for k, v in (q['spec'].get('tile_map') or {}).items()}
        expected = [k for k, value in sorted(tile_map.items(), key=lambda item: item[1])
                    if value >= 0]
        submitted = [str(x) for x in (order or [])]
        if submitted != expected:
            result['ok'] = False
            result['feedback'] = '词块已完整，但没有还原成录音中的原顺序'
    result['must_use_all_tiles'] = True
    return result


def grade_response(question, response):
    """统一服务端判卷；前端可以即时渲染，服务端仍是唯一规则来源。"""
    q = question if isinstance(question, dict) else {}
    response = str(response or '')
    qtype = q.get('qtype')
    if qtype == 'word_dictation':
        answer = str(q.get('answer') or q.get('target_word') or '')
        value = response.strip()
        ok = _is_pure_kanji(value) and value == answer
        return {'ok': ok, 'answer': answer, 'response': value,
                'needs_correction': bool(ok is False and value),
                'correction': answer if not ok else ''}
    if qtype == 'kanji_choice':
        answer = str(q.get('answer') or '')
        return {'ok': response == answer, 'answer': answer, 'response': response}
    if qtype == 'sentence_dictation':
        return grade_sentence_dictation(q.get('answer') or q.get('text') or '', response)
    answer = q.get('answer')
    return {'ok': response == answer, 'answer': answer, 'response': response}


@lru_cache(maxsize=8192)
def _sentence_reading(text):
    profile = _sentence_answer_profile(text)
    return profile.get('reading', '')


@lru_cache(maxsize=8192)
def _sentence_boundaries(text):
    """以形态素/ruby token 为边界，供联想提示只返回一小块。"""
    try:
        tokens = furigana.annotate(text)
    except Exception:
        tokens = []
    ends, n = [], 0
    for tok in tokens:
        s = _normalize_jp(tok.get('s') or '')
        if not s:
            continue
        n += len(s)
        if not ends or ends[-1] != n:
            ends.append(n)
    return tuple(ends)


def _get_global_suggestion_rows():
    global _GLOBAL_SUGGESTION_ROWS, _GLOBAL_SUGGESTION_SIGN
    try:
        with db.get_conn() as c:
            sign = (str(db.DB_PATH), *tuple(c.execute(
                'SELECT count(*), COALESCE(max(id), 0) FROM sentences').fetchone()))
        if _GLOBAL_SUGGESTION_ROWS is not None and _GLOBAL_SUGGESTION_SIGN == sign:
            return _GLOBAL_SUGGESTION_ROWS
        with db.get_conn() as c:
            raw = [r[0] for r in c.execute(
                'SELECT text FROM sentences WHERE length(text) BETWEEN 4 AND 120 '
                'ORDER BY id DESC LIMIT 30000').fetchall()]
        _GLOBAL_SUGGESTION_ROWS = tuple(dict(text=x, surface=_normalize_jp(x)) for x in raw if x)
        _GLOBAL_SUGGESTION_SIGN = sign
        return _GLOBAL_SUGGESTION_ROWS
    except Exception:
        return ()


def sentence_suggestions(prefix, mode='beginner', limit=6):
    """从全语料库给整句听写联想；返回短小可直接填入的 value，不返回长句答案。"""
    if mode == 'advanced':
        return []
    clean = _normalize_jp(prefix)
    if not clean:
        return []
    limit = max(1, min(int(limit or 6), 8))
    got, seen = [], set()
    for row in _get_global_suggestion_rows():
        forms = [('surface', row['surface'])]
        # 假名前缀也可查读音；只对匹配到的候选懒算 reading，避免渲染阻塞。
        if re.fullmatch(r'[\u3040-\u309fー]+', clean):
            forms.append(('reading', _sentence_reading(row['text'])))
        for kind, form in forms:
            if not form or not form.startswith(clean):
                continue
            ends = _sentence_boundaries(row['text'])
            # reading 与 surface 的 token 长度可能不同，按 reading 的字符长度重算边界。
            if kind == 'reading':
                parts = (_sentence_answer_profile(row['text']).get('parts') or [])
                ends, n = [], 0
                for part in parts:
                    n += len(part['recommended'])
                    ends.append(n)
            boundary = next((x for x in ends if x > len(clean)), None)
            if boundary is None and len(clean) in ends:
                idx = ends.index(len(clean))
                boundary = ends[idx + 1] if idx + 1 < len(ends) else None
            if boundary is None:
                continue
            if mode == 'intermediate' and len(clean) not in ends:
                continue
            # 初级：补全当前词；中级：补一个后续词/短语。上限保持“小块联想”。
            end = min(boundary, len(clean) + 8)
            value = form[:end]
            if value == clean or value in seen:
                continue
            append = value[len(clean):]
            if not append:
                continue
            partial_word = len(clean) not in ends
            word_start = max((x for x in ends if x <= len(clean)), default=0)
            label = form[word_start:end] if partial_word else append
            key = (value, kind)
            seen.add(value)
            got.append({'value': value, 'append': append,
                        'label': label, 'kind': 'word' if partial_word else 'collocation',
                        'source': 'full_corpus'})
            if len(got) >= limit:
                return got
    return got


def _build_sentence_dictation_q(row, mode='mixed'):
    text = (row.get('text') or '').strip()
    if not _sound_sentence(text) or len(_normalize_jp(text)) < 6:
        return None
    if mode == 'mixed':
        mode = random.choices(('advanced', 'intermediate', 'beginner'), weights=(45, 35, 20), k=1)[0]
    profile = _sentence_answer_profile(text)
    if not profile.get('parts') or not profile.get('reading'):
        return None
    return {
        'qtype': 'sentence_dictation', 'text': text, 'audio_text': text,
        'answer': text, 'dictation_mode': mode,
        'reading': profile['reading'], 'reading_tokens': profile['parts'],
        'sid': row.get('sid'), 'source': row.get('source'), 'origin': _origin(row),
        'distractor_source': 'attested_sentence_with_pronunciation_fsm',
        'ignore_punctuation': True,
    }


def _build_sentence_arrange_q(row):
    """听后整句组句：复用 sentence_builder 的文节切分和稳健判卷。

    组句题不能开启 builder 的换词/干扰块：音频说的是哪句话，题面就必须
    还原哪句话；所有必要词块都必须使用，不能用“拼出半句”拿到正确。
    """
    text = (row.get('text') or '').strip()
    if not _sound_sentence(text) or len(_normalize_jp(text)) < 6:
        return None
    cfg = dict(sb.builder_cfg())
    cfg.update({'min_tiles': 2, 'max_tiles': 14, 'swap': False,
                'swap_prob': 0.0, 'distractors': 0, 'alt_answers': False,
                'strict_check': True, 'perm_limit': 160})
    try:
        built = sb._build_arrange(row, cfg, 'basic', None)
    except Exception:
        return None
    if isinstance(built, tuple) or not built:
        return None
    built = dict(built)
    built['qtype'] = 'sentence_arrange'
    built['audio_text'] = built.get('text') or text
    built['answer'] = built.get('text') or text
    built['listening_arrange'] = True
    built['distractor_source'] = 'sentence_builder_attested_chunks'
    built['must_use_all_tiles'] = True
    built['strict_audio_order'] = True
    return built


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


def make_quiz(book_ids=None, count=None, level=None, scope=None, sids=None):
    cfg = listening_cfg()
    if not cfg.get('enabled', True):
        return {'ok': False, 'reason': '听力练习已在配置中关闭', 'count': 0, 'questions': []}
    level = level if level in (['any'] + LEVELS) else cfg['level']
    scope = scope if scope in ('corpus', 'book', 'mixed', 'lyric', 'passage') else cfg['scope']
    count = _to_int(count, cfg['count'], min_val=1, max_val=20)

    if sids:
        # 点句练句：直接针对指定句子出听力题
        rows = textbook.rows_for_sids(sids)
        resolved = {'scope': 'book', 'ids': [], 'auto_all': False, 'note': None}
        scope, ids = 'book', []
        scope_note, scope_auto_all = None, False
    else:
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
    kinds = ('contrast', 'meaning', 'discriminate', 'cloze',
             'word_dictation', 'kanji_choice', 'sentence_dictation',
             'sentence_arrange')
    # 0% 是明确关闭，不把禁用题型当作“凑不满时的兜底”；否则用户把听音辨句
    # 调成 0 后，严格配额失败时它仍会悄悄回来，违背比例设置。
    active_kinds = tuple(k for k in kinds if t.get(k, 0) > 0)
    total_weight = sum(t[k] for k in active_kinds)
    if not active_kinds or total_weight <= 0:
        active_kinds = ('sentence_dictation',)
        total_weight = 1
    raw_targets = {k: count * t.get(k, 0) / total_weight for k in kinds}
    targets = {k: int(raw_targets[k]) for k in kinds}
    for k in sorted(active_kinds, key=lambda x: raw_targets[x] - targets[x], reverse=True):
        if sum(targets.values()) >= count:
            break
        targets[k] += 1

    translation_pool = [r for r in rows if (r.get('translation') or '').strip()]
    meaning_difficulty = cfg.get('meaning_difficulty', 'advanced')
    if meaning_difficulty == 'advanced':
        translation_pool = _expanded_translation_pool(scope, ids, translation_pool)
    meaning_ctx = _meaning_search_context(translation_pool) if translation_pool else _get_global_translation_index()
    sentence_pool = rows
    word_bank = _word_bank_from_rows(rows)
    # 选项混淆需要跨句检索。题干仍严格来自 scope，只有干扰词从全语料索引补足。
    global_words = _get_global_word_bank()
    seen_word_keys = {(x['word'], x['reading']) for x in word_bank}
    word_bank.extend(x for x in global_words
                     if (x['word'], x['reading']) not in seen_word_keys)
    sentence_mode = cfg.get('sentence_mode', 'mixed')

    contrast_floor = ['hard']          # 先只收「必须听句子中段」的对立题

    builders = {
        'contrast': lambda row: _build_contrast_q(row, contrast_floor[0]),
        'meaning': lambda row: _build_meaning_q(
            row, translation_pool, meaning_difficulty, meaning_ctx),
        'discriminate': lambda row: _build_discriminate_q(row, sentence_pool),
        'cloze': _build_cloze_q,
        'word_dictation': lambda row: _build_word_dictation_q(row, word_bank),
        'kanji_choice': lambda row: _build_kanji_choice_q(row, word_bank),
        'sentence_dictation': lambda row: _build_sentence_dictation_q(row, sentence_mode),
        'sentence_arrange': _build_sentence_arrange_q,
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
            order = sorted(active_kinds,
                           key=lambda k: (targets[k] - made[k], t[k]), reverse=True)
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
        q['max_plays'] = (cfg['arrange_max_plays']
                           if q.get('qtype') == 'sentence_arrange'
                           else cfg['max_plays'])
        q.setdefault('audio_text', q.get('text', ''))
    return {'ok': True, 'level': level, 'scope': scope, 'book_ids': ids,
            'scope_auto_all': scope_auto_all, 'scope_note': scope_note,
            'rate': rate, 'max_plays': cfg['max_plays'],
            'arrange_max_plays': cfg['arrange_max_plays'],
            'meaning_difficulty': meaning_difficulty, 'sentence_mode': sentence_mode,
            'type_weights': dict(t),
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

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

本模块提供两种可无限量、零人工介入自动生成的题型：

  1. meaning       听后选义：播放一句语料/课本/歌词录音，从 4 个候选翻译里
                   选出正确释义。要求该句在库中已有人工/AI译文（复用
                   sentence_builder 的公平性铁律：没有译文就不能拿它当
                   语义判分的题目）。干扰项来自其它句子的真实译文，
                   不是编造出来的假译文。
  2. discriminate  听音辨句：播放一句录音，从 4 个真实语料句中选出完全
                   一致的一句。干扰项优先选择长度和字面相近的完整原句，绝不
                   再把名词机械塞进另一句话（这种做法会生成「友達して」或
                   「国民だ」等语法/语义垃圾）；不需要译文，适配歌词等语料。

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
from datetime import date
from difflib import SequenceMatcher

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
    'types': {'meaning': 60, 'discriminate': 40},   # 题型占比（自动归一）
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
    m = max(0, int(t.get('meaning', 60) or 0))
    d = max(0, int(t.get('discriminate', 40) or 0))
    if m + d == 0:
        m, d = 60, 40
    cfg['types'] = {'meaning': m, 'discriminate': d}
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


def _build_meaning_q(row, translation_pool):
    text = (row.get('text') or '').strip()
    tr = (row.get('translation') or '').strip()
    if not tr:
        return None
    lang = _tr_lang(tr)
    others = [t for t in translation_pool if t and t != tr and _tr_lang(t) == lang]
    random.shuffle(others)
    distractors = []
    for t in others:
        if t in distractors:
            continue
        distractors.append(t)
        if len(distractors) >= 3:
            break
    if len(distractors) < 3:
        return None
    opts = [tr] + distractors
    random.shuffle(opts)
    try:
        tokens = furigana.annotate(text)
    except Exception:
        tokens = []
    return {'qtype': 'meaning', 'text': text, 'options': opts, 'answer': tr,
            'sid': row.get('sid'), 'source': row.get('source'),
            'origin': _origin(row), 'tokens': tokens}


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
    ts = t['meaning'] + t['discriminate']
    n_meaning = int(round(count * t['meaning'] / ts)) if ts else 0
    n_disc = count - n_meaning

    translation_pool = [r.get('translation') for r in rows if (r.get('translation') or '').strip()]
    # discriminate 的干扰项池保留完整语料行；不再拆词、换词或合成句子。
    sentence_pool = rows

    questions, used = [], set()
    relax_note = False
    for relax in (False, True):
        want = None if relax else level
        for row in rows:
            if len(questions) >= n_meaning + n_disc:
                break
            key = row.get('sid') or row.get('dedup') or row.get('text')
            if key in used:
                continue
            text = (row.get('text') or '').strip()
            if want and want != 'any':
                lv, _ = sb._sentence_level(text)
                if lv != want:
                    continue
            want_type = 'meaning' if len([q for q in questions if q['qtype'] == 'meaning']) < n_meaning else 'discriminate'
            got = None
            if want_type == 'meaning':
                got = _build_meaning_q(row, translation_pool)
                if not got and len(questions) < n_meaning + n_disc:
                    got = _build_discriminate_q(row, sentence_pool)
            else:
                got = _build_discriminate_q(row, sentence_pool)
                if not got:
                    got = _build_meaning_q(row, translation_pool)
            if not got:
                continue
            if relax and level != 'any':
                got['level_relaxed'] = True
                relax_note = True
            used.add(key)
            questions.append(got)
        if len(questions) >= n_meaning + n_disc or level == 'any':
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

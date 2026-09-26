# -*- coding: utf-8 -*-
"""基于证据中心设计（ECD）的综合日语测评。

这不是把已有挖空题简单加难，而是把「构念→任务→证据」写进每道题：
* language_knowledge: 汉字读音、语境语法（局部语言知识）
* contextual_use: 在完整语境中辨别意义（语言使用）
* reading: 理解完整文本并选择释义（读解）

自动题只测能够可靠自动评分的接受性能力；写作、口语不会被选择题分数冒充。
旧的 cloze / sentence builder 保留为 foundation 模式，本模块提供
proficiency（N级备考）和 academic（日语专业/学术）蓝图。
"""
import hashlib
import json
import random
import re
import secrets
import threading
import time
from collections import Counter, defaultdict

import db
import grammar
import textbook

LEVEL_ORDER = {'N5': 1, 'N4': 2, 'N3': 3, 'N2': 4, 'N1': 5}

BLUEPRINTS = {
    'foundation': {
        'label': '基础巩固',
        'description': '保留原算法，集中检索单个形式；适合初学、错题补救。',
        'weights': {'grammar_context': 60, 'kanji_reading': 40},
        'min_level': 'N5',
    },
    'proficiency': {
        'label': 'N级综合',
        'description': '参照JLPT构成，语言知识与完整语境读解并重。',
        'weights': {'grammar_context': 35, 'kanji_reading': 25, 'meaning_in_context': 40},
        'min_level': 'N3',
    },
    'academic': {
        'label': '专业·学术',
        'description': '提高语篇与抽象文本比重；局部助词/时态不单独代表高级能力。',
        'weights': {'grammar_context': 20, 'kanji_reading': 15, 'meaning_in_context': 65},
        'min_level': 'N2',
    },
}

TYPE_META = {
    'grammar_context': ('语境语法', 'language_knowledge', '在完整句境中辨别句型功能与接续'),
    'kanji_reading': ('汉字读音', 'language_knowledge', '根据词内语境辨别汉字词读音'),
    'meaning_in_context': ('语境理解', 'reading', '理解完整文本的主要意义，而非孤立形式'),
}


def blueprint(mode='proficiency'):
    mode = mode if mode in BLUEPRINTS else 'proficiency'
    b = dict(BLUEPRINTS[mode])
    b['mode'] = mode
    b['types'] = {k: {'label': TYPE_META[k][0], 'domain': TYPE_META[k][1],
                       'evidence': TYPE_META[k][2], 'weight': w}
                  for k, w in b['weights'].items()}
    b['limitations'] = [
        '自动客观题只推断阅读与语言知识，不声称测得口语或写作产出能力',
        '题库来自用户语料，题源质量与翻译质量会影响题目质量',
        '分数用于形成性诊断，不等同于官方JLPT换算分',
    ]
    return b


def _rows(limit=1500, min_chars=8, translated=False):
    where = ["length(text)>=?"]
    args = [min_chars]
    if translated:
        where.append("translation IS NOT NULL AND trim(translation)!=''")
    with db.get_conn() as c:
        rows = c.execute(
            'SELECT id,text,translation,tokens,source FROM sentences WHERE ' +
            ' AND '.join(where) + ' ORDER BY id DESC LIMIT ?', args + [limit]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d['tokens'] = json.loads(d.get('tokens') or '[]')
        except Exception:
            d['tokens'] = []
        if grammar.is_sentence_grammatically_sound(d['text']):
            out.append(d)
    return out


def _alloc(total, weights):
    total = max(3, min(int(total or 12), 40))
    raw = {k: total * v / sum(weights.values()) for k, v in weights.items()}
    n = {k: int(v) for k, v in raw.items()}
    for k, _ in sorted(raw.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True):
        if sum(n.values()) >= total:
            break
        n[k] += 1
    return n


def _base(qtype, level, prompt, source, sid):
    label, domain, evidence = TYPE_META[qtype]
    return {'type': qtype, 'type_label': label, 'domain': domain, 'level': level,
            'prompt': prompt, 'source': source, 'sid': sid, 'evidence': evidence,
            'scoring': 'selected_response', 'points': 1}


def _shuffle_options(answer, distractors, rng):
    opts, seen = [], set()
    for x in [answer] + list(distractors):
        x = (x or '').strip()
        if x and x not in seen:
            seen.add(x); opts.append(x)
    if len(opts) < 4:
        return None
    opts = opts[:4]
    rng.shuffle(opts)
    return opts


def _reading_questions(rows, need, rng):
    candidates, reading_pool = [], defaultdict(set)
    for r in rows:
        words = {}
        for t in r['tokens']:
            w, rd = t.get('w'), t.get('wr') or t.get('r')
            if w and rd and re.search(r'[一-龯々]', w) and re.fullmatch(r'[ぁ-ゖー]+', rd):
                words[(w, rd)] = True
                reading_pool[max(1, len(rd))].add(rd)
        for w, rd in words:
            if 1 <= len(w) <= 8 and r['text'].count(w) == 1:
                candidates.append((r, w, rd))
    rng.shuffle(candidates)
    out, used = [], set()
    all_readings = sorted({x for s in reading_pool.values() for x in s})
    for r, word, answer in candidates:
        key = (r['id'], word)
        if key in used:
            continue
        near = list(reading_pool.get(len(answer), set()) - {answer})
        rng.shuffle(near)
        fall = [x for x in all_readings if x != answer and x not in near]
        opts = _shuffle_options(answer, near + fall, rng)
        if not opts:
            continue
        q = _base('kanji_reading', 'N4', f'文中「{word}」的读音是哪一项？', r['source'], r['id'])
        q.update({'text': r['text'], 'focus': word, 'answer': answer, 'options': opts,
                  'explanation': f'「{word}」在本句中读作「{answer}」。'})
        out.append(q); used.add(key)
        if len(out) >= need: break
    return out


def _meaning_questions(rows, need, level, rng):
    usable = [r for r in rows if r.get('translation') and 10 <= len(r['text']) <= 180
              and 5 <= len(r['translation']) <= 300]
    rng.shuffle(usable)
    translations = [r['translation'].strip() for r in usable]
    out = []
    for r in usable:
        answer = r['translation'].strip()
        # 长度相近可减少凭选项长度猜题；不同句来源避免改写时引入伪正确答案。
        distractors = sorted((x for x in translations if x != answer),
                             key=lambda x: abs(len(x) - len(answer)))[:12]
        rng.shuffle(distractors)
        opts = _shuffle_options(answer, distractors, rng)
        if not opts: continue
        q = _base('meaning_in_context', level, '选择最符合全文意思的一项。', r['source'], r['id'])
        q.update({'text': r['text'], 'answer': answer, 'options': opts,
                  'explanation': '应先确定主干、修饰关系、否定/条件与说话者立场，再核对整体意义。',
                  'translation_language': 'source-provided'})
        out.append(q)
        if len(out) >= need: break
    return out


def _grammar_questions(need, level, rng, book_ids=None):
    """复用旧引擎的候选/接续门禁，但自行确定抽样，保证 seed 可复现。"""
    min_o = LEVEL_ORDER.get(level, 3)
    rows = _rows(limit=1200, translated=False)
    pool = []
    for r in rows:
        meta = {'sid': r['id'], 'translation': r.get('translation'),
                'source': r.get('source', ''), 'book_id': None,
                'book_title': None, 'lesson': None}
        pool.extend(textbook._cloze_candidates(r['text'], min_o, meta))
    rng.shuffle(pool)
    pool_by_level = defaultdict(list)
    for p in pool: pool_by_level[p['level']].append(p['answer'])
    out, used_sid, used_answer = [], set(), set()
    for p in pool:
        if p['sid'] in used_sid or p['answer'] in used_answer: continue
        state = random.getstate()
        random.seed(rng.randrange(0, 2**63))
        try:
            distractors = textbook._cloze_distractors(
                p['name'], p['answer'], p['level'], pool_by_level,
                after=p['after'], attr=p.get('attr'), before=p['before'],
                base_name=p.get('base_name'))
        finally:
            random.setstate(state)
        opts = _shuffle_options(p['answer'], distractors, rng)
        if not opts: continue
        q = _base('grammar_context', p.get('level', level),
                  '结合全句语义与接续，选择最恰当的一项。', p.get('source', 'corpus'), p.get('sid'))
        q.update({k: p.get(k) for k in ('text','before','after','answer','translation',
                                        'name','structure','explain')})
        q['options'] = opts
        q['explanation'] = p.get('explain') or '根据语义、接续和语体综合判断。'
        out.append(q); used_sid.add(p['sid']); used_answer.add(p['answer'])
        if len(out) >= need: break
    return out


def audit_item(q):
    """出题前最低质量门禁；返回机器可解释的问题列表。"""
    issues = []
    if not q.get('text') or len(q['text'].strip()) < 4: issues.append('stem_too_short')
    opts = q.get('options') or []
    if len(opts) != 4 or len(set(opts)) != 4: issues.append('options_not_four_unique')
    if q.get('answer') not in opts: issues.append('answer_missing')
    if not q.get('evidence'): issues.append('construct_unspecified')
    if q.get('type') == 'meaning_in_context' and not q.get('answer'): issues.append('no_reference_meaning')
    return issues


def make_exam(mode='proficiency', level=None, count=12, seed=None, book_ids=None):
    mode = mode if mode in BLUEPRINTS else 'proficiency'
    bp = blueprint(mode)
    level = level if level in LEVEL_ORDER else bp['min_level']
    rng = random.Random(seed if seed is not None else time.time_ns())
    allocation = _alloc(count, bp['weights'])
    rows = _rows(translated=False)
    translated = [r for r in rows if r.get('translation')]
    makers = {
        'grammar_context': lambda n: _grammar_questions(n, level, rng, book_ids),
        'kanji_reading': lambda n: _reading_questions(rows, n, rng),
        'meaning_in_context': lambda n: _meaning_questions(translated, n, level, rng),
    }
    questions, shortfalls = [], {}
    for typ, n in allocation.items():
        made = makers[typ](n)
        valid = [q for q in made if not audit_item(q)]
        questions.extend(valid)
        if len(valid) < n: shortfalls[typ] = n - len(valid)
    rng.shuffle(questions)
    questions = questions[:max(3, min(int(count or 12), 40))]
    for i, q in enumerate(questions, 1):
        raw = f"{q.get('type')}|{q.get('sid')}|{q.get('focus','')}|{q.get('answer')}"
        q['item_uid'] = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
        q['id'] = f'{mode}-{i}'
    actual = Counter(q['type'] for q in questions)
    return {'ok': bool(questions), 'mode': mode, 'level': level, 'count': len(questions),
            'requested': int(count), 'questions': questions, 'blueprint': bp,
            'allocation': allocation, 'actual': dict(actual), 'shortfalls': shortfalls,
            'validity_note': '本测验为形成性诊断；口语与写作须另用表现性任务和量规评价。'}


def score_exam(answers):
    """客户端只回传最小题目证据，按领域/题型诊断；不伪造JLPT量表分。"""
    by_type, by_domain = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for a in answers or []:
        ok = bool(a.get('ok'))
        typ, domain = a.get('type', 'unknown'), a.get('domain', 'unknown')
        by_type[typ][1] += 1; by_domain[domain][1] += 1
        if ok: by_type[typ][0] += 1; by_domain[domain][0] += 1
    def pack(d):
        return {k: {'correct': v[0], 'total': v[1], 'rate': round(v[0]/v[1], 3) if v[1] else 0}
                for k, v in d.items()}
    total = len(answers or []); correct = sum(bool(a.get('ok')) for a in answers or [])
    result = {'ok': True, 'correct': correct, 'total': total,
              'rate': round(correct/total, 3) if total else 0,
              'by_type': pack(by_type), 'by_domain': pack(by_domain)}
    db.log('proficiency_exam', f'综合测评：{correct}/{total}')
    return result


# ----------------------------------------------------------------
# 服务端考试会话：答案不下发，避免“客户端自报 ok”；会话仅短期驻留内存。
# 长期仅保存匿名聚合项目统计，不保存作答文本或个人标识。
# ----------------------------------------------------------------
_SESSIONS = {}
_SESSION_LOCK = threading.RLock()
_SESSION_TTL = 3 * 60 * 60
_ITEM_STATS_KEY = 'proficiency_item_stats_v1'


def _purge_sessions(now=None):
    now = now or time.time()
    for token in list(_SESSIONS):
        if now - _SESSIONS[token]['created'] > _SESSION_TTL:
            _SESSIONS.pop(token, None)


def _public_item(q):
    hidden = {'answer', 'explanation', 'explain', 'translation'}
    return {k: v for k, v in q.items() if k not in hidden}


def start_exam(mode='proficiency', level=None, count=12, seed=None, book_ids=None):
    exam = make_exam(mode, level, count, seed, book_ids)
    if not exam.get('ok'):
        return exam
    token = secrets.token_urlsafe(24)
    with _SESSION_LOCK:
        _purge_sessions()
        _SESSIONS[token] = {'created': time.time(), 'exam': exam, 'answered': False}
    public = {k: v for k, v in exam.items() if k != 'questions'}
    public.update({'session_id': token, 'expires_in': _SESSION_TTL,
                   'questions': [_public_item(q) for q in exam['questions']]})
    return public


def _load_item_stats():
    try:
        return json.loads(db.get_setting(_ITEM_STATS_KEY, '') or '{}')
    except Exception:
        return {}


def _save_observations(pairs):
    stats = _load_item_stats()
    now = int(time.time())
    for q, a, ok in pairs:
        uid = q['item_uid']
        s = stats.setdefault(uid, {'type': q['type'], 'sid': q.get('sid'),
                                   'focus': q.get('focus') or q.get('name'),
                                   'attempts': 0, 'correct': 0, 'options': {},
                                   'time_sum_ms': 0, 'confidence_sum': 0.0,
                                   'confidence_n': 0, 'last_seen': now})
        s['attempts'] += 1
        s['correct'] += int(ok)
        chosen = str(a.get('choice', ''))[:300]
        s['options'][chosen] = s['options'].get(chosen, 0) + 1
        try:
            elapsed = max(0, min(int(a.get('time_ms') or 0), 30 * 60 * 1000))
        except (TypeError, ValueError):
            elapsed = 0
        s['time_sum_ms'] += elapsed
        try:
            confidence = float(a.get('confidence'))
            if 0 <= confidence <= 1:
                s['confidence_sum'] += confidence; s['confidence_n'] += 1
        except (TypeError, ValueError):
            pass
        s['last_seen'] = now
    # 防止设置无限增长；保留最近出现的五千道题。
    if len(stats) > 5000:
        keep = sorted(stats, key=lambda k: stats[k].get('last_seen', 0), reverse=True)[:5000]
        stats = {k: stats[k] for k in keep}
    db.set_setting(_ITEM_STATS_KEY, json.dumps(stats, ensure_ascii=False))


def submit_exam(session_id, answers):
    with _SESSION_LOCK:
        _purge_sessions()
        sess = _SESSIONS.get(session_id)
        if not sess:
            return {'ok': False, 'error': '考试会话不存在或已过期'}
        if sess['answered']:
            return {'ok': False, 'error': '本试卷已经提交，不能重复计分'}
        sess['answered'] = True
        exam = sess['exam']
    by_id = {q['id']: q for q in exam['questions']}
    seen, pairs, diagnostic = set(), [], []
    for a in answers or []:
        qid = a.get('id')
        if qid in seen or qid not in by_id: continue
        seen.add(qid); q = by_id[qid]
        ok = a.get('choice') == q.get('answer')
        pairs.append((q, a, ok))
        diagnostic.append({'id': qid, 'item_uid': q['item_uid'], 'type': q['type'],
                           'domain': q['domain'], 'ok': ok, 'choice': a.get('choice'),
                           'answer': q.get('answer'), 'explanation': q.get('explanation'),
                           'name': q.get('name')})
    _save_observations(pairs)
    scored = score_exam(diagnostic)
    scored.update({'mode': exam['mode'], 'level': exam['level'], 'results': diagnostic,
                   'unanswered': len(exam['questions']) - len(seen)})
    return scored


def item_analysis(min_attempts=1):
    stats = _load_item_stats(); rows = []
    for uid, s in stats.items():
        n = s.get('attempts', 0)
        if n < min_attempts: continue
        option_counts = s.get('options', {})
        unused = [o for o, c in option_counts.items() if not c]
        rows.append({**s, 'item_uid': uid, 'p_value': round(s.get('correct', 0)/n, 3),
                     'avg_time_ms': round(s.get('time_sum_ms', 0)/n),
                     'avg_confidence': round(s.get('confidence_sum', 0)/s.get('confidence_n', 1), 3)
                     if s.get('confidence_n') else None,
                     'observed_distractors': option_counts, 'unused_observed': unused,
                     'review_flags': (['too_easy'] if n >= 10 and s.get('correct',0)/n > .95 else []) +
                                     (['too_hard'] if n >= 10 and s.get('correct',0)/n < .2 else [])})
    rows.sort(key=lambda x: (-x['attempts'], x['p_value']))
    return {'ok': True, 'items': rows, 'note': 'p值仅为经典测验难度；样本不足时不得用于高风险决策。'}

# -*- coding: utf-8 -*-
"""AI 辅助起草听力/阅读理解题（v21）
================================================================
为什么需要这个模块（对应 QUESTION_SOURCE_POLICY.md 的"完整性"缺口）
----------------------------------------------------------------
sentence_builder / listening 两个模块能做到的自动出题，天花板是「句子长什么
样」的机械性质（词形、语序、词性替换）。它们**理解不了**句子在说什么，所以
出不了「说话人接下来会怎么做」「这段话的主旨是什么」这类真正的理解题——
不是实现细节的缺失，是规则引擎的能力边界。

要跨过这条边界，唯一诚实的办法是引入真正"读得懂"文本的模型（LLM）来起草，
再由人复核。这正是本模块做的事，且严格遵守三条红线：

  1. 不静默：调用 AI 失败（没配置 key / 网络错误 / 返回格式不对）一律
     报错，绝不偷偷退化成规则引擎题或编造答案（复用 ai_translate.py 已经
     验证过的"在线 Provider 出错直接报错"哲学）；
  2. 不跳过复核：起草的每一题落库时 status 强制为 'draft'。只有人工调用
     review_draft() 并勾选检查项，才能把某道题标为 approved；服务端不会
     在任何"自动组卷"路径里悄悄把 draft 题当 approved 用；
  3. 不脱离原文：出题时把原文/译文整段作为唯一依据交给模型，并在校验阶段
     做一次"证据必须能在原文或译文里找到"的机器检查（挡不住模型编造细节，
     但能挡住证据栏本身文不对题这种低级错误）——机器检查永远只是门禁，
     不是"内容正确"的证明，这点与 assessment_bank.py 的立场完全一致。

题源（based_on）—— 只用本地已有、且在 CORPUS_ARCHITECTURE.md 白名单内的文本：
  - sentence：单句 + 其译文（语料库/课本），适合「细节复述/语气判断/指代」
    这类不需要跨句上下文的理解题；
  - passage：同一课本课文（按 book_sentences.idx 顺序）或同一首歌词
    （按行序）拼成的连续段落，适合「主旨/前后呼应/情节推断」——这才是
    真正意义上「更难」的理解题，规则引擎完全做不到。

起草出的题绝不会自动进入 sentence_builder / listening 的组卷池；它们只在
被人工 approve 之后，才能被 approved_items() 取出用于练习。
"""
import json
import re
import time

import ai_translate
import db

DEFAULT_GEN_MAX_TOKENS = 1400
DEFAULT_GEN_TEMPERATURE = 0.4
DEFAULT_GEN_TIMEOUT = 60

_PROCESS_SET = {'retrieve', 'apply_condition', 'infer', 'main_idea', 'argument_role',
                'integrate_commonality', 'integrate_difference', 'evaluate_claim',
                'detail', 'paraphrase', 'register', 'referent'}

_SENTENCE_SYSTEM = (
    '你是日语能力测评编写者。给定一句日语原文和它的参考译文，只依据这句话本身'
    '出一道单选理解题（可以问细节复述、敬体/语气判断、指代对象、说话人意图，'
    '不要考翻译技巧本身，不要引入原文没有的信息）。'
    '严格只输出 JSON，不要解释文字、不要代码块标记，不要在 JSON 前后添加任何字符。'
    'JSON 结构：{"process":"detail|paraphrase|register|referent|infer",'
    '"prompt":"...","options":["...","...","...","..."],"answer":0,"rationale":"..."}。'
    'options 必须是 4 个不重复的中文选项，且仅有一个正确；answer 是正确选项从 0 开始的下标；'
    'rationale 必须引用原文或译文中的具体内容作为依据。'
)

_PASSAGE_SYSTEM = (
    '你是日语能力测评编写者。给定一段连续的日语文本（可能是课文或歌词，已标注'
    '句序 s1/s2/…）和可用的参考译文，请出 2 到 3 道单选理解题，覆盖主旨、'
    '细节定位、前后呼应或合理推断中的不同能力点，不要互相重复，不要考翻译本身。'
    '严格只输出 JSON，不要解释文字、不要代码块标记。'
    'JSON 结构：{"items":[{"process":"main_idea|retrieve|infer|integrate_commonality|'
    'integrate_difference|argument_role","evidence":["s1","s2"],"prompt":"...",'
    '"options":["...","...","...","..."],"answer":0,"rationale":"..."}, ...]}。'
    'evidence 是本题依据的句序标签数组（如 ["s2","s3"]）；options 4 个不重复中文选项，'
    '仅一个正确；rationale 必须具体引用文本内容。'
)

_FENCE_RE = re.compile(r'^```[a-zA-Z]*\s*|\s*```$')


def _gen_config():
    """复用 ai_translate 已配置的 Provider/Key/模型（同一套 BYO Key，不用户
    再配置一遍），只针对"起草题目需要更长输出"这一点覆盖 max_tokens/温度。"""
    base = ai_translate.load_config()
    return ai_translate.AIConfig(
        provider=base.provider, model=base.model, api_key=base.api_key,
        base_url=base.base_url, lang=base.lang,
        max_tokens=DEFAULT_GEN_MAX_TOKENS, temperature=DEFAULT_GEN_TEMPERATURE,
        timeout=max(base.timeout, DEFAULT_GEN_TIMEOUT))


def _strip_fence(t):
    t = (t or '').strip()
    if t.startswith('```'):
        t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
        t = re.sub(r'\s*```\s*$', '', t)
    return t.strip()


def _mock_json(kind, text):
    """离线可用的确定性 mock（仅测试/演示用，绝不冒充真实模型质量）。"""
    if kind == 'sentence':
        return json.dumps({'process': 'detail', 'prompt': f'[MOCK] 关于「{text[:10]}…」，下列哪项符合原文？',
                           'options': ['[MOCK]正确复述', '[MOCK]无关选项A', '[MOCK]无关选项B', '[MOCK]无关选项C'],
                           'answer': 0, 'rationale': f'[MOCK] 依据原文「{text[:15]}」'}, ensure_ascii=False)
    return json.dumps({'items': [
        {'process': 'main_idea', 'evidence': ['s1'], 'prompt': '[MOCK] 这段话主要在说什么？',
         'options': ['[MOCK]正确概括', '[MOCK]无关A', '[MOCK]无关B', '[MOCK]无关C'],
         'answer': 0, 'rationale': '[MOCK] 依据 s1'}]}, ensure_ascii=False)


def _chat(cfg, system_prompt, user_content, _http_post=None):
    """通用 chat completion 调用（与 ai_translate.translate_text 共用同一套
    错误处理哲学：在线 Provider 任何失败都直接返回 ok=False，绝不静默降级）。"""
    if cfg.provider == 'mock':
        return True, None, 'mock-json-placeholder'   # 由调用方按 kind 生成 mock 内容
    if not cfg.api_key:
        return False, f'{cfg.provider} 未配置 API Key（请先在 AI 翻译面板配置，起草功能复用同一把 key）', None
    if not cfg.base_url:
        return False, f'{cfg.provider} 未配置接口地址 base_url', None
    url = cfg.base_url + '/chat/completions'
    payload = {'model': cfg.model,
               'messages': [{'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': user_content}],
               'stream': False}
    if cfg.provider == 'spark':
        payload['max_completion_tokens'] = cfg.max_tokens
    else:
        payload['max_tokens'] = cfg.max_tokens
        payload['temperature'] = cfg.temperature
    headers = {'Authorization': f'Bearer {cfg.api_key}', 'Content-Type': 'application/json'}
    try:
        if _http_post is not None:
            status, data = _http_post(url, headers=headers, payload=payload, timeout=cfg.timeout)
        else:
            import requests
            r = requests.post(url, headers=headers, json=payload, timeout=cfg.timeout)
            status, data = r.status_code, r.json()
    except Exception as e:
        return False, f'请求失败（{type(e).__name__}: {e}）', None
    if status != 200:
        msg = (data.get('error', {}) or {}).get('message', '') if isinstance(data, dict) else ''
        return False, f'接口返回 {status}：{msg or data}', None
    if isinstance(data, dict) and 'code' in data and data.get('code') not in (0, '0', None):
        return False, f"业务错误 {data.get('code')}：{data.get('message') or '未知错误'}", None
    try:
        raw = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return False, f'接口返回结构异常：{str(data)[:200]}', None
    return True, None, raw


def _parse_item_json(raw, kind, fallback_text):
    if raw == 'mock-json-placeholder':
        raw = _mock_json(kind, fallback_text)
    clean = _strip_fence(raw)
    try:
        return json.loads(clean), None
    except Exception as e:
        return None, f'模型输出不是合法 JSON（已裁剪围栏后仍解析失败：{e}）：{clean[:200]}'


def _grounded(rationale, *texts):
    """轻量"证据落地"检查：rationale 至少要和原文/译文有一定重叠，不能通篇
    空话。挡不住模型编造细节，但能挡住证据栏文不对题这种低级错误——机器检查
    永远只是门禁，不是"内容正确"的证明。"""
    if not rationale or len(rationale.strip()) < 4:
        return False
    hay = ''.join(t or '' for t in texts)
    # 取 rationale 里最长的一段连续汉字/假名子串，检查是否出现在原文/译文中
    runs = re.findall(r'[\u3040-\u30ff\u4e00-\u9fff]{3,}', rationale)
    if not runs:
        return True   # rationale 是纯解释性文字（如全英文/纯逻辑陈述）时不强求
    return any(run in hay for run in runs)


def _validate_options(options, answer):
    issues = []
    if not isinstance(options, list) or len(options) != 4 or len(set(options)) != 4:
        issues.append('options_invalid')
    if not isinstance(answer, int) or not (isinstance(options, list) and 0 <= answer < len(options)):
        issues.append('answer_invalid')
    return issues


def generate_sentence_item(sid, text, translation, source='', level=None, config=None, _http_post=None):
    """给定单句 + 译文，起草一道理解题（status 落库为 draft）。"""
    text = (text or '').strip()
    translation = (translation or '').strip()
    if not text:
        return {'ok': False, 'error': '原文为空'}
    if not translation:
        return {'ok': False, 'error': '这句话没有译文——没有语义锚点，AI 起草的题无法核验对错，拒绝生成'}
    cfg = config or _gen_config()
    user = f'原文：{text}\n参考译文：{translation}'
    ok, err, raw = _chat(cfg, _SENTENCE_SYSTEM, user, _http_post=_http_post)
    if not ok:
        return {'ok': False, 'error': err}
    obj, perr = _parse_item_json(raw, 'sentence', text)
    if perr:
        return {'ok': False, 'error': perr}
    issues = _validate_options(obj.get('options'), obj.get('answer'))
    if not obj.get('prompt') or not str(obj.get('prompt')).strip():
        issues.append('prompt_empty')
    if not obj.get('rationale') or not str(obj.get('rationale')).strip():
        issues.append('rationale_empty')
    elif not _grounded(obj.get('rationale'), text, translation):
        issues.append('rationale_not_grounded')
    process = obj.get('process') if obj.get('process') in _PROCESS_SET else 'detail'
    if issues:
        return {'ok': False, 'error': '模型输出未通过结构校验：' + ','.join(issues), 'raw': obj}
    payload = {'skill': 'listening', 'kind': 'sentence', 'level': level, 'genre': 'sentence',
              'text': text, 'translation': translation,
              'source': {'kind': 'ai_generated', 'title': None, 'author': None, 'url': None,
                         'license': None, 'provider': cfg.provider, 'model': cfg.model,
                         'generated_at': time.time(), 'based_on_sid': sid, 'based_on_source': source},
              'items': [{'id': 'q1', 'process': process, 'evidence': ['text'],
                        'prompt': obj['prompt'], 'options': obj['options'],
                        'answer': obj['answer'], 'rationale': obj['rationale']}]}
    draft_id = db.add_ai_draft('listening', payload, level=level, genre='sentence',
                               based_on_sid=sid, based_on_source=source,
                               provider=cfg.provider, model=cfg.model)
    return {'ok': True, 'draft_id': draft_id, 'payload': payload}


def generate_passage_item(text, sids=None, translation_hint='', source='', title='',
                          level=None, skill='reading', config=None, _http_post=None):
    """给定一段连续文本（课文/歌词，已用 s1/s2/… 标好句序），起草 2-3 道理解题。"""
    lines = [l for l in (text or '').split('\n') if l.strip()]
    if len(lines) < 2:
        return {'ok': False, 'error': '段落至少需要 2 行连续文本才有"上下文理解"的意义'}
    labeled = '\n'.join(f's{i+1}: {l}' for i, l in enumerate(lines))
    cfg = config or _gen_config()
    user = f'标题：{title or "（无）"}\n正文（已标句序）：\n{labeled}'
    if translation_hint:
        user += f'\n参考译文/大意：{translation_hint}'
    ok, err, raw = _chat(cfg, _PASSAGE_SYSTEM, user, _http_post=_http_post)
    if not ok:
        return {'ok': False, 'error': err}
    obj, perr = _parse_item_json(raw, 'passage', text)
    if perr:
        return {'ok': False, 'error': perr}
    items_in = obj.get('items') if isinstance(obj, dict) else None
    if not isinstance(items_in, list) or not (1 <= len(items_in) <= 5):
        return {'ok': False, 'error': '模型未返回 1-5 道合理数量的 items', 'raw': obj}
    items_out, issues = [], []
    valid_labels = {f's{i+1}' for i in range(len(lines))}
    for i, it in enumerate(items_in):
        qi = f'q{i + 1}'
        opt_issues = _validate_options(it.get('options'), it.get('answer'))
        if opt_issues:
            issues.append(f'{qi}:' + ','.join(opt_issues))
            continue
        if not it.get('prompt') or not str(it.get('prompt')).strip():
            issues.append(f'{qi}:prompt_empty')
            continue
        rationale = it.get('rationale') or ''
        if not rationale.strip() or not _grounded(rationale, text, translation_hint):
            issues.append(f'{qi}:rationale_not_grounded')
            continue
        evidence = [e for e in (it.get('evidence') or []) if e in valid_labels] or ['s1']
        process = it.get('process') if it.get('process') in _PROCESS_SET else 'retrieve'
        items_out.append({'id': qi, 'process': process, 'evidence': evidence,
                          'prompt': it['prompt'], 'options': it['options'],
                          'answer': it['answer'], 'rationale': rationale})
    if not items_out:
        return {'ok': False, 'error': '所有候选题都未通过结构校验：' + '; '.join(issues), 'raw': obj}
    payload = {'skill': skill, 'kind': 'passage', 'level': level, 'genre': 'passage',
              'title': title, 'text': text, 'labeled_text': labeled,
              'source': {'kind': 'ai_generated', 'title': title or None, 'author': None, 'url': None,
                         'license': None, 'provider': cfg.provider, 'model': cfg.model,
                         'generated_at': time.time(), 'based_on_sids': sids or [], 'based_on_source': source},
              'items': items_out}
    draft_id = db.add_ai_draft(skill, payload, level=level, genre='passage',
                               based_on_sid=(sids or [None])[0], based_on_source=source,
                               provider=cfg.provider, model=cfg.model)
    return {'ok': True, 'draft_id': draft_id, 'payload': payload, 'partial_issues': issues or None}


# ================================================================
# 候选文本采集（只用本地已有、符合 CORPUS_ARCHITECTURE.md 白名单的文本）
# ================================================================
def _sentence_candidates(scope, book_ids, level, limit):
    import textbook
    resolved = textbook.resolve_book_scope(scope, book_ids)
    rows = []
    if resolved['scope'] in ('book', 'mixed') and resolved['ids']:
        rows += textbook.fetch_book_sentence_rows(resolved['ids'], limit * 3)
    if resolved['scope'] in ('corpus', 'mixed'):
        with db.get_conn() as c:
            rows += [dict(r) for r in c.execute(
                "SELECT id sid, text text, translation translation, source source FROM sentences "
                "WHERE translation IS NOT NULL AND TRIM(translation)!='' "
                "ORDER BY RANDOM() LIMIT ?", (limit * 3,)).fetchall()]
    rows = [r for r in rows if (r.get('translation') or '').strip()
            and 6 <= len((r.get('text') or '').strip()) <= 80]
    return rows[:limit], resolved


def _passage_candidates_from_books(book_ids, max_lines=6):
    """从课本课文里按 lesson 顺序拼连续段落（天然有语义连贯性）。"""
    import textbook
    resolved = textbook.resolve_book_scope('book', book_ids)
    ids = resolved['ids']
    out = []
    if not ids:
        return out, resolved
    with db.get_conn() as c:
        for bid in ids:
            lessons = c.execute('SELECT id, title FROM book_lessons WHERE book_id=?', (bid,)).fetchall()
            for les in lessons:
                srows = c.execute(
                    'SELECT s.id sid, s.text text FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id '
                    'WHERE bs.lesson_id=? ORDER BY bs.idx LIMIT ?', (les['id'], max_lines)).fetchall()
                if len(srows) < 2:
                    continue
                out.append({'text': '\n'.join(r['text'] for r in srows),
                           'sids': [r['sid'] for r in srows],
                           'title': les['title'] or '', 'source': f'book:{bid}'})
    return out, resolved


def _passage_candidates_from_songs(max_lines=8):
    out = []
    try:
        with db.get_conn() as c:
            songs = c.execute('SELECT id, title, lyrics FROM songs ORDER BY RANDOM() LIMIT 20').fetchall()
    except Exception:
        return out
    for s in songs:
        lines = [l.strip() for l in (s['lyrics'] or '').split('\n') if l.strip()][:max_lines]
        if len(lines) < 2:
            continue
        out.append({'text': '\n'.join(lines), 'sids': [], 'title': s['title'] or '',
                   'source': f'lyric:{s["id"]}'})
    return out


def draft_batch(n=5, kind='sentence', skill='listening', level=None, scope='corpus',
                book_ids=None, config=None, _http_post=None):
    """批量起草 n 道草稿题。任何一次 Provider 级别错误（没配 key/网络/鉴权失败）
    立刻中止并如实报错，不会假装"跳过继续"掩盖配置问题。"""
    cfg = config or _gen_config()
    n = max(1, min(int(n or 5), 20))
    made, failed, errors = [], 0, []
    if kind == 'sentence':
        rows, resolved = _sentence_candidates(scope, book_ids, level, n * 2)
        if not rows:
            return {'ok': False, 'error': '没有找到带译文的候选句子（试试放宽题源或先补充翻译）'}
        for row in rows:
            if len(made) >= n:
                break
            r = generate_sentence_item(row.get('sid'), row['text'], row.get('translation'),
                                       source=row.get('source', ''), level=level, config=cfg,
                                       _http_post=_http_post)
            if r.get('ok'):
                made.append(r['draft_id'])
            else:
                failed += 1
                errors.append(r.get('error'))
                if _is_provider_fatal(r.get('error')):
                    return {'ok': False, 'error': r.get('error'), 'made': made, 'failed': failed}
    else:
        cands, resolved = _passage_candidates_from_books(book_ids)
        cands += _passage_candidates_from_songs()
        if not cands:
            return {'ok': False, 'error': '没有找到可组段落的课本课文或歌词（至少需要一课/一首里连续 2 行以上）'}
        import random
        random.shuffle(cands)
        for cand in cands:
            if len(made) >= n:
                break
            r = generate_passage_item(cand['text'], sids=cand['sids'], source=cand['source'],
                                      title=cand['title'], level=level, skill=skill, config=cfg,
                                      _http_post=_http_post)
            if r.get('ok'):
                made.append(r['draft_id'])
            else:
                failed += 1
                errors.append(r.get('error'))
                if _is_provider_fatal(r.get('error')):
                    return {'ok': False, 'error': r.get('error'), 'made': made, 'failed': failed}
    return {'ok': True, 'made': made, 'failed': failed, 'errors': errors[:10],
            'requested': n, 'generated': len(made)}


def _is_provider_fatal(err):
    if not err:
        return False
    return any(s in err for s in ('未配置 API Key', '未配置接口地址', '请求失败', '接口返回 401',
                                  '接口返回 403', '接口返回 5'))


# ================================================================
# 复核生命周期（与 assessment_bank.py 同构：draft → reviewed → approved → retired）
# ================================================================
_REQUIRED_CHECKS = {'content_correct', 'grounded_in_source', 'level_fit', 'language_natural'}


def list_drafts(skill=None, status=None, limit=200):
    return db.list_ai_drafts(skill=skill, status=status, limit=limit)


def get_draft(draft_id):
    return db.get_ai_draft(draft_id)


def review_draft(draft_id, status, reviewer, checklist=None, notes=''):
    if status not in ('draft', 'reviewed', 'approved', 'retired'):
        return {'ok': False, 'error': 'invalid status'}
    if not str(reviewer or '').strip():
        return {'ok': False, 'error': 'reviewer required'}
    d = db.get_ai_draft(draft_id)
    if not d:
        return {'ok': False, 'error': 'draft not found'}
    checks = {k: bool((checklist or {}).get(k)) for k in _REQUIRED_CHECKS}
    if status == 'approved' and not all(checks.values()):
        return {'ok': False, 'error': '批准前必须完成全部复核项（内容正确/确有原文依据/难度匹配/表达自然）',
                'missing': [k for k, v in checks.items() if not v]}
    ok = db.review_ai_draft(draft_id, status, reviewer, notes)
    return {'ok': ok}


def delete_draft(draft_id):
    return {'ok': db.delete_ai_draft(draft_id)}


def approved_items(skill=None, level=None, limit=50):
    """给听力/阅读练习消费的入口：只返回 status=approved 的题。"""
    rows = db.list_ai_drafts(skill=skill, status='approved', limit=limit)
    if level:
        rows = [r for r in rows if r.get('level') == level]
    return rows


def stats():
    return {'listening': db.count_ai_drafts('listening'),
           'reading': db.count_ai_drafts('reading')}

# -*- coding: utf-8 -*-
"""
自建课本模块（v11）
================================================================
用户可以「自己出教材」：粘贴若干句子 / 整篇文章 → 自动拆分（课本 → 课 → 句）
→ 自动提取「字 / 词 / 句」三级学习单元 → 绑定截止日期，用艾宾浩斯记忆曲线
排出「每天学什么、复习什么」的计划，保证在截止日前走完整条记忆曲线。

设计要点
- 拆分：显式标记（《书名》/书名：/作者：/第N課/Lesson N）优先；无标记时按段落
  分组、组内再按句末标点逐句切；宁多切一句，不硬合并两句。首行短标题会被借用
  为课本名但**仍保留在正文**（绝不因识别标题而丢内容）。
- 提取：字=句中出现的汉字（按首次出现顺序，符合教材教学顺序）；词=形态素分析出
  的实词，读音复用 furigana 引擎的词典级仲裁结果（与界面显示注音完全一致）；
  句=写入 sentences 表，因此复习/朗读/语法解析/收藏/RAG 全部天然可用。
- 计划：把 srs.INTERVALS_MIN（5分…2月）换算成「首次学习后第几天复习」，逐字模拟
  曲线；以「每天可用分钟数」为硬上限做负载平滑，新字排在容量允许的最早一天；
  并强制所有新字必须早于 (截止日 − 走完目标阶段所需天数) 引入，
  否则明确报告不可行，并给出「最少需要多少天 / 每天至少多少分钟」的替代方案。
- 进度：全局 SRS 是唯一事实来源 —— 以前学过的汉字自动算作已学，课本进度、
  计划完成度都能自动识别；本模块只额外保存「本书跳过/已掌握标记」与计划本身。
"""
import json
import math
import random
import re
import time
from datetime import date, timedelta

import corpus
import db
import furigana
import grammar
import srs

# ================================================================
# 1. 规整与拆分
# ================================================================
_SENT_SPLIT = re.compile(r'(?<=[。！？!?…])')
_BULLET_RE = re.compile(r'^\s*(?:[-*•·・]|\d{1,2}\s*[.、)）]|\(\d{1,2}\)|[①-⑳])\s*')
_TAIL = '」』】）》）)]】"\''

_BOOK_LABEL_RE = re.compile(r'^\s*(?:书名|書名|课本|課本|教材|タイトル|题目|标题)\s*[:：]\s*(.+?)\s*$')
_BOOK_BRACKET_RE = re.compile(r'^\s*[《『【]([^》』】]{1,60})[》』】]\s*(?:[-–—―]\s*(.{1,40}?)\s*)?$')
_BOOK_DASH_RE = re.compile(r'^\s*([^\s。！？!?、:：]{1,28}?)\s*[-–—―]\s*([^\s。！？!?、]{1,28})\s*$')
_AUTHOR_RE = re.compile(r'^\s*(?:作者|著者|編者|编者|出題|出题)\s*[:：]\s*(.+?)\s*$')
_LEVEL_RE = re.compile(r'^\s*(?:难度|難易度|级别|級別|level|JLPT)\s*[:：]\s*(.{1,12}?)\s*$', re.I)
_LESSON_MARK_RE = re.compile(
    r'^\s*(?:第\s*(\d{1,3})\s*[課课章回節节]|(?:レッスン|Lesson|Unit|ユニット|UNIT)\s*(\d{1,3}))'
    r'\s*[:：.、,，-]?\s*(.{0,40}?)\s*$', re.I)
_SEP_RE = re.compile(r'^\s*[-=*_~—─•·\^#]{3,}\s*$')
_CJK_RE = re.compile(r'[一-鿿ぁ-んァ-ヶ]')

MIN_SENT = 3          # 短于此长度且无句末标点的残段并回上一句
AUTO_LESSON_SIZE = 12  # 无标记时，每课最多多少句（自动分课）
BOOK_TITLE_MAX = 16    # 无标记时，多短的首行才可能被借用为课本名


def normalize(text: str) -> str:
    """统一换行/去行尾空白/空行压缩为单行（=段落分隔），去首尾空行。"""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n').replace('\ufeff', '')
    out, blank = [], 0
    for ln in text.split('\n'):
        ln = ln.rstrip()
        if ln.strip():
            out.append(ln)
            blank = 0
        else:
            blank += 1
            if blank == 1:
                out.append('')
    while out and not out[0]:
        out.pop(0)
    while out and not out[-1]:
        out.pop()
    return '\n'.join(out)


def _is_noise(s: str) -> bool:
    """噪音行：无假名/汉字（纯符号或纯拉丁）、长度不足、明显垃圾字符。"""
    if not s or len(s.strip()) < 2:
        return True
    if not _CJK_RE.search(s):
        return True
    if corpus.is_junk(s):
        return True
    # 纯书目版权/引用行（如 （『日本人の法則』株式会社ヤック企画））过滤
    s_str = s.strip()
    if re.match(r'^[（(【\[『「].*[）)】\]』」]$', s_str) and any(
        k in s_str for k in ('書', '著', '社', '刊', '号', '企画', '新聞', 'シリーズ', '加筆', '出典', '引用')
    ):
        return True
    return False


def split_sentences(block: str):
    """把一段文本切成句子：先按行，行内再按句末标点切，残段自动并回。"""
    out = []
    for raw in str(block or '').split('\n'):
        line = _BULLET_RE.sub('', raw).strip()
        if not line:
            continue
        buf = ''
        for part in _SENT_SPLIT.split(line):
            part = part.strip()
            if not part:
                continue
            buf += part
            core = buf.rstrip(_TAIL)
            if core and core[-1] in '。！？!?…':
                out.append(buf.strip())
                buf = ''
        if buf.strip():
            if len(buf.strip()) >= MIN_SENT or not out:
                out.append(buf.strip())
            else:
                out[-1] = (out[-1] + buf.strip()).strip()
    return [s for s in out if not _is_noise(s)]


def _parse_blocks(text: str):
    """按 --- 等分隔行切成块（章/篇分隔）。"""
    blocks, cur = [], []
    for ln in normalize(text).split('\n'):
        if _SEP_RE.match(ln):
            if any(x.strip() for x in cur):
                blocks.append(cur)
            cur = []
            continue
        cur.append(ln)
    if any(x.strip() for x in cur):
        blocks.append(cur)
    return blocks or [[]]


def _bracket_title(line: str):
    m = _BOOK_BRACKET_RE.match(line)
    if m:
        inner = m.group(1).strip()
        if 0 < len(inner) <= 60:
            return inner, (m.group(2) or '').strip() or None
    return None, None


def _looks_like_title(line: str) -> bool:
    t = line.strip()
    if not (1 <= len(t) <= BOOK_TITLE_MAX) or any(c in t for c in '。！？!?…'):
        return False
    return bool(_CJK_RE.search(t) or re.search(r'[A-Za-z]', t))


def _split_lessons(lines, lesson_size=AUTO_LESSON_SIZE):
    """块内切课：显式「第N課」标记优先；否则按段落分组（每组 ≤ lesson_size 句）。"""
    marked, cur = [], {'title': None, 'lines': []}
    for ln in lines:
        m = _LESSON_MARK_RE.match(ln)
        if m:
            if cur['lines']:
                marked.append(cur)
            num = m.group(1) or m.group(2)
            tail = (m.group(3) or '').strip()
            cur = {'title': (f'第{num}課' + (f'（{tail}）' if tail else '')) if tail
                   else f'第{num}課', 'lines': []}
            continue
        cur['lines'].append(ln)
    if cur['lines']:
        marked.append(cur)
    explicit = any(l['title'] for l in marked)

    lessons = []
    for item in marked:
        sents = []
        for ln in item['lines']:
            sents += split_sentences(ln)
        if not sents:
            continue
        if item['title']:
            lessons.append({'title': item['title'], 'sentences': sents})
            continue
        # 无标记：按段落分组，每组不超过 lesson_size 句
        group = []
        for s in sents:
            group.append(s)
            if len(group) >= lesson_size:
                lessons.append({'title': None, 'sentences': group})
                group = []
        if group:
            lessons.append({'title': None, 'sentences': group})
    for i, l in enumerate(lessons):
        if not l['title']:
            l['title'] = f'第{i + 1}課'
    return lessons, explicit


def parse_books(text, lesson_size=AUTO_LESSON_SIZE, default_title='未命名课本'):
    """把粘贴文本解析成 [{title, author, explicit, lessons:[{title,sentences}], sentences}]"""
    drafts = []
    for block in _parse_blocks(text):
        chunks, cur = [], None
        for ln in block:
            if not ln.strip():
                if cur is not None:
                    cur['lines'].append('')
                continue
            title, author = _bracket_title(ln)
            label = _BOOK_LABEL_RE.match(ln)
            if label:
                title = label.group(1).strip()
            elif title is None and cur is None:
                dash = _BOOK_DASH_RE.match(ln)
                if dash:
                    title, author = dash.group(1).strip(), dash.group(2).strip()
            if title:
                cur = {'title': title, 'author': author or '', 'explicit': True, 'lines': []}
                chunks.append(cur)
                continue
            if cur is None:
                cur = {'title': None, 'author': '', 'explicit': False, 'lines': []}
                chunks.append(cur)
            empty_so_far = not any(x.strip() for x in cur['lines'])
            m = _AUTHOR_RE.match(ln)
            if m and empty_so_far:
                cur['author'] = m.group(1).strip()
                continue
            lv = _LEVEL_RE.match(ln)
            if lv and empty_so_far:
                cur['level'] = lv.group(1).strip()
                continue
            cur['lines'].append(ln)
        drafts += chunks

    # 首行短标题 → 借用为课本名（正文原样保留，绝不因识别标题丢内容）
    for d in drafts:
        if d['title']:
            continue
        first = next((l.strip() for l in d['lines'] if l.strip()), '')
        if first and _looks_like_title(first) and len(split_sentences('\n'.join(d['lines']))) >= 2:
            d['title'] = first

    # 多块但没有一块有明确书名 → 合并为一本（--- 视为章分隔，避免碎片化）
    if len(drafts) > 1 and not any(d['explicit'] for d in drafts):
        lines = []
        for i, d in enumerate(drafts):
            if i:
                lines.append('')
            lines += d['lines']
        drafts = [{'title': None, 'author': '', 'explicit': False, 'lines': lines}]

    books = []
    for i, d in enumerate(drafts):
        lessons, _explicit = _split_lessons(d['lines'], lesson_size)
        if not lessons:
            continue
        title = d['title'] or (default_title if len(drafts) == 1 else f'{default_title}{i + 1}')
        books.append({'title': title, 'author': d['author'] or '', 'level': d.get('level') or '',
                      'explicit': d['explicit'], 'lessons': lessons,
                      'sentences': [s for l in lessons for s in l['sentences']]})
    if not books:
        books = [{'title': default_title, 'author': '', 'level': '', 'explicit': False,
                  'lessons': [], 'sentences': []}]
    return books


# ================================================================
# 2. 字 / 词 / 句 三级提取
# ================================================================
_CONTENT_POS = {'名詞', '代名詞', '動詞', '形容詞', '形状詞', '副詞', '連体詞', '接続詞', '感動詞'}
_LEMMA_POS_TAILS = {'代名詞', '普通名詞', '固有名詞', '数詞', '動詞', '形容詞',
                    '形状詞', '副詞', '接続詞', '感動詞', '連体詞'}
_KANJI_EXTRA = '々〆ヶ'


def _offset_words(text):
    """MeCab 词 + 在原文中的起始偏移（与 furigana 引擎同一分词器）"""
    pos = 0
    for w in furigana._tagger(text):
        if not w.surface:
            continue
        start = text.find(w.surface, pos)
        if start < 0:
            start = pos
        pos = start + len(w.surface)
        yield start, w


def _furigana_by_offset(text, tokens):
    """偏移 → furigana token（取词典级仲裁读音，保证与界面注音一致）"""
    out, pos = {}, 0
    for t in tokens or []:
        s = t.get('s') or ''
        if not s:
            continue
        i = text.find(s, pos)
        if i < 0:
            i = pos
        pos = i + len(s)
        out.setdefault(i, t)
    return out


def _clean_lemma(lemma, surface):
    if not lemma or lemma == '*':
        return surface
    if '-' in lemma:
        head, tail = lemma.rsplit('-', 1)
        if tail in _LEMMA_POS_TAILS and head:
            return head
        if surface and all('\u30a0' <= c <= '\u30ff' for c in surface):
            return surface          # 片假名未知词：以原样为准
    return lemma


def extract_units(text, tokens=None):
    """返回 (kanji_rows, word_rows)
       kanji_rows: [(汉字, 所属词, 词读音)]（与界面注音同源）
       word_rows:  [(词, 读音, 含汉字, 词性)]"""
    tokens = tokens if tokens is not None else furigana.annotate(text)
    kanji_rows = furigana.extract_kanji_words(tokens)
    fb = _furigana_by_offset(text, tokens)
    word_rows, seen = [], set()
    for off, w in _offset_words(text):
        f = w.feature
        pos1 = getattr(f, 'pos1', '') or ''
        if pos1 not in _CONTENT_POS:
            continue
        if pos1 == '名詞' and (getattr(f, 'pos2', '') or '') == '数詞':
            continue                      # 数词不进词汇表
        surface = w.surface
        if _is_noise(surface):
            continue
        word = _clean_lemma(getattr(f, 'lemma', None), surface)
        t = fb.get(off)
        reading = ''
        if t:
            reading = t.get('dr') or t.get('wr') or t.get('r') or ''
        if not reading:
            kana = getattr(f, 'kana', None)
            reading = furigana.kata_to_hira(kana) if kana and kana != '*' else ''
        kch = [c for c in surface if furigana.is_kanji(c) and c not in _KANJI_EXTRA]
        key = (word, reading)
        if key in seen:
            continue
        seen.add(key)
        word_rows.append((word, reading, kch[0] if kch else '', pos1))
    return kanji_rows, word_rows


def analyze(text, lesson_size=AUTO_LESSON_SIZE, sample=150):
    """导入前预览（不写库）：拆出几本书、多少课/句，以及字/词规模与重复情况、语法合规分析。"""
    books = parse_books(text, lesson_size)
    all_sents = [s for b in books for s in b['sentences']]
    dup = 0
    kanji, words = {}, {}
    valid_grammar, invalid_grammar = 0, 0
    grammar_issues = []
    for i, s in enumerate(all_sents):
        if db.sentence_exists(s):
            dup += 1
        if i < sample:                      # 长文本只抽样分析，保证预览秒回
            chk = grammar.check_sentence_grammar(s, strict_mode=False)
            if chk['ok']:
                valid_grammar += 1
            else:
                invalid_grammar += 1
                if len(grammar_issues) < 10:
                    grammar_issues.append({
                        'text': s,
                        'errors': chk['errors'],
                        'warnings': chk['warnings'],
                        'score': chk['score']
                    })
            k_rows, w_rows = extract_units(s)
            for k, _w, _r in k_rows:
                kanji[k] = kanji.get(k, 0) + 1
            for w, _r, _k, _pos in w_rows:
                words[w] = words.get(w, 0) + 1
    total_checked = valid_grammar + invalid_grammar
    grammar_rate = round((valid_grammar / max(1, total_checked)) * 100, 1)
    return {
        'books': [{'title': b['title'], 'author': b['author'], 'lessons': len(b['lessons']),
                   'sentences': len(b['sentences']), 'excerpt': b['sentences'][:3]} for b in books],
        'book_count': len([b for b in books if b['sentences']]),
        'lessons': sum(len(b['lessons']) for b in books),
        'sentences': len(all_sents), 'duplicated': dup,
        'new_sentences': len(all_sents) - dup,
        'kanji': len(kanji), 'words': len(words),
        'sampled': len(all_sents) > sample, 'sample_size': min(sample, len(all_sents)),
        'top_kanji': [{'kanji': k, 'n': n} for k, n in
                      sorted(kanji.items(), key=lambda x: -x[1])[:20]],
        'grammar_check': {
            'valid': valid_grammar,
            'invalid': invalid_grammar,
            'rate': grammar_rate,
            'issues': grammar_issues,
            'sampled': len(all_sents) > sample,
        },
    }


def _store_sentence(text, translation=None, orig_text=None):
    """句子入 sentences 表（复用注音/汉字索引管线）；已存在则复用原 id。返回 (sid, is_new)"""
    text = (text or '').strip()
    if not text:
        return None, False
    text, _n = corpus.repair_inline_furigana(text)
    text, orig = corpus.modernize_old_kana(text)
    tokens = furigana.annotate(text)
    kw = furigana.extract_kanji_words(tokens)
    sid = db.add_sentence(text, translation or None, 'book', None, tokens, kw,
                          orig_text=orig if orig else orig_text)
    if sid is not None:
        return sid, True
    with db.get_conn() as c:
        r = c.execute('SELECT id FROM sentences WHERE text=?', (text,)).fetchone()
    return (r['id'] if r else None), False


def import_book(book, deadline=None, minutes_per_day=30, target_stage=7,
                note='', level=None, source_text=None):
    """把 parse_books 的结果写库：建书 → 建课 → 存句 → 建字/词索引。
    返回 {id, title, lessons, sentences, new_sentences, kanji, words}"""
    title = (book.get('title') or '未命名课本').strip()
    exist = db.find_book_by_title(title)
    if exist:
        # 幂等导入：同名书复用（进度不分裂），清掉旧课与句子链接后按最新文本重建
        bid = exist['id']
        db.update_book(bid,
                       author=book.get('author') or exist.get('author') or '',
                       level=level or book.get('level') or exist.get('level') or '',
                       note=note or exist.get('note') or '',
                       deadline=deadline or exist.get('deadline'))
        db.clear_book_links(bid)
    else:
        bid = db.add_book(title, book.get('author') or '', level or book.get('level') or '',
                          note or '', deadline, minutes_per_day, target_stage, 1)
    n_new, n_dup, sid_ok = 0, 0, 0
    for li, lesson in enumerate(book.get('lessons') or []):
        lid = db.add_lesson(bid, li + 1, lesson.get('title') or f'第{li + 1}課')
        for s in lesson.get('sentences') or []:
            sid, is_new = _store_sentence(s)
            if not sid:
                continue
            db.add_book_sentence(bid, lid, sid_ok, sid)
            sid_ok += 1
            n_new += 1 if is_new else 0
            n_dup += 0 if is_new else 1
    stat = rebuild_book_index(bid)
    db.log('book', f'导入课本《{title}》：{sid_ok} 句（新 {n_new}）· {len(book.get("lessons") or [])} 课')
    return {'id': bid, 'title': title, 'lessons': len(book.get('lessons') or []),
            'sentences': sid_ok, 'new_sentences': n_new, 'duplicated': n_dup,
            'kanji': stat['kanji'], 'words': stat['words']}


def rebuild_book_index(book_id):
    """按课本顺序重建「字 / 词」索引：字按首次出现排序（= 教材教学顺序），词同理。"""
    _total, rows = db.list_book_sentences(book_id, per=1000000)
    kanji_agg, word_agg = {}, {}
    for r in rows:
        tokens = r.get('tokens')
        if isinstance(tokens, str):
            try:
                tokens = json.loads(tokens)
            except Exception:
                tokens = []
        k_rows, w_rows = extract_units(r['text'], tokens or [])
        pos_idx = r.get('bs_idx') if r.get('bs_idx') is not None else r['id']
        for k, word, reading in k_rows:
            a = kanji_agg.get(k)
            if a is None:
                kanji_agg[k] = {'freq': 1, 'first': pos_idx, 'word': word or '', 'reading': reading or ''}
            else:
                a['freq'] += 1
        for word, reading, kanji_ch, pos1 in w_rows:
            a = word_agg.get(word)
            if a is None:
                word_agg[word] = {'freq': 1, 'first': pos_idx, 'reading': reading or '',
                                  'kanji': kanji_ch or '', 'pos': pos1 or ''}
            else:
                a['freq'] += 1
    kanji_rows = [(k, v['word'], v['reading'], v['freq'], v['first'])
                  for k, v in sorted(kanji_agg.items(), key=lambda x: (x[1]['first'], x[0]))]
    word_rows = [(w, v['reading'], v['kanji'], v['pos'], v['freq'], v['first'])
                 for w, v in sorted(word_agg.items(), key=lambda x: (x[1]['first'], x[0]))]
    db.replace_book_index(book_id, kanji_rows, word_rows)
    return {'kanji': len(kanji_rows), 'words': len(word_rows)}
# ================================================================
# 3. 课本进度（自动识别既有学习进度）
# ================================================================
def _day_ts(day_iso):
    y, m, d = (int(x) for x in str(day_iso).split('-')[:3])
    return time.mktime(date(y, m, d).timetuple())


def lesson_progress(book_id):
    """每课的汉字掌握情况（课本目录显示进度用）"""
    with db.get_conn() as c:
        rows = c.execute('''
            SELECT bs.lesson_id lid, bk.kanji kanji, MAX(s.stage) stage
            FROM book_sentences bs
            JOIN kanji_index ki ON ki.sentence_id = bs.sentence_id
            JOIN book_kanji bk ON bk.book_id = bs.book_id AND bk.kanji = ki.kanji
            LEFT JOIN srs s ON s.kanji = bk.kanji
            WHERE bs.book_id=? GROUP BY bs.lesson_id, bk.kanji''', (book_id,)).fetchall()
    agg = {}
    for r in rows:
        a = agg.setdefault(r['lid'] or 0, {'kanji': set(), 'learned': set(), 'mature': set()})
        a['kanji'].add(r['kanji'])
        if r['stage'] is not None:
            a['learned'].add(r['kanji'])
            if r['stage'] >= 7:
                a['mature'].add(r['kanji'])
    out = {}
    for lid, a in agg.items():
        n = len(a['kanji'])
        out[lid] = {'kanji': n, 'learned': len(a['learned']), 'mature': len(a['mature']),
                    'progress': round(100.0 * len(a['learned']) / n, 1) if n else 0.0}
    return out


def book_detail(book_id):
    """课本详情：规模 + 进度 + 目录（每课进度）+ 记忆曲线 + 已保存计划"""
    book = db.get_book(book_id)
    if not book:
        return None
    info = next((b for b in db.list_books() if b['id'] == book_id), dict(book))
    lessons = db.list_lessons(book_id)
    lp = lesson_progress(book_id)
    for l in lessons:
        p = lp.get(l['id']) or {}
        l['kanji'] = p.get('kanji', 0)
        l['learned'] = p.get('learned', 0)
        l['progress'] = p.get('progress', 0.0)
    info['lessons_list'] = lessons
    info['curve'] = full_curve_preview(book.get('target_stage') or 7)
    info['curve_target_days'] = curve_days(book.get('target_stage') or 7)
    info['plan'] = load_plan([book_id])
    info['marks'] = db.list_book_progress(book_id)
    info['word_pos_stats'] = _word_pos_stats(book_id)
    return info


def _word_pos_stats(book_id):
    with db.get_conn() as c:
        rows = c.execute('SELECT pos, COUNT(*) n FROM book_words WHERE book_id=? '
                         'GROUP BY pos ORDER BY n DESC', (book_id,)).fetchall()
        return [dict(r) for r in rows]


# ================================================================
# 4. 学习曲线 + 截止日排程（核心算法）
# ================================================================
NEW_SECONDS = 45        # 一个新字的首次学习（含当日 3 次短复习）均摊耗时
REVIEW_SECONDS = 12     # 一次复习耗时
SAME_DAY_REVIEWS = 3    # 5分 / 30分 / 12时 三次短复习都在当日完成
DEFAULT_MINUTES = 30
MIN_MINUTES, MAX_MINUTES = 5, 600


def _cum_curve_days():
    """各阶段复习相对「首次学习」的天数（向下取整，与每日颗粒度对齐）"""
    total, out = 0, []
    for m in srs.INTERVALS_MIN:
        total += m
        out.append(int(total // 1440))
    return out


def curve_days(target_stage):
    """从零记忆走到「答对进入第 target_stage 阶段」所需天数（理论曲线全部答对）"""
    cum = _cum_curve_days()
    if target_stage <= 0:
        return 0
    return cum[min(int(target_stage), len(cum)) - 1]


def curve_future_days(intro_day, horizon, target_stage):
    """引入日为 intro_day 的汉字，其后续复习落在第几天（同日内的三次短复习不计）"""
    cum = _cum_curve_days()
    out = []
    for i in range(min(int(target_stage), len(cum))):
        d = intro_day + cum[i]
        if d <= intro_day or d >= horizon:
            continue
        if not out or out[-1] != d:
            out.append(d)
    return out


def full_curve_preview(target_stage=7):
    """记忆曲线可视化数据（前端展示第几次复习落在第几天）"""
    cum = _cum_curve_days()
    out = []
    for i, d in enumerate(cum):
        out.append({'stage': i + 1,
                    'name': srs.STAGE_NAMES[min(i, len(srs.STAGE_NAMES) - 1)],
                    'day': d, 'same_day': d == 0,
                    'target': (i + 1) == int(target_stage)})
    return out


def _future_review_days(row, day0_ts, horizon):
    """已学汉字在未来 horizon 天内的复习落点（按其当前阶段 + next_due 推算，估算）"""
    nd = row.get('next_due')
    if not nd:
        return []
    stage = int(row.get('stage') or 0)
    idx = int((nd - day0_ts) // 86400)
    out, guard = [], 0
    while 0 <= idx < horizon and guard < 12:
        out.append(idx)
        idx += max(1, int(round(srs.INTERVALS_MIN[min(stage, len(srs.INTERVALS_MIN) - 1)] / 1440)))
        stage += 1
        guard += 1
    return [i for i in out if 0 <= i < horizon]


def _simulate(fresh, existing_days, cap_sec, horizon, last_intro, target_stage, max_new_per_day):
    """负载平滑排程（水填充算法）：
    ① 均匀铺开：每日新字目标 = ⌈总新字数 / 可用引入天数⌉，把新字尽量均匀分散到
       [0, last_intro]，避免「第一天塞爆、之后全空闲」的突击式安排；
    ② 容量顺延：某天装不下（当日成本 > 每日容量）就自动往后找最早有空的一天；
    ③ 放宽重试：均匀目标内放不下时，逐步放宽到硬上限（max_new_per_day）再试；
       全都放不下才进 unplaced（触发不可行报告）。
    fresh: [(key, book_id, kind)]   —— kind='kanji' 或 'words'
    返回 (new_of_day, load, rev_of_day, rev_count, unplaced)"""
    load = [n * REVIEW_SECONDS for n in existing_days]
    new_of_day = [[] for _ in range(horizon)]
    rev_of_day = [[] for _ in range(horizon)]
    rev_count = list(existing_days)
    unplaced = []
    intro_days = max(0, last_intro) + 1
    hard_cap = max(1, max_new_per_day or 10 ** 9)   # 每日硬上限 ≥1（防除零）
    limit = min(max(1, -(-len(fresh) // intro_days)), hard_cap)   # 每日目标新字数

    def try_place(item, max_count):
        k, bid, kind = item
        for d in range(0, intro_days):
            if len(new_of_day[d]) >= max_count:
                continue
            future = curve_future_days(d, horizon, target_stage)
            # 当日成本 = 新字首次学习 + 3 次短复习（同日内完成）+ 后续曲线复习的分摊预告
            extra = NEW_SECONDS + SAME_DAY_REVIEWS * REVIEW_SECONDS + REVIEW_SECONDS * len(future)
            if load[d] + extra > cap_sec:
                continue
            load[d] += NEW_SECONDS + SAME_DAY_REVIEWS * REVIEW_SECONDS
            rev_count[d] += SAME_DAY_REVIEWS
            if (k, bid, kind) not in rev_of_day[d]:
                rev_of_day[d].append((k, bid, kind))
            for dd in future:                       # 后续曲线复习点
                load[dd] += REVIEW_SECONDS
                rev_count[dd] += 1
                if (k, bid, kind) not in rev_of_day[dd]:
                    rev_of_day[dd].append((k, bid, kind))
            new_of_day[d].append(item)
            return True
        return False

    for item in fresh:
        if try_place(item, limit):
            continue
        if not try_place(item, hard_cap):         # 放宽均匀目标（仍受每日容量约束）
            unplaced.append(item)
    return new_of_day, load, rev_of_day, rev_count, unplaced


# ================================================================
# 5. 计划生成 / 保存 / 读取（planner 入口）
# ================================================================
FALLBACK_DAYS = 60      # 未填截止日时的默认计划天数


def _parse_day(s, default=None):
    if not s:
        return default
    try:
        y, m, d = (int(x) for x in str(s).strip().split('-')[:3])
        return date(y, m, d)
    except Exception:
        return default


def _iso(d):
    return d.isoformat() if isinstance(d, date) else str(d)


def _srs_stages():
    """全局 SRS 记忆状态（自动识别以前学习进度的唯一事实来源）
    返回 {汉字或单词: stage}。字和词都以全局 SRS 为准自动识别。"""
    with db.get_conn() as c:
        rows = c.execute('SELECT kanji, stage FROM srs').fetchall()
    return {r['kanji']: (r['stage'] or 0) for r in rows}


def _fresh_kanji(book_ids, stages):
    """按书的顺序取「没学过的汉字」：全局 SRS 已有的自动算作已学（不排新字），
    本书标记 skip/done 的也跳过；同一字出现在多本书时只学一次（先出现的书负责引入）。"""
    out, seen = [], set()
    for bid in book_ids:
        for r in db.book_kanji_set([bid]):
            k = r['kanji']
            if k in seen or k in stages:
                continue
            seen.add(k)
            out.append((k, bid, 'kanji'))
    return out


def _fresh_words(book_ids, stages):
    """按书的顺序取「没学过的词」：全局 SRS 里该词首字阶段≥3 且已形成较稳固记忆时，
    再把该词当作成熟不排新；否则加到新词计划里（词汇学习也是真正的学习项）。"""
    seen, out = set(), []
    for bid in book_ids:
        for r in db.book_words_set([bid]):
            w = r['word']
            if w in seen:
                continue
            seen.add(w)
            cjk = r.get('kanji') or ''
            if cjk and stages.get(cjk, 0) >= 3:
                continue
            out.append((w, bid, 'words'))
    return out


def _existing_load(horizon, day0_ts):
    """已学汉字（全库，不只本书）未来每天的复习次数预估 —— 排程前给它们占好容量。"""
    with db.get_conn() as c:
        rows = c.execute('SELECT stage, next_due FROM srs '
                         'WHERE next_due IS NOT NULL AND next_due < ?',
                         (day0_ts + (horizon + 1) * 86400,)).fetchall()
    days = [0] * horizon
    for r in rows:
        for i in _future_review_days({'stage': r['stage'], 'next_due': r['next_due']}, day0_ts, horizon):
            days[i] += 1
    return days


def _meta_map(book_ids):
    """汉字 → 词/读音/所属书（计划表展示用）；缓存里没有的实词也补齐映射。"""
    ids = list(book_ids)
    if not ids:
        return {}
    ph = ','.join('?' * len(ids))
    with db.get_conn() as c:
        rows = c.execute(
            f'SELECT bk.kanji kanji, MIN(bk.word) word, MIN(bk.reading) reading, '
            f'MAX(b.title) book_title '
            f'FROM book_kanji bk JOIN books b ON b.id=bk.book_id '
            f'WHERE bk.book_id IN ({ph}) GROUP BY bk.kanji', ids).fetchall()
    m = {r['kanji']: dict(r) for r in rows}
    with db.get_conn() as c:
        rows = c.execute(
            f'SELECT bw.word word, MIN(bw.reading) reading, MIN(bw.kanji) kanji, '
            f'MAX(b.title) book_title '
            f'FROM book_words bw JOIN books b ON b.id=bw.book_id '
            f'WHERE bw.book_id IN ({ph}) GROUP BY bw.word', ids).fetchall()
        for r in rows:
            m[r['word']] = dict(r)
    return m


def build_plan(book_ids=None, start=None, deadline=None, minutes_per_day=None,
               target_stage=None, max_new_per_day=None, save=True, content='both'):
    """为选中的一本或多本课本排出「截止日前每天学什么、复习什么」。

    content: 'both'(默认，汉字+词汇双轨) | 'kanji'(仅汉字) | 'words'(仅词汇)。
    保证（可行性算法）：
    - 每个新学项走完 target_stage 阶段艾宾浩斯曲线的**全部复习**都落在截止日之前
      （最晚引入日 = 截止日 − 曲线天数）；
    - 每天总负载（首次学习 + 同日 3 次短复习 + 后续曲线复习 + 已学项的到期复习）
      不超过「每日可用分钟数」，装不下就顺延到最早有空的一天；
    - 不可行时给出量化补救：最早能完成的日子 / 每天至少需要多少分钟。
    """
    ids = [int(b) for b in (book_ids or [])] or \
          [b['id'] for b in db.list_books() if b.get('active')]
    books = [b for b in (db.get_book(i) for i in ids) if b]
    if not books:
        return {'ok': False, 'feasible': False, 'reason': '没有可排计划的课本（先导入一本）'}
    book_ids = [b['id'] for b in books]

    today = date.today()
    start_d = _parse_day(start, today) or today
    if start_d < today:
        start_d = today
    deadline_d = _parse_day(deadline)
    if not deadline_d:
        latest = max((b['deadline'] for b in books if b.get('deadline')), default=None)
        deadline_d = _parse_day(latest) or (start_d + timedelta(days=FALLBACK_DAYS - 1))
    if deadline_d < start_d:
        deadline_d = start_d
    minutes = int(minutes_per_day or max(int(b['minutes_per_day'] or DEFAULT_MINUTES) for b in books))
    minutes = max(MIN_MINUTES, min(MAX_MINUTES, minutes))
    target = int(target_stage or max(int(b['target_stage'] or 7) for b in books))
    target = max(1, min(target, len(srs.INTERVALS_MIN)))
    cap_sec = minutes * 60

    horizon = (deadline_d - start_d).days + 1
    curve_need = curve_days(target)
    last_intro = horizon - 1 - curve_need      # 新字最晚引入日（之后只复习）
    if last_intro < 0:
        return {'ok': False, 'feasible': False, 'start': _iso(start_d), 'deadline': _iso(deadline_d),
                'reason': f'截止日太早：走完第 {target} 阶段记忆曲线本身就需要 {curve_need + 1} 天',
                'need_days': curve_need + 1}

    stages = _srs_stages()
    content = content if content in ('both', 'kanji', 'words') else 'both'
    kanji_fresh = _fresh_kanji(book_ids, stages) if content in ('both', 'kanji') else []
    words_fresh = _fresh_words(book_ids, stages) if content in ('both', 'words') else []
    fresh = kanji_fresh + words_fresh
    existing = _existing_load(horizon, _day_ts(_iso(start_d)))
    new_of_day, load, rev_of_day, rev_count, unplaced = _simulate(
        fresh, existing, cap_sec, horizon, last_intro, target, max_new_per_day or 0)

    # ---- 不可行时的量化补救建议 ----
    suggestion = None
    if unplaced:
        big = horizon + curve_need + len(fresh) * 2 + 60
        n2, _l2, _r2, _c2, un2 = _simulate(
            fresh, _existing_load(big, _day_ts(_iso(start_d))), cap_sec, big,
            big - 1 - curve_need, target, max_new_per_day or 0)
        last_new = max([d for d, lst in enumerate(n2) if lst] or [-1])
        work_sec = (len(fresh) * (NEW_SECONDS + SAME_DAY_REVIEWS * REVIEW_SECONDS
                                  + REVIEW_SECONDS * max(0, target - 1))
                    + REVIEW_SECONDS * sum(existing))
        suggestion = {'min_minutes_per_day': int(math.ceil(work_sec / max(1, horizon) / 60))}
        if not un2 and last_new >= 0:
            suggestion['need_days'] = last_new + curve_need + 1
            suggestion['earliest_finish'] = _iso(start_d + timedelta(days=last_new + curve_need))

    meta = _meta_map(book_ids)
    book_titles = {b['id']: b['title'] for b in books}
    per_day = []
    for i in range(horizon):
        d_iso = _iso(start_d + timedelta(days=i))
        per_day.append({
            'day': d_iso,
            'new': [{'kanji': k, 'kind': kd, 'book_id': b, 'book': book_titles.get(b),
                     **(meta.get(k) or {})}
                    for k, b, kd in new_of_day[i]],
            'review_items': [{'kanji': k, 'kind': kd, 'book_id': b, 'book': book_titles.get(b),
                              **(meta.get(k) or {})}
                             for k, b, kd in rev_of_day[i]],
            'review_count': rev_count[i],          # 含既有全局复习
            'load_min': round(load[i] / 60.0, 1),
            'capacity_min': minutes,
        })

    if save and not unplaced:
        # 计划落库：新学项(is_new=1)与复习(is_new=0)按书保存，逐项可勾选完成
        for bid in book_ids:
            rows = []
            for i in range(horizon):
                d_iso = per_day[i]['day']
                for k, b, kd in new_of_day[i]:
                    if b == bid:
                        rows.append((d_iso, 1, k, kd))
                for k, b, kd in rev_of_day[i]:
                    if b == bid:
                        rows.append((d_iso, 0, k, kd))
            db.save_book_plan(bid, rows)
        # 排程实际采用的参数回写（界面展示与计划读取保持一致）
        for b in books:
            db.update_book(b['id'], deadline=_iso(deadline_d),
                           minutes_per_day=minutes, target_stage=target)
        db.log('book_plan', f'生成学习计划：{len(book_ids)} 本书 · {len(kanji_fresh)} 字 + '
                            f'{len(words_fresh)} 词 · {_iso(start_d)} → {_iso(deadline_d)} · '
                            f'每天 {minutes} 分钟')

    return {'ok': not unplaced, 'feasible': not unplaced,
            'reason': None if not unplaced else f'容量不足，{len(unplaced)} 个学习项在截止日前排不下',
            'start': _iso(start_d), 'deadline': _iso(deadline_d), 'days': horizon,
            'minutes_per_day': minutes, 'target_stage': target, 'content': content,
            'curve_days': curve_need, 'last_intro_day': _iso(start_d + timedelta(days=last_intro)),
            'books': [{'id': b['id'], 'title': b['title']} for b in books],
            'new_total': len(fresh), 'new_kanji': len(kanji_fresh), 'new_words': len(words_fresh),
            'unplaced_count': len(unplaced),
            'unplaced': [k for k, _b, _kd in unplaced[:50]], 'suggestion': suggestion,
            'existing_review_total': sum(existing),
            'per_day': per_day}


def save_plan(book_ids=None, start=None, deadline=None, minutes_per_day=None,
              target_stage=None, max_new_per_day=None, content='both'):
    """生成并保存计划（= build_plan(save=True) 的语义化别名）"""
    return build_plan(book_ids, start, deadline, minutes_per_day, target_stage,
                      max_new_per_day, save=True, content=content)


def load_plan(book_ids=None):
    """读取已保存的计划：按天聚合，并自动识别既有进度 ——
    全局 SRS 里已学过的字，其「新字」格子自动打勾；已长期记忆(stage≥7)的复习格子自动打勾；
    手动勾选（done 标记）叠加其上，互不覆盖。"""
    ids = [int(b) for b in (book_ids or [])]
    rows = db.load_book_plan(ids)
    books = [b for b in (db.get_book(i) for i in ids) if b]
    if not rows:
        return {'ok': True, 'empty': True, 'per_day': [],
                'books': [{'id': b['id'], 'title': b['title']} for b in books]}
    stages = _srs_stages()
    meta = _meta_map(ids)
    per_day = {}
    for r in rows:
        d = per_day.setdefault(r['day'], {'day': r['day'], 'new': [], 'review': []})
        it = {'kanji': r['kanji'], 'kind': r.get('kind') or
              ('words' if len(r['kanji'] or '') > 1 else 'kanji'),
              'manual_done': bool(r['done']),
              'stage': stages.get(r['kanji']), **(meta.get(r['kanji']) or {})}
        (d['new'] if r['is_new'] else d['review']).append(it)
    out_days = []
    for key in sorted(per_day):
        d = per_day[key]
        for it in d['new']:
            it['done'] = it['manual_done'] or it['stage'] is not None
        for it in d['review']:
            it['done'] = it['manual_done'] or (it['stage'] or 0) >= 7
        d['total'] = len(d['new']) + len(d['review'])
        d['done_n'] = sum(1 for it in d['new'] + d['review'] if it['done'])
        out_days.append(d)
    today_iso = date.today().isoformat()
    total_new = sum(len(d['new']) for d in out_days)
    done_new = sum(1 for d in out_days for it in d['new'] if it['done'])
    deadlines = [b['deadline'] for b in books if b.get('deadline')]
    return {'ok': True, 'empty': False, 'per_day': out_days, 'today': today_iso,
            'today_tasks': next((d for d in out_days if d['day'] == today_iso), None),
            'next_day': next((d['day'] for d in out_days if d['done_n'] < d['total']), None),
            'books': [{'id': b['id'], 'title': b['title']} for b in books],
            'deadline': max(deadlines) if deadlines else None,
            'total_new': total_new, 'done_new': done_new,
            'progress': round(100.0 * done_new / total_new, 1) if total_new else 0.0}


# ================================================================
# 6. 学习配置 / 例句全库检索 / 语法抽取 / 挖空测验
# ================================================================
DEFAULT_CFG = {
    'example_source': 'all',      # book=仅本书 | corpus=仅全库语料 | all=本书优先+全库补足
    'example_limit': 8,           # 每个字/词展示的例句数
    'grammar_min_level': 'N3',    # 语法抽取难度下限：低于此（更简单的 N5/N4）不抽
    'cloze_enabled': True,        # 学习曲线中穿插挖空测验
    'cloze_scope': 'corpus',      # 挖空题源：book=仅本书 | corpus=全库语料
    'cloze_per_day': 5,           # 每次练习题数
    'cloze_min_level': 'N4',      # 挖空考的语法难度下限（默认不考 N5 太简单的）
}

# 语料来源 → 中文出处标签（例句/挖空统一使用，保证每条例句都标明出处）
SOURCE_LABELS = {
    'tatoeba': '🌐 Tatoeba 例句库',
    'wikipedia': '🌐 日语维基百科',
    'wikinews': '🌐 维基新闻',
    'manual': '✍️ 手动添加',
    'import': '📥 导入备份',
    'book': '📖 课本句子',
}


def origin_label(source, book_title=None, lesson_title=None):
    if book_title:
        return f'📖《{book_title}》' + (f' · {lesson_title}' if lesson_title else '')
    return SOURCE_LABELS.get(source or '', f'🌐 {source or "语料库"}')


def study_cfg():
    """学习配置（settings 表 JSON，所有环节的用户自定义项）"""
    cfg = dict(DEFAULT_CFG)
    try:
        raw = db.get_setting('book_study_cfg', '')
        if raw:
            cfg.update({k: v for k, v in json.loads(raw).items() if k in DEFAULT_CFG})
    except Exception:
        pass
    return cfg


def save_study_cfg(patch):
    """增量保存配置（只接受白名单键），返回合并后的完整配置"""
    patch = {k: v for k, v in (patch or {}).items() if k in DEFAULT_CFG}
    cfg = study_cfg()
    cfg.update(patch)
    db.set_setting('book_study_cfg', json.dumps(cfg, ensure_ascii=False))
    db.log('book', '更新学习配置：' + ', '.join(f'{k}={v}' for k, v in patch.items()))
    return cfg


def unit_examples(kanji=None, word=None, book_ids=None, source=None, limit=None):
    """例句检索：本书句子优先，全库语料补足（可配置只查其一）。
    kanji 用子串匹配（书中）+ kanji_index（全库）；word 用子串 + LIKE 检索。
    source/limit 为空时取学习配置（example_source / example_limit）。
    每条例句都带出处标注：课本句标书名+课名，语料句标渠道名。"""
    cfg = study_cfg()
    if not source:
        source = cfg.get('example_source') or 'all'
    limit = max(1, min(int(limit or cfg.get('example_limit') or 8), 30))
    ids = [int(b) for b in (book_ids or [])]
    out, seen = [], set()
    if source in ('book', 'all') and ids and (kanji or word):
        ph = ','.join('?' * len(ids))
        with db.get_conn() as c:
            rows = c.execute(
                f'SELECT s.id id, s.text text, s.translation translation, s.tokens tokens, '
                f's.source source, bs.book_id book_id, b.title book_title, l.title lesson_title '
                f'FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id '
                f'JOIN books b ON b.id=bs.book_id '
                f'LEFT JOIN book_lessons l ON l.id=bs.lesson_id '
                f'WHERE bs.book_id IN ({ph}) ORDER BY bs.id LIMIT 800', ids).fetchall()
        for r in rows:
            hit = (kanji and kanji in r['text']) or (word and word in r['text'])
            if not hit or r['id'] in seen:
                continue
            seen.add(r['id'])
            out.append({'id': r['id'], 'text': r['text'], 'translation': r['translation'],
                        'tokens': json.loads(r['tokens']) if r['tokens'] else [], 'src': 'book',
                        'source': r['source'], 'book_id': r['book_id'],
                        'book_title': r['book_title'], 'lesson': r['lesson_title'],
                        'origin': origin_label(r['source'], r['book_title'], r['lesson_title'])})
            if len(out) >= limit:
                return out
    if source in ('corpus', 'all') and (kanji or word):
        if kanji:
            rows = db.sentences_for_kanji(kanji, limit * 4)
        else:
            _, rows = db.query_sentences(q=word, per=limit * 4)
        # 带翻译的优先（更适合学习），其次短句优先
        rows = sorted(rows, key=lambda r: (0 if r.get('translation') else 1,
                                           len(r.get('text') or ''), -r.get('id', 0)))
        for r in rows:
            if r['id'] in seen:
                continue
            seen.add(r['id'])
            out.append({'id': r['id'], 'text': r['text'], 'translation': r.get('translation'),
                        'tokens': json.loads(r['tokens']) if r.get('tokens') else [],
                        'src': 'corpus', 'source': r.get('source'),
                        'origin': origin_label(r.get('source'))})
            if len(out) >= limit:
                break
    return out


def _lv(level):
    return grammar.LEVEL_ORDER.get(level, 0)


def book_grammar(book_ids=None, min_level='N3', per=40, sample=120):
    """抽取选中书的语法点（复用 grammar.analyze 全库引擎）。
    默认排除太简单的级别（min_level 以下，如 N5/N4）；按难度高→低、出现次数排序；
    每个语法点附带一条书中原句作例句。"""
    ids = [int(b) for b in (book_ids or [])]
    if not ids:
        return []
    min_o = _lv(min_level or 'N3')
    ph = ','.join('?' * len(ids))
    with db.get_conn() as c:
        rows = c.execute(
            f'SELECT s.id sid, s.text text FROM book_sentences bs '
            f'JOIN sentences s ON s.id=bs.sentence_id '
            f'WHERE bs.book_id IN ({ph}) ORDER BY bs.id LIMIT ?',
            ids + [max(1, min(int(sample), 400))]).fetchall()
    agg = {}
    for r in rows:
        if not grammar.is_sentence_grammatically_sound(r['text']):
            continue
        try:
            pts = grammar.analyze(r['text'])
        except Exception:
            continue
        for g in pts:
            if g.get('kind') != 'pattern' or _lv(g.get('level')) < min_o:
                continue
            a = agg.get(g['name'])
            if a is None:
                agg[g['name']] = {
                    'name': g['name'], 'level': g['level'], 'structure': g['structure'],
                    'explain': g['explain'], 'count': 1,
                    'example': {'sid': r['sid'], 'text': r['text'], 'surface': g['surface'],
                                'before': g['before'], 'after': g['after']}}
            else:
                a['count'] += 1
    items = sorted(agg.values(), key=lambda x: (-_lv(x['level']), -x['count']))
    return items[:max(1, min(int(per or 40), 100))]


def check_book_grammar(bid):
    """对指定课本的全量句子进行基础语法审计"""
    _tot, rows = db.list_book_sentences(bid, per=100000)
    valid, invalid = 0, 0
    issues = []
    for r in rows:
        text = r.get('text', '')
        chk = grammar.check_sentence_grammar(text, strict_mode=False)
        if chk['ok']:
            valid += 1
        else:
            invalid += 1
            issues.append({
                'sid': r.get('sentence_id') or r.get('id'),
                'bs_idx': r.get('bs_idx'),
                'text': text,
                'errors': chk['errors'],
                'warnings': chk['warnings'],
                'score': chk['score']
            })
    return {
        'book_id': bid,
        'total': len(rows),
        'valid': valid,
        'invalid': invalid,
        'rate': round((valid / max(1, len(rows))) * 100, 1),
        'issues': issues
    }


# 挖空禁挖名单：挖掉后题干不可答、或配不出合格干扰项的句型
# （意向形/命令形挖的是动词本身；て形单独挖无意义；疑问词组含实词内容；
#  たがる左边是たい词干、右边又常跟名词——除たがる家族外没有任何形式能同时成立）
_CLOZE_SKIP_NAMES = {
    '意向形（〜う／よう）', '命令形', '動詞て形（接続）',
    '疑問詞+でも（全面肯定）', '疑問詞+も+否定（全面否定）',
    '〜がる／たがる（第三者感情）',
}

# 后接断定（だ/です…）的空位：干扰项必须同样能接断定，否则会被瞬间排除
# （如 べき|だ 的干扰项若是 なければならない → なければならないだ，直接出局）。
# 以下词干接だ/です全部成立、且语义各异，是该槽位唯一合格的混淆集。
_COPULA_STEMS = ['べき', 'はず', 'わけ', 'そう', 'の', 'ん', 'もの', 'ところ', 'こと']

# 定语槽位（答案以連体形修饰后方名词，如 ような|男、食べたい|もの）：
# 干扰项必须同时满足「左接续」与「右作定语」。按答案的左接续分三类——
#  词干类（食べ|___|もの）：STEM_RENTAI 全员接词干、全员可作定语
#  原形类（彼の|___|男）：PLAIN_RENTAI 全员接体言/原形、全员可作定语
#  て形类（作って|___|人）：TE_RENTAI 全员接て形、全员可作定语
_STEM_RENTAI = ['たい', 'やすい', 'にくい', 'がたい', 'すぎる', 'っぽい',
                'かねない', 'かねる']
_STEM_SET = set(_STEM_RENTAI)
_PLAIN_RENTAI = ['ような', 'みたいな', 'らしい', 'ごとき', '並みの']
_PLAIN_SET = set(_PLAIN_RENTAI)
_TE_RENTAI = ['てほしい', 'みたい', 'てしまう', 'てみる', 'ておく',
              'てある', 'てくれる', 'てもらう', 'てあげる']
_TE_SET = set(_TE_RENTAI) | {'ている', 'ていく', 'てくる', 'ちゃう', 'てる', 'とく'}

# 同类混淆组：答案所属组的其他成员优先做干扰项（形近/义近/功能近，
# 如 ので↔から↔ために、ている↔てある↔てしまう）—— 这是「选项有区分度」的关键。
# names：组内可作答案的句型名；options：组内标准形（含可作干扰项的非答案形如 たら/だけ/しか）
_CLOZE_GROUPS = [
    {'names': {'〜ので（原因）', '〜ために（目的・原因）', '〜おかげで／せいで（因果）',
               '〜ゆえに（原因）',
               # v18 消歧子句型（与大纲通用名同组，保证挖空干扰项不断流）
               '〜ために（目的）', '〜ために（原因・理由）',
               '〜おかげで（積極的因果）', '〜せいで（消極的因果）'},
     'options': ['ので', 'から', 'ために', 'おかげで', 'せいで']},
    {'names': {'条件「ば」', '条件「と」', '条件「なら」', '条件「たら」'},
     'options': ['ば', 'たら', 'と', 'なら']},
    {'names': {'〜ている（進行・状態）', '〜てある（結果状態）', '〜ておく（準備）',
               '〜てしまう（完了・遺憾）', '〜てみる（嘗試）', '〜ていく／てくる（方向・変化）',
               '縮約形〜ちゃう／じゃう', '縮約形〜とく', '縮約形〜てる／てた（ている）',
               # v18 消歧子句型
               '〜ている（結果状態・存続）', '〜ている（習慣・反復）', '〜ている（動作の進行）',
               '縮約形〜てる（結果状態・存続）', '縮約形〜てる（習慣・反復）', '縮約形〜てる（動作の進行）',
               '〜てしまう（自発・自制不能）', '〜てしまう（遺憾・失敗）',
               '〜てしまう（遺憾・被害）', '〜てしまう（完了・完全終了）',
               '縮約形〜ちゃう（自発・自制不能）', '縮約形〜ちゃう（遺憾・失敗）',
               '縮約形〜ちゃう（遺憾・被害）', '縮約形〜ちゃう（完了・完全終了）',
               '〜ていく（空間移動）', '〜ていく（時間推移・変化）',
               '〜てくる（知覚・出現）', '〜てくる（空間移動）', '〜てくる（時間推移・変化）'},
     'options': ['ている', 'てある', 'ておく', 'てしまう', 'てみる', 'ていく', 'てくる',
                 'ちゃう', 'てる', 'とく']},
    {'names': {'〜てあげる／てくれる／てもらう（授受）', '〜てほしい（願望）',
               # v18 消歧子句型
               '〜てあげる（授受・施恵）', '〜てくれる（授受・受恵）', '〜てもらう（授受・依頼受益）'},
     'options': ['てあげる', 'てくれる', 'てもらう', 'てほしい']},
    # たい接动词词干（食べたい），与接て形的授受组严格分开、二者不可互作干扰项
    {'names': {'〜たい（願望）'},
     # てほしい排首位：一段/サ変词干槽位里 食べ|たい↔食べ|てほしい 都是
     # 合法替换（求人替己愿望），是最有区分度的干扰项；五段词干槽位
     # （行き|たい）左接续不合会被自动跳过。
     'options': ['てほしい', 'たい', 'やすい', 'にくい', 'がたい', 'すぎる',
                 'がち']},
    {'names': {'〜かもしれない（推測）', '〜はずだ（確信）', '〜らしい（推定・典型）',
               '〜ようだ／みたいだ（比況・推定）', '〜そうだ（様態）', '〜そうだ（伝聞）',
               '〜に違いない（確信）', '〜でしょう（推量）', '〜まい（否定推量・意志）'},
     'options': ['かもしれない', 'はずだ', 'らしい', 'ようだ', 'みたいだ', 'そうだ',
                 'に違いない', 'でしょう', 'まい']},
    {'names': {'〜ことにする（決心）', '〜ことになる（決定・結果）',
               '〜ようになる（変化）', '〜になる／くなる（変化）',
               '〜ことができる（可能）', '〜たことがある（経験）'},
     'options': ['ことにする', 'ことになる', 'ようになる', 'ことができる', 'たことがある']},
    {'names': {'〜なければならない（義務）', '〜てはいけない（禁止）', '〜てもいい（許可）',
               '〜べきだ（当然）', '縮約形〜なきゃ', '縮約形〜なくちゃ',
               '〜ざるを得ない（不可避）', '〜わけにはいかない（不可）'},
     'options': ['なければならない', 'なくてはならない', 'ないといけない', 'てはいけない',
                 'てもいい', 'べきだ', 'ざるを得ない']},
    {'names': {'〜ばかり（限定・直後）', '〜たばかり（直後）',
               '〜ばかり（限定・頻度）', '〜ばかり（直後・完了）', '〜たばかり（直後・完了）'},
     'options': ['ばかり', 'だけ', 'しか', 'のみ', 'きり']},
    {'names': {'〜ほど', },  # 占位：ほど为单词类，暂无句型答案，保留组以便干扰项复用
     'options': ['ほど', 'くらい', 'ぐらい']},
    {'names': {'〜すぎる（過度）', '〜やすい／にくい', '〜がたい（困難）', '〜かねる（困難）',
               '〜かねない（危険性）', '〜っぽい（傾向）', '〜がち（頻度傾向）'},
     'options': ['すぎる', 'やすい', 'にくい', 'がたい', 'かねる', 'かねない', 'っぽい']},
    {'names': {'〜ながら（同時）', '〜たり〜たり（列挙）', '〜し（並列理由）',
               '〜つつ（同時・逆接）', '〜つつある（進行）',
               '〜つつ（同時進行）', '〜つつも（逆接）'},
     'options': ['ながら', 'つつ', 'つつある', 'し', 'たり', 'だり']},
    {'names': {'〜のに（逆接）', '〜ものの（逆接）', '〜にもかかわらず（逆接）',
               '〜ものを（...）', '〜てもいい（許可）',
               '〜のに（目的・用途）', '〜のに（遺憾・願望の終助詞）'},
     'options': ['のに', 'ものの', 'にもかかわらず', 'けれど', 'が', 'ても']},
    {'names': {'〜んです／のです（説明）', '〜わけだ／わけではない', '〜はずだ（確信）',
               '〜ものだ（本性・感慨）', '〜ものか（反語）'},
     'options': ['んです', 'のです', 'わけだ', 'わけではない', 'はずだ', 'ものだ']},
    {'names': {'〜ないでください', '〜てください（依頼）', '〜ないで／なくて（否定接续）',
               '〜ずに（否定状態）'},
     'options': ['てください', 'ないでください', 'ないで', 'なくて', 'ずに',
                 'なさい', 'ちょうだい', 'もらえ', 'くれ', 'てくれ']},
    {'names': {'〜ように（目的・引用）',
               '〜ように（祈願・希望）', '〜ように（引用・間接指示）', '〜ように（目的）'},
     'options': ['ように', 'ために', 'みたいに', 'そうに']},
    {'names': {'〜たびに（反復）', '〜うちに（時間帯）'},
     'options': ['たびに', 'うちに', 'ごとに', '最中に', 'ところで']},
    {'names': {'〜ほうがいい（忠告）'},
     'options': ['ほうがいい', 'ものだ', 'ことだ', 'かもしれない', 'わけだ',
                 'はずだ']},
    {'names': {'〜かどうか（不確定）', '〜ば〜ほど（比例）',
               '〜ようとする（意志・寸前）'},
     'options': ['かどうか', 'ものか', 'ことか', 'とする', 'と思う']},
    {'names': {'〜まま（放任）', '〜ところだ（局面）', '〜最中',
               '〜ところだ（直前・これから）', '〜ところだ（進行・最中）', '〜ところだ（直後・完了）'},
     'options': ['まま', 'ところ', 'ところだ', 'とおり', '最中', '途中']},
    {'names': {'〜について（対象）', '〜に対して（対象・対比）', '〜に関して（関連）',
               '〜にとって（立場）', '〜として（資格）', '〜によって／による（手段・原因・依拠）',
               '〜における／において（場面）', '〜を通じて／を通して（媒介）',
               '〜のあまり（極度）'},
     'options': ['について', 'に対して', 'に関して', 'にとって', 'として', 'によって',
                 'において', 'を通じて']},
    {'names': {'受身・可能・尊敬「れる／られる」', '使役「せる／させる」'},
     'options': ['れる', 'られる', 'せる', 'させる']},
    {'names': {'〜がほしい（願望）', '〜がある／いる（存在文）'},
     'options': ['がほしい', 'が要る', 'が必要だ', 'が好きだ', 'が嫌いだ',
                 'が心配だ', 'が得意だ', 'が苦手だ', 'が分かる', 'ができる',
                 'がある', 'がいる']},
    {'names': {'〜じゃない（口語否定）', '〜ではない／ではなく（否定断定）',
               '〜じゃ（ではの口語形）', '〜である（断定の書面語）',
               '〜だった（断定の過去）', '〜です（丁寧体）',
               '〜ます（丁寧体）', '〜ません（丁寧否定）',
               '〜ましょう（劝诱）', '〜でしょう（推量）'},
     'options': ['ではない', 'ではなく', 'じゃない', 'である', 'だった', 'です',
                 'ます', 'ません', 'ましょう', 'でしょう']},
    {'names': {'〜な（ナ形容詞の連体修飾）', '〜に（ナ形容詞の副詞用法）'},
     'options': ['な', 'に', 'の', 'へ', 'まで', 'から', 'より', 'を',
                 'で']},
    {'names': {'口語「って」（引用・主題）', '〜ってば', '縮約形〜とく'},
     'options': ['って', 'と', 'ってば', 'なんて']},
    {'names': {'〜だらけ（充満）', '〜まみれ（付着）', '〜気味（気配）',
               '〜っぱなし（放置）', '〜放題'},
     'options': ['だらけ', 'まみれ', '気味', 'っぱなし']},
    {'names': {'〜のみならず（累加）', '〜を問わず（無関係）',
               '〜ずにはいられない（禁不住）', '〜んばかり（寸前の様子）',
               '〜かのように（比況強調）', '〜ごとく／ごとき（比況）'},
     'options': ['のみならず', 'を問わず', 'ずにはいられない', 'んばかり',
                 'かのように', 'ごとく']},
]

# 等价形互斥：同一语法的原形与口语缩约形绝不能同时出现在选项里
# （否则「两个都对」—— 如 ている ↔ てる、てしまう ↔ ちゃう、ておく ↔ とく）
# 等价形互斥：同一语法的原形与口语缩约形/同义形绝不能同时出现在
# 选项里（否则「两个都对」）。注意：と↔なら、ので↔から、そうだ↔
# らしい、ものだ↔ことだ 语义不同，不互斥、可互作干扰项。
_CLOZE_EQUIV = [frozenset({'ている', 'てる'}),
                frozenset({'てしまう', 'ちゃう', 'じゃう'}),
                frozenset({'ておく', 'とく'}),
                frozenset({'ない', 'ぬ'}),
                frozenset({'ず', 'ずに', 'ないで'}),
                frozenset({'ながら', 'つつ'}),
                frozenset({'んです', 'のです'}),
                frozenset({'なければならない', 'なくてはならない',
                            'ないといけない'}),
                frozenset({'だけ', 'のみ'}),
                frozenset({'ほど', 'くらい', 'ぐらい'}),
                frozenset({'にくい', 'がたい'}),
                frozenset({'けれど', 'が'}),
                frozenset({'ようだ', 'みたいだ'}),
                frozenset({'について', 'に関して'}),
                frozenset({'である', 'です'}),
                frozenset({'ではない', 'じゃない'}),
                frozenset({'れる', 'られる'}),
                # 条件形互斥：条件从句槽位里 ば/たら/と/なら 常可互换且都
                # 成立（如 着いた|たら/なら|、電話してください），必须互斥
                # 否则双正确答案。
                frozenset({'ば', 'たら', 'と', 'なら'}),
                # 同义比況互斥：ように↔みたいに、ような↔みたいな。
                frozenset({'ように', 'みたいに'}),
                frozenset({'ような', 'みたいな'}),
                # 浊音缩约互斥（与清音集镜像）。
                frozenset({'でおく', 'どく'}),
                frozenset({'でいる', 'でる'}),
                frozenset({'でしまう', 'じゃう'}),
                # 引用形互斥：って/と/ってば/なんて/とか 在引用槽位里常可
                # 互换且都成立，必须互斥否则双正确答案。
                frozenset({'って', 'と', 'ってば', 'なんて', 'とか'})]

# 带前缀形的 CTX 族：同族前缀形之间可互换作干扰项（如 高くなる ↔
# 安くなる），与裸形/异族不可互换。
_CTX_FAMILY = frozenset({'KUNARU', 'NINARU', 'TONARU', 'TOSURU',
                         'VDICTCTX', 'MAMIRE', 'DARACKE'})

# 引用答案：后必须跟引用动词（QUO），否则任何从句补语填入都成立、
# 天生双正解，只能弃题。かどうか除外（后跟分からない类谓语是安全的）。
_QUO_ANS = frozenset({'って', 'なんて', 'ってば', 'とか', 'という',
                      'ということ', 'ってこと'})


def _cloze_equiv(a, b):
    if a == b:
        return True
    return any(a in g and b in g for g in _CLOZE_EQUIV)


# ================================================================
# 挖空左右接续校验（v14）
# ================================================================
# 每个候选干扰项必须同时满足左接续（before 末词的形态）与右接续（after
# 首词的形态），否则会被瞬间排除——如 行き|てほしい、食べる|まま、
# 行く|って|、太る、彼の|らしい|男。实现：before/after 分类器（形态素
# 分析全文 + 空位定位）+ 候选表面形的左右类词典（精确匹配优先，最长
# 后缀兜底）。未知=放行（宁可漏过罕见形，不可误杀常见形）；已知且左右
# 类与槽位完全不交=拒绝。
#
# 左类（before 末词）：VSA 动词ます词干 / VSB_U 清音て形词尾（促音便/
# イ音便清音组）/ VSB_V 浊音て形词尾（撥音便/ぐイ音便）/ VSAB 两可词干
# （一上一段/サ変/カ変/す动词的し）/ M1B 一段裸未然 / M1KO カ変こ段未
# 然 / M1NA 未然+な（行かな：只接なきゃ/なければ类）/ M1NASA さな・せ
# な（永不匹配）/ M5 五段ア段未然 / MSI/MSA/MSE サ変未然し・さ・せ /
# MKAT 假定・命令形 / M5O 五段オ段未然（+う）/ VOL 意向形 / VDICT 动
# 词辞书形 / ADICT イ形容词辞书形 / ADJS イ形容词语干 / ADJKU イ形容
# 词く形 / ADJTA イ形容词た词尾（高かっ）/ VTE て形 / TEIRU ている形 /
# TAFORM_U/TAFORM_V 清音/浊音た形 / NAI ない形 / TAIB たい・ほしい形
# / COPD だ形 / COPP です形 / MASB ます形 / SOUB・STMB skeleton（永不
# 匹配，专用于必弃槽位）/ NOUN 名词直后 / NONO 名词+の / NAS ナ形容词
# 词干 / NAB な直后（学生な|…）/ NIB に直后 / RENTAI 连体词（この…）
# / TARAB・TARIB・NAGARAB・BAB・TOB・NARAB・CONJNB・HAB・WOB・
# CASEB・SOJIB・NARIB2・MAIB 槽位末尾码（永不匹配，必弃题）/
# SHIKAB しか-final（只接ない族）/ DEMOB でも-final（只接ない族）/
# PARTICLEB 副助词-final（只接だ/です/だろう族）。
# 右类（after 首词）：END 句末 / QUO 引用动词 / PRED 普通谓语 / MASU
# ます系 / DA だ系 / DESU です系 / DARO だろう系 / NOUNR 裸名词 /
# NOP の / NAP な / NIP に / DEP で / WOP を / GAP が・けれど类 /
# HAP は / MOP も / CASEP 其他格助词 / CONJN 名词・从句两可接续 /
# TEMO ても / TEWA ては / TEN 顿号 / TEP て接续 / NAIR ない系 /
# NODA のだ系 / NOX のは系 / NARU なる直后 / MIERU 见える类 /
# VOLR 意向词直后 / SOJI 瞬时接续（やいなや…）/ SHIKA しか直后 /
# IMPR 命令形（只接て形/ないで/ます词干/ください类）/ REJ 永不匹配
# （必弃）/ None 未知（放行）。
_LQ_TAGGER = None


def _lq_tagger():
    global _LQ_TAGGER
    if _LQ_TAGGER is None:
        import fugashi
        _LQ_TAGGER = fugashi.Tagger()
    return _LQ_TAGGER


def _lq_spans(text, words):
    """各形态素在原文中的字符区间（游标查找，容忍原文中的空白换行）。"""
    spans, cur = [], 0
    for w in words:
        i = text.find(w.surface, cur)
        if i < 0:
            i = cur
        spans.append((i, i + len(w.surface)))
        cur = i + len(w.surface)
    return spans


# 五段-る动词原形：i 段假名词干 + る结尾时，仅这些是五段（ます词干），
# 其余一律为一段（两可词干）。さ行・しゃ行结尾另有规则，不必列入。
_GODAN_RU = frozenset({
    '帰る', '切る', '知る', '走る', '入る', '要る', '参る', '減る', '滑る',
    '握る', '練る', '散る', '照る', '蹴る', '焦る', '罵る', '限る', '茂る',
    '覆る', '蘇る', '漲る', '罵る', '捻る', '練る', '翻る', '滅入る', '入る',
    '走る', '呟る', '諍る', '軋る', '競る',
    # 五段る动词补全（连用形后接て/た时须走浊化分支，误判一段会放行
    # 返り|て 等错误；嘲る是一段，不在此列）
    '返る', '反る', '耽る', '湿る', '轢る', '抉る', '訛る',
    '炒る', '煎る', '射る', '括る', '掬る', '縊る', '輸る',
    '足る', 'たる', '釣る', '吊る', '攣る', '連る', '蔓る', '弦る',
    '張る', '貼る', '春る', '晴る', '昼る', '干る',
    '降る', '振る', '震る', '古る', '経る',
    '丸る', '回る', '廻る', '円る', '盛る', '漏る',
    '緩る', '弛る', '揺る', '寄る', '選る', '因る', '拠る',
    '割る', '悪る', '破る',
})

# 引用动词原形（lemma）：后接 と/って/なんて 时归入 QUO 类。
_QUOTE_VERBS = frozenset({
    '言う', '思う', '聞く', '話す', '述べる', '書く', '呼ぶ', '答える',
    '尋ねる', '問う', '感じる', '考える', '信じる', '伝える', '報告する',
    '説明する', '主張する', '頼む', '注意する', '名付ける', '呼称する',
    '呼ぶ', '囁く', '呟く', '叫ぶ', '尋ねる', '訊く', '思う', '考える',
})

_I_ROW = frozenset('きぎしちにひみりいじびぴ')
_E_ROW = frozenset('けげせてねへめれえぜでべぺ')
_O_ROW = frozenset('こごそとのでもよろぼぽおぞど')


def _lq_verb_stem_class(lemma, surface):
    """动词连用形细分：VSA（ます专用）/ VSB_U（清音て词尾：っ/き/し/ち/
    り/み/い(く)）/ VSB_V（浊音て词尾：ん/い(ぐ)）/ VSAB（两可）。清浊不
    分会放行 行っ|でいる、読ん|てみる 等错误，故必须拆分。"""
    lemma = lemma or ''
    if lemma in ('来る', 'くる', 'する', '為る'):
        return frozenset({'VSAB'})
    if surface.endswith('ん'):
        return frozenset({'VSB_V'})
    if surface.endswith('っ'):
        return frozenset({'VSB_U'})
    if lemma.endswith('る'):
        if lemma.endswith(('さる', 'しゃる', 'ざる')):
            return frozenset({'VSA'})
        last = surface[-1:] if surface else ''
        if last in _E_ROW:
            return frozenset({'VSAB'})
        if lemma in _GODAN_RU:
            return frozenset({'VSA'})
        return frozenset({'VSAB'})
    if lemma.endswith('す') and surface.endswith('し'):
        return frozenset({'VSAB'})
    if lemma.endswith('う') and surface.endswith('う'):
        return frozenset({'VSAB'})
    if lemma.endswith('ぐ') and surface.endswith('い'):
        return frozenset({'VSB_V'})
    if lemma.endswith('く') and surface.endswith('い'):
        return frozenset({'VSB_U'})
    return frozenset({'VSA'})


def _lq_is_gu_verb(word):
    """前词是否为ぐ行动词（泳ぐ/急ぐ…，其いだ词尾发浊音）。"""
    if word is None:
        return False
    try:
        lemma = (word.feature.lemma or '').split('-')[0]
    except Exception:
        return False
    return lemma.endswith('ぐ')


def _cloze_left_class(text, b0):
    """before 部分末词的左接续类（全文形态素分析 + 空位定位）。

    返回 frozenset 类代码；无法判定（句首/助词/副词/标点结尾等）返回
    None（调用方回退到「与答案同类即放行」的宽松策略）。"""
    try:
        words = [w for w in _lq_tagger()(text) if w.surface]
    except Exception:
        return None
    if not words:
        return None
    spans = _lq_spans(text, words)
    idx = -1
    for i, (s, e) in enumerate(spans):
        if e <= b0:
            idx = i
        else:
            break
    if idx < 0:
        return None
    w = words[idx]
    f = w.feature
    pos1, lemma, cf = f.pos1, (f.lemma or ''), (f.cForm or '')
    prev = words[idx - 1] if idx > 0 else None
    prev_surf = prev.surface if prev is not None else ''

    if pos1 == '動詞':
        if cf.startswith('連用形'):
            if lemma == 'ます':                      # まし（ましょう・ました的词尾）
                return frozenset({'VSA'})
            return _lq_verb_stem_class(lemma, w.surface)
        if cf.startswith('未然形'):
            if lemma in ('する', '為る'):
                if w.surface.endswith('な'):
                    # しな→M1NA（しなきゃ√）；さな/せな无任何后接→M1NASA 必弃
                    return frozenset({'M1NA'}) if w.surface.endswith('しな') \
                        else frozenset({'M1NASA'})
                if w.surface.endswith('し'):
                    return frozenset({'MSI'})
                if w.surface.endswith('せ'):
                    return frozenset({'MSE'})
                return frozenset({'MSA'})
            if w.surface.endswith('な'):
                # 未然+な（行かな/食べな/来な）：只接 なきゃ/なければ类，
                # 不接裸ない/ず/せる类，故独立成码（旧 M1/M5 混同会放行
                # 行かな|ない、しな|ない 等错误）
                return frozenset({'M1NA'})
            if lemma in ('来る', 'くる'):
                return frozenset({'M1KO'})
            if lemma.endswith('る') and lemma not in _GODAN_RU \
                    and not lemma.endswith(('さる', 'しゃる', 'ざる')):
                return frozenset({'M1B'})
            if w.surface[-1:] in _O_ROW:
                return frozenset({'M5O'})
            return frozenset({'M5'})
        if cf.startswith(('仮定形', '命令形')):
            return frozenset({'MKAT'})
        if '意志推量' in cf:
            return frozenset({'VOL'})
        if cf.startswith(('終止形', '連体形')):
            # ている形：いる系列助动词 + 前接て/で → TEIRU（まま/ばかり…
            # 只接这类，不接普通辞书形，必须区分）。
            if lemma.split('-')[0] in ('居る', 'おる', '有る', '在る',
                                       'いらっしゃる', 'ござる') \
                    and prev_surf in ('て', 'で'):
                return frozenset({'TEIRU'})
            return frozenset({'VDICT'})
        return None
    if pos1 == '形容詞':
        if cf.startswith('語幹'):
            return frozenset({'ADJS'})
        if cf.startswith('連用形'):
            if w.surface.endswith('く'):
                return frozenset({'ADJKU'})
            if w.surface.endswith(('かっ', 'なかっ', 'よかっ')):
                return frozenset({'ADJTA'})
            return None
        if cf.startswith(('仮定形', '未然形')):      # 高けれ・高かろ
            return frozenset({'MKAT'})
        if cf.startswith(('終止形', '連体形')):
            return frozenset({'ADICT'})
        return None
    if pos1 == '助動詞':
        base = lemma.split('-')[0]
        if base in ('た', 'だ') and w.surface in ('た', 'だ'):
            if cf.startswith(('終止形', '連体形')):
                # た形清浊拆分：んだ/いだ(ぐ)后只接だり/だら，っ/いた/し
                # た等后只接たり/たら；混同会放行 買った|だり、死んだ|たり
                if prev_surf.endswith('ん') or \
                        (prev_surf.endswith('い') and _lq_is_gu_verb(prev)):
                    return frozenset({'TAFORM_V'})
                return frozenset({'TAFORM_U'})
            return None
        if base in ('た', 'だ') and w.surface in ('たら', 'だら'):
            return frozenset({'TARAB'})   # 条件句末+挖空答案必无解，弃题
        if base == 'だ' and w.surface == 'なら':
            return frozenset({'NARAB'})   # 同上
        if base == 'ない':
            if cf.startswith(('終止形', '連体形')):
                return frozenset({'NAI'})
            return None
        if base in ('たい', '欲しい', 'たがる'):
            if cf.startswith(('終止形', '連体形')):
                return frozenset({'TAIB'})
            return None
        if base == 'ます':
            if cf.startswith(('終止形', '連体形')):
                return frozenset({'MASB'})
            if w.surface in ('まし', 'ませ'):
                return frozenset({'VSA'}) if w.surface == 'まし' else None
            if w.surface == 'ましょ':
                return frozenset({'M5O'})
            return None
        if base in ('だ', 'である', 'です', 'である', 'であります'):
            if w.surface in ('な', 'なん'):          # 学生な|…（先于连体形判定）
                return frozenset({'NAB'})
            if cf.startswith(('終止形', '連体形')):
                return frozenset({'COPD'}) if base in ('だ', 'である') \
                    else frozenset({'COPP'})
            return None
        if base in ('れる', 'られる', 'せる', 'させる'):
            if cf.startswith(('終止形', '連体形')):
                return frozenset({'VDICT'})
            return None
        if base in ('そう', 'よう', 'らしい', 'みたい'):
            return frozenset({'STMB'})
        if base == 'まい':
            return frozenset({'MAIB'})    # まい句末+挖空答案必无解，弃题
        if base in ('う', 'よう'):
            return None
        if cf.startswith(('終止形', '連体形')):
            return frozenset({'VDICT'})
        return None
    if pos1 in ('名詞', '代名詞'):
        if f.pos2 == '数詞' or pos1 == '代名詞':
            return frozenset({'NOUN'})
        return frozenset({'NOUN'})
    if pos1 == '形状詞':
        return frozenset({'NAS'})
    if pos1 == '連体詞':
        return frozenset({'RENTAI'})
    if pos1 == '助詞':
        if w.surface == 'の':
            return frozenset({'NONO'})
        if w.surface in ('て', 'で'):
            # て形（前为用言）与格助词で（前为体言）必须区分，否则会放行
            # 学校で|ください；前词缺失时保守按体言处理
            if prev is not None:
                try:
                    ppos = prev.feature.pos1
                except Exception:
                    ppos = ''
                if ppos in ('動詞', '形容詞', '助動詞'):
                    return frozenset({'VTE'})
            return frozenset({'CASEB'})
        if w.surface == 'に':
            return frozenset({'NIB'})
        if w.surface == 'な':
            return frozenset({'NAB'})
        if w.surface in ('たり', 'だり'):
            return frozenset({'TARIB'})
        if w.surface in ('ながら', 'つつ'):
            return frozenset({'NAGARAB'})
        if w.surface == 'ば':
            return frozenset({'BAB'})
        if w.surface == 'と':
            return frozenset({'TOB'})
        if w.surface in ('ので', 'のに', 'けど', 'けれど', 'けれども',
                         'が', 'し', 'ものの', 'ものを',
                         'にもかかわらず', 'ところが'):
            return frozenset({'CONJNB'})
        if w.surface in ('は', 'も'):
            # でも = で+も 两词：も末尾且前词为で时是 でも-final，
            # 只接 ない族（本でもない√），与 HAB 分离
            if w.surface == 'も' and prev_surf == 'で':
                return frozenset({'DEMOB'})
            return frozenset({'HAB'})
        if w.surface == 'を':
            return frozenset({'WOB'})
        if w.surface == 'しか':
            return frozenset({'SHIKAB'})
        if w.surface == 'でも':
            return frozenset({'DEMOB'})
        if w.surface in ('ね', 'よ', 'さ', 'ぜ', 'ぞ', 'わ', 'い',
                         'かな', 'かしら', 'っけ'):
            return frozenset({'SOJIB'})
        if w.surface in ('だけ', 'ばかり', 'のみ', 'まで', 'ほど',
                         'くらい', 'ぐらい', 'より', 'きり', 'こそ',
                         'さえ', 'など', 'なんか', '等', 'ずつ', 'おき',
                         'ごと', '目'):
            # 可接だ/です/だろう继续的副助词（本だけだ、3時までだ…）
            return frozenset({'PARTICLEB'})
        if w.surface == 'なり':
            # 格助词なり（前为体言，可接だ继续）vs 瞬时なり（前为用言，
            # 句末必弃）：看前词词性区分
            if prev is not None:
                try:
                    ppos = prev.feature.pos1
                except Exception:
                    ppos = ''
                if ppos in ('動詞', '形容詞'):
                    return frozenset({'NARIB2'})
            return frozenset({'PARTICLEB'})
        if w.surface == 'から':
            # 格助词から（東京からだ√）vs 接续から（行くからだ×）vs 瞬时
            # そばから/とたんから（句末必弃）：看前词区分
            if prev_surf in ('そば', 'とたん', '途端'):
                return frozenset({'CONJNB'})
            if prev is not None:
                try:
                    ppos = prev.feature.pos1
                except Exception:
                    ppos = ''
                if ppos in ('名詞', '代名詞', '数詞'):
                    return frozenset({'PARTICLEB'})
            return frozenset({'CONJNB'})
        return frozenset({'CASEB'})
    if pos1 == '接尾辞':
        if w.surface in ('さ', 'み', 'げ', 'め'):
            return frozenset({'NOUN'})
        return None
    return None


# after 首串的表面优先判定（先于形态素分类）：のだ/のは复合、引用标记等
_AFTER_SURF = (
    (('のだ', 'のです', 'んだ', 'んです', 'のだろう', 'のでしょう',
       'んだろう', 'んでしょう', 'のだろうか', 'のだろ'), 'NODA'),
    (('のは', 'のが', 'のを', 'のに', 'ので', 'のと', 'のから', 'のまで',
       'のより', 'のへ', 'のや', 'のか', 'のかどうか'), 'NOX'),
)


# ---- 左接续类词典 ----
# 常用左类组合（frozenset 共享，不可变）
_L_CLAUSE = frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI',
                             'TEIRU', 'TAIB'})
_L_MIZEN = frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'MSE', 'MSA'})
# 清音て形答案（てしまう/ちゃう/ておく…）：只接清音词尾+两可词干+一段/
# サ変词干（食べ|てしまう√、し|てしまう√）；浊音词尾（読ん|てしまう×）
# 与未然+な（行かな|てしまう×）一律拒绝。
_L_TE_U = frozenset({'VSB_U', 'VSAB', 'M1B', 'MSI'})
_L_TE = _L_TE_U
# 浊音て形答案（でいる/じゃう/どく…）：只接浊音词尾（読ん|でいる√）。
_L_TE_V = frozenset({'VSB_V'})
# ても/ては族（てもいい/てはならない…）：ても是清音但 digger 常切出
# 読ん|ても（=読んでも），清浊两可皆合法；另含一段/カ変/サ変词干
# （食べ|ても√、来|ても√、し|ても√）与イ形词干（高く|ても√）。
_L_TEMO = frozenset({'VSB_U', 'VSB_V', 'VSAB', 'M1B', 'M1KO', 'MSI',
                     'ADJKU'})
# ます/たい/すぎる…词干答案：五段连用+两可词干+一段/サ変词干。
_L_STEM = frozenset({'VSA', 'VSAB', 'M1B', 'MSI'})

# 表面形 → 左接续类（精确匹配；查不到时走后缀规则，再查不到=未知=放行）
_LQ_LEFT_EXACT = {
    # ---- ます・丁寧 ----
    'ます': _L_STEM, 'ません': _L_STEM,
    'ましょう': _L_STEM, 'ませ': _L_STEM,
    'です': frozenset({'NOUN', 'NAS', 'NAB', 'VDICT', 'ADICT', 'TAFORM_U',
                       'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'COPD',
                       'NONO', 'PARTICLEB'}),
    'でした': frozenset({'NOUN', 'NAS', 'COPD', 'NONO', 'PARTICLEB'}),
    # である两读：断定书面语（名词左）/てある连浊（て词尾左）
    # である两读：断定书面语（名词/な形左）/てある连浊（浊音词尾左）。
    'である': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB', 'VSB_V'}),
    'であった': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'であり': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'であります': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'であろう': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'だった': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'だったら': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'だったろ': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'じゃない': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'ではなく': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'ではない': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'じゃ': frozenset({'NOUN', 'NAS', 'NONO', 'PARTICLEB'}),
    'でしょう': frozenset({'NOUN', 'NAS', 'VDICT', 'ADICT', 'TAFORM_U',
                           'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'COPD',
                           'COPP', 'NONO', 'PARTICLEB'}),
    'だろう': frozenset({'NOUN', 'NAS', 'VDICT', 'ADICT', 'TAFORM_U',
                         'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'COPD',
                         'NONO', 'PARTICLEB'}),
    # ---- て复合 ----
    'ている': _L_TE, 'てある': _L_TE, 'ておく': _L_TE, 'てみる': _L_TE,
    'てしまう': _L_TE, 'ていく': _L_TE, 'てくる': _L_TE, 'てみせる': _L_TE,
    'てほしい': _L_TE, 'てくれる': _L_TE, 'てもらう': _L_TE, 'てあげる': _L_TE,
    'ていただく': _L_TE, 'てくださる': _L_TE, 'てさしあげる': _L_TE,
    'ていただきたい': _L_TE, 'てもらいたい': _L_TE, 'てちょうだい': _L_TE,
    'てごらん': _L_TE, 'ちゃう': _L_TE, 'とく': _L_TE, 'てる': _L_TE,
    # 浊音形只接浊音词尾（VSB_V），不接一段词干（食べ|でいる不成立）
    'でいる': _L_TE_V,
    'でおく': _L_TE_V, 'でしまう': _L_TE_V,
    'でもらう': _L_TE_V, 'でくれる': _L_TE_V,
    'でほしい': _L_TE_V, 'じゃう': _L_TE_V,
    'どく': _L_TE_V, 'でる': _L_TE_V,
    'でいく': _L_TE_V, 'でくる': _L_TE_V,
    'ては': _L_TEMO, 'ても': _L_TEMO, 'てから': _L_TEMO,
    'てもいい': _L_TEMO,
    'てはいけない': _L_TEMO, 'てはならない': _L_TEMO,
    'てもかまわない': _L_TEMO,
    'ではいけない': _L_TE_V, 'でもいい': _L_TE_V,
    'てください': frozenset({'VSB_U', 'VSAB', 'VTE', 'VSA', 'M1B',
                             'MSI'}),
    'て下さい': frozenset({'VSB_U', 'VSAB', 'VTE', 'VSA', 'M1B',
                             'MSI'}),
    'ください': frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'}),
    '下さい': frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'}),
    'なさい': frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'}),
    'ちょうだい': frozenset({'VSB_U', 'VSAB', 'VTE', 'M1B', 'M1KO',
                               'MSI'}),
    'たまえ': frozenset({'VSB_U', 'VSAB', 'M1B', 'M1KO', 'MSI'}),
    'もらえ': frozenset({'VSB_U', 'VSAB', 'M1B', 'M1KO', 'MSI'}),
    'くれ': frozenset({'VSB_U', 'VSAB', 'VTE', 'M1B', 'M1KO', 'MSI'}),
    'てくれ': frozenset({'VSB_U', 'VSAB', 'M1B', 'M1KO', 'MSI'}),
    # たり（清音）/だり（浊音）：た形清浊必须匹配，否则放行买った|だり。
    'たり': frozenset({'VSB_U', 'VSAB', 'TAFORM_U'}),
    'だり': frozenset({'VSB_V', 'TAFORM_V'}),
    # ---- 未然 ----
    # ない：一段裸未然（M1B）/カ変（M1KO）/五段（M5）/サ変し（MSI）。
    # 未然+な（M1NA：行かな|ない×）、さ/せ（MSA/MSE）一律拒绝。
    'ない': frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB',
                          'DEMOB'}),
    'せる': frozenset({'M5', 'MSA'}),
    'させる': frozenset({'M1KO', 'M1B', 'M5', 'MSA'}),
    'れる': frozenset({'M1KO', 'M1B', 'M5', 'MSA'}),
    'られる': frozenset({'M1KO', 'M1B', 'M5', 'MSA'}),
    'う': frozenset({'M5O'}),   # よう（意向/比況两读）见下方合并条目
    'まい': frozenset({'VDICT', 'ADICT'}),
    # ば只接假定形（MKAT）：行か|ば×、し|ば×，一律拒绝。
    'ば': frozenset({'MKAT'}),
    'ねば': frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
    'なければ': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なかったら': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'ないと': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'ないなら': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なきゃ': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なきゃいけない': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なくちゃ': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なくちゃいけない': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なければならない': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なければいけない': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'なくてはならない': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'ないといけない': frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI',
                              'SHIKAB', 'DEMOB'}),
    'ねばならない': frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
    'ざるを得ない': frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
    'ざる': frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
    'ず': frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
    'ぬ': frozenset({'M1KO', 'M1B', 'M5'}),
    'んばかり': frozenset({'M1KO', 'M1B', 'M5'}),
    'ずに': frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
    'ずにはいられない': frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
    'ないで': frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB',
                          'DEMOB'}),
    'なくて': frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB',
                          'DEMOB'}),
    'ないでください': frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB',
                                  'DEMOB'}),
    'ないで下さい': frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB',
                                  'DEMOB'}),
    # ---- 条件（裸形几乎不可互换，左类严格区分；靠接续校验自动弃题）----
    # たら（清音）：だら走浊音后缀规则。た形清浊必须匹配。
    'たら': frozenset({'VSB_U', 'VSAB', 'TAFORM_U', 'ADJTA'}),
    'と': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI',
                       'TEIRU', 'TAIB', 'NAS',
                     'COPD', 'COPP', 'NOUN'}),
    'なら': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI',
                         'TEIRU', 'TAIB', 'NAS',
                       'COPD', 'COPP', 'NOUN'}),
    'ならば': frozenset({'VDICT', 'ADICT', 'COPD', 'NOUN', 'NAS'}),
    'であれば': frozenset({'NOUN', 'NAS'}), 'だと': frozenset({'NOUN', 'NAS'}),
    # ---- 词干 ----
    'たい': _L_STEM, 'たがる': _L_STEM,
    'がる': frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS'}),
    'やすい': _L_STEM, 'にくい': _L_STEM, 'がたい': _L_STEM,
    'すぎる': frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'}),
    'っぽい': frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'}),
    'かねる': _L_STEM, 'かねない': _L_STEM,
    'がち': frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'}),
    'ながら': frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}),
    'つつ': frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}),
    'つつある': frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}),
    '方': _L_STEM, 'かた': _L_STEM, 'ぶり': _L_STEM,
    'っこない': _L_STEM, 'がてら': frozenset({'VSA', 'VSAB', 'M1B',
                                                   'MSI'}),
    # ---- 名词/形式名词 ----
    'もの': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NONO'}),
    'こと': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NONO'}),
    'の': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI',
                       'TEIRU', 'TAIB', 'NOUN',
                     'COPD', 'COPP', 'NAB', 'NAS'}),
    'ん': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'ため': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NONO'}),
    'ほう': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NONO'}),
    'ところ': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'ところだ': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U',
                           'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'まま': frozenset({'RENTAI', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NAI', 'NONO'}),
    'とおり': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    '途中': frozenset({'TEIRU', 'NONO', 'VSA', 'VSAB'}),
    '最中': frozenset({'RENTAI', 'TEIRU', 'NONO'}),
    'うちに': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NAI', 'TAIB'}),
    'たびに': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'TAIB'}),
    'ごとに': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TAIB', 'NOUN'}),
    '度に': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TAIB', 'NOUN'}),
    '最中に': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NONO'}),
    'ところで': frozenset({'RENTAI', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'ままに': frozenset({'RENTAI', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NAI'}),
    'とおりに': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'ことに': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    'ばかり': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NOUN'}),
    'ばかりに': frozenset({'RENTAI', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU'}),
    'たばかり': frozenset({'VSB_U', 'VSAB', 'M1B', 'MSI'}),
    'だけ': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NOUN'}),
    'だけに': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NOUN'}),
    'しか': frozenset({'RENTAI', 'NOUN', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                       'TAIB'}),
    'のみ': frozenset({'RENTAI', 'NOUN', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU'}),
    'きり': frozenset({'NOUN', 'TAFORM_U', 'TAFORM_V'}),
    'ほど': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN'}),
    'くらい': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NOUN'}),
    'ぐらい': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NOUN'}),
    'まで': frozenset({'RENTAI', 'VDICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NOUN'}),
    'より': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN', 'NAS'}),
    # ---- 推量・断定 ----
    'かもしれない': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                              'TAIB', 'NAS'}),
    'はず': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'わけ': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'べき': frozenset({'VDICT', 'ADICT'}),
    'ものだ': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'ことだ': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'わけだ': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'はずだ': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'べきだ': frozenset({'VDICT', 'ADICT'}),
    'のだ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'のです': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'んだ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'んです': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NAB'}),
    'んだろう': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                           'TAIB'}),
    'のでしょう': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                             'TAIB'}),
    'わけではない': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                               'TAIB'}),
    'に違いない': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                             'TAIB'}),
    'ものか': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'ことか': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'っけ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU'}),
    # ---- 様態・比況 ----
    # そう=样态（词干左）与传闻（辞书左）的合体，右接续另有联合校验
    'そう': frozenset({'VSA', 'VSAB', 'ADJS', 'NAS', 'VDICT', 'ADICT'}),
    'そうだ': frozenset({'VSA', 'VSAB', 'ADJS', 'NAS', 'VDICT', 'ADICT'}),
    'そうです': frozenset({'VSA', 'VSAB', 'ADJS', 'NAS', 'VDICT', 'ADICT'}),
    'そうに': frozenset({'VSA', 'VSAB', 'ADJS', 'NAS'}),
    'そうな': frozenset({'VSA', 'VSAB', 'ADJS', 'NAS'}),
    'らしい': frozenset({'NONO', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NOUN', 'NAS'}),
    'らしく': frozenset({'VDICT', 'NOUN', 'NAS'}),
    # よう两读合并（意向：未然左；比況：原形/た形/の左）
    'よう': frozenset({'RENTAI', 'M1KO', 'M1B', 'MSI', 'VDICT', 'ADICT',
                       'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NONO', 'RENTAI'}),
    'ようだ': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NONO'}),
    'ような': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NONO'}),
    'ように': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NONO'}),
    'みたい': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NOUN', 'NONO', 'NAS'}),
    'みたいだ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                           'NOUN', 'NONO', 'NAS'}),
    'みたいな': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                           'NOUN', 'NONO', 'NAS'}),
    'みたいに': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                           'NOUN', 'NONO', 'NAS'}),
    'ごとき': frozenset({'RENTAI', 'VDICT', 'NOUN', 'NONO'}),
    'ごとく': frozenset({'RENTAI', 'VDICT', 'NOUN', 'NONO'}),
    '並み': frozenset({'NOUN'}),
    '並みの': frozenset({'NOUN'}),
    'かのように': frozenset({'NOUN'}),
    # ---- 引用 ----
    'って': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'COPD', 'COPP', 'NOUN'}),
    'なんて': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'COPD', 'COPP', 'NOUN'}),
    'ってば': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                         'TAIB', 'NOUN'}),
    'とか': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN'}),
    'という': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB', 'NOUN'}),
    'ということ': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'ってこと': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'かどうか': frozenset({'NAS', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'か': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                     'COPD', 'COPP', 'NOUN', 'NAS'}),
    # ---- 接续 ----
    'ので': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'COPD', 'COPP', 'NAB'}),
    'のに': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'COPD', 'COPP', 'NAB'}),
    'から': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'COPD', 'COPP', 'NOUN'}),
    'けど': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'COPD', 'COPP'}),
    'けれど': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'COPD', 'COPP'}),
    'が': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                     'COPD', 'COPP', 'NOUN'}),
    'し': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI'}),
    'ものの': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'ものを': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB'}),
    'にもかかわらず': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                                 'TAIB', 'NOUN'}),
    'ために': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NONO'}),
    'おかげで': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU',
                           'TAIB', 'NONO'}),
    'せいで': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NONO'}),
    'おかげ': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NONO'}),
    'せい': frozenset({'RENTAI', 'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NONO'}),
    'やいなや': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V'}),
    # なり两读合并（瞬时：辞书/た形左；格助词：名词左）
    'なり': frozenset({'NOUN', 'VDICT', 'ADICT', 'TAFORM_U',
                          'TAFORM_V'}),
    'そばから': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V'}),
    'とたん': frozenset({'ADICT', 'TAFORM_U', 'TAFORM_V'}),
    '途端': frozenset({'ADICT', 'TAFORM_U', 'TAFORM_V'}),
    'が早いか': frozenset({'ADICT', 'TAFORM_U', 'TAFORM_V'}),
    # ---- 名词短语 ----
    'がほしい': frozenset({'NOUN'}), 'が欲しい': frozenset({'NOUN'}),
    'が要る': frozenset({'NOUN'}), 'が必要だ': frozenset({'NOUN'}),
    'が好きだ': frozenset({'NOUN'}), 'が嫌いだ': frozenset({'NOUN'}),
    'が心配だ': frozenset({'NOUN'}), 'が得意だ': frozenset({'NOUN'}),
    'が苦手だ': frozenset({'NOUN'}), 'が分かる': frozenset({'NOUN'}),
    'ができる': frozenset({'NOUN'}),
    'がある': frozenset({'NOUN'}), 'がいる': frozenset({'NOUN'}),
    'になる': frozenset({'NOUN', 'NAS', 'NIB'}),
    'にする': frozenset({'NOUN', 'NAS'}),
    'にできる': frozenset({'NOUN', 'NAS'}),
    'にある': frozenset({'NOUN', 'NAS'}),
    'について': frozenset({'NOUN'}), 'に対して': frozenset({'NOUN'}),
    'に関して': frozenset({'NOUN'}), 'にとって': frozenset({'NOUN'}),
    'として': frozenset({'NOUN'}), 'によって': frozenset({'NOUN'}),
    'において': frozenset({'NOUN'}), 'を通じて': frozenset({'NOUN'}),
    'を通して': frozenset({'NOUN'}), 'のあまり': frozenset({'NOUN', 'NONO'}),
    'のみならず': frozenset({'NOUN'}),
    'を問わず': frozenset({'NOUN'}),
    # ---- こと/よう句型 ----
    'ことができる': frozenset({'VDICT', 'RENTAI'}),
    'ことがある': frozenset({'VSB_U', 'VSAB'}),
    'たことがある': frozenset({'VSB_U', 'VSAB'}),
    'ことにする': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    'ことになる': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    'ようになる': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    'ほうがいい': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    'ほうがよい': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    '方がいい': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    '方がよい': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    '方が良い': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU'}),
    'わけにはいかない': frozenset({'VDICT'}),
    # ---- 意向接续（とする/と思う系，左为意向形）----
    'とする': frozenset({'VOL'}), 'としている': frozenset({'VOL'}),
    'とした': frozenset({'VOL'}), 'と思う': frozenset({'VOL'}),
    'と思っている': frozenset({'VOL'}),
    # ---- 敬语动词（辞书形，左为句首侧名词/从句，上下文选词）----
    'おっしゃる': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'いらっしゃる': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'くださる': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'なさる': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'ござる': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'うかがう': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    '申す': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'もうす': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    '頂く': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'いただく': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    '参る': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    '致す': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'おる': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    '存じる': frozenset({'NOUN', 'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    # ---- 付着・放置 ----
    'だらけ': frozenset({'NOUN'}), 'まみれ': frozenset({'NOUN'}),
    '気味': frozenset({'NOUN', 'VSA', 'VSAB', 'M1B', 'MSI'}),
    'っぱなし': frozenset({'VSA', 'VSB_U', 'VSAB', 'M1B', 'MSI'}),
    'っ放し': frozenset({'VSA', 'VSB_U', 'VSAB', 'M1B', 'MSI'}),
    'ぎみ': frozenset({'NOUN', 'VSA', 'VSAB', 'M1B', 'MSI'}),
    'な': frozenset({'NAS'}),
    'に': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                     'NAS', 'NOUN'}),
    # ---- 格助词/系助词/副助词（左类严格限定，否则 行く|を 会被放行）----
    'を': frozenset({'NOUN'}), 'へ': frozenset({'NOUN'}),
    'で': frozenset({'NOUN', 'NAS'}),
    'は': frozenset({'NOUN'}), 'も': frozenset({'NOUN'}),
    'や': frozenset({'NOUN'}), 'やら': frozenset({'NOUN'}),
    'とも': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN'}),
    'こそ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN'}),
    'さえ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN'}),
    'でも': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN', 'NAS'}),
    'など': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                       'NOUN'}),
    'なんか': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                         'NOUN'}),
    'ずつ': frozenset({'NOUN'}), 'おき': frozenset({'NOUN'}),
    'ごと': frozenset({'NOUN'}), '目': frozenset({'NOUN'}),
    '等': frozenset({'NOUN'}),
    'ね': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                     'COPD', 'COPP', 'NOUN', 'NAS'}),
    'よ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                     'COPD', 'COPP', 'NOUN', 'NAS'}),
    'さ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'TAIB',
                     'COPD', 'COPP', 'NOUN', 'NAS'}),
    'ぜ': frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'ぞ': frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V'}),
    'わ': frozenset({'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NOUN'}),
    'い': frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V'}),
}


# 后缀规则：（后缀，裸形左类，带前缀形左类-CTX）
# 带前缀形（如 高くなる、変えようとする、お世話になる）与裸形分属不同
# 槽位，互不可代——CTX 类彼此独立，只能在同族前缀形之间互换（上下文选词）。
_LQ_LEFT_SUF = [
    ('なければならな', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('なければならない', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('なくてはならな', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('ないといけな', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('なければいけな', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('てはいけな', _L_TEMO, _L_TEMO), ('てはならな', _L_TEMO, _L_TEMO),
    ('てもいい', _L_TEMO, _L_TEMO), ('ても良い', _L_TEMO, _L_TEMO),
    ('てしまう', _L_TE_U, _L_TE_U), ('でしまう', _L_TE_V, _L_TE_V),
    ('ていただ', _L_TE_U, _L_TE_U), ('てもら', _L_TE_U, _L_TE_U),
    ('てくれ', _L_TE_U, _L_TE_U), ('でくれ', _L_TE_V, _L_TE_V),
    ('てあげ', _L_TE_U, _L_TE_U), ('てさしあげ', _L_TE_U, _L_TE_U),
    ('てくださ', _L_TE_U, _L_TE_U), ('て下さ', _L_TE_U, _L_TE_U),
    ('てほしい', _L_TE_U, _L_TE_U), ('て欲しい', _L_TE_U, _L_TE_U),
    ('でほしい', _L_TE_V, _L_TE_V),
    ('てみ', _L_TE_U, _L_TE_U), ('てお', _L_TE_U, _L_TE_U),
    ('でお', _L_TE_V, _L_TE_V),
    ('てい', _L_TE_U, _L_TE_U), ('でい', _L_TE_V, _L_TE_V),
    ('てあ', _L_TE_U, _L_TE_U), ('であ', _L_TE_V, _L_TE_V),
    ('ちゃ', _L_TE_U, _L_TE_U), ('じゃ', _L_TE_V, _L_TE_V),
    ('とく', _L_TE_U, _L_TE_U), ('どく', _L_TE_V, _L_TE_V),
    ('てる', _L_TE_U, _L_TE_U), ('でる', _L_TE_V, _L_TE_V),
    ('てごらん', _L_TE_U, _L_TE_U), ('てちょうだい', _L_TE_U, _L_TE_U),
    ('たことがあ', frozenset({'VSB_U', 'VSAB'}),
     frozenset({'VSB_U', 'VSAB'})),
    ('だがことがあ', _L_TE_V, _L_TE_V),
    ('ことができる', frozenset({'VDICT', 'RENTAI'}), frozenset({'VDICTCTX'})),
    ('ことが出来る', frozenset({'VDICT', 'RENTAI'}), frozenset({'VDICTCTX'})),
    ('ことにな', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'RENTAI'})),
    ('ことにし', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'RENTAI'})),
    ('ようにな', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'RENTAI'})),
    ('くなる', frozenset({'ADJKU'}), frozenset({'KUNARU'})),
    ('くなる', frozenset({'ADJKU'}), frozenset({'KUNARU'})),
    ('になる', frozenset({'NOUN', 'NAS', 'NIB'}), frozenset({'NINARU'})),
    ('となる', frozenset({'NOUN', 'QUO'}), frozenset({'TONARU'})),
    ('とする', frozenset({'VOL'}), frozenset({'TOSURU'})),
    ('と思', frozenset({'VOL'}), frozenset({'TOSURU'})),
    ('がほしい', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('が欲しい', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('がほし', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('があ', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('がい', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('がいる', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('ざるを得な', frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSE'})),
    ('ずにはいられな', frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSE'})),
    ('わけにはいかな', frozenset({'VDICT'}), frozenset({'VDICT'})),
    ('んばかり', frozenset({'M1KO', 'M1B', 'M5'}),
     frozenset({'M1KO', 'M1B', 'M5'})),
    ('ないでくださ', frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('ないで下さ', frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('ないで', frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('なくて', frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('ずに', frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSE'})),
    ('なけれ', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('なかっ', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('なかった', frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'}),
     frozenset({'M1KO', 'M1B', 'M1NA', 'M5', 'MSI', 'SHIKAB', 'DEMOB'})),
    ('ねば', frozenset({'M1KO', 'M1B', 'M5', 'MSE'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSE'})),
    ('せる', frozenset({'M5', 'MSA'}), frozenset({'M5', 'MSA'})),
    ('させる', frozenset({'M1KO', 'M1B', 'M5', 'MSA'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSA'})),
    ('られる', frozenset({'M1KO', 'M1B', 'M5', 'MSA'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSA'})),
    ('れる', frozenset({'M1KO', 'M1B', 'M5', 'MSA'}),
     frozenset({'M1KO', 'M1B', 'M5', 'MSA'})),
    ('すぎ', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'}),
     frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'})),
    ('やす', _L_STEM, _L_STEM),
    ('にく', _L_STEM, _L_STEM),
    ('がた', _L_STEM, _L_STEM),
    ('かね', _L_STEM, _L_STEM),
    ('っぽ', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'}),
     frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'})),
    ('つつあ', frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}),
     frozenset({'VSA', 'VSAB', 'M1B', 'MSI'})),
    ('ながら', frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}),
     frozenset({'VSA', 'VSAB', 'M1B', 'MSI'})),
    ('つつ', frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}),
     frozenset({'VSA', 'VSAB', 'M1B', 'MSI'})),
    ('まみれ', frozenset({'NOUN'}), frozenset({'MAMIRE'})),
    ('だらけ', frozenset({'NOUN'}), frozenset({'DARACKE'})),
    ('気味', frozenset({'NOUN', 'VSA', 'VSAB', 'M1B', 'MSI'}),
     frozenset({'NOUN', 'VSA', 'VSAB', 'M1B', 'MSI'})),
    ('っぱなし', frozenset({'VSA', 'VSB_U', 'VSAB', 'M1B', 'MSI'}),
     frozenset({'VSA', 'VSB_U', 'VSAB', 'M1B', 'MSI'})),
    ('ものでし',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('もので',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('ものでしょう',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NONO', 'RENTAI'})),
    ('ものです',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('ものだ',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('もんだ',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NONO', 'RENTAI'})),
    ('ことだ',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('わけだ',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('はずだ',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('べきだ', frozenset({'VDICT', 'ADICT'}), frozenset({'VDICT', 'ADICT'})),
    ('のだ',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('のです',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('んだ',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('んです',
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('ようだ', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('みたいだ', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NOUN', 'NONO', 'NAS'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NOUN', 'NONO', 'NAS'})),
    ('らしい', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NOUN', 'NONO', 'NAS'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NOUN', 'NONO', 'NAS'})),
    ('そうだ', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS', 'VDICT', 'ADICT'}),
     frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS', 'VDICT', 'ADICT'})),
    ('かもしれな', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO'})),
    ('でしょ', frozenset({'NOUN', 'NAS', 'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'COPD', 'COPP', 'NONO', 'PARTICLEB'}),
     frozenset({'NOUN', 'NAS', 'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'COPD', 'COPP', 'NONO', 'PARTICLEB'})),
    ('だろ', frozenset({'NOUN', 'NAS', 'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'COPD', 'NONO', 'PARTICLEB'}),
     frozenset({'NOUN', 'NAS', 'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'COPD', 'NONO', 'PARTICLEB'})),
    ('ましょ', _L_STEM, _L_STEM),
    ('ません', _L_STEM, _L_STEM),
    ('くださ', frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'}),
     frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'})),
    ('下さ', frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'}),
     frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'})),
    ('なさ', frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'}),
     frozenset({'VSA', 'VSAB', 'VTE', 'M1B', 'MSI'})),
    ('いただ', frozenset({'VSB_U', 'VSAB', 'M1B', 'MSI'}),
     frozenset({'VSB_U', 'VSAB', 'M1B', 'MSI'})),
    ('頂', frozenset({'VSB_U', 'VSAB', 'M1B', 'MSI'}),
     frozenset({'VSB_U', 'VSAB', 'M1B', 'MSI'})),
    ('におい', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('における', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('において', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('について', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('に対して', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('に対する', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('に関して', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('に関する', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('にとって', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('として', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('によって', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('により', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('による', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('を通じ', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('を通し', frozenset({'NOUN'}), frozenset({'NOUN'})),
    ('にもかかわらず', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NOUN'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NOUN'})),
    ('にも関わらず', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NOUN'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'NOUN'})),
    ('に違いな', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI'})),
    ('にちがいな', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI'})),
    ('おかげで', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('せいで', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('ために', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('ように', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'}),
     frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NONO', 'RENTAI'})),
    ('みたいに', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NOUN', 'NONO', 'NAS'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NAI', 'TEIRU', 'NOUN', 'NONO', 'NAS'})),
    ('うちに', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NAI'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU', 'NAI'})),
    ('たびに', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'TEIRU'})),
    ('ごとに', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NOUN'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NOUN'})),
    ('度に', frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NOUN'}), frozenset({'VDICT', 'TAFORM_U', 'TAFORM_V', 'NOUN'})),
    # ---- 屈折后缀（ます词干/た形/て形/ない形，digger 常挖出屈折
    # 形如 てしまった/てみて/てしまわない；无规则会走未知放行、
    # 放出 行か|てしまった 类错误干扰项）----
    ('てしまい', _L_TE_U, _L_TE_U),
    ('でしまい', _L_TE_V, _L_TE_V),
    ('ておき', _L_TE_U, _L_TE_U),
    ('でおき', _L_TE_V, _L_TE_V),
    ('てみせ', _L_TE_U, _L_TE_U),
    ('でみせ', _L_TE_V, _L_TE_V),
    ('ていき', _L_TE_U, _L_TE_U),
    ('でいき', _L_TE_V, _L_TE_V),
    ('てき', _L_TE_U, _L_TE_U),
    ('でき', _L_TE_V, _L_TE_V),
    ('てもらい', _L_TE_U, _L_TE_U),
    ('でもらい', _L_TE_V, _L_TE_V),
    ('てさしあげ', _L_TE_U, _L_TE_U),
    ('でさしあげ', _L_TE_V, _L_TE_V),
    ('ていただき', _L_TE_U, _L_TE_U),
    ('でいただき', _L_TE_V, _L_TE_V),
    ('てほし', _L_TE_U, _L_TE_U),
    ('でほし', _L_TE_V, _L_TE_V),
    ('ていただきた', _L_TE_U, _L_TE_U),
    ('でいただきた', _L_TE_V, _L_TE_V),
    ('てもらいた', _L_TE_U, _L_TE_U),
    ('でもらいた', _L_TE_V, _L_TE_V),
    ('て頂', _L_TE_U, _L_TE_U),
    ('て頂け', _L_TE_U, _L_TE_U),
    ('て頂き', _L_TE_U, _L_TE_U),
    ('て戴け', _L_TE_U, _L_TE_U),
    ('て貰い', _L_TE_U, _L_TE_U),
    ('て揚げる', _L_TE_U, _L_TE_U),
    ('で貰い', _L_TE_V, _L_TE_V),
    ('てしまった', _L_TE_U, _L_TE_U),
    ('でしまった', _L_TE_V, _L_TE_V),
    ('ておいた', _L_TE_U, _L_TE_U),
    ('でおいた', _L_TE_V, _L_TE_V),
    ('てみた', _L_TE_U, _L_TE_U),
    ('でみた', _L_TE_V, _L_TE_V),
    ('ていた', _L_TE_U, _L_TE_U),
    ('でいた', _L_TE_V, _L_TE_V),
    ('てあった', _L_TE_U, _L_TE_U),
    ('であった', _L_TE_V, _L_TE_V),
    ('てみせた', _L_TE_U, _L_TE_U),
    ('でみせた', _L_TE_V, _L_TE_V),
    ('ていった', _L_TE_U, _L_TE_U),
    ('でいった', _L_TE_V, _L_TE_V),
    ('てきた', _L_TE_U, _L_TE_U),
    ('できた', _L_TE_V, _L_TE_V),
    ('てくれた', _L_TE_U, _L_TE_U),
    ('でくれた', _L_TE_V, _L_TE_V),
    ('てもらった', _L_TE_U, _L_TE_U),
    ('でもらった', _L_TE_V, _L_TE_V),
    ('てあげた', _L_TE_U, _L_TE_U),
    ('であげた', _L_TE_V, _L_TE_V),
    ('てさしあげた', _L_TE_U, _L_TE_U),
    ('でさしあげた', _L_TE_V, _L_TE_V),
    ('てくださった', _L_TE_U, _L_TE_U),
    ('でくださった', _L_TE_V, _L_TE_V),
    ('ていただいた', _L_TE_U, _L_TE_U),
    ('でいただいた', _L_TE_V, _L_TE_V),
    ('ちゃった', _L_TE_U, _L_TE_U),
    ('じゃった', _L_TE_V, _L_TE_V),
    ('とった', _L_TE_U, _L_TE_U),
    ('どった', _L_TE_V, _L_TE_V),
    ('てった', _L_TE_U, _L_TE_U),
    ('でった', _L_TE_V, _L_TE_V),
    ('すぎた', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'})),
    ('かねた', _L_STEM, _L_STEM),
    ('つつあった', frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI'})),
    ('たがった', _L_STEM, _L_STEM),
    ('っこなかった', _L_STEM, _L_STEM),
    ('てほしかった', _L_TE_U, _L_TE_U),
    ('やすかった', _L_STEM, _L_STEM),
    ('にくかった', _L_STEM, _L_STEM),
    ('がたかった', _L_STEM, _L_STEM),
    ('っぽかった', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'})),
    ('でほしかった', _L_TE_V, _L_TE_V),
    ('てしまって', _L_TE_U, _L_TE_U),
    ('でしまって', _L_TE_V, _L_TE_V),
    ('ておいて', _L_TE_U, _L_TE_U),
    ('でおいて', _L_TE_V, _L_TE_V),
    ('てみて', _L_TE_U, _L_TE_U),
    ('でみて', _L_TE_V, _L_TE_V),
    ('ていて', _L_TE_U, _L_TE_U),
    ('でいて', _L_TE_V, _L_TE_V),
    ('てあって', _L_TE_U, _L_TE_U),
    ('であって', _L_TE_V, _L_TE_V),
    ('てみせて', _L_TE_U, _L_TE_U),
    ('でみせて', _L_TE_V, _L_TE_V),
    ('ていって', _L_TE_U, _L_TE_U),
    ('でいって', _L_TE_V, _L_TE_V),
    ('てきて', _L_TE_U, _L_TE_U),
    ('できて', _L_TE_V, _L_TE_V),
    ('てくれて', _L_TE_U, _L_TE_U),
    ('でくれて', _L_TE_V, _L_TE_V),
    ('てもらって', _L_TE_U, _L_TE_U),
    ('でもらって', _L_TE_V, _L_TE_V),
    ('てあげて', _L_TE_U, _L_TE_U),
    ('であげて', _L_TE_V, _L_TE_V),
    ('てさしあげて', _L_TE_U, _L_TE_U),
    ('でさしあげて', _L_TE_V, _L_TE_V),
    ('てくださって', _L_TE_U, _L_TE_U),
    ('でくださって', _L_TE_V, _L_TE_V),
    ('ていただいて', _L_TE_U, _L_TE_U),
    ('でいただいて', _L_TE_V, _L_TE_V),
    ('てほしくて', _L_TE_U, _L_TE_U),
    ('でほしくて', _L_TE_V, _L_TE_V),
    ('ちゃって', _L_TE_U, _L_TE_U),
    ('じゃって', _L_TE_V, _L_TE_V),
    ('とって', _L_TE_U, _L_TE_U),
    ('どって', _L_TE_V, _L_TE_V),
    ('てって', _L_TE_U, _L_TE_U),
    ('でって', _L_TE_V, _L_TE_V),
    ('すぎて', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'})),
    ('やすくて', _L_STEM, _L_STEM),
    ('にくくて', _L_STEM, _L_STEM),
    ('がたくて', _L_STEM, _L_STEM),
    ('かねて', _L_STEM, _L_STEM),
    ('っぽくて', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'})),
    ('つつあって', frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI'})),
    ('たがって', _L_STEM, _L_STEM),
    ('っこなくて', _L_STEM, _L_STEM),
    ('てしまわない', _L_TE_U, _L_TE_U),
    ('でしまわない', _L_TE_V, _L_TE_V),
    ('ておかない', _L_TE_U, _L_TE_U),
    ('でおかない', _L_TE_V, _L_TE_V),
    ('てみない', _L_TE_U, _L_TE_U),
    ('でみない', _L_TE_V, _L_TE_V),
    ('ていない', _L_TE_U, _L_TE_U),
    ('でいない', _L_TE_V, _L_TE_V),
    ('てあらない', _L_TE_U, _L_TE_U),
    ('であらない', _L_TE_V, _L_TE_V),
    ('てみせない', _L_TE_U, _L_TE_U),
    ('でみせない', _L_TE_V, _L_TE_V),
    ('ていかない', _L_TE_U, _L_TE_U),
    ('でいかない', _L_TE_V, _L_TE_V),
    ('てこない', _L_TE_U, _L_TE_U),
    ('でこない', _L_TE_V, _L_TE_V),
    ('てくれない', _L_TE_U, _L_TE_U),
    ('でくれない', _L_TE_V, _L_TE_V),
    ('てもらわない', _L_TE_U, _L_TE_U),
    ('でもらわない', _L_TE_V, _L_TE_V),
    ('てあげない', _L_TE_U, _L_TE_U),
    ('であげない', _L_TE_V, _L_TE_V),
    ('てさしあげない', _L_TE_U, _L_TE_U),
    ('でさしあげない', _L_TE_V, _L_TE_V),
    ('てくださらない', _L_TE_U, _L_TE_U),
    ('でくださらない', _L_TE_V, _L_TE_V),
    ('ていただかない', _L_TE_U, _L_TE_U),
    ('でいただかない', _L_TE_V, _L_TE_V),
    ('てほしくない', _L_TE_U, _L_TE_U),
    ('でほしくない', _L_TE_V, _L_TE_V),
    ('ちゃわない', _L_TE_U, _L_TE_U),
    ('じゃわない', _L_TE_V, _L_TE_V),
    ('とらない', _L_TE_U, _L_TE_U),
    ('どらない', _L_TE_V, _L_TE_V),
    ('てない', _L_TE_U, _L_TE_U),
    ('でない', _L_TE_V, _L_TE_V),
    ('すぎない', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS', 'NAS'})),
    ('やすくない', _L_STEM, _L_STEM),
    ('にくくない', _L_STEM, _L_STEM),
    ('がたくない', _L_STEM, _L_STEM),
    ('っぽくない', frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI', 'NOUN'})),
    ('つつあらない', frozenset({'VSA', 'VSAB', 'M1B', 'MSI'}), frozenset({'VSA', 'VSAB', 'M1B', 'MSI'})),
    ('たがらない', _L_STEM, _L_STEM),
    ('っこなくない', _L_STEM, _L_STEM),
    ('だら', frozenset({'VSB_V', 'TAFORM_V'}), frozenset({'VSB_V', 'TAFORM_V'})),
]
# 过滤占位，整理为最长优先
_LQ_LEFT_SUF = sorted(
    [e for e in _LQ_LEFT_SUF if isinstance(e, tuple)],
    key=lambda e: -len(e[0]))


def _lq_left(surface):
    """候选/答案表面形的左接续类。精确匹配优先，最长后缀兜底；
    带前缀形（高くなる、変えようとする）取 CTX 类。未知返回 None（放行）。"""
    hit = _LQ_LEFT_EXACT.get(surface)
    if hit is not None:
        return hit
    for suf, bare, ctx in _LQ_LEFT_SUF:
        if surface.endswith(suf):
            return bare if surface == suf else ctx
    return None


# ---- 右接续类词典 ----
# 常用右类组合
_R_VP = frozenset({'END', 'NAP_E', 'QUO', 'MASU', 'NOUNR', 'NOP', 'CONJN',
                   'TEMO', 'TEWA', 'TEN', 'NODA', 'CONDTO', 'DARO'})
# て形清浊音变对照（U 清音 ↔ V 浊音，按最长优先匹配）：答案 てしま
# う/ちゃう/ておく/ている 等是清音词尾（接 VSB_U/TAFORM_U），でしま
# う/じゃう/どく/でいる 等是浊音词尾（接 VSB_V/TAFORM_V）。清浊不分会放
# 行 行っ|でいる、読ん|てみる、買った|だり、死んだ|たり 等错误。
_VOICE_U = ('ちゃ', 'とく', 'てる', 'て', 'た')
_VOICE_V = ('じゃ', 'どく', 'でる', 'で', 'だ')

_R_VP_TE = _R_VP | frozenset({'TEP'})
# 注：MASU 必须保留在 _R_VP_TE 中——行っ|ている|ます（行っています）、
# 行っ|ておく|ます（行っておきます）都是合法的；之前误判为 bug，已撤销。
# 注：_R_IP 不含 TEMO/TEWA——ない/たい/てもいい…后不可直接接ても/ては
# （高くないても×、高くないては×），必须经 なくても/なくては 迂回。
_R_IP = frozenset({'END', 'NAP_E', 'QUO', 'DESU', 'NOUNR', 'NOP',
                   'CONJN', 'TEN', 'NODA', 'CONDTO', 'DARO'})
_R_DAFORM = frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'})
_R_DESUFORM = frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN'})
_R_MASUFORM = frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN'})
_R_IMP = frozenset({'END', 'NAP_E', 'QUO', 'TEN', 'IMPR'})
_R_CONJ = frozenset({'PRED', 'QUO', 'TEN'})
# ます词干答案（てき/ておき/てみせ…）：后必须接续行成分——ます
# （てきます√）、に+移动动词（ておきに行く√）、复合动词后项
# （てしまい始める√）、てください类（お読みください√）；不可句末
# （行ってき。×），故不含 END。
_R_STEM = frozenset({'MASU', 'NIP', 'PRED', 'IMPR'})
# た形动词答案（てしまった…）：_R_VP 去 MASU（てしまったます×）
# 加 DESU（てしまったです√，礼貌过去）。
_R_PAST_V = (_R_VP - frozenset({'MASU'})) | frozenset({'DESU'})
# て形/ないで答案（てしまって/ないで/なくて…）：_R_CONJ+CONJN 再加
# IMPR（てしまってください√、ないでください√）。
_R_TE = _R_CONJ | frozenset({'CONJN', 'IMPR'})

_LQ_RIGHT_EXACT = {
    # ---- ます・丁寧 ----
    'ます': _R_MASUFORM, 'ません': _R_MASUFORM, 'ましょう': _R_MASUFORM,
    'ませ': _R_MASUFORM,
    'です': _R_DESUFORM, 'でした': _R_DESUFORM, 'である': _R_DESUFORM,
    'であった': _R_DESUFORM, 'であり': _R_DESUFORM,
    'であります': _R_DESUFORM, 'であろう': _R_DESUFORM,
    'だった': _R_DAFORM, 'だったら': _R_CONJ,
    'だったろ': _R_DAFORM,
    'じゃない': _R_DAFORM, 'ではなく': _R_CONJ | frozenset({'CONJN'}),
    'ではない': _R_DAFORM, 'じゃ': _R_DAFORM,
    'でしょう': frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'}),
    'だろう': frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'}),
    # ---- て复合（ます形可接ます；てほしい系是形容词、不可接ます但可接です）----
    'ている': _R_VP_TE, 'てある': _R_VP_TE, 'ておく': _R_VP_TE,
    'てみる': _R_VP_TE, 'てしまう': _R_VP_TE, 'ていく': _R_VP_TE,
    'てくる': _R_VP_TE, 'てみせる': _R_VP_TE,
    'てくれる': _R_VP_TE, 'てもらう': _R_VP_TE, 'てあげる': _R_VP_TE,
    'ていただく': _R_VP_TE, 'てくださる': _R_VP_TE, 'てさしあげる': _R_VP_TE,
    'ちゃう': _R_VP, 'とく': _R_VP, 'てる': _R_VP,
    'でいる': _R_VP_TE, 'でおく': _R_VP_TE, 'でしまう': _R_VP_TE,
    'でもらう': _R_VP_TE, 'でくれる': _R_VP_TE, 'じゃう': _R_VP,
    'どく': _R_VP, 'でる': _R_VP, 'でいく': _R_VP_TE, 'でくる': _R_VP_TE,
    'てほしい': _R_IP, 'て欲しい': _R_IP, 'でほしい': _R_IP,
    'ていただきたい': _R_IP, 'てもらいたい': _R_IP,
    'てちょうだい': _R_IMP, 'てごらん': _R_IMP,
    'ては': _R_CONJ, 'ても': _R_CONJ, 'てから': _R_CONJ,
    'てもいい': _R_IP, 'ても良い': _R_IP, 'でもいい': _R_IP,
    'てはいけない': _R_IP, 'てはならない': _R_IP,
    'てもかまわない': _R_IP, 'ではいけない': _R_IP,
    'てください': _R_IMP, 'て下さい': _R_IMP,
    'ください': _R_IMP, '下さい': _R_IMP, 'なさい': _R_IMP,
    'ちょうだい': _R_IMP, 'たまえ': _R_IMP,
    'もらえ': _R_IMP | frozenset({'TEP'}),
    'くれ': _R_IMP | frozenset({'TEP'}), 'てくれ': _R_IMP | frozenset({'TEP'}),
    'たり': _R_IMP, 'だり': _R_IMP,
    # ---- 未然 ----
    'ない': _R_IP, 'せる': _R_VP | frozenset({'TEP'}),
    'させる': _R_VP | frozenset({'TEP'}),
    'れる': _R_VP | frozenset({'TEP'}), 'られる': _R_VP | frozenset({'TEP'}),
    'う': frozenset({'END', 'NAP_E', 'QUO', 'TEN'}),
    # よう（意向/比況两读）见下方合并条目
    'まい': frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'}),
    'ば': _R_CONJ, 'ねば': _R_CONJ,
    'なければ': _R_CONJ | frozenset({'CONJN'}),
    'なかったら': _R_CONJ | frozenset({'CONJN'}),
    'ないと': _R_CONJ | frozenset({'CONJN'}),
    'ないなら': _R_CONJ | frozenset({'CONJN'}),
    'なきゃ': _R_CONJ | frozenset({'CONJN'}),
    'なきゃいけない': _R_IP, 'なくちゃ': _R_CONJ | frozenset({'CONJN'}),
    'なくちゃいけない': _R_IP, 'なければならない': _R_IP,
    'なければいけない': _R_IP, 'なくてはならない': _R_IP,
    'ないといけない': _R_IP, 'ねばならない': _R_IP,
    'ざるを得ない': _R_IP, 'ざる': frozenset({'PRED', 'QUO'}),
    'ず': frozenset({'PRED', 'QUO'}), 'ぬ': _R_IP,
    'んばかり': frozenset({'PRED', 'QUO', 'TEN'}),
    'ずに': _R_CONJ | frozenset({'CONJN'}),
    'ずにはいられない': _R_IP,
    'ないで': _R_TE,
    'なくて': _R_TE,
    'ないでください': _R_IMP, 'ないで下さい': _R_IMP,
    # ---- 条件 ----
    'たら': _R_CONJ, 'と': frozenset({'PRED', 'QUO', 'TEN'}),
    'なら': _R_CONJ | frozenset({'CONJN'}),
    'ならば': _R_CONJ | frozenset({'CONJN'}),
    'であれば': _R_CONJ | frozenset({'CONJN'}),
    'だと': frozenset({'PRED', 'QUO', 'TEN'}),
    # ---- 词干 ----
    'たい': _R_IP, 'たがる': _R_VP, 'がる': _R_VP,
    'やすい': _R_IP, 'にくい': _R_IP, 'がたい': _R_IP,
    'すぎる': _R_VP | frozenset({'TEP'}),
    'っぽい': _R_IP, 'かねる': _R_VP | frozenset({'TEP'}),
    'かねない': _R_IP,
    'がち': frozenset({'END', 'NAP_E', 'QUO', 'DA', 'DESU', 'DARO', 'NAP',
                       'NOP', 'CONJN', 'TEN'}),
    'ながら': _R_CONJ, 'つつ': _R_CONJ, 'つつある': _R_VP,
    '方': frozenset({'NOP', 'NIP', 'DEP', 'WOP', 'CONJN', 'GAP', 'HAP',
                     'MOP', 'CASEP', 'DA', 'DESU', 'DARO', 'TEN', 'END',
                     'NAP_E'}),
    'かた': frozenset({'NOP', 'NIP', 'DEP', 'WOP', 'CONJN', 'GAP', 'HAP',
                       'MOP', 'CASEP', 'DA', 'DESU', 'DARO', 'TEN', 'END',
                       'NAP_E'}),
    'ぶり': frozenset({'NOP', 'NIP', 'DEP', 'WOP', 'CONJN', 'GAP', 'HAP',
                       'MOP', 'CASEP', 'DA', 'DESU', 'DARO', 'TEN'}),
    'っこない': _R_IP,
    'がてら': frozenset({'PRED', 'QUO', 'TEN'}),
    # ---- 名词 ----
    'もの': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP', 'WOP',
                       'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP', 'TEN',
                       'SHIKA', 'NAP_E'}),
    'こと': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP', 'WOP',
                       'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP', 'TEN',
                       'SHIKA', 'NAP_E'}),
    'の': frozenset({'DA', 'DESU', 'DARO', 'NIP', 'DEP', 'WOP', 'CONJN',
                     'GAP', 'HAP', 'MOP', 'CASEP', 'TEN', 'SHIKA', 'NAP_E'}),
    'ん': frozenset({'DA', 'DESU', 'DARO', 'NIP', 'DEP', 'WOP', 'CONJN',
                     'GAP', 'HAP', 'MOP', 'CASEP', 'TEN', 'NAP_E'}),
    'ため': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP', 'NIP',
                       'DEP', 'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP', 'TEN',
                       'SHIKA'}),
    'ほう': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP', 'NIP',
                       'DEP', 'WOP', 'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP',
                       'TEN', 'SHIKA'}),
    'ところ': frozenset({'DA', 'DESU', 'DARO', 'NIP', 'DEP', 'WOP', 'CONJN',
                         'GAP', 'HAP', 'MOP', 'CASEP', 'TEN', 'SHIKA'}),
    'ところだ': _R_DAFORM,
    'まま': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP', 'WOP',
                       'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP', 'TEN',
                       'SHIKA'}),
    'とおり': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP', 'WOP',
                         'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP', 'TEN',
                         'SHIKA'}),
    '途中': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP', 'WOP',
                       'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP', 'TEN'}),
    '最中': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP', 'WOP',
                       'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP', 'TEN'}),
    'うちに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'MOP', 'NAP_E'}),
    'たびに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'MOP', 'NAP_E'}),
    'ごとに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    '度に': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    '最中に': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'ところで': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'ままに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'NARU'}),
    'とおりに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'MIERU'}),
    'ことに': frozenset({'NARU', 'MIERU', 'PRED', 'QUO', 'NAP_E'}),
    'ばかり': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP', 'NIP',
                         'DEP', 'WOP', 'CONJN', 'GAP', 'HAP', 'MOP', 'TEN'}),
    'ばかりに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'たばかり': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP',
                           'CONJN', 'TEN'}),
    'だけ': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP', 'NIP',
                       'DEP', 'CONJN', 'HAP', 'MOP', 'TEN', 'SHIKA'}),
    'だけに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    # しか后必须是否定谓语（ない系），别无其他
    'しか': frozenset({'NAIR'}),
    'のみ': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP', 'NIP',
                       'DEP', 'CONJN', 'HAP', 'MOP', 'TEN', 'NAP_E'}),
    'きり': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP', 'CONJN',
                       'HAP', 'MOP', 'TEN'}),
    'ほど': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP', 'CONJN',
                       'MOP', 'TEN', 'SHIKA'}),
    'くらい': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP',
                         'CONJN', 'MOP', 'TEN'}),
    'ぐらい': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP',
                         'CONJN', 'MOP', 'TEN'}),
    'まで': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP',
                       'NIP', 'DEP', 'CONJN', 'HAP', 'MOP', 'TEN',
                       'SHIKA', 'NAIR', 'PRED'}),
    'より': frozenset({'END', 'NAP_E', 'DA', 'DESU', 'DARO', 'NOP',
                       'NIP', 'CONJN', 'HAP', 'MOP', 'TEN', 'SHIKA',
                       'PRED'}),
    # ---- 推量・断定 ----
    'かもしれない': frozenset({'END', 'NAP_E', 'QUO', 'DESU', 'NOP',
                              'CONJN', 'TEN', 'NODA', 'NOX', 'CONDTO'}),
    'はず': frozenset({'DA', 'DESU', 'DARO', 'NAP'}),
    'わけ': frozenset({'DA', 'DESU', 'DARO', 'NAP', 'NOP', 'NIP',
                       'DEP', 'WOP', 'CONJN', 'GAP', 'HAP', 'MOP',
                       'CASEP', 'TEN'}),
    'べき': frozenset({'DA', 'DESU', 'DARO', 'NAP'}),
    'ものだ': _R_DAFORM, 'ことだ': _R_DAFORM, 'わけだ': _R_DAFORM,
    'はずだ': _R_DAFORM, 'べきだ': _R_DAFORM,
    'のだ': _R_DAFORM, 'のです': _R_DESUFORM,
    'んだ': _R_DAFORM, 'んです': _R_DESUFORM,
    'んだろう': frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN'}),
    'のでしょう': frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN'}),
    'わけではない': _R_IP, 'に違いない': _R_IP,
    'ものか': frozenset({'END', 'NAP_E', 'QUO', 'TEN', 'CONJN'}),
    'ことか': frozenset({'END', 'NAP_E', 'QUO', 'TEN', 'CONJN'}),
    'っけ': frozenset({'END', 'NAP_E', 'QUO', 'DESU', 'TEN', 'CONJN'}),
    # ---- 様態・比況 ----
    'そう': frozenset({'DA', 'DESU', 'NIP', 'NAP', 'NAP_E'}),
    'そうだ': _R_DAFORM, 'そうです': _R_DESUFORM,
    'そうに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'MIERU'}),
    'そうな': frozenset({'NOUNR'}),
    'らしい': _R_IP, 'らしく': frozenset({'PRED', 'QUO', 'TEN', 'NAP_E'}),
    # よう两读合并（意向：句末；比況：接断定/な/に）
    'よう': frozenset({'END', 'NAP_E', 'QUO', 'TEN', 'DA', 'DESU',
                       'DARO', 'NAP', 'NIP'}),
    'ようだ': _R_DAFORM, 'ような': frozenset({'NOUNR'}),
    'ように': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'NARU',
                         'MIERU'}),
    'みたい': frozenset({'DA', 'DESU', 'DARO', 'NAP', 'NAP_E', 'NIP'}),
    'みたいだ': _R_DAFORM, 'みたいな': frozenset({'NOUNR'}),
    'みたいに': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'MIERU'}),
    'ごとき': frozenset({'NOUNR', 'NAP_E'}),
    'ごとく': frozenset({'PRED', 'QUO', 'TEN', 'NAP_E'}),
    '並み': frozenset({'DA', 'DESU', 'DARO', 'NOP'}),
    '並みの': frozenset({'NOUNR'}),
    'かのように': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    # ---- 引用 ----
    'って': frozenset({'QUO', 'END', 'NAP_E', 'TEN', 'CONJN', 'NOP', 'HAP',
                       'MOP', 'CASEP', 'NODA', 'NOX'}),
    'なんて': frozenset({'QUO', 'END', 'NAP_E', 'TEN', 'CONJN', 'NOP',
                         'HAP', 'MOP', 'CASEP', 'NODA', 'NOX'}),
    'ってば': frozenset({'QUO', 'END', 'NAP_E', 'TEN'}),
    'とか': frozenset({'QUO', 'END', 'NAP_E', 'TEN', 'CONJN', 'NOP'}),
    'という': frozenset({'QUO', 'NOUNR', 'NOP', 'NAP_E', 'NODA',
                           'NOX'}),
    'ということ': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP',
                             'WOP', 'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP',
                             'TEN', 'NAP_E'}),
    'ってこと': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP',
                           'WOP', 'CONJN', 'GAP', 'HAP', 'MOP', 'CASEP',
                           'TEN', 'NAP_E'}),
    'かどうか': frozenset({'END', 'NAP_E', 'QUO', 'TEN', 'CONJN', 'NOP'}),
    'か': frozenset({'END', 'NAP_E', 'QUO', 'TEN', 'CONJN'}),
    # ---- 接续 ----
    'ので': _R_CONJ | frozenset({'CONJN'}),
    'のに': _R_CONJ | frozenset({'CONJN'}),
    'から': _R_CONJ | frozenset({'CONJN'}),
    'けど': _R_CONJ | frozenset({'CONJN'}),
    'けれど': _R_CONJ | frozenset({'CONJN'}),
    'が': _R_CONJ | frozenset({'CONJN'}),
    'し': _R_CONJ | frozenset({'CONJN'}),
    'ものの': _R_CONJ, 'ものを': _R_CONJ,
    'にもかかわらず': _R_CONJ | frozenset({'CONJN'}),
    'ために': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'おかげで': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'せいで': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'おかげ': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'DEP', 'CONJN',
                         'TEN'}),
    'せい': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'DEP', 'CONJN', 'TEN'}),
    'やいなや': frozenset({'PRED', 'TEN'}),
    'なり': frozenset({'PRED', 'TEN'}),
    'そばから': frozenset({'PRED', 'TEN'}),
    'とたん': frozenset({'NOP', 'NIP', 'PRED', 'TEN'}),
    '途端': frozenset({'NOP', 'NIP', 'PRED', 'TEN'}),
    'が早いか': frozenset({'PRED', 'TEN'}),
    # ---- 名词短语 ----
    'がほしい': _R_IP, 'が欲しい': _R_IP, 'が要る': _R_VP,
    'が必要だ': _R_DAFORM, 'が好きだ': _R_DAFORM, 'が嫌いだ': _R_DAFORM,
    'が心配だ': _R_DAFORM, 'が得意だ': _R_DAFORM, 'が苦手だ': _R_DAFORM,
    'が分かる': _R_VP, 'ができる': _R_VP,
    'がある': _R_VP, 'がいる': _R_VP,
    'になる': _R_VP, 'にする': _R_VP, 'にできる': _R_VP, 'にある': _R_VP,
    'について': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'に対して': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'に関して': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'にとって': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'として': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'によって': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'において': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'を通じて': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'を通して': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'のあまり': frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
    'のみならず': frozenset({'PRED', 'QUO', 'TEN'}),
    'を問わず': frozenset({'PRED', 'QUO', 'TEN'}),
    # ---- こと/よう句型 ----
    'ことができる': _R_VP, 'ことがある': _R_VP, 'たことがある': _R_VP,
    'ことにする': _R_VP, 'ことになる': _R_VP, 'ようになる': _R_VP,
    'ほうがいい': _R_IP, 'ほうがよい': _R_IP,
    '方がいい': _R_IP, '方がよい': _R_IP, '方が良い': _R_IP,
    'わけにはいかない': _R_IP,
    # ---- 意向接续 ----
    'とする': _R_VP, 'としている': _R_VP, 'とした': _R_VP,
    'と思う': _R_VP, 'と思っている': _R_VP,
    # ---- 敬语 ----
    'おっしゃる': _R_VP, 'いらっしゃる': _R_VP, 'くださる': _R_VP,
    'なさる': _R_VP, 'ござる': _R_VP, 'うかがう': _R_VP,
    '申す': _R_VP, 'もうす': _R_VP, '頂く': _R_VP,
    'いただく': _R_VP, '参る': _R_VP, '致す': _R_VP,
    'おる': _R_VP, '存じる': _R_VP,
    # ---- 付着 ----
    'だらけ': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'CONJN', 'NAP',
                         'TEN', 'END', 'NAP_E'}),
    'まみれ': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'CONJN', 'TEN',
                         'END', 'NAP_E'}),
    '気味': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'CONJN', 'TEN',
                       'END', 'NAP_E'}),
    'っぱなし': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP',
                           'CONJN', 'TEN'}),
    'っ放し': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP',
                         'CONJN', 'TEN'}),
    'ぎみ': frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'CONJN', 'TEN',
                       'END', 'NAP_E'}),
    'な': frozenset({'NOUNR'}), 'に': frozenset({'PRED', 'QUO'}),
    # ---- 格助词等（主要作候选，很少作答案）----
    'を': frozenset({'PRED', 'QUO', 'TEN', 'MOP'}),
    'へ': frozenset({'PRED', 'QUO', 'TEN'}),
    'で': frozenset({'PRED', 'QUO', 'TEN', 'MOP'}),
    'は': frozenset({'PRED', 'QUO', 'TEN', 'MOP'}),
    'も': frozenset({'PRED', 'QUO', 'TEN', 'NAIR'}),
    'や': frozenset({'PRED', 'QUO', 'TEN'}),
    'やら': frozenset({'PRED', 'QUO', 'TEN'}),
    'とも': frozenset({'PRED', 'QUO', 'TEN', 'NAIR'}),
    'こそ': frozenset({'PRED', 'QUO', 'TEN', 'NAIR'}),
    'さえ': frozenset({'PRED', 'QUO', 'TEN', 'NAIR'}),
    'でも': frozenset({'PRED', 'QUO', 'TEN', 'NAIR'}),
    'など': frozenset({'PRED', 'QUO', 'TEN'}),
    'なんか': frozenset({'PRED', 'QUO', 'TEN'}),
    'ずつ': frozenset({'PRED', 'QUO', 'TEN'}),
    'おき': frozenset({'PRED', 'QUO', 'TEN'}),
    'ごと': frozenset({'PRED', 'QUO', 'TEN', 'NOP'}),
    '目': frozenset({'NOP', 'NIP', 'WOP', 'CONJN', 'GAP', 'HAP', 'DA',
                     'DESU', 'TEN'}),
    '等': frozenset({'PRED', 'QUO', 'TEN'}),
    'ね': frozenset({'END', 'NAP_E', 'TEN'}),
    'よ': frozenset({'END', 'NAP_E', 'TEN'}),
    'さ': frozenset({'END', 'NAP_E', 'TEN'}),
    'ぜ': frozenset({'END', 'NAP_E', 'TEN'}),
    'ぞ': frozenset({'END', 'NAP_E', 'TEN'}),
    'わ': frozenset({'END', 'NAP_E', 'TEN'}),
    'い': frozenset({'END', 'NAP_E', 'TEN'}),
}


# 后缀规则：（后缀，裸形右类，带前缀形右类）
_LQ_RIGHT_SUF = [
    ('なければならない', _R_IP, _R_IP),
    ('なくてはならな', _R_IP, _R_IP),
    ('ないといけな', _R_IP, _R_IP),
    ('なければいけな', _R_IP, _R_IP),
    ('ねばならな', _R_IP, _R_IP),
    ('ざるを得な', _R_IP, _R_IP),
    ('ずにはいられな', _R_IP, _R_IP),
    ('わけにはいかな', _R_IP, _R_IP),
    ('てはいけな', _R_IP, _R_IP),
    ('てはならな', _R_IP, _R_IP),
    ('てもいい', _R_IP, _R_IP),
    ('ても良い', _R_IP, _R_IP),
    ('てしまう', _R_VP_TE, _R_VP_TE),
    ('でしまう', _R_VP_TE, _R_VP_TE),
    ('ていただ', _R_VP_TE, _R_VP_TE),
    ('てもら', _R_VP_TE, _R_VP_TE),
    ('てくれ', _R_VP_TE, _R_VP_TE),
    ('でくれ', _R_VP_TE, _R_VP_TE),
    ('てあげ', _R_VP_TE, _R_VP_TE),
    ('てさしあげ', _R_VP_TE, _R_VP_TE),
    ('てくださ', _R_VP_TE, _R_VP_TE),
    ('て下さ', _R_VP_TE, _R_VP_TE),
    ('てほしい', _R_IP, _R_IP),
    ('て欲しい', _R_IP, _R_IP),
    ('でほしい', _R_IP, _R_IP),
    ('てみ', _R_VP_TE, _R_VP_TE),
    ('てお', _R_VP_TE, _R_VP_TE),
    ('でお', _R_VP_TE, _R_VP_TE),
    ('てい', _R_VP_TE, _R_VP_TE),
    ('でい', _R_VP_TE, _R_VP_TE),
    ('てあ', _R_VP_TE, _R_VP_TE),
    ('であ', _R_VP_TE, _R_VP_TE),
    ('ちゃ', _R_VP, _R_VP),
    ('じゃ', _R_VP, _R_VP),
    ('とく', _R_VP, _R_VP),
    ('どく', _R_VP, _R_VP),
    ('てる', _R_VP, _R_VP),
    ('でる', _R_VP, _R_VP),
    ('たことがあ', _R_VP, _R_VP),
    ('ことができる', _R_VP, _R_VP),
    ('ことが出来る', _R_VP, _R_VP),
    ('ことにな', _R_VP, _R_VP),
    ('ことにし', _R_VP, _R_VP),
    ('ようにな', _R_VP, _R_VP),
    ('くなる', _R_VP, _R_VP),
    ('になる', _R_VP, _R_VP),
    ('となる', _R_VP, _R_VP),
    ('とする', _R_VP, _R_VP),
    ('と思', _R_VP, _R_VP),
    ('がほしい', _R_IP, _R_IP),
    ('が欲しい', _R_IP, _R_IP),
    ('があ', _R_VP, _R_VP),
    ('がい', _R_VP, _R_VP),
    ('がいる', _R_VP, _R_VP),
    ('ないでくださ', _R_IMP, _R_IMP),
    ('ないで下さ', _R_IMP, _R_IMP),
    ('ないで', _R_TE, _R_TE),
    ('なくて', _R_TE, _R_TE),
    ('ずに', _R_CONJ | frozenset({'CONJN'}), _R_CONJ | frozenset({'CONJN'})),
    ('なけれ', _R_CONJ | frozenset({'CONJN'}), _R_CONJ | frozenset({'CONJN'})),
    ('ねば', _R_CONJ, _R_CONJ),
    ('せる', _R_VP | frozenset({'TEP'}), _R_VP | frozenset({'TEP'})),
    ('させる', _R_VP | frozenset({'TEP'}), _R_VP | frozenset({'TEP'})),
    ('られる', _R_VP | frozenset({'TEP'}), _R_VP | frozenset({'TEP'})),
    ('れる', _R_VP | frozenset({'TEP'}), _R_VP | frozenset({'TEP'})),
    ('すぎ', _R_VP | frozenset({'TEP'}), _R_VP | frozenset({'TEP'})),
    ('やす', _R_IP, _R_IP),
    ('にく', _R_IP, _R_IP),
    ('がた', _R_IP, _R_IP),
    ('かね', _R_VP, _R_VP),
    ('っぽ', _R_IP, _R_IP),
    ('ながら', _R_CONJ, _R_CONJ),
    ('つつあ', _R_VP, _R_VP),
    ('つつ', _R_CONJ, _R_CONJ),
    ('まみれ', frozenset({'DA', 'DESU', 'DARO', 'NOP', 'CONJN', 'TEN',
                          'END', 'NAP_E'}),
     frozenset({'DA', 'DESU', 'DARO', 'NOP', 'CONJN', 'TEN', 'END',
                'NAP_E'})),
    ('だらけ', frozenset({'DA', 'DESU', 'DARO', 'NOP', 'CONJN', 'NAP',
                          'TEN', 'END', 'NAP_E'}),
     frozenset({'DA', 'DESU', 'DARO', 'NOP', 'CONJN', 'NAP', 'TEN',
                'END', 'NAP_E'})),
    ('気味', frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'CONJN', 'TEN',
                        'END', 'NAP_E'}),
     frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'CONJN', 'TEN',
                'END', 'NAP_E'})),
    ('っぱなし', frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP',
                            'CONJN', 'TEN'}),
     frozenset({'DA', 'DESU', 'DARO', 'NOP', 'NIP', 'DEP', 'CONJN',
                'TEN'})),
    ('ものでし', _R_DESUFORM, _R_DESUFORM),
    ('もので', _R_CONJ | frozenset({'CONJN'}), _R_CONJ | frozenset({'CONJN'})),
    ('ものです', _R_DESUFORM, _R_DESUFORM),
    ('ものだ', _R_DAFORM, _R_DAFORM),
    ('もんだ', _R_DAFORM, _R_DAFORM),
    ('ことだ', _R_DAFORM, _R_DAFORM),
    ('わけだ', _R_DAFORM, _R_DAFORM),
    ('はずだ', _R_DAFORM, _R_DAFORM),
    ('べきだ', _R_DAFORM, _R_DAFORM),
    ('のだ', _R_DAFORM, _R_DAFORM),
    ('のです', _R_DESUFORM, _R_DESUFORM),
    ('んだ', _R_DAFORM, _R_DAFORM),
    ('んです', _R_DESUFORM, _R_DESUFORM),
    ('ようだ', _R_DAFORM, _R_DAFORM),
    ('みたいだ', _R_DAFORM, _R_DAFORM),
    ('らしい', _R_IP, _R_IP),
    ('そうだ', _R_DAFORM, _R_DAFORM),
    ('かもしれな', frozenset({'END', 'NAP_E', 'QUO', 'DESU', 'NOP',
                             'CONJN', 'TEMO', 'TEWA', 'TEN', 'NODA', 'NOX',
                             'CONDTO'}),
     frozenset({'END', 'NAP_E', 'QUO', 'DESU', 'NOP', 'CONJN', 'TEMO',
                'TEWA', 'TEN', 'NODA', 'NOX', 'CONDTO'})),
    ('でしょ', frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'}),
     frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'})),
    ('だろ', frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'}),
     frozenset({'END', 'NAP_E', 'QUO', 'CONJN', 'TEN', 'CONDTO'})),
    ('ましょ', _R_MASUFORM, _R_MASUFORM),
    ('ません', _R_MASUFORM, _R_MASUFORM),
    ('くださ', _R_IMP, _R_IMP),
    ('下さ', _R_IMP, _R_IMP),
    ('なさ', _R_IMP, _R_IMP),
    ('いただ', _R_VP_TE, _R_VP_TE),
    ('におい', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('における', frozenset({'NOUNR'}), frozenset({'NOUNR'})),
    ('において', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('について', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('に対して', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('に対する', frozenset({'NOUNR'}), frozenset({'NOUNR'})),
    ('に関して', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('に関する', frozenset({'NOUNR'}), frozenset({'NOUNR'})),
    ('にとって', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('として', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('によって', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('により', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('による', frozenset({'NOUNR'}), frozenset({'NOUNR'})),
    ('を通じ', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('を通し', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('にもかかわらず', _R_CONJ | frozenset({'CONJN'}),
     _R_CONJ | frozenset({'CONJN'})),
    ('にも関わらず', _R_CONJ | frozenset({'CONJN'}),
     _R_CONJ | frozenset({'CONJN'})),
    ('に違いな', _R_IP, _R_IP),
    ('にちがいな', _R_IP, _R_IP),
    ('おかげで', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('せいで', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('ために', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('ように', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'NARU',
                          'MIERU'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'NARU', 'MIERU'})),
    ('みたいに', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'MIERU'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E', 'MIERU'})),
    ('うちに', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'MOP', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'MOP', 'NAP_E'})),
    ('たびに', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'MOP', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'MOP', 'NAP_E'})),
    ('ごとに', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    ('度に', frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'}),
     frozenset({'PRED', 'QUO', 'TEN', 'CONJN', 'NAP_E'})),
    # ---- 屈折后缀（与左表镜像）----
    ('てしまい', _R_STEM, _R_STEM),
    ('でしまい', _R_STEM, _R_STEM),
    ('ておき', _R_STEM, _R_STEM),
    ('でおき', _R_STEM, _R_STEM),
    ('てみせ', _R_STEM, _R_STEM),
    ('でみせ', _R_STEM, _R_STEM),
    ('ていき', _R_STEM, _R_STEM),
    ('でいき', _R_STEM, _R_STEM),
    ('てき', _R_STEM, _R_STEM),
    ('でき', _R_STEM, _R_STEM),
    ('てもらい', _R_STEM, _R_STEM),
    ('でもらい', _R_STEM, _R_STEM),
    ('てさしあげ', _R_STEM, _R_STEM),
    ('でさしあげ', _R_STEM, _R_STEM),
    ('ていただき', _R_STEM, _R_STEM),
    ('でいただき', _R_STEM, _R_STEM),
    ('てほし', _R_STEM, _R_STEM),
    ('でほし', _R_STEM, _R_STEM),
    ('ていただきた', _R_STEM, _R_STEM),
    ('でいただきた', _R_STEM, _R_STEM),
    ('てもらいた', _R_STEM, _R_STEM),
    ('でもらいた', _R_STEM, _R_STEM),
    ('て頂', _R_STEM, _R_STEM),
    ('て頂け', _R_STEM, _R_STEM),
    ('て頂き', _R_STEM, _R_STEM),
    ('て戴け', _R_STEM, _R_STEM),
    ('て貰い', _R_STEM, _R_STEM),
    ('て揚げる', _R_STEM, _R_STEM),
    ('で貰い', _R_STEM, _R_STEM),
    ('てしまった', _R_PAST_V, _R_PAST_V),
    ('でしまった', _R_PAST_V, _R_PAST_V),
    ('ておいた', _R_PAST_V, _R_PAST_V),
    ('でおいた', _R_PAST_V, _R_PAST_V),
    ('てみた', _R_PAST_V, _R_PAST_V),
    ('でみた', _R_PAST_V, _R_PAST_V),
    ('ていた', _R_PAST_V, _R_PAST_V),
    ('でいた', _R_PAST_V, _R_PAST_V),
    ('てあった', _R_PAST_V, _R_PAST_V),
    ('であった', _R_PAST_V, _R_PAST_V),
    ('てみせた', _R_PAST_V, _R_PAST_V),
    ('でみせた', _R_PAST_V, _R_PAST_V),
    ('ていった', _R_PAST_V, _R_PAST_V),
    ('でいった', _R_PAST_V, _R_PAST_V),
    ('てきた', _R_PAST_V, _R_PAST_V),
    ('できた', _R_PAST_V, _R_PAST_V),
    ('てくれた', _R_PAST_V, _R_PAST_V),
    ('でくれた', _R_PAST_V, _R_PAST_V),
    ('てもらった', _R_PAST_V, _R_PAST_V),
    ('でもらった', _R_PAST_V, _R_PAST_V),
    ('てあげた', _R_PAST_V, _R_PAST_V),
    ('であげた', _R_PAST_V, _R_PAST_V),
    ('てさしあげた', _R_PAST_V, _R_PAST_V),
    ('でさしあげた', _R_PAST_V, _R_PAST_V),
    ('てくださった', _R_PAST_V, _R_PAST_V),
    ('でくださった', _R_PAST_V, _R_PAST_V),
    ('ていただいた', _R_PAST_V, _R_PAST_V),
    ('でいただいた', _R_PAST_V, _R_PAST_V),
    ('ちゃった', _R_PAST_V, _R_PAST_V),
    ('じゃった', _R_PAST_V, _R_PAST_V),
    ('とった', _R_PAST_V, _R_PAST_V),
    ('どった', _R_PAST_V, _R_PAST_V),
    ('てった', _R_PAST_V, _R_PAST_V),
    ('でった', _R_PAST_V, _R_PAST_V),
    ('すぎた', _R_PAST_V, _R_PAST_V),
    ('かねた', _R_PAST_V, _R_PAST_V),
    ('つつあった', _R_PAST_V, _R_PAST_V),
    ('たがった', _R_PAST_V, _R_PAST_V),
    ('っこなかった', _R_PAST_V, _R_PAST_V),
    ('てほしかった', _R_IP, _R_IP),
    ('やすかった', _R_IP, _R_IP),
    ('にくかった', _R_IP, _R_IP),
    ('がたかった', _R_IP, _R_IP),
    ('っぽかった', _R_IP, _R_IP),
    ('でほしかった', _R_IP, _R_IP),
    ('てしまって', _R_TE, _R_TE),
    ('でしまって', _R_TE, _R_TE),
    ('ておいて', _R_TE, _R_TE),
    ('でおいて', _R_TE, _R_TE),
    ('てみて', _R_TE, _R_TE),
    ('でみて', _R_TE, _R_TE),
    ('ていて', _R_TE, _R_TE),
    ('でいて', _R_TE, _R_TE),
    ('てあって', _R_TE, _R_TE),
    ('であって', _R_TE, _R_TE),
    ('てみせて', _R_TE, _R_TE),
    ('でみせて', _R_TE, _R_TE),
    ('ていって', _R_TE, _R_TE),
    ('でいって', _R_TE, _R_TE),
    ('てきて', _R_TE, _R_TE),
    ('できて', _R_TE, _R_TE),
    ('てくれて', _R_TE, _R_TE),
    ('でくれて', _R_TE, _R_TE),
    ('てもらって', _R_TE, _R_TE),
    ('でもらって', _R_TE, _R_TE),
    ('てあげて', _R_TE, _R_TE),
    ('であげて', _R_TE, _R_TE),
    ('てさしあげて', _R_TE, _R_TE),
    ('でさしあげて', _R_TE, _R_TE),
    ('てくださって', _R_TE, _R_TE),
    ('でくださって', _R_TE, _R_TE),
    ('ていただいて', _R_TE, _R_TE),
    ('でいただいて', _R_TE, _R_TE),
    ('てほしくて', _R_TE, _R_TE),
    ('でほしくて', _R_TE, _R_TE),
    ('ちゃって', _R_TE, _R_TE),
    ('じゃって', _R_TE, _R_TE),
    ('とって', _R_TE, _R_TE),
    ('どって', _R_TE, _R_TE),
    ('てって', _R_TE, _R_TE),
    ('でって', _R_TE, _R_TE),
    ('すぎて', _R_TE, _R_TE),
    ('やすくて', _R_TE, _R_TE),
    ('にくくて', _R_TE, _R_TE),
    ('がたくて', _R_TE, _R_TE),
    ('かねて', _R_TE, _R_TE),
    ('っぽくて', _R_TE, _R_TE),
    ('つつあって', _R_TE, _R_TE),
    ('たがって', _R_TE, _R_TE),
    ('っこなくて', _R_TE, _R_TE),
    ('てしまわない', _R_IP, _R_IP),
    ('でしまわない', _R_IP, _R_IP),
    ('ておかない', _R_IP, _R_IP),
    ('でおかない', _R_IP, _R_IP),
    ('てみない', _R_IP, _R_IP),
    ('でみない', _R_IP, _R_IP),
    ('ていない', _R_IP, _R_IP),
    ('でいない', _R_IP, _R_IP),
    ('てあらない', _R_IP, _R_IP),
    ('であらない', _R_IP, _R_IP),
    ('てみせない', _R_IP, _R_IP),
    ('でみせない', _R_IP, _R_IP),
    ('ていかない', _R_IP, _R_IP),
    ('でいかない', _R_IP, _R_IP),
    ('てこない', _R_IP, _R_IP),
    ('でこない', _R_IP, _R_IP),
    ('てくれない', _R_IP, _R_IP),
    ('でくれない', _R_IP, _R_IP),
    ('てもらわない', _R_IP, _R_IP),
    ('でもらわない', _R_IP, _R_IP),
    ('てあげない', _R_IP, _R_IP),
    ('であげない', _R_IP, _R_IP),
    ('てさしあげない', _R_IP, _R_IP),
    ('でさしあげない', _R_IP, _R_IP),
    ('てくださらない', _R_IP, _R_IP),
    ('でくださらない', _R_IP, _R_IP),
    ('ていただかない', _R_IP, _R_IP),
    ('でいただかない', _R_IP, _R_IP),
    ('てほしくない', _R_IP, _R_IP),
    ('でほしくない', _R_IP, _R_IP),
    ('ちゃわない', _R_IP, _R_IP),
    ('じゃわない', _R_IP, _R_IP),
    ('とらない', _R_IP, _R_IP),
    ('どらない', _R_IP, _R_IP),
    ('てない', _R_IP, _R_IP),
    ('でない', _R_IP, _R_IP),
    ('すぎない', _R_IP, _R_IP),
    ('やすくない', _R_IP, _R_IP),
    ('にくくない', _R_IP, _R_IP),
    ('がたくない', _R_IP, _R_IP),
    ('っぽくない', _R_IP, _R_IP),
    ('つつあらない', _R_IP, _R_IP),
    ('たがらない', _R_IP, _R_IP),
    ('っこなくない', _R_IP, _R_IP),
    ('だら', _R_CONJ, _R_CONJ),
]
_LQ_RIGHT_SUF = sorted(_LQ_RIGHT_SUF, key=lambda e: -len(e[0]))


def _lq_right(surface):
    """表面形的右接续类（精确优先，最长后缀兜底）。未知返回 None（放行）。"""
    hit = _LQ_RIGHT_EXACT.get(surface)
    if hit is not None:
        return hit
    for suf, bare, ctx in _LQ_RIGHT_SUF:
        if surface.endswith(suf):
            return bare if surface == suf else ctx
    return None


def _cloze_after_class(text, b1):
    """after 部分首词的右接续类。返回 frozenset； REJ=必弃；None=未知放行。"""
    after = text[b1:]
    for prefs, cls in _AFTER_SURF:
        if after.startswith(prefs):
            return frozenset({cls})
    try:
        words = [w for w in _lq_tagger()(text) if w.surface]
    except Exception:
        return None
    if not words:
        return None
    spans = _lq_spans(text, words)
    idx = -1
    for i, (s, e) in enumerate(spans):
        if s >= b1:
            idx = i
            break
    if idx < 0:
        return frozenset({'END'})
    # 跳过右括号类（「…」|と言う → 按と言う判定）
    while idx < len(words) and words[idx].surface in \
            ('」', '』', '）', ')', '】', '〉', '》', '〗'):
        idx += 1
    if idx >= len(words):
        return frozenset({'END'})
    w = words[idx]
    f = w.feature
    pos1, lemma = f.pos1, (f.lemma or '').split('-')[0]
    cf = f.cForm or ''
    surf = w.surface
    nxt = words[idx + 1] if idx + 1 < len(words) else None
    nxt_lemma = (nxt.feature.lemma or '').split('-')[0] if nxt is not None else ''

    if pos1 == '補助記号':
        if surf in ('。', '！', '？', '．', '!', '?', '…'):
            return frozenset({'END'})
        if surf in ('、', '，', ','):
            return frozenset({'TEN'})
        if surf in ('「', '『', '（', '(', '【', '〈', '《', '〖'):
            return frozenset({'QUO'})
        return None
    if pos1 == '助詞':
        if f.pos2 == '終助詞' or surf in ('よ', 'ね', 'な', 'か', 'さ', 'ぜ',
                                          'ぞ', 'わ', 'い', 'かな', 'かしら',
                                          'っけ', 'っけか', 'とも'):
            return frozenset({'END'})
        if surf in ('ば',):
            return frozenset({'REJ'})
        if surf in ('たら', 'ら'):
            return frozenset({'REJ'})
        if surf == 'と':
            # と+引用动词/左引号=引用；否则为恒常条件（右类不同：
            # 条件と后可跟从句形态，引用と后只跟引用标记）
            if nxt_lemma in _QUOTE_VERBS or (nxt is not None and
                    nxt.surface in ('「', '『', 'って', 'なんて')):
                return frozenset({'QUO'})
            return frozenset({'CONDTO'})
        if surf == 'なら':
            return frozenset({'REJ'})
        if surf in ('ても', 'でも'):
            return frozenset({'TEMO'})
        if surf in ('ては', 'では'):
            return frozenset({'TEWA'})
        if surf in ('たり', 'だり', 'ながら', 'つつ'):
            return frozenset({'REJ'})
        if surf in ('けれど', 'けれども', 'けど', 'が', 'し', 'のに', 'ので',
                    'ものの', 'ものを', 'ところが', 'ものの'):
            return frozenset({'CONJN'})
        if surf in ('やいなや', 'なり', 'そばから', 'とたん', '途端'):
            return frozenset({'SOJI'})
        if surf == 'を':
            return frozenset({'WOP'})
        if surf == 'が':
            return frozenset({'CONJN'})   # 格助词が/逆接が：名词・从句两可
        if surf == 'は':
            return frozenset({'HAP'})
        if surf == 'も':
            return frozenset({'MOP'})
        if surf == 'の':
            return frozenset({'NOP'})
        if surf == 'な':
            return frozenset({'NAP'})
        if surf == 'に':
            return frozenset({'NIP'})
        if surf == 'で':
            return frozenset({'DEP'})
        if surf == 'へ':
            return frozenset({'CASEP'})
        if surf in ('って', 'なんて'):
            return frozenset({'QUO'})
        if surf == 'しか':
            return frozenset({'SHIKA'})
        if surf in ('から', 'まで', 'より', 'や', 'なり', 'やら', 'か', 'とも',
                    'こそ', 'さえ', 'でも', 'だけ', 'ほど', 'ばかり', 'くらい',
                    'ぐらい', 'など', 'なんか', 'きり', 'のみ', 'ずつ', 'おき',
                    'ごと', '目', '等', 'とて', 'なり'):
            return frozenset({'CASEP'})
        return None
    if pos1 == '助動詞':
        if lemma in ('だ', 'である') and surf not in ('だろう', 'だろ', 'でしょ'):
            return frozenset({'DA'})
        if lemma == 'だ' and surf in ('だろう', 'だろ'):
            return frozenset({'DARO'})
        if lemma in ('です', 'であります'):
            if surf in ('でしょう', 'でしょ'):
                return frozenset({'DARO'})
            return frozenset({'DESU'})
        if lemma == 'ます':
            return frozenset({'MASU'})
        if lemma in ('たい', 'たがる', '欲しい'):
            return frozenset({'REJ'})
        if lemma == 'ない':
            return frozenset({'NAIR'})
        if lemma in ('れる', 'られる', 'せる', 'させる', 'しめる'):
            return frozenset({'REJ'})
        if lemma in ('た', 'だ') and surf in ('た', 'だ'):
            return frozenset({'REJ'})
        if lemma in ('ぬ', 'ん', 'ず', 'まい'):
            return frozenset({'REJ'})
        return frozenset({'PRED'})
    if pos1 in ('動詞', '形容詞'):
        if '意志推量' in cf:
            return frozenset({'VOLR'})
        if cf.startswith('命令形'):
            # 命令形后：只接て形/ないで/ます词干/ください类（てしまって|
            # ください√、ないで|ください√、お読み|ください√）；其余拒绝。
            return frozenset({'IMPR'})
        if cf.startswith(('連用形', '未然形', '仮定形', '語幹')):
            return frozenset({'REJ'})
        if lemma in _QUOTE_VERBS:
            return frozenset({'QUO'})
        if lemma in ('成る', 'なる'):
            return frozenset({'NARU'})
        if lemma in ('見える', 'みえる', '聞こえる', '思える', '感じられる'):
            return frozenset({'MIERU'})
        return frozenset({'PRED'})
    if pos1 in ('名詞', '代名詞'):
        return frozenset({'NOUNR'})
    if pos1 in ('形状詞', '連体詞'):
        return frozenset({'NOUNR'})
    return None


def _voice_class(s):
    for pre in _VOICE_V:
        if s.startswith(pre):
            return 'v'
    for pre in _VOICE_U:
        if s.startswith(pre):
            return 'u'
    return None


def _voice_it(s):
    for u, v in zip(_VOICE_U, _VOICE_V):
        if s.startswith(u):
            return v + s[len(u):]
    return s
_CLOZE_FILLERS = ('ている', 'てしまう', 'について', 'ことにする', 'わけではない',
                  'ばかり', 'そうだ', 'かもしれない', 'なければならない',
                  'ことがある', 'ために', 'ようだ')

_END_PUNCT = ('。', '！', '？', '!', '?')


def _cloze_sentence_ok(text):
    """挖空题干质检：必须是单句完整日语句子。
    拒绝：无句末标点/句中有分句标点（多句拼接）、过短过长、无汉字无假名、垃圾字符、
    以及未通过基本语法检查（文末格助词/接续悬空/无谓语/非法助词连用/敬体断裂/伪假名串）的语病句。"""
    if not text or not (8 <= len(text) <= 80):
        return False
    if not text.endswith(_END_PUNCT):
        return False
    if any(p in text[:-1] for p in _END_PUNCT):
        return False
    if not furigana.has_kanji(text):
        return False
    if not re.search(r'[ぁ-んァ-ヶ]', text):
        return False
    if corpus.is_junk(text):
        return False
    if re.search(r'[{}\[\]_＿http]|\\d{7,}', text):
        return False
    if not grammar.is_sentence_grammatically_sound(text, strict_mode=True):
        return False
    return True


def _cloze_group_options(name, base_name=None):
    """答案句型所属混淆组的标准干扰项（保持组内顺序，不含答案本身由调用方过滤）。

    v18 兼容：先按消歧后的精准子句型名匹配，找不到再回退到大纲通用名
    （base_name），确保消歧前后挖空干扰项都不中断。"""
    for g in _CLOZE_GROUPS:
        if name in g['names']:
            return list(g['options'])
    if base_name:
        for g in _CLOZE_GROUPS:
            if base_name in g['names']:
                return list(g['options'])
    return []


def _cloze_distractors(name, answer, level, pool_by_level, after='',
                       attr=False, before='', base_name=None):
    """干扰项优先级：断定槽位词干 → 定语槽位（按左接续三选一）→ 同组混淆项
    （义近形近）→ 同级长度相近项 → 兜底项；去重、等价互斥、前后重叠排除、
    清浊匹配、左右接续校验，取 3 个。"""
    seen, out = {answer}, []
    ans_vc = _voice_class(answer)
    # 左右接续类（全文形态素分析一次，三个候选来源共用）
    text = (before or '') + answer + (after or '')
    b0 = len(before or '')
    bl = _cloze_left_class(text, b0) if before else None
    ar = _cloze_after_class(text, b0 + len(answer))
    ac_l, ac_r = _lq_left(answer), _lq_right(answer)
    if bl is None and ac_l is None:
        return []                         # 左右皆不可判定（如裸命令形）：弃题保正确
    if answer in _QUO_ANS and (ar is None or 'QUO' not in ar):
        # 引用答案（って/という…）后不跟引用动词时，任何从句补语（こと
        # にする/ような…）填入都成立，天生双正解，只能弃题。
        return []

    def _side_ok(cand_cls, slot_cls, ans_cls):
        if cand_cls is None:
            return True                   # 未知候选：放行（宁漏罕见形）
        if slot_cls is None:
            return ans_cls is None or bool(cand_cls & ans_cls)
        return bool(cand_cls & slot_cls)

    def _push(s):
        s = (s or '').strip()
        # 注：干扰项之间不互斥（两个都错是好事，无需互斥；互斥只针对答案，
        # 杜绝双正确答案）。清浊处理必须在接续校验之前，否则清音候选会被
        # 浊音槽位误杀（如 てある→である 在 でいる 槽位）。
        vc = _voice_class(s)
        if ans_vc == 'u' and vc == 'v':
            return                        # 清音槽位拒收浊音形（如 ている槽位拒 である）
        if ans_vc == 'v' and vc == 'u':
            s = _voice_it(s)              # 浊音槽位把清音候选浊化（如 ておく→でおく）
        if not s or s in seen or _cloze_equiv(s, answer):
            return                        # 去重 + 等价形互斥（杜绝双正确答案）
        if s.startswith(answer) or answer.startswith(s):
            return                        # 与答案前后重叠（如 ところ vs ところだ）会拼出重复
        lc, rc = _lq_left(s), _lq_right(s)
        if s == 'そう' and bl is not None and ar is not None:
            # そう两读必须联合判定：样态=词干左+だ/です/に/な右，
            # 传闻=辞书左+だ/です右；交叉组合（如传闻+に）不成立。
            sotai_l = bool(bl & {'VSA', 'VSAB', 'M1B', 'MSI', 'ADJS',
                                 'NAS'})
            denbun_l = bool(bl & {'VDICT', 'ADICT', 'TAFORM_U', 'TAFORM_V', 'NAI',
                                  'TEIRU', 'TAIB'})
            sotai_r = bool(ar & {'DA', 'DESU', 'DARO', 'NIP', 'NAP',
                                 'NAP_E'})
            denbun_r = bool(ar & {'DA', 'DESU', 'DARO'})
            if not ((sotai_l and sotai_r) or (denbun_l and denbun_r)):
                return
        else:
            if lc is not None and lc == ac_l and (lc & _CTX_FAMILY):
                pass                      # 同族前缀形互换（如 高くなる↔安くなる）
            elif not _side_ok(lc, bl, ac_l):
                return                    # 左接续不合（如 行き|てほしい）
            if not _side_ok(rc, ar, ac_r):
                return                    # 右接续不合
        if 1 <= len(s) <= 10:
            seen.add(s)
            out.append(s)

    def _drain(cands):
        for s in cands:
            _push(s)
            if len(out) >= 3:
                return True
        return False

    if after and (after.startswith('だ') or after.startswith('です')) \
            and answer in _COPULA_STEMS:
        if _drain(_COPULA_STEMS):         # 断定槽位：只有同类词干在语法上成立
            return out
    if attr:                              # 定语槽位：干扰项必须同左接续、同作定语
        if answer in _STEM_SET:
            if _drain(_STEM_RENTAI):
                return out
        elif answer in _PLAIN_SET:
            if _drain(_PLAIN_RENTAI):
                return out
        elif answer in _TE_SET:
            if _drain(_TE_RENTAI):
                return out
    for s in _cloze_group_options(name, base_name):
        _push(s)
        if len(out) >= 3:
            return out
    # 同级题池：字形（是否含汉字）一致优先，其次长度相近
    cands = [s for s in pool_by_level.get(level, []) if s != answer and 2 <= len(s) <= 10]
    cands = sorted(set(cands),
                   key=lambda s: (furigana.has_kanji(s) != furigana.has_kanji(answer),
                                  abs(len(s) - len(answer))))
    for s in cands:
        _push(s)
        if len(out) >= 3:
            return out
    # 跨级题池（同上排序）
    rest = []
    for lv, lst in pool_by_level.items():
        if lv != level:
            rest += [s for s in lst if 2 <= len(s) <= 10]
    rest = sorted(set(rest),
                  key=lambda s: (furigana.has_kanji(s) != furigana.has_kanji(answer),
                                 abs(len(s) - len(answer))))
    for s in rest:
        _push(s)
        if len(out) >= 3:
            return out
    for f in _CLOZE_FILLERS:
        _push(f)
        if len(out) >= 3:
            break
    return out


def _cloze_candidates(text, min_o, meta=None):
    """单句挖空候选抽取（含全部质检）：题干质检 → 语法分析 → 候选质检。
    meta: 随候选携带的出处信息 dict。返回候选列表（不含注音/干扰项）。"""
    if not _cloze_sentence_ok(text):
        return []
    try:
        pts = [g for g in grammar.analyze(text)
               if g.get('kind') == 'pattern' and _lv(g.get('level')) >= min_o]
    except Exception:
        return []
    # 被屈折碎片过滤器剔除的匹配区间：与之重叠的其他匹配多为误切
    # （如 盗もうとし|て 碎片内的 として≠資格用法），同样不挖。
    frag = [tuple(g['blank']) for g in pts
            if g.get('tail_cont') and len(g.get('blank') or []) == 2]
    out = []
    for g in pts:
        surf = g.get('surface') or ''
        blank = g.get('blank') or []
        name = g.get('name') or ''
        # ---- 候选质检 ----
        if name in _CLOZE_SKIP_NAMES:                # 禁挖名单
            continue
        if name == '条件「たら」' and surf != 'たら':
            continue                                 # たら必须挖完整形，不挖裸 た
        if len(surf) < 2 and not (surf in ('ば', 'と')
                                  and name in ('条件「ば」', '条件「と」')):
            continue                                 # 单字一般不挖；条件助词 ば/と 例外
        if g.get('tail_cont'):                       # 屈折碎片（如 てこ/ことにし）不挖
            continue
        if len(blank) != 2:                          # 无精确定位不挖
            continue
        b0, b1 = blank
        if not (0 <= b0 < b1 <= len(text)) or text[b0:b1] != surf:
            continue                                 # 定位与原文不一致不挖
        if any(a < b1 and b0 < b for a, b in frag):
            continue                                 # 与屈折碎片区间重叠（误切）不挖
        if text.count(surf) != 1:                    # 句中复现会产生歧义空位，不挖
            continue
        if re.search(r'[A-Za-z0-9]', surf):          # 含 ASCII 的不挖
            continue
        before, after = text[:b0], text[b1:]
        if len(before) < 1 or len(after) < 1:        # 空位必须有前后文
            continue
        out.append(dict(meta or {}, text=text, name=name, level=g['level'],
                        structure=g['structure'], explain=g['explain'],
                        base_name=g.get('base_name') or name,
                        answer=surf, before=before, after=after, blank=[b0, b1],
                        attr=bool(g.get('attr_slot'))))
    return out


def make_cloze(book_ids=None, scope=None, min_level=None, count=None):
    """挖空测验生成（v13 重写：完整题干 + 严格质检 + 同类混淆干扰项）。

    流程：随机取句 → 题干质检（单句完整日语）→ 语法分析 → 只保留 min_level 及以上
    的句型 → 候选质检（禁挖名单/屈折碎片/单字/歧义复现一律剔除）→ 完整句子挖空，
    4 选 1（干扰项优先取同组混淆项，保证形近义近有区分度）。

    返回每题：完整 text、before/answer/after 精确拼回原文（before+answer+after==text）、
    全句注音 tokens、翻译（答后展示）、出处 origin、语法讲解。
    """
    cfg = study_cfg()
    if not cfg.get('cloze_enabled', True):
        return {'ok': False, 'reason': '挖空测验已在学习配置中关闭', 'scope': cfg.get('cloze_scope'),
                'count': 0, 'questions': []}
    scope = scope or cfg.get('cloze_scope', 'corpus')
    min_level = min_level or cfg.get('cloze_min_level', 'N4')
    count = max(1, min(int(count or cfg.get('cloze_per_day', 5)), 20))
    min_o = _lv(min_level)
    ids = [int(b) for b in (book_ids or [])]

    need = min(count * 25, 200)
    if scope == 'book' and ids:
        ph = ','.join('?' * len(ids))
        with db.get_conn() as c:
            rows = c.execute(
                f'SELECT s.id sid, s.text text, s.translation translation, s.source source, '
                f'bs.book_id book_id, b.title book_title, l.title lesson_title '
                f'FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id '
                f'JOIN books b ON b.id=bs.book_id LEFT JOIN book_lessons l ON l.id=bs.lesson_id '
                f'WHERE bs.book_id IN ({ph}) ORDER BY RANDOM() LIMIT ?',
                ids + [need]).fetchall()
    else:
        scope = 'corpus'
        with db.get_conn() as c:
            rows = c.execute('SELECT id sid, text text, translation translation, source source '
                             'FROM sentences ORDER BY RANDOM() LIMIT ?', (need,)).fetchall()

    pool = []
    for r in rows:
        keys = r.keys()
        meta = {'sid': r['sid'],
                'translation': r['translation'] if 'translation' in keys else None,
                'source': r['source'] if 'source' in keys else '',
                'book_id': r['book_id'] if 'book_id' in keys else None,
                'book_title': r['book_title'] if 'book_title' in keys else None,
                'lesson': r['lesson_title'] if 'lesson_title' in keys else None}
        pool += _cloze_candidates(r['text'], min_o, meta)
        if len(pool) >= count * 6:                   # 候选够多就停（省分析耗时）
            break
    random.shuffle(pool)

    pool_by_level = {}
    for p in pool:
        pool_by_level.setdefault(p['level'], []).append(p['answer'])

    questions, chosen_key, chosen_sid, chosen_ans = [], set(), set(), set()
    # 第一遍：同句只出一题（保证题面多样）；不够时第二遍放开
    for relax in (False, True):
        for p in pool:
            key = (p['name'], p['sid'])
            if key in chosen_key or p['answer'] in chosen_ans:
                continue
            if not relax and p['sid'] in chosen_sid:
                continue
            opts = [p['answer']] + _cloze_distractors(
                p['name'], p['answer'], p['level'], pool_by_level,
                after=p['after'], attr=p.get('attr'), before=p['before'],
                base_name=p.get('base_name'))
            opts = opts[:4]
            if len(opts) < 4 or len(set(opts)) < 4 or p['answer'] not in opts:
                continue                             # 凑不够 4 个有效选项就弃题
            random.shuffle(opts)
            chosen_key.add(key)
            chosen_sid.add(p['sid'])
            chosen_ans.add(p['answer'])
            origin = origin_label(p['source'], p['book_title'], p['lesson'])
            try:
                tokens = furigana.annotate(p['text'])
                # 空位前后各自独立注音：避免整句 token 在空位处被切分导致注音串位
                tokens_b = furigana.annotate(p['before'])
                tokens_a = furigana.annotate(p['after'])
                atokens = furigana.annotate(p['answer'])
            except Exception:
                tokens, tokens_b, tokens_a, atokens = [], [], [], []
            questions.append({'sid': p['sid'], 'text': p['text'], 'name': p['name'],
                              'level': p['level'], 'structure': p['structure'],
                              'explain': p['explain'], 'answer': p['answer'],
                              'before': p['before'], 'after': p['after'],
                              'blank': p['blank'], 'options': opts,
                              'tokens': tokens, 'tokens_b': tokens_b,
                              'tokens_a': tokens_a, 'atokens': atokens,
                              'translation': p['translation'],
                              'origin': origin, 'source': p['source'],
                              'book_id': p['book_id'], 'lesson': p['lesson']})
            if len(questions) >= count:
                break
        if len(questions) >= count:
            break
    return {'ok': True, 'scope': scope, 'min_level': min_level,
            'count': len(questions), 'questions': questions,
            'short': len(questions) < count}


def record_cloze(results):
    """记录挖空练习结果：累计到当日统计（历史可查），并写操作日志"""
    results = [r for r in (results or []) if isinstance(r, dict)]
    n_ok = sum(1 for r in results if r.get('ok'))
    today = date.today().isoformat()
    try:
        stats = json.loads(db.get_setting('book_cloze_stats', '') or '{}')
    except Exception:
        stats = {}
    d = stats.setdefault(today, {'asked': 0, 'correct': 0})
    d['asked'] += len(results)
    d['correct'] += n_ok
    db.set_setting('book_cloze_stats', json.dumps(stats, ensure_ascii=False))
    db.log('cloze', f'挖空练习：{n_ok}/{len(results)} 正确（难度≥{study_cfg().get("cloze_min_level")}）')
    return {'ok': True, 'asked': len(results), 'correct': n_ok}


def cloze_stats(days=14):
    """最近 N 天的挖空练习统计（用于学习曲线页展示）"""
    try:
        stats = json.loads(db.get_setting('book_cloze_stats', '') or '{}')
    except Exception:
        stats = {}
    return [{'day': day, **stats[day]} for day in sorted(stats)[-max(1, int(days)):]]


# ================================================================
# 7. 出题配置面板：高级算法自动推荐 + 多源按比例出题（v15）
# ================================================================

def _user_accuracy():
    """用户过往答题正确率：综合 SRS (ok/ng) 与挖空统计，返回 0.0-1.0"""
    acc_srs = None
    try:
        with db.get_conn() as c:
            row = c.execute('SELECT SUM(ok) ok_sum, SUM(ng) ng_sum FROM srs').fetchone()
            ok = row['ok_sum'] or 0
            ng = row['ng_sum'] or 0
            if ok + ng >= 5:
                acc_srs = ok / float(ok + ng)
    except Exception:
        pass
    acc_cloze = None
    try:
        stats = json.loads(db.get_setting('book_cloze_stats', '') or '{}')
        asked = sum(v.get('asked', 0) for v in stats.values())
        correct = sum(v.get('correct', 0) for v in stats.values())
        if asked >= 5:
            acc_cloze = correct / float(asked) if asked else None
    except Exception:
        pass
    if acc_srs is not None and acc_cloze is not None:
        return round((acc_srs * 0.6 + acc_cloze * 0.4), 3)
    if acc_srs is not None:
        return round(acc_srs, 3)
    if acc_cloze is not None:
        return round(acc_cloze, 3)
    return 0.65  # 新用户默认值


def _book_difficulty(book_ids):
    """课文句子难度分级：分析书中句子的语法点平均等级，返回 (avg_order, level_str, count)"""
    ids = [int(b) for b in (book_ids or [])]
    if not ids:
        return 1.5, 'N4', 0
    ph = ','.join('?' * len(ids))
    try:
        with db.get_conn() as c:
            rows = c.execute(
                f'SELECT s.text FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id '
                f'WHERE bs.book_id IN ({ph}) ORDER BY bs.id LIMIT 120', ids).fetchall()
    except Exception:
        return 1.5, 'N4', 0
    levels = []
    for r in rows:
        try:
            pts = grammar.analyze(r['text'])
            for g in pts:
                if g.get('kind') == 'pattern':
                    levels.append(_lv(g.get('level')))
        except Exception:
            continue
    if not levels:
        # 退化：按句长估算难度
        try:
            avg_len = sum(len(r['text']) for r in rows) / max(1, len(rows))
            if avg_len < 15:
                return 0.5, 'N5', len(rows)
            if avg_len < 25:
                return 1.2, 'N4', len(rows)
            if avg_len < 35:
                return 2.0, 'N3', len(rows)
            if avg_len < 45:
                return 3.0, 'N2', len(rows)
            return 3.8, 'N1', len(rows)
        except Exception:
            return 1.5, 'N4', len(rows)
    avg = sum(levels) / len(levels)
    # order -> level
    order_to_level = {0: 'N5', 1: 'N4', 2: 'N3', 3: 'N2', 4: 'N1'}
    lv = order_to_level.get(int(round(avg)), 'N4')
    return round(avg, 2), lv, len(rows)


def recommend_quiz_config(book_ids=None, total_override=None):
    """高级算法自动计算推荐题量与三类语料占比

    算法逻辑（需求）：
    - 读取当前课文句子总量、用户过往答题正确率、句子难度分级，自动算出推荐题量
    - 自动分配三类语料百分比

    返回：{total, ratios:{book,corpus,lyric}, accuracy, difficulty, explain}
    """
    ids = [int(b) for b in (book_ids or [])]
    if not ids:
        ids = [b['id'] for b in db.list_books() if b.get('active')]
    # 课文句子总量
    book_sent_total = 0
    try:
        if ids:
            ph = ','.join('?' * len(ids))
            with db.get_conn() as c:
                book_sent_total = c.execute(
                    f'SELECT COUNT(*) n FROM book_sentences WHERE book_id IN ({ph})', ids).fetchone()['n']
    except Exception:
        book_sent_total = 0
    # 语料库与歌词总量
    try:
        with db.get_conn() as c:
            corpus_total = c.execute('SELECT COUNT(*) n FROM sentences WHERE source != \"book\"').fetchone()['n']
            lyric_total = c.execute('SELECT COUNT(*) n FROM songs').fetchone()['n']
            lyric_lines = 0
            if lyric_total:
                # 估算歌词行数
                rows = c.execute('SELECT lyrics FROM songs').fetchall()
                lyric_lines = sum(len((r['lyrics'] or '').split('\n')) for r in rows)
    except Exception:
        corpus_total = 0
        lyric_total = 0
        lyric_lines = 0

    accuracy = _user_accuracy()
    avg_order, avg_level, sampled = _book_difficulty(ids)

    # ---- 推荐题量 ----
    # 基础：课文句数的 60%，最少 5，最多 30
    if book_sent_total > 0:
        base = book_sent_total * 0.6
    else:
        base = 12
    # 正确率修正：正确率高 → 多出题；低 → 少出题
    if accuracy < 0.55:
        base *= 0.65
    elif accuracy < 0.7:
        base *= 0.85
    elif accuracy > 0.85:
        base *= 1.35
    elif accuracy > 0.75:
        base *= 1.15
    # 难度修正：难度高 → 少出题
    if avg_order >= 3.0:  # N2+
        base *= 0.8
    elif avg_order <= 1.0:  # N5-N4
        base *= 1.2

    if total_override and total_override > 0:
        total = max(1, min(int(total_override), 50))
    else:
        total = int(round(base))
        total = max(5, min(total, 30))

    # ---- 占比分配 ----
    # 默认 60/25/15
    r_book, r_corpus, r_lyric = 60, 25, 15

    if accuracy < 0.6:
        r_book, r_corpus, r_lyric = 70, 20, 10
    elif accuracy > 0.8:
        r_book, r_corpus, r_lyric = 40, 30, 30
    elif accuracy > 0.7:
        r_book, r_corpus, r_lyric = 50, 30, 20

    # 课文句数很少时，降低课文占比
    if book_sent_total < 8 and book_sent_total > 0:
        r_book = max(20, r_book - 20)
        r_corpus += 10
        r_lyric += 10
    if book_sent_total == 0:
        r_book = 0
        # 重新分配
        if corpus_total and lyric_total:
            r_corpus, r_lyric = 60, 40
        elif corpus_total:
            r_corpus, r_lyric = 100, 0
        elif lyric_total:
            r_corpus, r_lyric = 0, 100
        else:
            r_corpus, r_lyric = 100, 0

    # 歌词库为空时，归零并分给其他
    if lyric_total == 0 or lyric_lines == 0:
        if r_lyric:
            # 分给课文和语料
            if r_book:
                r_book += r_lyric // 2
                r_corpus += r_lyric - r_lyric // 2
            else:
                r_corpus += r_lyric
            r_lyric = 0

    # 语料库为空
    if corpus_total == 0:
        if r_corpus:
            if r_book:
                r_book += r_corpus
            else:
                r_lyric += r_corpus
            r_corpus = 0

    # 归一化到 100
    s = r_book + r_corpus + r_lyric
    if s != 100 and s > 0:
        # 按比例缩放
        r_book = int(round(r_book * 100 / s))
        r_corpus = int(round(r_corpus * 100 / s))
        r_lyric = 100 - r_book - r_corpus
    # 兜底
    if r_book + r_corpus + r_lyric != 100:
        # 简单修正
        diff = 100 - (r_book + r_corpus + r_lyric)
        if r_book >= 30:
            r_book += diff
        elif r_corpus >= 20:
            r_corpus += diff
        else:
            r_lyric += diff

    explain = (
        f'课文 {book_sent_total} 句 · 语料库 {corpus_total} 句 · 歌词 {lyric_total} 首({lyric_lines}行) · '
        f'正确率 {int(accuracy*100)}% · 平均难度 {avg_level}({avg_order}) → 推荐 {total} 题，'
        f'课文{r_book}%/语料{r_corpus}%/歌词{r_lyric}%'
    )

    return {
        'ok': True,
        'book_sent_total': book_sent_total,
        'corpus_total': corpus_total,
        'lyric_total': lyric_total,
        'lyric_lines': lyric_lines,
        'accuracy': accuracy,
        'avg_difficulty_order': avg_order,
        'avg_difficulty_level': avg_level,
        'total': total,
        'ratios': {'book': r_book, 'corpus': r_corpus, 'lyric': r_lyric},
        'explain': explain,
        'book_ids': ids,
    }


def _fetch_lyric_lines(limit=200):
    """从歌词库随机取行，返回 [(sid, title, artist, line)]"""
    try:
        with db.get_conn() as c:
            rows = c.execute('SELECT id, title, artist, lyrics FROM songs ORDER BY RANDOM() LIMIT 80').fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        title = r['title']
        artist = r['artist'] or ''
        sid = r['id']
        for ln in (r['lyrics'] or '').split('\n'):
            t = ln.strip()
            if not t or len(t) < 4:
                continue
            # 过滤明显不是日语句子的行（可选）
            if not re.search(r'[ぁ-んァ-ヶ一-鿿]', t):
                continue
            out.append((sid, title, artist, t))
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    random.shuffle(out)
    return out


def make_cloze_multi(book_ids=None, total=None, ratios=None, difficulty=None,
                     min_level=None, count=None):
    """多源按比例出题（v15）

    参数：
    - book_ids: 课本 id 列表（当前课文源）
    - total: 题目总量（手动模式）
    - ratios: {book, corpus, lyric} 百分比，自动归一 100
    - difficulty: {book, corpus, lyric} 每源的最小难度等级，或单个等级字符串
    - min_level: 全局最小难度（兼容旧接口）
    - count: total 别名

    返回：{ok, total, ratios, counts:{book,corpus,lyric}, questions, explain}
    """
    cfg = study_cfg()
    if not cfg.get('cloze_enabled', True):
        return {'ok': False, 'reason': '挖空测验已在学习配置中关闭', 'count': 0, 'questions': []}

    # 归一参数
    ids = [int(b) for b in (book_ids or [])]
    if not ids:
        try:
            ids = [b['id'] for b in __import__('db').list_books() if b.get('active')]
        except Exception:
            ids = []
    total = int(total or count or cfg.get('cloze_per_day', 10) or 10)
    total = max(1, min(total, 50))

    # ratios 归一
    if ratios is None:
        ratios = {'book': 60, 'corpus': 25, 'lyric': 15}
    rb = int(ratios.get('book', 60) or 0)
    rc = int(ratios.get('corpus', 25) or 0)
    rl = int(ratios.get('lyric', 15) or 0)
    # 允许传数组或字符串，兼容
    if isinstance(ratios, (list, tuple)) and len(ratios) == 3:
        rb, rc, rl = int(ratios[0]), int(ratios[1]), int(ratios[2])
    # 负数/超限修正
    rb, rc, rl = max(0, rb), max(0, rc), max(0, rl)
    s = rb + rc + rl
    if s == 0:
        rb, rc, rl = 60, 25, 15
        s = 100
    # 归一到 100，再按 total 分配题数
    rb_n = rb * 100.0 / s
    rc_n = rc * 100.0 / s
    rl_n = rl * 100.0 / s
    # 按 total 分配，四舍五入后修正
    n_book = int(round(total * rb_n / 100.0))
    n_corpus = int(round(total * rc_n / 100.0))
    n_lyric = total - n_book - n_corpus
    # 保证非负
    if n_lyric < 0:
        # 从最大的里扣
        if n_book >= n_corpus:
            n_book += n_lyric
        else:
            n_corpus += n_lyric
        n_lyric = 0
    # 再次修正总和
    diff = total - (n_book + n_corpus + n_lyric)
    if diff != 0:
        # 加到占比最高的源
        if rb_n >= rc_n and rb_n >= rl_n:
            n_book += diff
        elif rc_n >= rl_n:
            n_corpus += diff
        else:
            n_lyric += diff

    # difficulty 归一
    if difficulty is None:
        difficulty = {}
    if isinstance(difficulty, str):
        # 全局同一难度
        difficulty = {'book': difficulty, 'corpus': difficulty, 'lyric': difficulty}
    # 每源最小等级，默认取配置
    def _min_lv(src):
        if src in difficulty and difficulty[src]:
            return difficulty[src]
        if min_level:
            return min_level
        return cfg.get('cloze_min_level', 'N4')

    min_book = _min_lv('book')
    min_corpus = _min_lv('corpus')
    min_lyric = _min_lv('lyric')

    # ---- 各源候选池 ----
    pools = {'book': [], 'corpus': [], 'lyric': []}

    # book 源
    if n_book > 0 and ids:
        need = min(n_book * 30, 300)
        ph = ','.join('?' * len(ids))
        try:
            with db.get_conn() as c:
                rows = c.execute(
                    f'SELECT s.id sid, s.text text, s.translation translation, s.source source, '
                    f'bs.book_id book_id, b.title book_title, l.title lesson_title '
                    f'FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id '
                    f'JOIN books b ON b.id=bs.book_id LEFT JOIN book_lessons l ON l.id=bs.lesson_id '
                    f'WHERE bs.book_id IN ({ph}) ORDER BY RANDOM() LIMIT ?', ids + [need]).fetchall()
        except Exception:
            rows = []
        min_o = _lv(min_book)
        for r in rows:
            meta = {'sid': r['sid'], 'translation': r['translation'], 'source': r['source'],
                    'book_id': r['book_id'], 'book_title': r['book_title'],
                    'lesson': r['lesson_title'] if 'lesson_title' in r.keys() else None,
                    'origin_type': 'book'}
            pools['book'] += _cloze_candidates(r['text'], min_o, meta)

    # corpus 源
    if n_corpus > 0:
        need = min(n_corpus * 30, 400)
        try:
            with db.get_conn() as c:
                rows = c.execute(
                    'SELECT id sid, text text, translation translation, source source '
                    'FROM sentences WHERE source != \"book\" OR source IS NULL '
                    'ORDER BY RANDOM() LIMIT ?', (need,)).fetchall()
        except Exception:
            rows = []
        min_o = _lv(min_corpus)
        for r in rows:
            meta = {'sid': r['sid'], 'translation': r['translation'], 'source': r['source'],
                    'origin_type': 'corpus'}
            pools['corpus'] += _cloze_candidates(r['text'], min_o, meta)

    # lyric 源
    if n_lyric > 0:
        lines = _fetch_lyric_lines(limit=n_lyric * 50)
        min_o = _lv(min_lyric)
        for sid, title, artist, line in lines:
            if not _cloze_sentence_ok(line):
                continue
            meta = {'sid': sid, 'translation': None, 'source': 'lyric',
                    'book_id': None, 'book_title': title, 'artist': artist,
                    'lesson': None, 'origin_type': 'lyric', 'lyric_text': line,
                    'title': title}
            pools['lyric'] += _cloze_candidates(line, min_o, meta)

    # 合并全局词池用于干扰项（跨源共享，保证选项丰富）
    pool_by_level = {}
    for src in pools:
        for p in pools[src]:
            pool_by_level.setdefault(p['level'], []).append(p['answer'])

    # ---- 按配额选题 ----
    questions = []
    chosen_key = set()
    chosen_sid = set()
    chosen_ans = set()

    def _pick_from(src_pool, need_count, src_name):
        nonlocal questions, chosen_key, chosen_sid, chosen_ans
        random.shuffle(src_pool)
        picked = 0
        for relax in (False, True):
            for p in src_pool:
                if picked >= need_count:
                    break
                key = (p['name'], p['sid'], p['text'])
                if key in chosen_key or p['answer'] in chosen_ans:
                    continue
                if not relax and p['sid'] in chosen_sid:
                    continue
                opts = [p['answer']] + _cloze_distractors(
                    p['name'], p['answer'], p['level'], pool_by_level,
                    after=p['after'], attr=p.get('attr'), before=p['before'],
                    base_name=p.get('base_name'))
                opts = opts[:4]
                if len(opts) < 4 or len(set(opts)) < 4 or p['answer'] not in opts:
                    continue
                random.shuffle(opts)
                chosen_key.add(key)
                chosen_sid.add(p['sid'])
                chosen_ans.add(p['answer'])
                # 注音
                try:
                    tokens = furigana.annotate(p['text'])
                    tokens_b = furigana.annotate(p['before'])
                    tokens_a = furigana.annotate(p['after'])
                    atokens = furigana.annotate(p['answer'])
                except Exception:
                    tokens, tokens_b, tokens_a, atokens = [], [], [], []
                # 出处
                if p.get('origin_type') == 'book':
                    origin = origin_label(p['source'], p.get('book_title'), p.get('lesson'))
                elif p.get('origin_type') == 'lyric':
                    origin = f"🎵《{p.get('book_title') or '歌词'}》" + (f" · {p.get('artist')}" if p.get('artist') else '')
                else:
                    origin = origin_label(p.get('source'))

                questions.append({
                    'sid': p['sid'], 'text': p['text'], 'name': p['name'],
                    'level': p['level'], 'structure': p['structure'],
                    'explain': p['explain'], 'answer': p['answer'],
                    'before': p['before'], 'after': p['after'],
                    'blank': p['blank'], 'options': opts,
                    'tokens': tokens, 'tokens_b': tokens_b,
                    'tokens_a': tokens_a, 'atokens': atokens,
                    'translation': p.get('translation'),
                    'origin': origin, 'source': p.get('source'),
                    'book_id': p.get('book_id'), 'lesson': p.get('lesson'),
                    'origin_type': p.get('origin_type'),
                    'title': p.get('book_title') or p.get('title'),
                })
                picked += 1
            if picked >= need_count:
                break
        return picked

    got_book = _pick_from(pools['book'], n_book, 'book') if n_book > 0 else 0
    got_corpus = _pick_from(pools['corpus'], n_corpus, 'corpus') if n_corpus > 0 else 0
    got_lyric = _pick_from(pools['lyric'], n_lyric, 'lyric') if n_lyric > 0 else 0

    # 如果某源不够，尝试从其他源补足
    total_got = len(questions)
    if total_got < total:
        # 剩余需求
        remain = total - total_got
        # 合并剩余池
        rest_pool = []
        for src in pools:
            # 过滤已选
            for p in pools[src]:
                if (p['name'], p['sid'], p['text']) not in chosen_key:
                    rest_pool.append(p)
        random.shuffle(rest_pool)
        for p in rest_pool:
            if len(questions) >= total:
                break
            key = (p['name'], p['sid'], p['text'])
            if key in chosen_key or p['answer'] in chosen_ans:
                continue
            opts = [p['answer']] + _cloze_distractors(
                p['name'], p['answer'], p['level'], pool_by_level,
                after=p['after'], attr=p.get('attr'), before=p['before'],
                base_name=p.get('base_name'))
            opts = opts[:4]
            if len(opts) < 4 or len(set(opts)) < 4 or p['answer'] not in opts:
                continue
            random.shuffle(opts)
            chosen_key.add(key)
            chosen_sid.add(p['sid'])
            chosen_ans.add(p['answer'])
            try:
                tokens = furigana.annotate(p['text'])
                tokens_b = furigana.annotate(p['before'])
                tokens_a = furigana.annotate(p['after'])
                atokens = furigana.annotate(p['answer'])
            except Exception:
                tokens, tokens_b, tokens_a, atokens = [], [], [], []
            if p.get('origin_type') == 'book':
                origin = origin_label(p['source'], p.get('book_title'), p.get('lesson'))
            elif p.get('origin_type') == 'lyric':
                origin = f"🎵《{p.get('book_title') or '歌词'}》"
            else:
                origin = origin_label(p.get('source'))
            questions.append({
                'sid': p['sid'], 'text': p['text'], 'name': p['name'],
                'level': p['level'], 'structure': p['structure'],
                'explain': p['explain'], 'answer': p['answer'],
                'before': p['before'], 'after': p['after'],
                'blank': p['blank'], 'options': opts,
                'tokens': tokens, 'tokens_b': tokens_b,
                'tokens_a': tokens_a, 'atokens': atokens,
                'translation': p.get('translation'),
                'origin': origin, 'source': p.get('source'),
                'book_id': p.get('book_id'), 'lesson': p.get('lesson'),
                'origin_type': p.get('origin_type'),
                'title': p.get('book_title') or p.get('title'),
            })

    random.shuffle(questions)
    # 按请求比例截断
    questions = questions[:total]

    return {
        'ok': True,
        'total': total,
        'ratios': {'book': rb_n, 'corpus': rc_n, 'lyric': rl_n},
        'counts': {'book': got_book, 'corpus': got_corpus, 'lyric': got_lyric, 'total': len(questions)},
        'questions': questions,
        'short': len(questions) < total,
        'explain': f'按比例出题：课文{rb_n:.0f}%({got_book}) 语料{rc_n:.0f}%({got_corpus}) 歌词{rl_n:.0f}%({got_lyric}) / 共{len(questions)}/{total}',
        'book_ids': ids,
    }
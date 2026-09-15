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
import re
import time
from datetime import date, timedelta

import corpus
import db
import furigana
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
    """导入前预览（不写库）：拆出几本书、多少课/句，以及字/词规模与重复情况。"""
    books = parse_books(text, lesson_size)
    all_sents = [s for b in books for s in b['sentences']]
    dup = 0
    kanji, words = {}, {}
    for i, s in enumerate(all_sents):
        if db.sentence_exists(s):
            dup += 1
        if i < sample:                      # 长文本只抽样分析，保证预览秒回
            k_rows, w_rows = extract_units(s)
            for k, _w, _r in k_rows:
                kanji[k] = kanji.get(k, 0) + 1
            for w, _r, _k, _pos in w_rows:
                words[w] = words.get(w, 0) + 1
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
    返回 (new_of_day, load, rev_of_day, rev_count, unplaced)"""
    load = [n * REVIEW_SECONDS for n in existing_days]
    new_of_day = [[] for _ in range(horizon)]
    rev_of_day = [[] for _ in range(horizon)]
    rev_count = list(existing_days)
    unplaced = []
    intro_days = max(0, last_intro) + 1
    hard_cap = max_new_per_day or 10 ** 9
    limit = min(max(1, -(-len(fresh) // intro_days)), hard_cap)   # 每日目标新字数

    def try_place(k, bid, max_count):
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
            if (k, bid) not in rev_of_day[d]:
                rev_of_day[d].append((k, bid))
            for dd in future:                       # 后续曲线复习点
                load[dd] += REVIEW_SECONDS
                rev_count[dd] += 1
                if (k, bid) not in rev_of_day[dd]:
                    rev_of_day[dd].append((k, bid))
            new_of_day[d].append((k, bid))
            return True
        return False

    for k, bid in fresh:
        if try_place(k, bid, limit):
            continue
        if not try_place(k, bid, hard_cap):         # 放宽均匀目标（仍受每日容量约束）
            unplaced.append((k, bid))
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
    """全局 SRS 记忆状态（自动识别以前学习进度的唯一事实来源）"""
    with db.get_conn() as c:
        return {r['kanji']: (r['stage'] or 0) for r in c.execute('SELECT kanji, stage FROM srs')}


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
            out.append((k, bid))
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
    """汉字 → 词/读音/所属书（计划表展示用）"""
    ids = list(book_ids)
    if not ids:
        return {}
    ph = ','.join('?' * len(ids))
    with db.get_conn() as c:
        rows = c.execute(
            f'SELECT bk.kanji kanji, MIN(bk.word) word, MIN(bk.reading) reading, '
            f'MAX(b.title) book_title FROM book_kanji bk JOIN books b ON b.id=bk.book_id '
            f'WHERE bk.book_id IN ({ph}) GROUP BY bk.kanji', ids).fetchall()
    return {r['kanji']: dict(r) for r in rows}


def build_plan(book_ids=None, start=None, deadline=None, minutes_per_day=None,
               target_stage=None, max_new_per_day=None, save=True):
    """为选中的一本或多本课本排出「截止日前每天学什么、复习什么」。

    保证（可行性算法）：
    - 每个新字走完 target_stage 阶段艾宾浩斯曲线的**全部复习**都落在截止日之前
      （新字最晚引入日 = 截止日 − 曲线天数）；
    - 每天总负载（首次学习 + 同日 3 次短复习 + 后续曲线复习 + 已学字的到期复习）
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
    fresh = _fresh_kanji(book_ids, stages)
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
            'new': [{'kanji': k, 'book_id': b, 'book': book_titles.get(b), **(meta.get(k) or {})}
                    for k, b in new_of_day[i]],
            'review_items': [{'kanji': k, 'book_id': b, 'book': book_titles.get(b), **(meta.get(k) or {})}
                             for k, b in rev_of_day[i]],
            'review_count': rev_count[i],          # 含既有全局复习
            'load_min': round(load[i] / 60.0, 1),
            'capacity_min': minutes,
        })

    if save and not unplaced:
        # 计划落库：新字(is_new=1)与复习(is_new=0)都按书保存，逐字可勾选完成
        for bid in book_ids:
            rows = []
            for i in range(horizon):
                d_iso = per_day[i]['day']
                rows += [(d_iso, 1, k) for k, b in new_of_day[i] if b == bid]
                rows += [(d_iso, 0, k) for k, b in rev_of_day[i] if b == bid]
            db.save_book_plan(bid, rows)
        # 排程实际采用的参数回写（界面展示与计划读取保持一致）
        for b in books:
            db.update_book(b['id'], deadline=_iso(deadline_d),
                           minutes_per_day=minutes, target_stage=target)
        db.log('book_plan', f'生成学习计划：{len(book_ids)} 本书 · {len(fresh)} 个新字 · '
                            f'{_iso(start_d)} → {_iso(deadline_d)} · 每天 {minutes} 分钟')

    return {'ok': not unplaced, 'feasible': not unplaced,
            'reason': None if not unplaced else f'容量不足，{len(unplaced)} 个字在截止日前排不下',
            'start': _iso(start_d), 'deadline': _iso(deadline_d), 'days': horizon,
            'minutes_per_day': minutes, 'target_stage': target,
            'curve_days': curve_need, 'last_intro_day': _iso(start_d + timedelta(days=last_intro)),
            'books': [{'id': b['id'], 'title': b['title']} for b in books],
            'new_total': len(fresh), 'unplaced_count': len(unplaced),
            'unplaced': [k for k, _b in unplaced[:50]], 'suggestion': suggestion,
            'existing_review_total': sum(existing),
            'per_day': per_day}


def save_plan(book_ids=None, start=None, deadline=None, minutes_per_day=None,
              target_stage=None, max_new_per_day=None):
    """生成并保存计划（= build_plan(save=True) 的语义化别名）"""
    return build_plan(book_ids, start, deadline, minutes_per_day, target_stage,
                      max_new_per_day, save=True)


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
        it = {'kanji': r['kanji'], 'manual_done': bool(r['done']),
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
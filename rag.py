# -*- coding: utf-8 -*-
"""
RAG 多源语义检索引擎 v2（本地、零外部服务依赖）
================================================================
三类可检索内容（联邦多通道，用户可指定优先级）：
  🎵 lyric     歌词（KTV 页导入的歌曲：逐行 + 歌名）
  📖 textbook  自建课本（书名 / 课名 / 例句，含译文）
  🌐 web       网络语料（Tatoeba / 维基百科 / 维基新闻抓取 + 手动添加的散句）

检索管线（各通道并行召回 → 融合精排）：
  1) 查询归一化：全/半角、大小写、片假名→平假名、去空白与长音符
  2) 关键词扩展：分词表记 + 词典原形(lemma) + 读音（汉字⇄假名互查）
     + 罗马音→假名（gakkou→がっこう）+ 片假名连字符 bigram（外来语容错）
  3) BM25 粗召回（k1=1.4, b=0.72；IDF 抑制高频词、文档长度归一化）
  4) 字符 bigram Dice 召回补充（防分词漏召回，继承旧引擎亲和检索能力）
  5) 精排 rerank：0.40×BM25 + 0.20×Dice + 0.20×词元覆盖 + 0.20×短语包含
  6) 用户指定来源优先级：序位加权（每提前一位 +10%）+ 歌词/课本小额先验
  7) 全局去重（同文同 key 只留一条）→ 每首歌/每本书配额 → 截断输出
索引全内存；数据签名（句子/歌词/课本变更）不一致时自动同步重建。
RagIndex 保留全库 BM25 检索，供 /api/rag/similar（找相似例句）兼容使用。
"""
import math
import re
import threading
import time

import db
import furigana
import ktv

CHANNELS = ('lyric', 'textbook', 'web')
_CH_PRIOR = {'lyric': 0.03, 'textbook': 0.02, 'web': 0.0}   # 歌词优先、课本次之
_ORIGIN = {'tatoeba': 'Tatoeba', 'wikipedia': '维基百科', 'wikinews': '维基新闻'}

# ---------------- 查询归一化 ----------------
# 注意：str.translate 需要「码位(int) → 替换串」的映射，故先写字面表再转码位，
# 否则映射会被静默忽略（全角/半角与长音符归一化会失效）。
_FULL2HALF_CHARS = {
    **{chr(ord('Ａ') + i): chr(ord('A') + i) for i in range(26)},
    **{chr(ord('ａ') + i): chr(ord('a') + i) for i in range(26)},
    **{chr(ord('０') + i): str(i) for i in range(10)},
    '！': '!', '？': '?', '。': '.', '、': '.', '，': ',', '：': ':', '；': ';',
    '・': '-', '～': '~', '〜': '-', 'ｰ': '', 'ー': '', '－': '', '　': '',
}
_FULL2HALF = {ord(k): v for k, v in _FULL2HALF_CHARS.items()}
_KATA2HIRA = {chr(0x30A1 + i): chr(0x3041 + i) for i in range(0x5A)}
_KANA_RE = re.compile(r'[぀-ヿ]')
_ASCII_WORD_RE = re.compile(r'[A-Za-z]{2,}')


def normalize(text: str) -> str:
    """检索统一形：半角化→小写→片假名→平假名→去空白/长音符。"""
    s = (text or '').translate(_FULL2HALF).lower()
    s = ''.join(_KATA2HIRA.get(ch, ch) for ch in s)
    return re.sub(r'\s+', '', s)


def _bigrams(text: str):
    """字符 bigram 集合（Dice 亲和用）。"""
    s = normalize(text)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


# ---------------- 分词与关键词扩展 ----------------
_TAGGER = None
_TAG_LOCK = threading.Lock()


def _tagger():
    global _TAGGER
    with _TAG_LOCK:
        if _TAGGER is None:
            import fugashi
            _TAGGER = fugashi.Tagger()
    return _TAGGER


def _base_tokens(text: str):
    """检索 token：表记规范形 + 词典原形(lemma) + 读音(仅汉字词) + 片假名连 bigram。"""
    raw = text or ''
    toks = []
    try:
        ws = [w for w in _tagger()(raw) if w.surface and w.surface.strip()]
    except Exception:
        ws = []
    for w in ws:
        s = w.surface.strip()
        f = getattr(w, 'feature', None)
        p1 = (getattr(f, 'pos1', '') or '') if f else ''
        if p1 in ('補助記号', '空白') or not s:
            continue
        if p1 == '記号' and not _KANA_RE.search(s) and not furigana.has_kanji(s):
            continue
        n = normalize(s)
        if not n or (len(n) == 1 and _KANA_RE.match(n)):   # 单个假名 = 助词/活用碎片
            continue
        toks.append(n)
        if f:
            lm = normalize((getattr(f, 'lemma', '') or '').split('-')[0])
            if lm and lm != n:
                toks.append(lm)
            kn = normalize(getattr(f, 'kana', '') or '')
            if kn and kn not in (n, lm) and furigana.has_kanji(s):
                toks.append(kn)
    for run in re.findall(r'[ァ-ヶー]{3,}', raw):          # 外来语连读容错
        rn = normalize(run)
        toks += [rn[i:i + 2] for i in range(len(rn) - 1)]
    return toks


def _tokens(text: str):
    """检索 token；分词无果时回退整串规范形，保证查询/文档永不为空。"""
    t = _base_tokens(text)
    if t:
        return t
    n = normalize(text)
    return [n] if n else []

def key_terms(text: str):
    """查询关键词（前端高亮用）：实词表记 + 原形 + 读音。"""
    raw = text or ''
    out = set()
    try:
        ws = [w for w in _tagger()(raw) if w.surface and w.surface.strip()]
    except Exception:
        ws = []
    for w in ws:
        s = w.surface.strip()
        f = getattr(w, 'feature', None)
        p1 = (getattr(f, 'pos1', '') or '') if f else ''
        if not s or p1 in ('補助記号', '空白', '助詞', '記号', '接続詞'):
            continue
        if len(s) == 1 and _KANA_RE.match(s):
            continue
        out.add(s)
        if f:
            lm = (getattr(f, 'lemma', '') or '').split('-')[0]
            if lm:
                out.add(lm)
            kn = normalize(getattr(f, 'kana', '') or '')
            if kn:
                out.add(kn)
    out.discard('')
    return sorted(out)[:12]


def query_variants(q: str):
    """查询变体（透明化展示 + 召回扩展）：罗马音逐词→假名。
    先全角→半角再提取拉丁词，故「Ｇａｋｋｏ」与「gakkou」效果一致。"""
    out = []
    for w in _ASCII_WORD_RE.findall((q or '').translate(_FULL2HALF)):
        if len(w) < 3:
            continue
        k = normalize(ktv.romaji_to_kana(w))
        if k and len(k) >= 2 and k not in out:
            out.append(k)
    return out


def _as_int_list(value):
    out = []
    for x in value or []:
        try:
            n = int(x)
        except Exception:
            continue
        if n not in out:
            out.append(n)
    return out


# ---------------- 紧凑 BM25 倒排索引 ----------------
class _BM25:
    """内存 BM25（Okapi，k1/b 可调）；add() 增量写入，search() 返回归一化得分。"""

    def __init__(self, k1=1.4, b=0.72):
        self.k1, self.b = k1, b
        self.post = {}      # token -> [(doc_id, tf)]
        self.doclen = {}    # doc_id -> token 数
        self.docs = {}      # doc_id -> payload dict
        self.N = 0
        self.sumdl = 0

    def add(self, doc_id, tokens, payload):
        self.docs[doc_id] = payload
        L = max(len(tokens), 1)
        self.doclen[doc_id] = L
        self.N += 1
        self.sumdl += L
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        for t, n in tf.items():
            self.post.setdefault(t, []).append((doc_id, n))

    def search(self, qtokens, topk=50):
        """返回 [(归一化得分 0..1, doc_id)]，按得分降序。"""
        if not qtokens or not self.N:
            return []
        avgdl = self.sumdl / self.N
        scores = {}
        for t in set(qtokens):
            plist = self.post.get(t)
            if not plist:
                continue
            idf = math.log(1 + (self.N - len(plist) + 0.5) / (len(plist) + 0.5))
            if idf <= 0:
                continue
            for doc_id, tf in plist:
                L = self.doclen[doc_id]
                scores[doc_id] = scores.get(doc_id, 0.0) + \
                    idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * L / avgdl))
        if not scores:
            return []
        mx = max(scores.values()) or 1.0
        out = [(s / mx, d) for d, s in scores.items()]
        out.sort(key=lambda x: -x[0])
        return out[:topk]


# ---------------- 多源联邦检索索引 ----------------
class MultiIndex:
    """歌词 / 课本 / 网络语料 三通道 BM25 联邦索引 + 歌名书名辅助索引。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._bm = {c: _BM25() for c in CHANNELS}
        self._tbm = _BM25()                       # 歌名/书名/课名
        self._wset = {c: {} for c in CHANNELS}    # doc_id -> 词元集合（覆盖度）
        self._dset = {c: {} for c in CHANNELS}    # doc_id -> 字符 bigram 集合（Dice）
        self._counts = {'lyric': 0, 'textbook': 0, 'web': 0, 'songs': 0, 'books': 0}
        self._stamp = None
        self._built = False
        self._building = False

    # ---------- 数据快照与构建 ----------
    def _sig(self):
        """数据签名：任一通道数据增删改 → 变化 → 重建。"""
        with db.get_conn() as c:
            a = c.execute('SELECT COUNT(*) n, COALESCE(MAX(id),0) m, '
                          'COALESCE(MAX(created_at),0) t FROM sentences').fetchone()
            b = c.execute('SELECT COUNT(*) n, COALESCE(MAX(updated_at),0) t FROM songs').fetchone()
            k = c.execute('SELECT COUNT(*) n, COALESCE(MAX(updated_at),0) t FROM books').fetchone()
        return (f"{a['n']}:{a['m']}:{a['t']}", f"{b['n']}:{b['t']}", f"{k['n']}:{k['t']}")

    def ensure(self):
        """索引就绪保障：签名变化（或首次）→ 同步重建（本地数据量，毫秒~秒级）。"""
        if self._building:
            return False
        try:
            sig = self._sig()
        except Exception:
            return False
        if self._built and sig == self._stamp:
            return False
        self._building = True
        try:
            self._build()
            self._stamp = sig
            self._built = True
        finally:
            self._building = False
        return True

    def _build(self):
        rows, songs, books, lessons, bs = [], [], [], [], {}
        with db.get_conn() as c:
            rows = c.execute('SELECT id,text,translation,source FROM sentences').fetchall()
            songs = c.execute('SELECT id,title,artist,lyrics FROM songs').fetchall()
            books = c.execute('SELECT id,title,author,level,note FROM books').fetchall()
            lessons = c.execute('SELECT l.id,l.book_id,l.title,b.title btitle FROM book_lessons l '
                                'JOIN books b ON b.id=l.book_id').fetchall()
            for r in c.execute('''SELECT bs.sentence_id sid, bs.book_id bid, l.title lesson, b.title btitle
                                  FROM book_sentences bs JOIN books b ON b.id=bs.book_id
                                  LEFT JOIN book_lessons l ON l.id=bs.lesson_id'''):
                bs.setdefault(r['sid'], []).append(dict(r))
        bm = {c: _BM25() for c in CHANNELS}
        tbm = _BM25()
        wset = {c: {} for c in CHANNELS}
        dset = {c: {} for c in CHANNELS}
        counts = {'lyric': 0, 'textbook': 0, 'web': 0, 'songs': 0, 'books': 0}
        # —— 句子（课本链接优先，其次网络/手动语料） ——
        for r in rows:
            text = r['text'] or ''
            toks = _tokens(text)
            d = ('s', r['id'])
            linked = bs.get(r['id'])
            if linked:
                ch = 'textbook'
                meta = {'book_id': linked[0]['bid'], 'book_title': linked[0]['btitle'] or '',
                        'lesson_title': linked[0]['lesson'] or ''}
            else:
                ch = 'web'
                meta = {'source': r['source'] or ''}
            meta.update({'kind': 'sentence', 'id': r['id'], '_text': text,
                         'translation': r['translation'] or ''})
            bm[ch].add(d, toks, meta)
            wset[ch][d] = set(toks)
            dset[ch][d] = _bigrams(text)
            counts[ch] += 1
        # —— 歌词（逐行 + 歌名） ——
        for s in songs:
            title = s['title'] or ''
            if title:
                tbm.add(('t', s['id']), _tokens(title),
                        {'kind': 'song', 'id': s['id'], 'title': title, 'artist': s['artist'] or ''})
                counts['songs'] += 1
            for i, line in enumerate((s['lyrics'] or '').split('\n')):
                line = line.strip()
                if not line or ktv.is_latin_line(line):
                    continue
                d = ('l', s['id'], i)
                d = ('l', s['id'], i)
                lt = _tokens(line)
                bm['lyric'].add(d, lt,
                                {'kind': 'line', 'id': s['id'], 'title': title,
                                 'artist': s['artist'] or '', '_text': line, 'line_no': i})
                wset['lyric'][d] = set(lt)
                dset['lyric'][d] = _bigrams(line)
                counts['lyric'] += 1
        # —— 课本（书名/备注/课名） ——
        for b in books:
            tbm.add(('b', b['id']), _tokens((b['title'] or '') + ' ' + (b['note'] or '')),
                    {'kind': 'book', 'id': b['id'], 'title': b['title'] or '',
                     'author': b['author'] or '', 'level': b['level'] or ''})
            counts['books'] += 1
        for l in lessons:
            if not l['title']:
                continue
            tbm.add(('e', l['id']), _tokens(l['title']),
                    {'kind': 'lesson', 'id': l['id'], 'book_id': l['book_id'],
                     'title': l['title'], 'book_title': l['btitle'] or ''})
        with self._lock:
            self._bm = bm
            self._tbm = tbm
            self._wset = wset
            self._dset = dset
            self._counts = counts


    # ---------- 检索 ----------
    def _dice_scan(self, ch, qgrams, threshold, topk=40):
        """字符 bigram Dice 召回（防分词漏召回）。"""
        out = []
        for d, grams in self._dset[ch].items():
            if not qgrams or not grams:
                continue
            inter = len(qgrams & grams)
            if not inter:
                continue
            dc = 2.0 * inter / (len(qgrams) + len(grams))
            if dc >= threshold:
                out.append((d, dc))
        out.sort(key=lambda x: -x[1])
        return out[:topk]

    def _rerank(self, qn, qset, qgrams, bm_s, text, words, grams):
        """综合分 ∈ [0,1]：0.40×BM25 + 0.20×Dice + 0.20×词元覆盖 + 0.20×短语包含。"""
        phrase = 1.0 if qn and qn in text else 0.0
        cov = (len(qset & words) / len(qset)) if qset and words else 0.0
        dice = (2.0 * len(qgrams & grams) / (len(qgrams) + len(grams))) if qgrams and grams else 0.0
        s = 0.40 * bm_s + 0.20 * dice + 0.20 * cov + 0.20 * phrase
        if s > 0 and qn and text:
            lr = min(len(qn), len(text)) / max(len(qn), len(text), 1)
            s *= (0.8 + 0.2 * lr)                 # 长度悬殊轻惩罚
        return s

    def _row(self, m, sc, ch):
        sc = round(min(max(sc, 0.0), 1.0), 3)
        if ch == 'lyric':
            return {'type': 'lyric', 'channel': ch, 'kind': m.get('kind'), 'id': m['id'],
                    'title': m.get('title') or '', 'artist': m.get('artist') or '',
                    'text': m.get('_text') or '', 'line_no': m.get('line_no'),
                    'score': sc, 'affinity': sc}
        if ch == 'textbook':
            return {'type': 'textbook', 'channel': ch, 'kind': m.get('kind'), 'id': m['id'],
                    'title': m.get('book_title') or '', 'book_id': m.get('book_id'),
                    'book_title': m.get('book_title') or '', 'lesson': m.get('lesson_title') or '',
                    'text': m.get('_text') or '',
                    'translation': m.get('translation') or '', 'score': sc}
        src = m.get('source') or ''
        origin = _ORIGIN.get(src, '手动添加' if src == 'manual' else (src or '语料'))
        return {'type': 'web', 'channel': ch, 'kind': 'sentence', 'id': m['id'],
                'title': origin, 'text': m.get('_text') or '',
                'translation': m.get('translation') or '', 'score': sc}
    def search(self, q, limit=12, sources=None, per_song=3, per_book=4,
               min_score=0.0, min_affinity=0.0, book_ids=None, sort='priority'):
        """联邦多源检索。
        sources: 优先级列表（CHANNELS 子集，有序）；未指定的通道排在后面。
        per_song: 每首歌最多命中行数（0=不限）；per_book: 每本书最多句数（0=不限）。
        sort: 'priority'（默认，按用户指定的来源顺序分档排列）| 'score'（相关性优先混排）。
        返回 {'rows': 句子行, 'lyrics': 歌词行, 'results': 统一排名,
              'groups': 分组, 'titles': 歌名/书名命中, 'meta': 统计与查询分析}。"""
        t0 = time.time()
        q = (q or '').strip()
        if not q:
            return {'rows': [], 'lyrics': [], 'results': [],
                    'groups': {c: [] for c in CHANNELS},
                    'titles': {'songs': [], 'books': []},
                    'meta': {'counts': {}, 'terms': [], 'qvars': [], 'prior': [], 'qnorm': '', 'ms': 0}}
        self.ensure()
        qn = normalize(q)
        qtoks = _tokens(q)
        qv = query_variants(q)                     # 罗马音→假名扩展
        for v in qv:
            qtoks += _tokens(v)
        qset = set(qtoks)
        qgrams = _bigrams(q)
        enabled = [c for c in (sources or CHANNELS) if c in CHANNELS]
        if not enabled:
            enabled = list(CHANNELS)
        pri = list(enabled)
        enabled_set = set(enabled)
        selected_books = set(_as_int_list(book_ids))
        with self._lock:
            bm = self._bm
            wset = self._wset
            dset = self._dset
            counts = dict(self._counts)
        # 1) 双路召回（BM25 + Dice）→ 2) 精排
        scored = {c: [] for c in CHANNELS}
        for ch in CHANNELS:
            if ch not in enabled_set:
                continue
            cand = {}
            for s, d in bm[ch].search(qtoks, topk=max(limit * 5, 50)):
                cand[d] = s
            th = min(0.14, max(0.10, min_affinity or 0.14))
            for d, dc in self._dice_scan(ch, qgrams, th):
                if d not in cand:
                    cand[d] = 0.0
            for d, bm_s in cand.items():
                m = bm[ch].docs[d]
                if ch == 'textbook' and selected_books:
                    bid = m.get('book_id') or m.get('id')
                    if bid not in selected_books:
                        continue
                s = self._rerank(qn, qset, qgrams, bm_s, m.get('_text') or m.get('title') or '',
                                 wset[ch].get(d) or set(), dset[ch].get(d) or set())
                if ch == 'textbook' and selected_books and (m.get('book_id') in selected_books):
                    s = min(1.0, s + 0.08)
                if s >= 0.10:
                    scored[ch].append((s, d))
            scored[ch].sort(key=lambda x: -x[0])
        # 3) 优先级加权 → 4) 融合去重 + 配额
        def boost(ch):
            return 1.0 + 0.22 * (len(pri) - 1 - pri.index(ch))

        pool = []
        for ch in CHANNELS:
            for s, d in scored[ch]:
                pool.append((s * boost(ch) + _CH_PRIOR[ch], ch, d))
        pool.sort(key=lambda x: -x[0])
        seen, cnt_song, cnt_book = set(), {}, {}
        rows, lyrics, groups = [], [], {c: [] for c in CHANNELS}
        unified = []        # 跨通道统一排名（用户指定的来源优先级在这里体现）
        for sc, ch, d in pool:
            m = bm[ch].docs[d]
            key = m.get('_text') or ''
            if not key or key in seen:
                continue
            if ch == 'lyric' and per_song and cnt_song.get(m['id'], 0) >= per_song:
                continue
            if (ch == 'textbook' and m.get('kind') == 'sentence' and per_book
                    and cnt_book.get(m.get('book_id'), 0) >= per_book):
                continue
            seen.add(key)
            row = self._row(m, sc, ch)
            row['rank'] = round(sc, 3)
            if ch == 'lyric':
                cnt_song[m['id']] = cnt_song.get(m['id'], 0) + 1
                lyrics.append(row)
            else:
                if ch == 'textbook' and m.get('kind') == 'sentence':
                    cnt_book[m.get('book_id')] = cnt_book.get(m.get('book_id'), 0) + 1
                rows.append(row)
            groups[ch].append(row)
            unified.append(row)
            if len(unified) >= 60:
                break
        rows = [r for r in rows if r['score'] >= min_score]
        lyrics = [r for r in lyrics if r['score'] >= max(min_affinity, 0.0)]
        # 5) 歌名/书名命中（强意图信号：置顶对应组 + 置顶歌词列表）
        titles = {'songs': [], 'books': []}
        with self._lock:
            tbm = self._tbm
        for s, d in tbm.search(qtoks, topk=6):
            m = tbm.docs[d]
            if m['kind'] == 'song' and 'lyric' not in enabled_set:
                continue
            if m['kind'] in ('book', 'lesson') and 'textbook' not in enabled_set:
                continue
            if selected_books and m.get('kind') in ('book', 'lesson'):
                bid = m.get('id') if m.get('kind') == 'book' else m.get('book_id')
                if bid not in selected_books:
                    continue
            sc = round(0.85 + 0.1 * s, 3)
            if m['kind'] == 'song':
                trow = {'type': 'lyric', 'channel': 'lyric', 'kind': 'song',
                        'id': m['id'], 'title': m['title'], 'artist': m['artist'],
                        'text': '', 'line_no': None, 'score': sc,
                        'affinity': sc, 'title_match': True}
                titles['songs'].append(trow)
            else:
                titles['books'].append({'id': m['id'], 'title': m['title'],
                                        'author': m['author'], 'level': m['level'],
                                        'score': round(s, 3),
                                        'row': {'type': 'textbook', 'channel': 'textbook',
                                                'kind': 'book', 'id': m['id'], 'book_id': m['id'],
                                                'title': m['title'], 'lesson': '', 'text': '',
                                                'translation': '', 'score': sc, 'title_match': True}})
        # 歌名/书名命中置顶：歌名先出现在歌词列表首位（点击 = 直接打开整首歌），
        # 再跟上逐行歌词命中；同一首歌只保留一条「整首」入口。
        # 统一列表（results）同样把标题命中排在最前 —— 这是最强的意图信号。
        seen_title, top_songs, top_books = set(), [], []
        for t in titles['songs']:
            if t['title'] in seen_title:
                continue
            seen_title.add(t['title'])
            t['_title_only'] = True
            top_songs.append(t)
            if len(top_songs) >= 2:
                break
        for t in titles['books']:
            top_books.append(t['row'])
            if len(top_books) >= 2:
                break
        groups['lyric'] = top_songs + groups['lyric']
        groups['textbook'] = top_books + groups['textbook']
        merged = top_songs + [r for r in lyrics if r.get('text')]
        # 统一排名列表：标题命中 →（用户指定的来源优先级为第一排序键）。
        # sort='priority'（默认）：① 来源的结果整体排在 ② 之前，匹配用户「优先匹配指定内容」的意图；
        # 同来源内按分数降序（助词/词元覆盖等精排分）。命中为空则自然落到下一来源。
        # sort='score'：纯相关性优先，仅用优先级做轻微加权（跨来源混排）。
        _pri_idx = {c: pri.index(c) for c in pri}
        _thr = lambda r: (max(min_affinity, 0.0) if r['channel'] == 'lyric' else min_score)
        kept = [r for r in unified if r['score'] >= _thr(r)]
        if sort == 'score':
            ordered = sorted(kept, key=lambda r: (-r['rank'], _pri_idx.get(r['channel'], len(pri)),
                                                  -len(r.get('text') or '')))
        else:
            ordered = sorted(kept, key=lambda r: (_pri_idx.get(r['channel'], len(pri)),
                                                  -r['score'], -len(r.get('text') or '')))
        results = top_songs + top_books + ordered
        meta = {'counts': counts, 'terms': key_terms(q), 'qvars': qv,
                'prior': pri, 'qnorm': qn, 'sort': sort, 'ms': round((time.time() - t0) * 1000),
                'book_ids': sorted(selected_books),
                'hits': {'lyric': len(groups['lyric']), 'textbook': len(groups['textbook']),
                         'web': len(groups['web'])}}
        return {'rows': rows[:max(limit, 1)],
                'lyrics': merged[:max(8, limit)],
                'results': results[:max(limit, 1)],
                'groups': groups, 'titles': titles, 'meta': meta}



# ---------------- 全库兼容索引（/api/rag/similar 用） ----------------
class RagIndex:
    """全库语料 BM25 检索；query() 接口与旧版（TF-IDF）一致：[(sid, score)]。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._bm = _BM25()
        self._n_built = -1

    def _build(self):
        bm = _BM25()
        with db.get_conn() as c:
            rows_ = c.execute('SELECT id, text FROM sentences').fetchall()
        for r in rows_:
            bm.add(r['id'], _tokens(r['text']), {'_text': r['text']})
        self._bm = bm
        self._n_built = len(rows_)

    def ensure(self):
        with self._lock:
            with db.get_conn() as c:
                cnt = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
            if cnt != self._n_built:
                self._build()

    def query(self, text, limit=10, exclude_sid=None):
        self.ensure()
        hits = self._bm.search(_tokens(text), topk=limit + 2)
        return [(d, round(s, 4)) for s, d in hits if d != exclude_sid][:limit]


INDEX = RagIndex()
MULTI = MultiIndex()


def warmup():
    """启动预热（后台线程调用）：预构建多源索引，避免首个请求等待。"""
    try:
        MULTI.ensure()
    except Exception:
        pass

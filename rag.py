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
索引全内存（v26 紧凑重写：机器码倒排 + 查询侧累计，内存降一个数量级；
语料超过内存预算时按最新 N 篇降级，见 perf.doc_cap）；数据签名（句子/歌词/
课本变更）不一致时自动同步重建。
RagIndex 保留全库 BM25 检索，供 /api/rag/similar（找相似例句）兼容使用。
"""
import math
import re
import threading
import time
from array import array

import db
import furigana
import ktv
import corpus_shards
import federated_search

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
    """内存 BM25（Okapi，k1/b 可调）——v26 紧凑重写。

    旧版每个 (token, doc) 挂一条 Python tuple：23k 句 × ~15 词元 =
    35 万个 tuple ≈ 25MB，加上 doclen dict、payload dict，配合上层
    MultiIndex 的 wset/dset/nset 三份冗余，2.4 万句就吃掉 ~400MB RSS。

    现在的存储布局（同样的语义，小一个数量级）：
    - post:  token -> (array('l') 文档号, array('h') 词频)，机器码数组；
    - doclen: array('l')，文档号即下标；
    - docs:   列表，文档号即下标（payload 仍是 dict，供出结果用）。

    search() 在同一遍倒排扫描里顺带累计「查询词元命中数」，供上层
    免二次扫描地算覆盖度（coverage），这是 recall 阶段的免费副产品。
    """

    def __init__(self, k1=1.4, b=0.72):
        self.k1, self.b = k1, b
        self.post = {}      # token -> (array doc_ids, array tfs)
        self.doclen = array('l')
        self.docs = []      # doc_id -> payload dict
        self.N = 0
        self.sumdl = 0

    def add(self, tokens, payload):
        """写入一篇文档，返回分配的文档号（int）。"""
        d = len(self.docs)
        self.docs.append(payload)
        L = max(len(tokens), 1)
        self.doclen.append(L)
        self.N += 1
        self.sumdl += L
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        for t, n in tf.items():
            slot = self.post.get(t)
            if slot is None:
                slot = (array('l'), array('h'))
                self.post[t] = slot
            slot[0].append(d)
            slot[1].append(n)
        return d

    def ids_for(self, token):
        """包含该词元的文档号数组（覆盖度/存在性判断用），无命中返回 None。"""
        slot = self.post.get(token)
        return slot[0] if slot else None

    def search(self, qtokens, topk=50, cov=None):
        """返回 [(归一化得分 0..1, doc_id)]，按得分降序。

        cov 传入 dict 时，同一遍扫描会把「文档命中了几个**不同**查询词元」
        累计进去（等价于旧版 len(qset & doc_tokens)），调用方免二次扫描。
        """
        if not qtokens or not self.N:
            return []
        avgdl = self.sumdl / self.N
        k1, b = self.k1, self.b
        doclen = self.doclen
        scores = {}
        for t in set(qtokens):
            slot = self.post.get(t)
            if not slot:
                continue
            ids, tfs = slot
            idf = math.log(1 + (self.N - len(ids) + 0.5) / (len(ids) + 0.5))
            if idf <= 0:
                continue
            if cov is not None:
                for d in ids:
                    cov[d] = cov.get(d, 0) + 1
            for d, tf in zip(ids, tfs):
                L = doclen[d]
                scores[d] = scores.get(d, 0.0) + \
                    idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * L / avgdl))
        if not scores:
            return []
        mx = max(scores.values()) or 1.0
        out = [(s / mx, d) for d, s in scores.items()]
        out.sort(key=lambda x: -x[0])
        return out[:topk]


# ---------------- 多源联邦检索索引 ----------------
class MultiIndex:
    """歌词 / 课本 / 网络语料 三通道 BM25 联邦索引 + 歌名书名辅助索引。

    v26 紧凑重写：旧版为每篇文档同时持有 token 列表、token 集合(wset)、
    字符 bigram 集合(dset)、bigram 倒排(dpost)、归一化文本(nset) 五份
    数据——2.4 万句 ~400MB RSS，Render 免费实例必然 OOM。
    现在只保留两份机器码倒排（词元 / bigram），覆盖度与 Dice 全部改为
    「查询侧倒排累计」：对每个查询词元/bigram 扫一遍倒排表，命中数
    加在文档上，数学上与旧的逐文档集合交完全等价，但不再为每篇文档
    常驻任何集合对象。归一化文本只在精排阶段对 ~百个候选即时计算。
    语料超过内存预算时按最新 N 篇降级（meta.index.capped 如实标注），
    绝不因为语料涨大而吃爆内存。
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._bm = {c: _BM25() for c in CHANNELS}
        self._tbm = _BM25()                       # 歌名/书名/课名
        self._gpost = {c: {} for c in CHANNELS}   # bigram -> array('l') 文档号
        self._glen = {c: array('l') for c in CHANNELS}  # 每篇文档 bigram 集合大小
        self._counts = {'lyric': 0, 'textbook': 0, 'web': 0, 'songs': 0, 'books': 0,
                        'capped': False}
        self._stamp = None
        self._built = False
        self._building = False
        self._qcache = {}                         # 查询 LRU：ckey -> 结果（v18）
        self._qorder = []                         # LRU 顺序（ckey 列表）
        self._QCACHE_MAX = 64

    # ---------- 数据快照与构建 ----------
    def _sig(self):
        """数据签名：任一通道数据增删改 → 变化 → 重建。

        v24：句子侧用 (COUNT, MAX(id)) 取代旧的 (COUNT, MAX(id), MAX(created_at))。
        created_at 与自增 id 同向单调（插入即两者齐增、从不回改），对变更检测而言
        与 MAX(id) 完全冗余；而 created_at 无索引，MAX(created_at) 是一次全表扫描
        （万级语料下约 6~7ms，且每次检索都跑）。去掉后签名检测能力不变，_sig 从
        ~10ms 降到亚毫秒——省的是「每一次检索」的固定开销。"""
        with db.get_conn() as c:
            a = c.execute('SELECT COUNT(*) n, COALESCE(MAX(id),0) m FROM sentences').fetchone()
            b = c.execute('SELECT COUNT(*) n, COALESCE(MAX(updated_at),0) t FROM songs').fetchone()
            k = c.execute('SELECT COUNT(*) n, COALESCE(MAX(updated_at),0) t FROM books').fetchone()
        return (f"{a['n']}:{a['m']}", f"{b['n']}:{b['t']}", f"{k['n']}:{k['t']}")

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
        """紧凑重建：流式游标 + 机器码倒排，语料超预算时按最新 N 篇降级。"""
        import perf
        cap = perf.doc_cap(default=200000, env='KANJI_RAG_MAX_DOCS')
        bm = {c: _BM25() for c in CHANNELS}
        tbm = _BM25()
        gpost = {c: {} for c in CHANNELS}          # bigram -> array('l') 文档号
        glen = {c: array('l') for c in CHANNELS}   # 每篇文档 bigram 集合大小
        counts = {'lyric': 0, 'textbook': 0, 'web': 0, 'songs': 0, 'books': 0,
                  'capped': False}
        with db.get_conn() as c:
            n_sent = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
            capped = n_sent > cap
            if capped:
                counts['capped'] = True
                # 只索引最新 cap 篇：按主键倒序走索引，无临时排序
                cur = c.execute(
                    'SELECT id,text,translation,source FROM sentences ORDER BY id DESC LIMIT ?',
                    (cap,))
            else:
                cur = c.execute('SELECT id,text,translation,source FROM sentences')
            # 课本链接关系小、一次性取全（句子→课本 归类用）
            bs = {}
            for r in c.execute('SELECT bs.sentence_id sid, bs.book_id bid, l.title lesson, b.title btitle '
                               'FROM book_sentences bs JOIN books b ON b.id=bs.book_id '
                               'LEFT JOIN book_lessons l ON l.id=bs.lesson_id'):
                bs.setdefault(r['sid'], []).append(dict(r))
            songs = c.execute('SELECT id,title,artist,lyrics FROM songs').fetchall()
            books = c.execute('SELECT id,title,author,level,note FROM books').fetchall()
            lessons = c.execute('SELECT l.id,l.book_id,l.title,b.title btitle FROM book_lessons l '
                                'JOIN books b ON b.id=l.book_id').fetchall()
        # —— 句子（课本链接优先，其次网络/手动语料）；流式游标，不整库 fetchall ——
        for r in cur:
            text = r['text'] or ''
            toks = _tokens(text)
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
            d = bm[ch].add(toks, meta)
            _bg = _bigrams(text)
            glen[ch].append(len(_bg))
            gp = gpost[ch]
            for _g in _bg:
                slot = gp.get(_g)
                if slot is None:
                    gp[_g] = array('l', [d])
                else:
                    slot.append(d)
            counts[ch] += 1
        # —— 歌词（逐行 + 歌名） ——
        for s in songs:
            title = s['title'] or ''
            if title:
                tbm.add(_tokens(title),
                        {'kind': 'song', 'id': s['id'], 'title': title, 'artist': s['artist'] or ''})
                counts['songs'] += 1
            for i, line in enumerate((s['lyrics'] or '').split('\n')):
                line = line.strip()
                if not line or ktv.is_latin_line(line):
                    continue
                lt = _tokens(line)
                meta = {'kind': 'line', 'id': s['id'], 'title': title,
                        'artist': s['artist'] or '', '_text': line, 'line_no': i}
                d = bm['lyric'].add(lt, meta)
                _bg = _bigrams(line)
                glen['lyric'].append(len(_bg))
                gp = gpost['lyric']
                for _g in _bg:
                    slot = gp.get(_g)
                    if slot is None:
                        gp[_g] = array('l', [d])
                    else:
                        slot.append(d)
                counts['lyric'] += 1
        # —— 课本（书名/备注/课名） ——
        for b in books:
            tbm.add(_tokens((b['title'] or '') + ' ' + (b['note'] or '')),
                    {'kind': 'book', 'id': b['id'], 'title': b['title'] or '',
                     'author': b['author'] or '', 'level': b['level'] or ''})
            counts['books'] += 1
        for l in lessons:
            if not l['title']:
                continue
            tbm.add(_tokens(l['title']),
                    {'kind': 'lesson', 'id': l['id'], 'book_id': l['book_id'],
                     'title': l['title'], 'book_title': l['btitle'] or ''})
        del songs, books, lessons, bs
        with self._lock:
            self._bm = bm
            self._tbm = tbm
            self._gpost = gpost
            self._glen = glen
            self._counts = counts
            self._qcache = {}      # 索引重建 → 查询缓存整体失效（防脏读）
            self._qorder = []
        try:
            import perf
            perf.trim_memory()     # 建库期间 array 扩容留下的 C 堆空洞归还系统
        except Exception:
            pass

    # ---------- 检索 ----------
    def _dice_scan(self, ch, qgrams, threshold, topk=40):
        """字符 bigram Dice 召回（防分词漏召回）——v26 查询侧倒排累计版。

        对每个**查询** bigram 扫一遍倒排表，把「与该文档共享的不同 bigram 数」
        累计到文档上，再按 Dice = 2·inter/(|q|+|d|) 打分。与旧的「每文档
        常驻 bigram 集合再求交」数学完全等价（查询 bigram 是集合、倒排表
        内文档号不重复，inter 即集合交大小），但不再为每篇文档存任何集合，
        内存从 O(语料×平均bigram数) 降为 O(倒排表)。
        """
        if not qgrams:
            return []
        post = self._gpost.get(ch) or {}
        glen = self._glen.get(ch) or array('l')
        inter = {}
        for g in qgrams:                      # set 去重后逐 bigram 累计
            ids = post.get(g)
            if not ids:
                continue
            for d in ids:
                inter[d] = inter.get(d, 0) + 1
        qn = len(qgrams)
        out = []
        for d, k in inter.items():
            dn = glen[d] if d < len(glen) else 0
            if not dn:
                continue
            dc = 2.0 * k / (qn + dn)
            if dc >= threshold:
                out.append((d, dc))
        out.sort(key=lambda x: -x[1])
        # 完整交集表一并返回：BM25 召回的候选也可能共享部分 bigram，
        # 精排要的是真实交集数，不能因为没进 Dice topk 就当 0。
        return out[:topk], inter

    def _qcache_get(self, ckey):
        with self._lock:
            hit = self._qcache.get(ckey)
            if hit is not None:
                try:
                    self._qorder.remove(ckey)
                except ValueError:
                    pass
                self._qorder.append(ckey)
            return hit

    def _qcache_put(self, ckey, value):
        with self._lock:
            if ckey in self._qcache:
                try:
                    self._qorder.remove(ckey)
                except ValueError:
                    pass
            self._qcache[ckey] = value
            self._qorder.append(ckey)
            while len(self._qorder) > self._QCACHE_MAX:
                old = self._qorder.pop(0)
                self._qcache.pop(old, None)

    def _rerank(self, qn, qn_len, qset_len, qgrams_len, bm_s, cov_hits, dice_hits,
                doc_glen, text_n):
        """综合分 ∈ [0,1]：0.40×BM25 + 0.20×Dice + 0.20×词元覆盖 + 0.20×短语包含。

        v26：不再传每文档的词元集合/bigram 集合（那是旧版吃内存的元凶），
        改传 recall 阶段顺带累计出的 cov_hits（命中了几个查询词元）与
        dice_hits（共享了几个查询 bigram），纯数值运算。
        """
        phrase = 1.0 if qn and qn_len <= len(text_n) and qn in text_n else 0.0
        cov = (cov_hits / qset_len) if qset_len and cov_hits else 0.0
        inter = dice_hits or 0
        dice = (2.0 * inter / (qgrams_len + doc_glen)) if qgrams_len and doc_glen and inter else 0.0
        s = 0.40 * bm_s + 0.20 * dice + 0.20 * cov + 0.20 * phrase
        if s > 0:
            tl = len(text_n)
            lr = min(qn_len, tl) / max(qn_len, tl, 1)
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
        # v18 查询 LRU：同查询+同参数+同数据签名 → 直接命中（ms≈0）
        # 不可变语料分片加入缓存签名；新增/删除分片后旧查询自动失效。
        try:
            shard_sig = tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                              for p in corpus_shards.SHARD_DIR.glob('corpus-*.db')))
        except OSError:
            shard_sig = ()
        ckey = (qn, limit, tuple(sources or []), per_song, per_book,
                min_score, min_affinity, tuple(sorted(selected_books)), sort,
                self._stamp, shard_sig)
        _hit = self._qcache_get(ckey)
        if _hit is not None:
            _hit = dict(_hit)
            _meta = dict(_hit.get('meta') or {})
            _meta['ms'] = 0
            _meta['cached'] = True
            _hit['meta'] = _meta
            return _hit
        with self._lock:
            bm = self._bm
            gpost = self._gpost
            glen = self._glen
            counts = dict(self._counts)
        capped = bool(counts.pop('capped', False))
        # v19: 预计算查询侧常量（避免精排循环内重复计算）
        qn_len = len(qn)
        qgrams_len = len(qgrams)
        qset_len = len(qset)
        t_recall = time.time()
        # 1) 双路召回（BM25 + Dice）→ 2) 精排
        # v26：覆盖度与 Dice 交集数在召回阶段由倒排扫描顺带累计（见 _BM25.search
        # 的 cov 参数与 _dice_scan 的 inter 表），精排不再需要每文档集合。
        scored = {c: [] for c in CHANNELS}
        for ch in CHANNELS:
            if ch not in enabled_set:
                continue
            cov = {}                                  # doc -> 命中的查询词元数
            cand = {}
            for s, d in bm[ch].search(qtoks, topk=max(limit * 4, 40), cov=cov):
                cand[d] = s
            th = min(0.14, max(0.10, min_affinity or 0.14))
            dice_top, dice_inter = self._dice_scan(ch, qgrams, th)
            for d, _dc in dice_top:
                if d not in cand:
                    cand[d] = 0.0
            _bm_docs = bm[ch].docs
            _glen_ch = glen.get(ch) or array('l')
            _norm_cache = {}
            for d, bm_s in cand.items():
                m = _bm_docs[d] if d < len(_bm_docs) else None
                if not m:
                    continue
                if ch == 'textbook' and selected_books:
                    bid = m.get('book_id') or m.get('id')
                    if bid not in selected_books:
                        continue
                text_n = _norm_cache.get(d)
                if text_n is None:
                    text_n = normalize(m.get('_text') or m.get('title') or '')
                    _norm_cache[d] = text_n
                s = self._rerank(qn, qn_len, qset_len, qgrams_len, bm_s,
                                 cov.get(d, 0), dice_inter.get(d, 0),
                                 _glen_ch[d] if d < len(_glen_ch) else 0, text_n)
                if ch == 'textbook' and selected_books and (m.get('book_id') in selected_books):
                    s = min(1.0, s + 0.08)
                if s >= 0.10:
                    scored[ch].append((s, d))
            scored[ch].sort(key=lambda x: -x[0])
        t_rerank = time.time()
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
        # 统一列表（results）：标题命中参与同一套排序 —— 既尊重用户指定的来源优先级，
        # 又保留「最强意图信号」：在 sort='score'（纯相关性）下高分自然置顶；
        # 在 sort='priority'（默认）下作为其所属通道的成员参与来源分档，
        # 同来源内凭高分排在该来源最前，不会被排到用户指定来源之前。
        _pri_idx = {c: pri.index(c) for c in pri}
        _thr = lambda r: (max(min_affinity, 0.0) if r['channel'] == 'lyric' else min_score)
        kept = [r for r in unified if r['score'] >= _thr(r)]
        for t in top_songs + top_books:
            t.setdefault('rank', t['score'])
        pool_all = kept + top_songs + top_books
        if sort == 'score':
            ordered = sorted(pool_all, key=lambda r: (-r['rank'], _pri_idx.get(r['channel'], len(pri)),
                                                      -len(r.get('text') or '')))
        else:
            ordered = sorted(pool_all, key=lambda r: (_pri_idx.get(r['channel'], len(pri)),
                                                      -r['score'], -len(r.get('text') or '')))
        results = ordered
        t_done = time.time()
        meta = {'counts': counts, 'terms': key_terms(q), 'qvars': qv,
                'index': {'capped': capped},
                'prior': pri, 'qnorm': qn, 'sort': sort, 'ms': round((t_done - t0) * 1000),
                'book_ids': sorted(selected_books),
                'hits': {'lyric': len(groups['lyric']), 'textbook': len(groups['textbook']),
                         'web': len(groups['web'])},
                'timing': {'recall_ms': round((t_recall - t0) * 1000),
                           'rerank_ms': round((t_rerank - t_recall) * 1000),
                           'merge_ms': round((t_done - t_rerank) * 1000)}}
        # 6) 大型只读分片按需召回，不把数百万文档常驻内存。作为 web 通道参与
        # 统一去重与排序；kanji.db 中已有同文时保留可编辑的主库版本。
        # v25：这一步此前不计入 meta.timing/meta.ms——分片全表扫描一旦变慢
        # （分片多、或分片存放在对象存储/网络盘上），前端进度条会一直停在
        # 「精排」而看不出真实耗时在哪；现在显式记录 shard_ms 并把它计入总 ms，
        # 同时受 federated_search.SHARD_BUDGET_S 墙钟预算保护，不会无界拖长。
        t_shard0 = time.time()
        if 'web' in enabled_set and shard_sig:
            try:
                fed = federated_search.search(q, limit=max(limit * 3, 30),
                                              include_primary=False, include_shards=True)
                existing_text = {r.get('text') for r in results}
                shard_rows = []
                for x in fed.get('rows', []):
                    if not x.get('text') or x['text'] in existing_text:
                        continue
                    existing_text.add(x['text'])
                    sr = {'type':'web','channel':'web','kind':'sentence','id':None,
                          'uid':x.get('uid'),'title':x.get('source') or '开放语料分片',
                          'text':x['text'],'translation':x.get('translation') or '',
                          'score':x.get('score',0),'rank':x.get('score',0),
                          'source':x.get('source'),'url':x.get('url'),
                          'license':x.get('license'),'attribution':x.get('attribution'),
                          'read_only':True,'storage':'shard'}
                    if sr['score'] >= max(.08, min_score): shard_rows.append(sr)
                groups['web'].extend(shard_rows); rows.extend(shard_rows); results.extend(shard_rows)
                if sort == 'score': results.sort(key=lambda r:-r.get('rank',r.get('score',0)))
                else: results.sort(key=lambda r:(_pri_idx.get(r['channel'],len(pri)),
                                                  -r.get('score',0)))
                rows.sort(key=lambda r:-r.get('score',0))
                meta['shards']={'count':fed.get('shards',0),'hits':len(shard_rows),
                                'candidates':fed.get('total_candidates',0),
                                'timed_out':fed.get('shard_ms',0)>=federated_search.SHARD_BUDGET_S*1000}
                meta['hits']['web']=len(groups['web'])
            except Exception as exc:
                meta['shards']={'count':len(shard_sig),'hits':0,'error':str(exc)[:160]}
        meta['timing']['shard_ms'] = round((time.time() - t_shard0) * 1000)
        meta['ms'] = round((time.time() - t0) * 1000)     # 补上分片阶段耗时，ms 反映端到端真实总耗时
        resp = {'rows': rows[:max(limit, 1)],
                'lyrics': merged[:max(8, limit)],
                'results': results[:max(limit, 1)],
                'groups': groups, 'titles': titles, 'meta': meta}
        self._qcache_put(ckey, resp)
        return resp



# ---------------- 全库兼容索引（/api/rag/similar 用） ----------------
class RagIndex:
    """全库语料 BM25 检索；query() 接口与旧版（TF-IDF）一致：[(sid, score)]。

    v26：_BM25 改为自增文档号，payload 里带 sid；同样受内存预算约束，
    语料超预算时只索引最新 N 篇（对「找相似」场景，最新语料优先完全够用）。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._bm = _BM25()
        self._stamp = None

    def _build(self):
        """重建（必须在已持有 self._lock 时调用；新索引建好才原子换上）。"""
        import perf
        cap = perf.doc_cap(default=200000, env='KANJI_RAG_MAX_DOCS')
        bm = _BM25()
        with db.get_conn() as c:
            cnt = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
            if cnt > cap:
                cur = c.execute('SELECT id, text FROM sentences ORDER BY id DESC LIMIT ?',
                                (cap,))
            else:
                cur = c.execute('SELECT id, text FROM sentences')
            for r in cur:                       # 流式游标，不 fetchall
                bm.add(_tokens(r['text']), {'sid': r['id'], '_text': r['text']})
        self._bm = bm
        self._stamp = self._sig()
        try:
            import perf
            perf.trim_memory()
        except Exception:
            pass

    @staticmethod
    def _sig():
        with db.get_conn() as c:
            r = c.execute('SELECT COUNT(*) n, COALESCE(MAX(id),0) m FROM sentences').fetchone()
        return (r['n'], r['m'])

    def ensure(self):
        with self._lock:
            try:
                sig = self._sig()
            except Exception:
                return
            if sig != self._stamp:
                self._build()

    def query(self, text, limit=10, exclude_sid=None):
        self.ensure()
        docs = self._bm.docs
        hits = self._bm.search(_tokens(text), topk=limit + 2)
        out = []
        for s, d in hits:
            m = docs[d] if d < len(docs) else None
            sid = m.get('sid') if m else None
            if sid is None or sid == exclude_sid:
                continue
            out.append((sid, round(s, 4)))
            if len(out) >= limit:
                break
        return out


INDEX = RagIndex()
MULTI = MultiIndex()


def warmup():
    """同步预热（保留旧入口）：预构建多源索引，避免首个请求等待。"""
    try:
        MULTI.ensure()
    except Exception:
        pass


def warmup_async(delay=0.0, extra_steps=()):
    """后台预热 v26：单线程串行 + 内存闸门，绝不再三路并发抢 CPU/内存。

    旧行为的问题（用户可感知的「打开页面什么都卡」）：
      1. RAG、结构相似、听写联想三路预热线程启动即全速开跑，在单核
         云实例上等于三个 CPU 密集任务抢一个核，所有页面请求都在排队；
      2. 每路都在建巨型 Python 对象索引，2 万句语料 ~1.4GB RSS，
         Render 512MB 直接 OOM 杀进程 → 重启 → 再预热 → 再 OOM 死循环。
    新行为：
      - 只有 RAG 联邦索引与 RagIndex 预热（紧凑重写后两者共几十 MB、
        几秒内建完）；结构相似索引改为首个查询惰性构建；听写联想索引
        默认随「输入联想」功能一起关闭（见 listening.suggest_enabled）；
      - KANJI_WARMUP=off 或可用内存 < 220MB（perf.warmup_allowed）时
        完全跳过，全部惰性构建，宁可第一个用户多等几秒也不 OOM；
      - 分片倒排低频轮询保留（无分片时零开销），不再与建索引抢跑。
    """
    def _run():
        try:
            if delay:
                time.sleep(delay)
        except Exception:
            pass
        for name, fn in extra_steps:
            if not _warmup_gate():
                return
            try:
                fn()
            except Exception as e:
                try:
                    print('[rag] 预热步骤 %s 失败（不影响启动）：%s' % (name, e))
                except Exception:
                    pass
        if not _warmup_gate():
            return
        try:
            MULTI.ensure()
        except Exception:
            pass
        if not _warmup_gate():
            return
        try:
            INDEX.ensure()
        except Exception:
            pass
        while True:
            try:
                built = federated_search.warm_shard_indices(budget_s=2.0, max_shards=4)
            except Exception:
                built = 0
            time.sleep(0.5 if built else 30.0)

    def _warmup_gate():
        try:
            import perf
            return perf.warmup_allowed()
        except Exception:
            return True

    threading.Thread(target=_run, daemon=True, name='rag-warmup').start()

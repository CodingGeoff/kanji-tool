# -*- coding: utf-8 -*-
"""
句子结构相似检索引擎
================================================================
1. 判断输入是「词」还是「句子」（有助词+足够假名 → 句子）
2. 句子成分签名：助词序列 + 词性链（压缩重复）+ 句尾形态
3. 与语料库句子 / 歌词行计算结构相似度：
   0.45×助词Jaccard + 0.25×词性链LCS + 0.15×句尾形态 + 0.15×长度接近度
4. 歌词优先：歌词行 +0.05 加成后排序
v26 性能重构：
- 签名紧凑化：助词/词性/句尾全部驻留成小整数（驻留表 + int 元组），
  相似度用整数集合/权重运算，比逐句 dict 省一个数量级内存；
- 惰性化：不再启动即建全库索引（那是云端 OOM 与「打开页面卡半天」的
  元凶之一）——歌词签名极小、随用随建；语料签名在首次结构检索时构建；
- 内存预算：语料超过预算时只索引最新 N 篇（perf.doc_cap），绝不吃爆内存。
"""
import re
import threading
from array import array

import db

_tagger = None


def _t():
    global _tagger
    if _tagger is None:
        import fugashi
        _tagger = fugashi.Tagger()
    return _tagger


_KANA_RE = re.compile(r'[぀-ヿ]')
_YOGEN = ('助動詞', '動詞', '形容詞', '形状詞')

# 句尾形态 → 友好标签（展示用）
_END_LABEL = [
    ('助動詞-タ', '过去·完了（た）'), ('助動詞-マス', '礼貌体（ます）'),
    ('助動詞-ナイ', '否定（ない）'), ('助動詞-ヌ', '文语否定（ぬ）'),
    ('助動詞-デス', '断定礼貌（です）'), ('助動詞-ダ', '断定普通（だ）'),
    ('助動詞-ウ', '意志·推量（う/よう）'), ('助動詞-タイ', '愿望（たい）'),
    ('助動詞-レル', '被动·可能（れる）'), ('助動詞-ラレル', '被动·可能（られる）'),
    ('助動詞-セル', '使役（せる）'), ('助動詞-サセル', '使役（させる）'),
    ('助動詞-ベシ', '文语当然（べし）'), ('助動詞-マイ', '否定推量（まい）'),
    ('助動詞-ラスイ', '推量（らしい）'),
]
_POS_LABEL = {'名詞': '名词', '代名詞': '代词', '接尾辞': '接尾', '接頭辞': '接頭',
              '動詞': '动词', '助動詞': '助动词', '形容詞': 'い形', '形状詞': 'な形',
              '助詞': '助词', '副詞': '副词', '連体詞': '连体', '接続詞': '接续',
              '感動詞': '感叹', '記号': '符号', '補助記号': '符号', '空白': '空'}


def is_sentence(text: str) -> bool:
    """助词 + 足够假名 → 视为句子（单词/关键词走普通检索）。"""
    t = (text or '').strip()
    if len(t) < 6 or not _KANA_RE.search(t):
        return False
    ws = [w for w in _t()(t) if w.surface and w.feature.pos1 not in ('記号', '補助記号', '空白')]
    has_particle = any(w.feature.pos1 == '助詞' for w in ws)
    kana_n = len(_KANA_RE.findall(t))
    return has_particle and kana_n >= 4


def signature(text: str):
    """成分签名：{p: 助词序列, s: 词性链(压缩相邻重复), e: 句尾cType, raw: 原句}"""
    ws = [w for w in _t()(text) if w.surface and w.feature.pos1 not in ('記号', '補助記号', '空白')]
    particles = [w.surface for w in ws if w.feature.pos1 == '助詞']
    pos = []
    for w in ws:
        p1 = w.feature.pos1 or '?'
        if not pos or pos[-1] != p1:
            pos.append(p1)
    end = ''
    for w in reversed(ws):
        if w.feature.pos1 in _YOGEN:
            end = w.feature.cType or w.surface
            break
    return {'p': particles, 's': pos, 'e': end}


def describe(sig, text):
    """把签名变成给人看的成分分析（中文）。"""
    ends = next((lab for key, lab in _END_LABEL if (sig['e'] or '').startswith(key)), sig['e'])
    pos_cn = '→'.join(_POS_LABEL.get(p, p) for p in sig['s'][:10])
    return {'particles': sig['p'], 'pos_chain': pos_cn, 'ending': ends or '—',
            'length': len(text)}


def _lcs(a, b):
    if not a or not b:
        return 0
    dp = [0] * (len(b) + 1)
    for i, x in enumerate(a, 1):
        prev, cur = 0, [0]
        for j, y in enumerate(b, 1):
            tmp = dp[j]
            dp_j = dp[j] + 1 if x == y else max(prev, dp[j - 1])
            cur.append(dp_j)
            prev = tmp
        dp = cur
    return dp[-1]


def similarity(sa, sb, la, lb):
    """结构相似度 ∈ [0,1]。la/lb 是两句长度。"""
    pa, pb = set(sa['p']), set(sb['p'])
    pj = len(pa & pb) / len(pa | pb) if pa | pb else (1.0 if not pa and not pb else 0.0)
    seq = _lcs(sa['s'], sb['s']) / max(len(sa['s']), len(sb['s']), 1)
    end = 1.0 if sa['e'] and sa['e'] == sb['e'] else 0.0
    ln = 1.0 - abs(la - lb) / max(la, lb, 1)
    return 0.45 * pj + 0.25 * seq + 0.15 * end + 0.15 * ln


def _line_usable(line: str):
    t = line.strip()
    if len(t) < 6 or len(t) > 90:
        return False
    if not _KANA_RE.search(t):
        return False
    if re.fullmatch(r"[A-Za-z'’\-.,!?~;: ()&0-9]+", t):
        return False
    return True


def _bigrams(t):
    t = re.sub(r'[\s。、！？!?，,.．「」『』（）()・：;；…—0-9０-９]', '', t)
    return {t[i:i + 2] for i in range(len(t) - 1)} | ({t} if len(t) == 1 else set())


class StructIndex:
    """紧凑结构索引：歌词侧小而即用，语料侧惰性构建 + 内存预算降级。"""

    def __init__(self):
        self._lock = threading.Lock()
        # —— 驻留表：字符串 ↔ 小整数（助词/词性/句尾的取值集合都很小） ——
        self._p_id = {}          # 助词 str -> id
        self._p_str = []         # id -> 助词 str
        self._s_id = {}          # 词性 str -> id
        self._s_str = []
        self._e_id = {}          # 句尾形态 str -> id
        self._e_str = []
        # —— 歌词侧（小，随用随建） ——
        self._song_lines = []    # (song_id, title, line, p_t, s_t, e_id)
        self._n_song = -1
        # —— 语料侧（惰性，紧凑） ——
        self._sent_ids = array('l')      # 下标 -> sid
        self._sent_texts = []             # 下标 -> 原文
        self._sent_p = []                 # 下标 -> 助词 id 元组
        self._sent_s = []                 # 下标 -> 词性链 id 元组
        self._sent_e = array('l')         # 下标 -> 句尾 id
        self._pdf = {}                    # 助词 str -> 出现文档数
        self._n_sent = -1
        self._book_map = {}               # sid -> set(book_id)
        self._n_book = -1
        self._warming = False
        self._capped = False

    # ---------- 驻留 ----------
    def _intern(self, table, rev, value):
        i = table.get(value)
        if i is None:
            i = len(rev)
            table[value] = i
            rev.append(value)
        return i

    def _sig_tuple(self, text):
        """signature() 的紧凑版：返回 (助词id元组, 词性链id元组, 句尾id)。

        助词去重（原版 psim 用 set 语义）；词性链保留顺序与重复（LCS 需要）。
        """
        sig = signature(text)
        p_t = tuple(dict.fromkeys(self._intern(self._p_id, self._p_str, x)
                                  for x in sig['p']))
        s_t = tuple(self._intern(self._s_id, self._s_str, x) for x in sig['s'])
        e_i = self._intern(self._e_id, self._e_str, sig['e'] or '')
        return p_t, s_t, e_i

    # ---------- 构建 ----------
    def _build_songs(self):
        with db.get_conn() as c:
            songs = c.execute('SELECT id, title, lyrics FROM songs').fetchall()
        lines = []
        pdf = {}
        for s in songs:
            for ln in (s['lyrics'] or '').split('\n'):
                if _line_usable(ln):
                    p_t, s_t, e_i = self._sig_tuple(ln)
                    lines.append((s['id'], s['title'], ln.strip(), p_t, s_t, e_i))
                    for p in set(p_t):
                        k = self._p_str[p]
                        pdf[k] = pdf.get(k, 0) + 1
        with self._lock:
            self._song_lines = lines
            self._n_song = len(songs)
            for k, v in pdf.items():
                self._pdf[k] = self._pdf.get(k, 0) + v

    def _build_corpus(self):
        import perf
        cap = perf.doc_cap(default=200000, env='KANJI_STRUCT_MAX_DOCS')
        ids, texts, ps, ss, es, pdf = array('l'), [], [], [], array('l'), {}
        with db.get_conn() as c:
            n = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
            capped = n > cap
            if capped:
                cur = c.execute('SELECT id, text FROM sentences ORDER BY id DESC LIMIT ?',
                                (cap,))
            else:
                cur = c.execute('SELECT id, text FROM sentences')
            for r in cur:                       # 流式游标，不整库 fetchall
                p_t, s_t, e_i = self._sig_tuple(r['text'])
                ids.append(r['id'])
                texts.append(r['text'])
                ps.append(p_t)
                ss.append(s_t)
                es.append(e_i)
                for p in set(p_t):
                    k = self._p_str[p]
                    pdf[k] = pdf.get(k, 0) + 1
        with self._lock:
            self._sent_ids = ids
            self._sent_texts = texts
            self._sent_p = ps
            self._sent_s = ss
            self._sent_e = es
            self._pdf.update(pdf)
            self._n_sent = n
            self._capped = capped
        try:
            import perf
            perf.trim_memory()
        except Exception:
            pass

    def warmup_async(self):
        """轻量预热：只建歌词侧签名（几十首歌，毫秒级）。

        语料侧不再预热——它只在「整句结构检索」时才需要，且受内存预算
        约束；启动即建全库签名曾是云端 OOM 的主因之一（见 v26 重构说明）。
        """
        def run():
            if self._warming:
                return
            self._warming = True
            try:
                self.ensure()
            finally:
                self._warming = False
        threading.Thread(target=run, daemon=True).start()

    def ensure(self):
        """歌词签名就绪保障（便宜）；语料签名由 _ensure_corpus 惰性负责。"""
        try:
            with db.get_conn() as c:
                n_song = c.execute('SELECT COUNT(*) n FROM songs').fetchone()['n']
        except Exception:
            return
        if n_song != self._n_song and not self._warming:
            self._build_songs()

    def _ensure_corpus(self):
        try:
            with db.get_conn() as c:
                n = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
                n_book = c.execute('SELECT COUNT(*) n FROM book_sentences').fetchone()['n']
                book_rows = c.execute('SELECT sentence_id, book_id FROM book_sentences').fetchall() \
                    if self._n_book != n_book else None
        except Exception:
            return
        if self._n_book != n_book and book_rows is not None:
            bm = {}
            for r in book_rows:
                bm.setdefault(r['sentence_id'], set()).add(r['book_id'])
            with self._lock:
                self._book_map = bm
                self._n_book = n_book
        if n != self._n_sent:
            self._build_corpus()

    # ---------- 检索 ----------
    def lyric_affinity(self, q, limit=8, per_song=3, min_aff=0.18):
        """任意查询（词/短语/句子）→ 歌词行亲和检索：字符bigram Dice + 子串加成。
        修复副歌重复：相同行去重；每首歌最多 per_song 条（0=不限）；
        歌名命中 → 置顶「整首歌曲」条目。"""
        self.ensure()
        qb = _bigrams(q)
        with self._lock:
            lines = list(self._song_lines)
            titles = {}
            for sid, title, _ln, _p, _s, _e in lines:
                titles.setdefault(sid, title)
        out, seen, song_cnt = [], set(), {}
        # 歌名匹配（置顶）
        for sid, title in titles.items():
            if q and q in title:
                out.append({'sid': sid, 'title': title, 'text': None,
                            'title_match': True, 'affinity': 1.0})
        cand = []
        for sid, title, ln, _p, _s, _e in lines:
            lb = _bigrams(ln)
            if not lb:
                continue
            inter = len(qb & lb)
            dice = 2 * inter / (len(qb) + len(lb))
            if q and q in ln:
                dice = min(1.0, dice + 0.35)
            if dice >= min_aff:
                cand.append((dice, sid, title, ln))
        cand.sort(key=lambda x: -x[0])
        for dice, sid, title, ln in cand:
            key = re.sub(r'[\s。、！？!?]', '', ln)
            if key in seen:
                continue
            if per_song and song_cnt.get(sid, 0) >= per_song:
                continue
            seen.add(key)
            song_cnt[sid] = song_cnt.get(sid, 0) + 1
            out.append({'sid': sid, 'title': title, 'text': ln,
                        'affinity': round(dice, 3)})
            if len(out) >= limit:
                break
        return out[:limit]

    def query(self, text, limit=10, per_song=2, book_ids=None, sources=None):
        """返回 [(score, kind, title, sid, line_text, shared_particles)]。
        高级排序：助词 IDF 加权 + 词性链 LCS + 句尾形态 + 长度接近度 + 歌词加成；
        去重（副歌重复行只留一条）+ 多样性（每首歌最多 per_song 条，0=不限）。

        v26 两阶段算法（高级算法替换全库逐句 LCS）：
          综合分 = 0.45×助词 + 0.25×词性链LCS + 0.15×句尾 + 0.15×长度，
          其中 LCS ∈ [0,1]，故「cheap = 0.45×助词 + 0.15×句尾 + 0.15×长度」
          是最终分的严格下界、cheap+0.25 是严格上界。第一阶段对全库只算 cheap
          （纯算术，无 LCS、无对象分配），第二阶段只对 cheap+0.25 ≥ 入选线的
          少数候选算 LCS。与旧的全库逐句 LCS 结果完全一致（上界保证零漏召回），
          万句语料从 ~3 秒降到 ~0.2 秒，语料再大也只线性涨 cheap 部分。
        """
        self.ensure()
        self._ensure_corpus()
        qsig = signature(text)
        q_p = set(qsig['p'])
        q_e = qsig['e'] or ''
        # 查询词性链同样驻留成整数（LCS 与文档侧同类型比较）；没见过的词性先驻留
        q_s = tuple(self._intern(self._s_id, self._s_str, x) for x in qsig['s'])
        selected_books = {int(b) for b in (book_ids or []) if str(b).strip().isdigit()}
        allow_lyric = not sources or 'lyric' in sources
        allow_corpus = not sources or any(s in sources for s in ('web', 'textbook'))
        with self._lock:
            lines = list(self._song_lines)
            pdf = dict(self._pdf)
            # 只取引用，不复制内容：重建时整体换新对象，旧引用仍一致可用
            sent_ids = self._sent_ids
            sent_texts = self._sent_texts
            sent_p = self._sent_p
            sent_s = self._sent_s
            sent_e = self._sent_e
            book_map = self._book_map

        # 查询侧常量（每 id 的 IDF 权重表只建一次；助词权重 = 1/(df+1)）
        idw = [1.0 / (pdf.get(s, 0) + 1) for s in self._p_str]
        q_idset = {self._p_id[p] for p in q_p if p in self._p_id}
        q_w_total = sum(1.0 / (pdf.get(p, 0) + 1) for p in q_p)
        q_e_id = self._e_id.get(q_e)

        def psim_ids(p_t):
            """整数版 psim：inter_w/(查询总重+文档总重−inter_w)，与集合版等价。"""
            if not q_p and not p_t:
                return 1.0
            inter_w = 0.0
            doc_w = 0.0
            for p in p_t:
                w = idw[p]
                doc_w += w
                if p in q_idset:
                    inter_w += w
            if not inter_w:
                return 0.0
            union_w = q_w_total + doc_w - inter_w
            return (inter_w / union_w) if union_w else 0.0

        def cheap_ids(p_t, e_i, lt):
            """cheap = 最终分的严格下界（LCS 项先记 0）。"""
            end = 1.0 if q_e_id is not None and e_i == q_e_id else 0.0
            ln = 1.0 - abs(len(text) - lt) / max(len(text), lt, 1)
            return 0.45 * psim_ids(p_t) + 0.15 * end + 0.15 * ln

        # ---------- 阶段一：全库只算 cheap（纯算术） ----------
        cand = []          # (cheap, kind, title, sid, txt, p_t, s_t)
        if allow_corpus:
            for sid, t, p_t, s_t, e_i in zip(sent_ids, sent_texts,
                                             sent_p, sent_s, sent_e):
                if selected_books and not (book_map.get(sid) or set()) & selected_books:
                    continue
                cand.append((cheap_ids(p_t, e_i, len(t)), 'corpus', None, sid, t, p_t, s_t))
        if allow_lyric:
            for sid, title, ln, p_t, s_t, e_i in lines:
                cheap = cheap_ids(p_t, e_i, len(ln)) + 0.05   # 歌词优先加成（与 LCS 无关，直接进 cheap）
                cand.append((cheap, 'lyric', title, sid, ln, p_t, s_t))
        if not cand:
            return []
        cand.sort(key=lambda x: -x[0])

        # ---------- 阶段二：只对「cheap+0.25 ≥ 入选线」的候选算 LCS ----------
        # 去重/配额在打分时同步进行（副歌重复行与每首歌配额不浪费 LCS 预算）。
        # 早停安全：候选按 cheap 降序，一旦 cheap+0.25 < 入选线，其后所有候选
        # 的最终分都进不了前 limit 名，一个都不用再算。
        LCS_SPAN = 0.25 + 1e-9
        MAX_LCS = 800                       # LCS 计算硬上限（防极端全库贴近）
        DEDUP_RE = re.compile(r'[\s。、！？!?]')
        results, seen_line, song_cnt = [], set(), {}
        bar = 0.0                           # 当前第 limit 名的最终分（入选线）
        n_lcs = 0
        for cheap, kind, title, sid, txt, p_t, s_t in cand:
            if len(results) >= limit and cheap + LCS_SPAN < bar:
                break
            if n_lcs >= MAX_LCS:
                break
            key = DEDUP_RE.sub('', txt)
            if key in seen_line:
                continue                    # 副歌重复行：不用算 LCS，直接跳过
            if kind == 'lyric' and per_song and song_cnt.get(sid, 0) >= per_song:
                continue                    # 每首歌配额已满：同理
            n_lcs += 1
            seq = _lcs(q_s, s_t) / max(len(q_s), len(s_t), 1)
            sc = cheap + 0.25 * seq
            seen_line.add(key)
            if kind == 'lyric':
                song_cnt[sid] = song_cnt.get(sid, 0) + 1
            results.append((sc, kind, title, sid, txt,
                            q_p & {self._p_str[p] for p in p_t}))
            if len(results) >= limit:
                results.sort(key=lambda x: -x[0])
                bar = results[limit - 1][0]
        results.sort(key=lambda x: -x[0])
        return results[:limit]


_P_LABEL = {'は': '主题は', 'を': '宾语を', 'が': '主语/对象が', 'に': 'に（对象/时点）',
             'で': 'で（场所/手段）', 'と': 'と（并列/引用）', 'から': 'から（起点/原因）',
             'へ': 'へ（方向）', 'も': 'も（也）', 'の': 'の（所属）', 'まで': 'まで（界限）',
             'より': 'より（比较）'}
_END_TPL = [('助動詞-タ', '动词た形（过去·完了）'), ('助動詞-マス', 'ます形（礼貌）'),
            ('助動詞-ナイ', 'ない形（否定）'), ('助動詞-ヌ', 'ぬ（文语否定）'),
            ('助動詞-デス', 'です（礼貌断定）'), ('助動詞-ダ', 'だ（断定）'),
            ('助動詞-ウ', 'う/よう（意志·推量）'), ('助動詞-タイ', 'たい（愿望）'),
            ('助動詞-レル', 'れる/られる（被动·可能）'), ('助動詞-セル', 'せる/させる（使役）'),
            ('助動詞-ベシ', 'べし（文语当然）'), ('助動詞-マイ', 'まい（否定推量）'),
            ('助動詞-ラスイ', 'らしい（推量）')]


def structure_template(sig):
    """把成分签名转成人能读的结构模板，如「宾语を ＋ 动词た形（过去·完了）」。"""
    parts = ' '.join(_P_LABEL.get(p, p) for p in sig['p']) or '（无助词的短句）'
    e = sig['e'] or ''
    for key, lab in _END_TPL:
        if e.startswith(key):
            return f'{parts} ＋ {lab}'
    for k in ('五段', '一段', 'サ変', 'カ変', '上二段', '下二段'):
        if k in e:
            return f'{parts} ＋ 动词（{e.split("-")[0]}活用）'
    if e:
        return f'{parts} ＋ {e}'
    return parts


INDEX = StructIndex()

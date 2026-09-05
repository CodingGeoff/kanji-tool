# -*- coding: utf-8 -*-
"""
句子结构相似检索引擎
================================================================
1. 判断输入是「词」还是「句子」（有助词+足够假名 → 句子）
2. 句子成分签名：助词序列 + 词性链（压缩重复）+ 句尾形态
3. 与语料库句子 / 歌词行计算结构相似度：
   0.45×助词Jaccard + 0.25×词性链LCS + 0.15×句尾形态 + 0.15×长度接近度
4. 歌词优先：歌词行 +0.05 加成后排序
索引全内存，后台线程预热，语料/歌词增长时自动增量重建。
"""
import re
import threading

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
    def __init__(self):
        self._lock = threading.Lock()
        self._sents = {}      # sid -> (text, sig)
        self._song_lines = []  # (song_id, title, line, sig)
        self._n_sent = -1
        self._n_song = -1
        self._warming = False

    def _collect(self):
        with db.get_conn() as c:
            rows = c.execute('SELECT id, text FROM sentences').fetchall()
            songs = c.execute('SELECT id, title, lyrics FROM songs').fetchall()
        return rows, songs

    def _build(self):
        rows, songs = self._collect()
        sents = {}
        for r in rows:
            sents[r['id']] = (r['text'], signature(r['text']))
        lines = []
        for s in songs:
            for ln in (s['lyrics'] or '').split('\n'):
                if _line_usable(ln):
                    lines.append((s['id'], s['title'], ln.strip(), signature(ln)))
        with self._lock:
            self._sents = sents
            self._song_lines = lines
            self._n_sent = len(rows)
            self._n_song = len(songs)

    def warmup_async(self):
        def run():
            if self._warming:
                return
            self._warming = True
            try:
                self._build()
            finally:
                self._warming = False
        threading.Thread(target=run, daemon=True).start()

    def ensure(self):
        rows, songs = self._collect()
        with self._lock:
            up2date = len(rows) == self._n_sent and len(songs) == self._n_song
        if not up2date and not self._warming:
            self._build()

    def lyric_affinity(self, q, limit=8):
        """任意查询（词/短语/句子）→ 歌词行亲和检索：字符bigram Dice + 子串加成。"""
        self.ensure()
        qb = _bigrams(q)
        with self._lock:
            lines = list(self._song_lines)
        out = []
        for sid, title, ln, _sig in lines:
            lb = _bigrams(ln)
            if not lb:
                continue
            inter = len(qb & lb)
            dice = 2 * inter / (len(qb) + len(lb))
            if q in ln:
                dice = min(1.0, dice + 0.35)
            if dice >= 0.18:
                out.append({'sid': sid, 'title': title, 'text': ln,
                            'affinity': round(dice, 3)})
        out.sort(key=lambda x: -x['affinity'])
        return out[:limit]

    def query(self, text, limit=10):
        """返回 [(score, kind, title, line_text, shared_particles)]，歌词加成后排序。"""
        self.ensure()
        sig = signature(text)
        out = []
        with self._lock:
            sents = list(self._sents.values())
            lines = list(self._song_lines)
        for t, s in sents:
            sc = similarity(sig, s, len(text), len(t))
            out.append((sc, 'corpus', None, t, set(sig['p']) & set(s['p'])))
        for sid, title, ln, s in lines:
            sc = similarity(sig, s, len(text), len(ln)) + 0.05   # 歌词优先
            out.append((sc, 'lyric', title, ln, set(sig['p']) & set(s['p'])))
        out.sort(key=lambda x: -x[0])
        return out[:limit]


INDEX = StructIndex()

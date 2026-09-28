# -*- coding: utf-8 -*-
"""篇章精读（v22）：把「一整篇长日语文章」变成一套可客观判分的阅读训练题
================================================================
设计底线（与 listening.py 同一套诚实原则）
----------------------------------------------------------------
本模块**不理解**文章在说什么。它只做两件规则引擎真正能做对的事：

  1. 把原文的某个成分挖掉，让你凭上下文把它**还原**成原文本来的样子
     —— 答案 = 原文，客观性 100%，不存在"出题人觉得"。
  2. 对原文做一次**有形态学/句法证据的改写**，使改写句与原文所断言的命题
     直接矛盾（极性翻转、数值替换、格成分互换）
     —— "与本文不一致"是可判定的，不是主观印象。

凡是需要"读懂意思"才能判对错的题（主旨概括、作者态度、推论、
段落小标题、同义改写判断），本模块一律**不生成**，理由见文末
"已被否决的题型"。那条路走 ai_item_writer.py（LLM 起草 + 人工复核）。

每道题都带 evidence（判定依据）与 objectivity（客观性类别）：
  - verbatim      ：答案就是原文原样，其余选项原文中不存在
  - contradiction ：错误项与原文某句显式矛盾（附矛盾点）
  - rule          ：答案由一条写死的、可复核的规则唯一确定（附规则名）
生成阶段凑不齐 evidence 的候选直接丢弃，宁可少出题，不出冤假错案。

题型一览（11 种，详见 DISCOURSE.md）
----------------------------------------------------------------
  connective     接续词还原（篇章逻辑：逆接/顺接/例示/换言/对比…）
  anaphora       指示语照应还原（「その＿＿」指回前文哪个名词）
  particle       格助词还原（带语料零实证门禁）
  polite_tense   文体×时制 2×2（敬体/简体 与 过去/非过去 的四格）
  insert         句子还原插入（把抽掉的一句放回唯一正确的位置）
  order          语序重排（3–4 句，规则可证明排列唯一）
  truth          内容一致判定（同一句的原文 vs 三种矛盾改写）
  fact           数值·专有名词检索（扫读定位）
  quote          引语话者判定（句法规则唯一确定）
  absent         本文未出现词判别（扫读，绝对客观）
  headword       复现词链（全篇出现最多的实词还原）
"""
import json
import random
import re
import time
from collections import Counter, defaultdict

import db

try:
    from sentence_builder import _tagger as _sb_tagger
except Exception:      # pragma: no cover - 词法分析器缺失时整个模块降级
    _sb_tagger = None

# ================================================================
# 0. 存储层
# ================================================================
DDL = '''
CREATE TABLE IF NOT EXISTS passages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT DEFAULT '',
    level TEXT DEFAULT '',
    note TEXT DEFAULT '',
    text TEXT NOT NULL,
    n_para INTEGER DEFAULT 0,
    n_sent INTEGER DEFAULT 0,
    n_char INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_passages_title ON passages(title);
CREATE TABLE IF NOT EXISTS passage_sents(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id INTEGER NOT NULL,
    para_idx INTEGER DEFAULT 0,
    idx INTEGER DEFAULT 0,
    text TEXT NOT NULL,
    kind TEXT DEFAULT 'body'
);
CREATE INDEX IF NOT EXISTS idx_psents ON passage_sents(passage_id, idx);
CREATE TABLE IF NOT EXISTS passage_results(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    passage_id INTEGER,
    qtype TEXT,
    ok INTEGER,
    peeked INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_presults ON passage_results(ts);
'''


def init():
    with db.get_conn() as c:
        c.executescript(DDL)
        # 老库补列（幂等）
        for ddl in ("ALTER TABLE passage_sents ADD COLUMN kind TEXT DEFAULT 'body'",
                    'ALTER TABLE passage_results ADD COLUMN peeked INTEGER DEFAULT 0',
                    'ALTER TABLE passages ADD COLUMN corpus_sids TEXT'):
            try:
                c.execute(ddl)
            except Exception:
                pass


_SENT_END_RE = re.compile(r'(?<=[。！？!?])')
_MIN_SENT = 6

# 网页复制常见的样板行（分享按钮、栏目标签、时间戳、广告位）——一律剔除，
# 它们既不是文章内容，混进语料还会污染「本文に出てこない語」这类题。
_BOILER_RE = re.compile(
    r'^\s*(シェアする|共有する|この記事をシェア|関連ニュース|関連記事|もっと見る|'
    r'あわせて読みたい|スポンサーリンク|広告|PR|Twitter|Facebook|LINE|はてな|'
    r'メールで送る|印刷する|コメント|目次|トップページ|NHKニュース|'
    r'ページの先頭へ戻る|前の記事|次の記事)\s*$')
# 纯时间戳行 / 行尾时间戳
_TS_RE = re.compile(r'^\s*\d{4}年\s*\d{1,2}月\s*\d{1,2}日\s*(\d{1,2}[:：]\d{2})?\s*$')
_TS_TAIL_RE = re.compile(r'\s*\d{4}年\s*\d{1,2}月\s*\d{1,2}日\s+\d{1,2}[:：]\d{2}\s*$')
_BULLET_RE = re.compile(r'^\s*[▽▼◆◇■□●○・*\-‐–—　]+\s*')
_SENT_FINAL = '。！？!?…'


def normalize(text):
    t = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    t = t.replace('\u3000', ' ').replace('\ufeff', '')
    t = re.sub(r'[ \t]+\n', '\n', t)
    return t


def _clean_lines(text):
    """逐行清洗：剔除样板行/时间戳，剥掉行首项目符号，
    把被硬换行拆开的长句接回去。返回 [(line, is_blank)]。"""
    out = []
    for raw in normalize(text).split('\n'):
        ln = raw.strip()
        if not ln:
            out.append('')
            continue
        if _BOILER_RE.match(ln) or _TS_RE.match(ln):
            continue
        ln = _TS_TAIL_RE.sub('', ln).strip()      # 标题行尾巴上粘着的发布时间
        ln = _BULLET_RE.sub('', ln).strip()
        if not ln:
            continue
        # 上一行没写完（不以句末标点结尾且足够长）→ 这一行是它的续行
        if out and out[-1] and out[-1][-1] not in _SENT_FINAL and len(out[-1]) >= 25:
            out[-1] = out[-1] + ln
        else:
            out.append(ln)
    return out


def _is_heading(line):
    """小标题/栏目标签：没有句末标点、不太长、不以助词结尾的独立行。"""
    if not line or line[-1] in _SENT_FINAL:
        return False
    if len(line) > 44:
        return False
    return True


def split_paragraphs(text):
    """空行分段；返回 [[line, ...], ...]（保留行结构，标题行不与正文合并）。"""
    paras, cur = [], []
    for ln in _clean_lines(text):
        if not ln:
            if cur:
                paras.append(cur)
                cur = []
            continue
        cur.append(ln)
    if cur:
        paras.append(cur)
    return paras


def split_sentences(para):
    """段内切句：按句末标点切，保留标点；引号/括号内的句点不切。"""
    s, out, depth, buf = str(para or ''), [], 0, ''
    for ch in s:
        buf += ch
        if ch in '「『（(“':
            depth += 1
        elif ch in '」』）)”':
            depth = max(0, depth - 1)
        elif ch in '。！？!?' and depth == 0:
            out.append(buf.strip())
            buf = ''
    if buf.strip():
        out.append(buf.strip())
    return [x for x in out if len(x) >= 2]


def parse_text(text):
    """把任意粘贴文本解析成 [(para_idx, kind, sentence)]。
    kind：'heading'（小标题/栏目行，不参与大部分出题）或 'body'。
    对「一整篇报道」「几段话」「一段话」「一行字」都必须给出合理结果。"""
    rows, pi = [], 0
    for para in split_paragraphs(text):
        got = False
        for line in para:
            if _is_heading(line):
                rows.append((pi, 'heading', line))
                got = True
                continue
            for sent in split_sentences(line):
                rows.append((pi, 'body', sent))
                got = True
        if got:
            pi += 1
    return rows


# ================================================================
# 0.5 输入质量体检（语法 / 词汇 / 可用性）
# ================================================================
def quality_report(text_or_rows):
    """对录入文本做一次体检，在**录入前**就把问题摆出来：
      - 语法门禁未通过的句子（复用 grammar.check_sentence_grammar）
      - 疑似未切干净的超长句、疑似乱码/非日语行
      - 可用于出题的有效句数
    这是提示不是拦截：新闻体里大量「〜とみられる」「〜ということです」
    本来就会让保守的语法门禁报警，所以只报告、不阻止录入。"""
    rows = text_or_rows if isinstance(text_or_rows, list) else parse_text(text_or_rows)
    body = [(i, t) for i, (_, k, t) in enumerate(rows) if k == 'body']
    issues = []
    try:
        import grammar
        checker = grammar.check_sentence_grammar
    except Exception:
        checker = None
    for i, t in body:
        tags = []
        if len(t) > 160:
            tags.append('超长句（可能没切干净，或原文本身是长句）')
        if not re.search(r'[ぁ-んァ-ヶ一-龥]', t):
            tags.append('不含日语文字（可能是残留的界面文字）')
        if t.count('「') != t.count('」'):
            tags.append('引号不配对（可能复制时截断）')
        if checker:
            try:
                r = checker(t)
                if not r.get('ok', True):
                    msgs = [m for m in (r.get('issues') or r.get('errors') or [])
                            if not any(k in str(m) for k in
                                       ('随机', '拼接', 'ランダム'))]
                    # 「随机假名拼接」类判据是为了拦截生成式垃圾文本，
                    # 对「〜ということです」「〜とみられる」这种新闻体固定说法
                    # 会大量误报，这里不往用户面前报。
                    if msgs:
                        tags.append('语法门禁提示：' + '；'.join(str(m) for m in msgs[:2]))
            except Exception:
                pass
        if tags:
            issues.append({'idx': i, 'text': t[:60], 'tags': tags})
    return {'n_sent': len(body),
            'n_heading': sum(1 for _, k, _ in rows if k == 'heading'),
            'n_issue': len(issues), 'issues': issues[:20]}


# ================================================================
# 0.6 录入
# ================================================================
def import_passage(title, text, source='', level='', note='', to_corpus=False):
    """录入一篇文章。to_corpus=True 时同时并入语料库，
    这样组句/听力/挖空/RAG 立刻就能用上这篇文章的句子。"""
    init()
    text = normalize(text).strip()
    if not text:
        raise ValueError('正文为空')
    rows = parse_text(text)
    body = [r for r in rows if r[1] == 'body']
    if not body:
        raise ValueError('切不出任何句子（可能整篇都是标题行或界面文字）')
    if not title:
        head = next((t for _, k, t in rows if k == 'heading'), '')
        title = (head or body[0][2])[:40]
    n_para = len({r[0] for r in rows})
    now = time.time()
    with db.get_conn() as c:
        cur = c.execute(
            'INSERT INTO passages(title,source,level,note,text,n_para,n_sent,n_char,created_at,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?)',
            (title, source, level, note, text, n_para, len(body), len(text), now, now))
        pid = cur.lastrowid
        c.executemany(
            'INSERT INTO passage_sents(passage_id,para_idx,idx,text,kind) VALUES(?,?,?,?,?)',
            [(pid, pa, i, t, k) for i, (pa, k, t) in enumerate(rows)])
    added = add_to_corpus(pid) if to_corpus else 0
    db.log('passage_import', json.dumps(
        {'id': pid, 'title': title, 'sents': len(body), 'to_corpus': added},
        ensure_ascii=False))
    return {'id': pid, 'title': title, 'n_para': n_para, 'n_sent': len(body),
            'n_heading': len(rows) - len(body), 'n_char': len(text),
            'corpus_added': added}


def add_to_corpus(pid):
    """把篇章正文句并入 sentences 表（source='passage'），
    组句 / 听力 / 挖空 / 语料检索会自动把它们纳入题源。重复句自动跳过。"""
    p = get_passage(pid)
    if not p:
        return 0
    try:
        import corpus
        import furigana
    except Exception:
        return 0
    n = 0
    for s in p['sentences']:
        if s.get('kind') != 'body':
            continue
        t = s['text'].strip()
        if len(t) < 6 or len(t) > 160:
            continue
        try:
            t2, _ = corpus.repair_inline_furigana(t)
            t2, orig = corpus.modernize_old_kana(t2)
            toks = furigana.annotate(t2)
            kw = furigana.extract_kanji_words(toks)
            sid = db.add_sentence(t2, None, 'passage', None, toks, kw,
                                  orig_text=orig if orig else None)
            if sid:
                n += 1
        except Exception:
            continue
    return n


def list_passages():
    init()
    with db.get_conn() as c:
        rs = c.execute('SELECT id,title,source,level,note,n_para,n_sent,n_char,created_at'
                       ' FROM passages ORDER BY id DESC').fetchall()
    return [dict(r) for r in rs]


def get_passage(pid):
    init()
    with db.get_conn() as c:
        r = c.execute('SELECT * FROM passages WHERE id=?', (pid,)).fetchone()
        if not r:
            return None
        ss = c.execute('SELECT para_idx,idx,text,kind FROM passage_sents'
                       ' WHERE passage_id=? ORDER BY idx', (pid,)).fetchall()
    d = dict(r)
    d['sentences'] = [dict(x) for x in ss]
    return d


def delete_passage(pid):
    init()
    with db.get_conn() as c:
        c.execute('DELETE FROM passage_sents WHERE passage_id=?', (pid,))
        n = c.execute('DELETE FROM passages WHERE id=?', (pid,)).rowcount
    return bool(n)


# ================================================================
# 1. 形态素工具
# ================================================================
def _tok(w):
    f = w.feature
    return {'s': w.surface, 'p1': f.pos1, 'p2': f.pos2 or '', 'p3': f.pos3 or '',
            'lemma': f.lemma or w.surface, 'cf': f.cForm or '', 'ct': f.cType or ''}


_TAG_CACHE = {}


def tag(text):
    if _sb_tagger is None:
        return []
    if text not in _TAG_CACHE:
        if len(_TAG_CACHE) > 4000:
            _TAG_CACHE.clear()
        _TAG_CACHE[text] = [_tok(w) for w in _sb_tagger(text)]
    return _TAG_CACHE[text]


# 形式名詞・量词类：出现频繁但不承载话题信息，做干扰项/照应链都没有学习价值
_STOP_NOUN = {'こと', 'もの', 'ため', 'とき', 'ところ', 'よう', 'ほう', 'うち', 'なか',
              'あと', 'まえ', 'ひと', '人々', 'それ', 'これ', 'あれ', 'ここ', 'そこ',
              '場合', '自分', '今日', '昨日', '明日'}
_JUNK_RE = re.compile(r'[A-Za-z0-9０-９\-–—・,、。「」]')


def content_words(toks):
    """篇章题一律使用**表层形名词**（不是词典形）。
    理由：所有「本文に出てくる/出てこない」类判定都要能逐字核对，
    而 UniDic 的 lemma（因る / ページ-page / タナカ）在原文里根本不存在，
    用它出题必然产生冤假错案。动词/形容词会活用，同样不进入词表。"""
    out = []
    for t in toks:
        if t['p1'] != '名詞' or t['p2'] in ('数詞',):
            continue
        w = t['s']
        if len(w) < 2 or _JUNK_RE.search(w) or w in _STOP_NOUN:
            continue
        if t['p3'] in ('助数詞可能', '助数詞'):
            continue
        out.append(w)
    return out


def _is_person_like(w):
    return bool(re.search(r'(さん|くん|ちゃん|氏|先生|博士|教授|社長|部長|課長|記者|selector)$', w)) \
        or w in ('私', '僕', '俺', '彼', '彼女', '母', '父', '兄', '姉', '友達', '先生', '学生')


# ================================================================
# 2. 语料实证（格助词题的客观性门禁）
# ================================================================
_CORPUS_CACHE = {}


def corpus_count(sub):
    """语料库里包含该字符串的句子数；库不可用时返回 -1（表示无法取证）。"""
    if not sub:
        return 0
    if sub in _CORPUS_CACHE:
        return _CORPUS_CACHE[sub]
    try:
        with db.get_conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM sentences WHERE text LIKE ? ESCAPE '\\'",
                          ('%' + sub.replace('\\', '\\\\').replace('%', '\\%')
                           .replace('_', '\\_') + '%',)).fetchone()
        n = int(r['n'])
    except Exception:
        n = -1
    if len(_CORPUS_CACHE) > 3000:
        _CORPUS_CACHE.clear()
    _CORPUS_CACHE[sub] = n
    return n


# ================================================================
# 3. 接续词表
# ================================================================
CONJ = {
    'しかし': '逆接', 'だが': '逆接', 'ところが': '逆接', 'けれども': '逆接',
    'とはいえ': '逆接', 'しかしながら': '逆接',
    'だから': '順接', 'したがって': '順接', 'そのため': '順接', 'それで': '順接',
    'ゆえに': '順接', 'そこで': '順接',
    'そして': '添加', 'また': '添加', 'さらに': '添加', 'しかも': '添加', 'そのうえ': '添加',
    'たとえば': '例示', '例えば': '例示',
    'つまり': '換言', 'すなわち': '換言', '要するに': '換言',
    '一方': '対比', '逆に': '対比', 'これに対して': '対比', 'むしろ': '対比',
    'ところで': '転換', 'さて': '転換',
    'まず': '時間順序', '次に': '時間順序', 'その後': '時間順序', '最後に': '時間順序',
    'ただし': '補足', 'なお': '補足', 'ちなみに': '補足',
    'なぜなら': '理由',
}
# 语义邻近、同一处可能都讲得通的类别，禁止互为干扰项
CONJ_CONFLICT = [{'逆接', '対比'}, {'順接', '理由'}, {'添加', '時間順序'},
                 {'換言', '例示'}, {'転換', '補足'}, {'順接', '時間順序'}]
CONJ_CLASS_DESC = {
    '逆接': '前后相反（しかし类）', '順接': '前因后果（だから类）',
    '添加': '并列追加（そして类）', '例示': '举例（たとえば类）',
    '換言': '换句话说（つまり类）', '対比': '两方对照（一方类）',
    '転換': '话题转换（ところで类）', '時間順序': '时间先后（まず/次に类）',
    '補足': '补充限定（ただし类）', '理由': '说明理由（なぜなら类）',
}


def _conj_conflict(a, b):
    if a == b:
        return True
    return any(a in g and b in g for g in CONJ_CONFLICT)


# ================================================================
# 4. 活用（文体×时制题用；带自校验）
# ================================================================
_GODAN_TA = {'く': 'いた', 'ぐ': 'いだ', 'す': 'した', 'つ': 'った', 'る': 'った',
             'う': 'った', 'ぬ': 'んだ', 'ぶ': 'んだ', 'む': 'んだ'}
_GODAN_I = {'く': 'き', 'ぐ': 'ぎ', 'す': 'し', 'つ': 'ち', 'る': 'り',
            'う': 'い', 'ぬ': 'に', 'ぶ': 'び', 'む': 'み'}


def conj_forms(lemma, ctype):
    """返回 {dict, ta, masu, mashita}；无法可靠活用时返回 None。"""
    if not lemma or not ctype:
        return None
    if ctype.startswith('五段'):
        end = lemma[-1]
        if end not in _GODAN_TA or len(lemma) < 2:
            return None
        if lemma == '行く':
            ta = '行った'
        else:
            ta = lemma[:-1] + _GODAN_TA[end]
        stem = lemma[:-1] + _GODAN_I[end]
        return {'dict': lemma, 'ta': ta, 'masu': stem + 'ます', 'mashita': stem + 'ました'}
    if ctype.startswith(('上一段', '下一段')):
        if not lemma.endswith('る') or len(lemma) < 2:
            return None
        stem = lemma[:-1]
        return {'dict': lemma, 'ta': stem + 'た', 'masu': stem + 'ます', 'mashita': stem + 'ました'}
    if ctype.startswith('サ行変格'):
        if lemma == 'する':
            return {'dict': 'する', 'ta': 'した', 'masu': 'します', 'mashita': 'しました'}
        if lemma.endswith('する'):
            b = lemma[:-2]
            return {'dict': b + 'する', 'ta': b + 'した',
                    'masu': b + 'します', 'mashita': b + 'しました'}
        return None
    if ctype.startswith('カ行変格'):
        return {'dict': '来る', 'ta': '来た', 'masu': '来ます', 'mashita': '来ました'}
    return None


# ================================================================
# 5. 题目通用校验
# ================================================================
def _mk(qtype, **kw):
    q = {'qtype': qtype}
    q.update(kw)
    return q


def _valid(q):
    """所有题目出厂前的硬门禁。任何一条不满足直接丢弃。"""
    opts = q.get('options') or []
    if len(opts) != len(set(opts)) or len(opts) < 3:
        return False
    if q.get('answer') not in opts:
        return False
    if not q.get('evidence'):
        return False
    if q.get('objectivity') not in ('verbatim', 'contradiction', 'rule'):
        return False
    if any(not str(o).strip() for o in opts):
        return False
    # 选项长度不能让答案一眼可辨（唯一的超长/超短项）
    ls = sorted(len(o) for o in opts)
    if len(opts) >= 4 and ls[-1] - ls[-2] > max(8, ls[-2]) and len(q['answer']) == ls[-1]:
        return False
    return True


def _finish(q, rng):
    opts = list(q['options'])
    rng.shuffle(opts)
    q['options'] = opts
    q['answer_index'] = opts.index(q['answer'])
    return q


# ================================================================
# 6. Passage 封装
# ================================================================
class Passage:
    """出题用的篇章视图。self.sents 只含正文句；小标题单独放在 self.headings。"""

    def __init__(self, title='', rows=None, pid=None):
        # rows: [(para_idx, kind, text)]
        rows = rows or []
        self.id = pid
        self.title = title
        self.sents, self.para_of, self.headings = [], [], []
        for pa, kind, t in rows:
            if kind == 'heading':
                self.headings.append({'para': pa, 'text': t})
            else:
                self.sents.append(t)
                self.para_of.append(pa)
        self.text = '\n'.join(t for _, _, t in rows)
        self.toks = [tag(s) for s in self.sents]
        self.cwords = [content_words(t) for t in self.toks]
        self.freq = Counter(w for ws in self.cwords for w in ws)

    def paras(self):
        d = defaultdict(list)
        for i, p in enumerate(self.para_of):
            d[p].append(i)
        return [d[k] for k in sorted(d)]

    def units(self):
        """出题用的「块序列」：段内句子≥3 时以句为单位，
        否则把连续的单句段落串起来（新闻体常见一段一句）。"""
        ps = self.paras()
        big = [g for g in ps if len(g) >= 3]
        if big:
            return big
        flat = [i for g in ps for i in g]
        return [flat[a:a + 5] for a in range(0, len(flat), 5) if len(flat[a:a + 5]) >= 3]

    def joined(self):
        return ''.join(self.sents)


def build(title, text):
    """不落库，直接从文本构造 Passage（预览用）。"""
    return Passage(title=title, rows=parse_text(text))


def load(pid):
    row = get_passage(pid)
    if not row:
        return None
    rows = [(s['para_idx'], s.get('kind') or 'body', s['text'])
            for s in row['sentences']]
    return Passage(title=row.get('title', ''), rows=rows, pid=pid)


# ================================================================
# 7. 生成器
# ================================================================
def g_connective(P, rng):
    """接续词还原：答案是原文接续词，干扰项来自语义类别互不冲突的其它接续词。"""
    out = []
    keys = sorted(CONJ, key=len, reverse=True)
    for i, s in enumerate(P.sents):
        if i == 0:
            continue
        hit = next((k for k in keys if s.startswith(k)), None)
        if not hit:
            continue
        rest = s[len(hit):]
        if not rest.startswith('、') or len(rest) < 8:
            continue
        cls = CONJ[hit]
        # 后句里若还有另一个接续词，逻辑关系可能由它承担 → 不出
        if any(k in rest for k in keys if CONJ[k] != cls):
            continue
        pool = [w for w, c in CONJ.items() if not _conj_conflict(c, cls)]
        rng.shuffle(pool)
        picked, used = [], set()
        for w in pool:
            if CONJ[w] in used or w in P.joined():
                continue
            picked.append(w)
            used.add(CONJ[w])
            if len(picked) == 3:
                break
        if len(picked) < 3:
            continue
        q = _mk('connective',
                title='接续词还原',
                prompt='空欄に入る接続詞として最も適切なものを選べ（篇章逻辑）',
                context=(P.sents[i - 1] + '\n＿＿' + rest),
                options=picked + [hit], answer=hit,
                objectivity='verbatim',
                evidence=[f'答案 {hit} 是原文用词（前句：{P.sents[i-1][:30]}…）',
                          f'该处逻辑关系为「{cls}」：{CONJ_CLASS_DESC[cls]}',
                          '三个干扰项分别属于 ' +
                          '、'.join(CONJ[w] for w in picked) + ' 类，与正确类别语义不相邻（互斥表 CONJ_CONFLICT 已排除近义类）'],
                explain=f'「{hit}」＝{CONJ_CLASS_DESC[cls]}。前句与后句构成{cls}关系。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


def g_anaphora(P, rng):
    """指示语照应还原：「その＿＿」——空里填回前文出现过的那个名词。"""
    out = []
    for i, s in enumerate(P.sents):
        if i == 0:
            continue
        toks = P.toks[i]
        for j, t in enumerate(toks[:-1]):
            if t['s'] not in ('その', 'この', 'こうした', 'そうした'):
                continue
            nx = toks[j + 1]
            if nx['p1'] != '名詞' or len(nx['s']) < 2:
                continue
            noun = nx['s']
            before = ''.join(P.sents[:i])
            if noun not in before:
                continue        # 必须是前文出现过的复现词（照应链）
            # 干扰项：前文只出现 1 次、没有照应链的名词
            cand = [w for w in set(sum(P.cwords[:i], []))
                    if w != noun and len(w) >= 2 and P.freq[w] == 1
                    and w not in s]
            rng.shuffle(cand)
            if len(cand) < 3:
                continue
            k = ''.join(x['s'] for x in toks[:j + 1])
            tail = ''.join(x['s'] for x in toks[j + 2:])
            q = _mk('anaphora',
                    title='指示语照应',
                    prompt='下線部「' + t['s'] + '＿＿」は前文の何を指すか。空欄に入る語を選べ',
                    context='\n'.join(P.sents[max(0, i - 2):i]) + '\n' + k + '＿＿' + tail,
                    options=cand[:3] + [noun], answer=noun,
                    objectivity='verbatim',
                    evidence=[f'答案「{noun}」为原文用词，且在前文已出现（全篇共 {P.freq[noun]} 次），构成指示语照应链',
                              '三个干扰项在全篇仅出现 1 次、且不在本句中，不存在可被「' + t['s'] + '」回指的先行词'],
                    explain=f'「{t["s"]}＋名詞」必须回指前文已提到的事物，这里指的是前文的「{noun}」。',
                    sent_idx=i)
            if _valid(q):
                out.append(q)
            break
    return out


_CASE_P = ['が', 'を', 'に', 'で', 'へ', 'と', 'から', 'まで', 'より']
_EQUIV = [{'は', 'が'}, {'に', 'へ'}, {'は', 'も'}, {'が', 'も'}, {'に', 'で'}, {'から', 'より'}]


def _equiv(a, b):
    return any({a, b} <= g for g in _EQUIV)


def g_particle(P, rng):
    """格助词还原：干扰项必须在语料库里与该名词「零共现」，否则不出题。"""
    out = []
    for i, toks in enumerate(P.toks):
        for j, t in enumerate(toks):
            if t['p1'] != '助詞' or t['p2'] != '格助詞' or t['s'] not in _CASE_P:
                continue
            if j == 0 or toks[j - 1]['p1'] != '名詞' or len(toks[j - 1]['s']) < 2:
                continue
            noun, ans = toks[j - 1]['s'], t['s']
            base = corpus_count(noun + ans)
            if base < 1:
                continue                  # 正确搭配自身无语料实证 → 不出
            distr = []
            for p in _CASE_P:
                if p == ans or _equiv(p, ans):
                    continue
                n = corpus_count(noun + p)
                if n == 0:
                    distr.append(p)
            rng.shuffle(distr)
            if len(distr) < 3:
                continue
            pre = ''.join(x['s'] for x in toks[:j])
            src = P.sents[i]
            pos = src.find(pre + ans) if pre else -1
            if pos < 0:
                head = pre
                tail = ''.join(x['s'] for x in toks[j + 1:])
            else:
                head = src[:pos + len(pre)]
                tail = src[pos + len(pre) + len(ans):]
            q = _mk('particle',
                    title='格助词还原',
                    prompt='空欄に入る助詞を選べ',
                    context=head + '（＿）' + tail,
                    options=distr[:3] + [ans], answer=ans,
                    objectivity='verbatim',
                    evidence=[f'答案「{noun}{ans}」为原文原样，语料库中另有 {base} 句实证',
                              '三个干扰项与「' + noun + '」在整个语料库中共现次数为 0（零实证门禁）'],
                    explain=f'「{noun}{ans}」是本文实际使用、且语料库反复出现的搭配。',
                    sent_idx=i)
            if _valid(q):
                out.append(q)
            break
    return out


_PAST_ADV = ['昨日', '一昨日', '先週', '先月', '去年', '昨年', '先日', 'かつて', '以前', '当時']
_NONPAST_ADV = ['明日', '明後日', '来週', '来月', '来年', '今後', 'これから', '将来', '毎日', 'いつも']


def _style_of(P):
    """全篇文体：'polite' / 'plain' / None（不够一致就不出题）。"""
    pol = pla = 0
    for s in P.sents:
        core = s.rstrip('。！？!?」』')
        if core.endswith(('ます', 'ました', 'ません', 'ですね', 'です', 'でした', 'ください', 'ましょう')):
            pol += 1
        elif core.endswith(('だ', 'である', 'た', 'る', 'ない', 'う')):
            pla += 1
    tot = pol + pla
    if tot < 5:
        return None
    if pol / tot >= 0.85:
        return 'polite'
    if pla / tot >= 0.85:
        return 'plain'
    return None


def g_polite_tense(P, rng):
    """文体×时制 2×2：两个轴都必须有显式证据（全篇文体一致 + 句内时间副词）。"""
    style = _style_of(P)
    if style != 'polite':
        return []
    out = []
    for i, s in enumerate(P.sents):
        adv_past = next((a for a in _PAST_ADV if a in s), None)
        adv_non = next((a for a in _NONPAST_ADV if a in s), None)
        if bool(adv_past) == bool(adv_non):
            continue
        toks = P.toks[i]
        # 找句末动词（允许后面跟句点）
        vi = None
        for j in range(len(toks) - 1, -1, -1):
            if toks[j]['p1'] == '動詞':
                vi = j
                break
            if toks[j]['p1'] not in ('助動詞', '補助記号', '助詞'):
                break
        if vi is None:
            continue
        f = conj_forms(toks[vi]['lemma'], toks[vi]['ct'])
        if not f:
            continue
        tail = ''.join(x['s'] for x in toks[vi:]).rstrip('。！？!?')
        want = f['mashita'] if adv_past else f['masu']
        if tail != want:
            continue        # 自校验：活用器还原不出原文 → 放弃，绝不猜
        core = s.rstrip('。！？!?')
        if not core.endswith(tail):
            continue
        head = core[:len(core) - len(tail)]      # 用原句切片，保留原文的空格与标点
        opts = [f['masu'], f['mashita'], f['dict'], f['ta']]
        if len(set(opts)) != 4:
            continue
        adv = adv_past or adv_non
        q = _mk('polite_tense',
                title='文体×时制',
                prompt='空欄に入る形を選べ（文体と時制の両方を合わせること）',
                context=head + '＿＿。',
                options=opts, answer=want,
                objectivity='rule',
                evidence=[f'时制轴：句中时间副词「{adv}」显式指定'
                          + ('过去' if adv_past else '非过去'),
                          f'文体轴：全篇 {round(100*_polite_ratio(P))}% 的句子为「です・ます」体，须保持统一',
                          '四个选项＝敬体/简体 × 过去/非过去 的 2×2，每个轴上正确值与错误值各占两项，光看选项无法反推'],
                explain=f'「{adv}」要求'
                        + ('过去形' if adv_past else '非过去形')
                        + f'，全篇为敬体，故答案为「{want}」。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


def _polite_ratio(P):
    pol = tot = 0
    for s in P.sents:
        core = s.rstrip('。！？!?」』')
        if core.endswith(('ます', 'ました', 'ません', 'です', 'でした', 'ください', 'ましょう')):
            pol += 1
            tot += 1
        elif core.endswith(('だ', 'である', 'た', 'る', 'ない', 'う')):
            tot += 1
    return pol / tot if tot else 0


def _starts_with_cue(s):
    for k in sorted(CONJ, key=len, reverse=True):
        if s.startswith(k):
            return k
    for k in ('その', 'この', 'それ', 'これ', 'そう', 'こう', 'そこで', 'こうした', 'そうした'):
        if s.startswith(k):
            return k
    return None


def g_insert(P, rng):
    """句子还原插入：被抽走的句子必须带「向前指」的线索，且线索只在唯一位置成立。"""
    out = []
    for idxs in P.units():
        if len(idxs) < 4:
            continue
        for pos, i in enumerate(idxs):
            if pos == 0:
                continue
            cue = _starts_with_cue(P.sents[i])
            if not cue:
                continue
            link = [w for w in P.cwords[i] if w in P.cwords[idxs[pos - 1]]]
            if not link:
                continue
            key = link[0]
            # 唯一性：该关键词不能出现在其它候选插入点的前一句里
            others = [k for k in idxs if k != i]
            if any(key in P.cwords[k] for k in others if k != idxs[pos - 1]):
                continue
            rest = [P.sents[k] for k in idxs if k != i]
            slots = ['①'] + []
            body = []
            for n, txt in enumerate(rest):
                body.append(f'（{n+1}）')
                body.append(txt)
            body.append(f'（{len(rest)+1}）')
            # 抽走后剩 len(rest) 句、共 len(rest)+1 个空位；原句排在第 pos 位
            # （0-based），还原后应落在「第 pos 句之后」＝ 第 pos+1 号空位。
            correct = f'（{pos + 1}）'
            opts = [f'（{n}）' for n in range(1, len(rest) + 2)]
            if len(opts) > 4:
                # 保留正确位置 + 3 个随机错误位置
                wrong = [o for o in opts if o != correct]
                rng.shuffle(wrong)
                opts = wrong[:3] + [correct]
            q = _mk('insert',
                    title='句子还原插入',
                    prompt='次の一文を戻すのに最も適切な位置を選べ：\n「' + P.sents[i] + '」',
                    context='\n'.join(body),
                    options=opts, answer=correct,
                    objectivity='rule',
                    evidence=[f'被抽句以「{cue}」开头，必须紧接在它所回指的句子之后',
                              f'被抽句与前一句共享实词「{key}」，而该词在本段其它候选位置的前句中均未出现（唯一性已逐一验证）',
                              '答案位置＝原文位置（原样还原）'],
                    explain=f'「{cue}」承接上句，且与上句共用关键词「{key}」，只有这一处成立。',
                    sent_idx=i)
            if _valid(q):
                out.append(q)
            break
    return out


_SEQ_RANK = {'まず': 0, '次に': 1, 'その後': 2, '最後に': 3}
_DEIXIS = ('その', 'この', 'それ', 'これ', 'そう', 'こう', 'こうした', 'そうした')


def _order_ok(seq, P):
    """一个排列是否满足全部硬规则（全部可机器复核、与「读懂意思」无关）：
      R1 首句不得以承接型接续词或指示语开头；时间序列标记只允许序号最小的那个打头；
      R2 带时间序列标记（まず/次に/その後/最後に）的句子必须按标记顺序排列；
      R3 以指示语开头的句子，必须紧跟在一个与它共享实词的句子之后；
      R4 既无接续词也无指示语的非首句，必须与前文某句共享实词（词汇衔接链）。
    只有当原顺序是**唯一**通过这四条的排列时才允许出题。"""
    first = P.sents[seq[0]]
    cue0 = _starts_with_cue(first)
    ranks = [_SEQ_RANK[c] for c in
             (_starts_with_cue(P.sents[i]) for i in seq) if c in _SEQ_RANK]
    if cue0:
        if cue0 in _DEIXIS:
            return False
        if cue0 not in _SEQ_RANK:
            return False
        if ranks and _SEQ_RANK[cue0] != min(ranks):
            return False
    seen = []
    for n, i in enumerate(seq):
        cue = _starts_with_cue(P.sents[i])
        if n and cue in _DEIXIS:
            prev = P.sents[seq[n - 1]]
            if not any(w in prev for w in P.cwords[i]):
                return False
        elif n and not cue:
            if not any(w in P.cwords[seq[m]] for m in range(n) for w in P.cwords[i]):
                return False
        seen.append(cue)
    rk = [_SEQ_RANK[c] for c in seen if c in _SEQ_RANK]
    if rk != sorted(rk):
        return False
    return True


def g_order(P, rng):
    """语序重排：只有当「原顺序是唯一满足全部规则的排列」时才出题（暴力验证）。"""
    from itertools import permutations
    out = []
    for idxs in P.units():
        for a in range(0, len(idxs) - 2):
            grp = idxs[a:a + 3]
            if len(grp) < 3:
                continue
            good = [p for p in permutations(grp) if _order_ok(list(p), P)]
            if good != [tuple(grp)]:
                continue
            labels = ['A', 'B', 'C']
            shuffled = list(grp)
            rng.shuffle(shuffled)
            mapping = {labels[k]: shuffled[k] for k in range(3)}
            rev = {v: k for k, v in mapping.items()}
            answer = ''.join(rev[x] for x in grp)
            opts = set([answer])
            for p in permutations(labels):
                if len(opts) >= 4:
                    break
                opts.add(''.join(p))
            ctx = '\n'.join(f'{labels[k]}. {P.sents[mapping[labels[k]]]}' for k in range(3))
            q = _mk('order',
                    title='语序重排',
                    prompt='A〜C を正しい順序に並べ替えよ',
                    context=ctx,
                    options=sorted(opts), answer=answer,
                    objectivity='rule',
                    evidence=['答案＝原文顺序',
                              '已对全部 6 种排列逐一做规则校验（R1 首句不得以承接词/指示语开头；'
                              'R2 まず→次に→その後→最後に 的序列标记必须递增；'
                              'R3 指示语开头的句子必须紧跟共享实词的句子；'
                              'R4 无线索句必须与前文共享实词），只有原顺序一种通过，故答案唯一'],
                    explain='按接续词与指示语的承接方向、以及实词复现链可唯一还原。',
                    sent_idx=grp[0])
            if _valid(q):
                out.append(q)
    return out


# ---- 内容一致：三种可判定的矛盾改写 ----
def _flip_polarity(s, toks):
    core = s.rstrip('。！？!?')
    pairs = [('ました', 'ませんでした'), ('ません', 'ます'), ('ます', 'ません'),
             ('である', 'ではない'), ('ではない', 'である'),
             ('でした', 'ではありませんでした'), ('です', 'ではありません')]
    for a, b in pairs:
        if core.endswith(a):
            return core[:-len(a)] + b + s[len(core):], f'句尾「{a}」→「{b}」，肯否定完全相反'
    return None, None


_NUM_RE = re.compile(r'[0-9０-９]+|[一二三四五六七八九十百千万]+')


def _swap_number(s, toks, numbank):
    """把句中「数詞＋量词」的数值换成本文别处**同一量词**下的另一个数值。
    只换同量词，保证改写后依然是合法的日语数量表达，错在事实而不是语法。"""
    for j, t in enumerate(toks):
        if t['p2'] != '数詞' or j + 1 >= len(toks):
            continue
        nxt = toks[j + 1]
        if not (nxt['p3'] in ('助数詞可能', '助数詞') or
                (nxt['p1'] == '接尾辞' and nxt['p2'] == '名詞的')):
            continue
        alts = [n for n in numbank.get(nxt['s'], []) if n != t['s']]
        if not alts:
            continue
        rep = alts[0]
        new = ''.join(x['s'] for x in toks[:j]) + rep + \
            ''.join(x['s'] for x in toks[j + 1:])
        return new, f'数量「{t["s"]}{nxt["s"]}」→「{rep}{nxt["s"]}」，与原文陈述的数量矛盾'
    return None, None


def _plain_noun(toks, j):
    """toks[j] 是否为可安全互换的普通名词（排除数量词、量词、时间名词，
    以及被数词修饰的名词——互换它们会造出「五十時間が読書パーセントを」这种
    既不是矛盾、只是坏句的选项，坏句会直接暴露答案）。"""
    t = toks[j]
    if t['p1'] != '名詞' or t['p2'] != '普通名詞' or t['p3'] not in ('一般', 'サ変可能'):
        return False
    if len(t['s']) < 2:
        return False
    if j and toks[j - 1]['p2'] == '数詞':
        return False
    return True


def _swap_args(s, toks):
    ga = wo = None
    for j, t in enumerate(toks):
        if t['p1'] == '助詞' and t['s'] in ('が', 'は') and j and _plain_noun(toks, j - 1):
            if ga is None:
                ga = (j - 1, toks[j - 1]['s'])
        if t['p1'] == '助詞' and t['s'] == 'を' and j and _plain_noun(toks, j - 1):
            if wo is None:
                wo = (j - 1, toks[j - 1]['s'])
    if not ga or not wo or ga[1] == wo[1]:
        return None, None
    new = []
    for j, t in enumerate(toks):
        if j == ga[0]:
            new.append(wo[1])
        elif j == wo[0]:
            new.append(ga[1])
        else:
            new.append(t['s'])
    return (''.join(new),
            f'把动作主体「{ga[1]}」与对象「{wo[1]}」互换，施受关系与原文相反')


def _grammar_ok(text):
    """改写句必须仍然是合法日语：错要错在「与原文矛盾」，不能错在「不像话」，
    否则考生靠语感就能挑出唯一通顺的那句，题目失去区分度。"""
    try:
        import grammar
        return bool(grammar.is_sentence_grammatically_sound(text))
    except Exception:
        return True


def g_truth(P, rng):
    """内容一致判定：四项同源于一句，一项原样、三项与原文显式矛盾。"""
    out = []
    numbank = defaultdict(list)
    for toks in P.toks:
        for j, t in enumerate(toks):
            if t['p2'] == '数詞' and j + 1 < len(toks):
                nxt = toks[j + 1]
                if (nxt['p3'] in ('助数詞可能', '助数詞') or
                        (nxt['p1'] == '接尾辞' and nxt['p2'] == '名詞的')):
                    if t['s'] not in numbank[nxt['s']]:
                        numbank[nxt['s']].append(t['s'])
    for i, s in enumerate(P.sents):
        if not (12 <= len(s) <= 70):
            continue
        toks = P.toks[i]
        variants, notes = [], []
        for fn in (lambda: _flip_polarity(s, toks),
                   lambda: _swap_number(s, toks, numbank),
                   lambda: _swap_args(s, toks)):
            v, note = fn()
            if v and v != s and v not in variants and v not in P.joined() \
                    and _grammar_ok(v):
                variants.append(v)
                notes.append(note)
        if len(variants) < 3:
            continue
        q = _mk('truth',
                title='内容一致判定',
                prompt='本文の内容と合っているものはどれか',
                context='（本文全体を参照）',
                options=variants[:3] + [s], answer=s,
                objectivity='contradiction',
                evidence=[f'答案是本文第 {i+1} 句的原文原样'] +
                         [f'干扰项{k+1}：{n}' for k, n in enumerate(notes[:3])],
                explain='三个错误项都由同一句机械改写而成，实词几乎不变，'
                        '只在肯否定 / 数值 / 施受关系上与原文矛盾。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


def g_fact(P, rng):
    """数值检索：挖掉句中的数量表达，干扰项为文中出现的其它数值。"""
    out = []
    nums = []
    for i, toks in enumerate(P.toks):
        for j, t in enumerate(toks):
            if t['p2'] != '数詞':
                continue
            nxt = toks[j + 1] if j + 1 < len(toks) else None
            suf = ''
            if nxt and (nxt['p3'] in ('助数詞可能', '助数詞') or
                        (nxt['p1'] == '接尾辞' and nxt['p2'] == '名詞的')):
                suf = nxt['s']
            if not suf:
                continue          # 光秃秃的数字不出题：没有量词就无法构成同类干扰项
            nums.append((i, j, t['s'] + suf, t['s'], suf))
    if len(nums) < 2:
        return out
    for (i, j, full, num, suf) in nums:
        same = [f2 for (_, _, f2, n2, s2) in nums if s2 == suf and n2 != num]
        other = [f2 for (_, _, f2, n2, s2) in nums if s2 != suf and f2 != full]
        # 还不够 3 个就用「本文出现过的别的数字 + 本量词」现造，
        # 这类组合在本文中一次也没出现过，同样可逐字排除
        built = [n2 + suf for (_, _, _, n2, _) in nums
                 if n2 != num and (n2 + suf) not in P.joined()]
        alts = [a for a in dict.fromkeys(same + other + built) if a != full]
        attested = set(same + other)
        if len(alts) < 3:
            continue
        toks = P.toks[i]
        k = j + (2 if suf else 1)
        head = ''.join(x['s'] for x in toks[:j])
        tail = ''.join(x['s'] for x in toks[k:])
        q = _mk('fact',
                title='数值检索',
                prompt='本文によると、空欄に入る数量表現はどれか',
                context=head + '＿＿' + tail,
                options=alts[:3] + [full], answer=full,
                objectivity='verbatim',
                evidence=[f'答案「{full}」是本文第 {i+1} 句原文原样',
                          '干扰项构成：' + '、'.join(
                              f'{a}（{"文中他处出现" if a in attested else "本文从未出现的数量组合"}）'
                              for a in alts[:3]),
                          '任一干扰项都可以回原句逐字核对排除，判定不依赖理解'],
                explain='回到原句逐字核对即可，训练的是定位与看清量词。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


_SAY = ('言う', '話す', '述べる', '答える', '語る', '叫ぶ', '尋ねる', '聞く')


def g_quote(P, rng):
    """引语话者：句法规则唯一确定（句中只有一个 が/は 标记的主语）。"""
    out = []
    for i, s in enumerate(P.sents):
        m = re.search(r'「([^」]{4,60})」と', s)
        if not m:
            continue
        after = s[m.end():]
        if not any(v[:-1] in after or v in after for v in _SAY):
            continue
        outside = s[:m.start()]
        toks = tag(outside)
        subj = []
        for j, t in enumerate(toks):
            if t['p1'] == '助詞' and t['s'] in ('は', 'が') and j and toks[j - 1]['p1'] in ('名詞', '接尾辞'):
                k = j - 1
                while k > 0:
                    prev = toks[k - 1]
                    if prev['p1'] in ('名詞', '接頭辞', '接尾辞') and prev['p2'] != '数詞':
                        k -= 1
                    elif (prev['s'] == 'の' and k >= 2 and toks[k - 2]['p1'] == '名詞'):
                        k -= 2      # 「町の人」「田中さんの母」整体才是主语
                    else:
                        break
                subj.append(''.join(x['s'] for x in toks[k:j]))
        subj = list(dict.fromkeys(subj))
        subj = [x for x in subj if len(x) >= 2]
        if len(subj) != 1:
            continue
        ans = subj[0]
        cand = [w for w in P.freq if w != ans and len(w) >= 2 and w not in s]
        cand.sort(key=lambda w: (not _is_person_like(w), -P.freq[w]))
        pers = [w for w in cand if _is_person_like(w)]
        pool = (pers if len(pers) >= 3 else cand)[:12]
        rng.shuffle(pool)
        if len(pool) < 3:
            continue
        q = _mk('quote',
                title='引语话者',
                prompt='「' + m.group(1)[:40] + '」と言ったのは誰か',
                context=s,
                options=pool[:3] + [ans], answer=ans,
                objectivity='rule',
                evidence=['规则：引用节「…」と＋発話動詞 的说话人＝同句引号之前唯一被 は/が 标记的名词',
                          f'本句引号前 は/が 标记的名词只有「{ans}」一个（已验证唯一）',
                          '三个干扰项在本句引号前未出现，不可能是本句的说话人'],
                explain=f'「{ans}」は/が … と言った —— 说话人由句法唯一确定。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


def g_absent(P, rng):
    """本文未出现词：三个词在文中，一个词不在（100% 可逐字核对）。"""
    inside = [w for w, n in P.freq.items() if len(w) >= 2 and n >= 1]
    if len(inside) < 6:
        return []
    joined = P.joined()
    outside = []
    try:
        with db.get_conn() as c:
            rs = c.execute('SELECT text FROM sentences ORDER BY RANDOM() LIMIT 60').fetchall()
        for r in rs:
            for w in content_words(tag(r['text'])):
                if len(w) >= 2 and w not in joined and w not in outside:
                    outside.append(w)
    except Exception:
        return []
    if not outside:
        return []
    out = []
    rng.shuffle(inside)
    rng.shuffle(outside)
    for k in range(min(3, len(outside))):
        ins = inside[k * 3:k * 3 + 3]
        if len(ins) < 3:
            break
        # 最终逐字复核：三个干扰项必须真在文中，答案必须真不在（绝不靠词表推断）
        if any(w not in joined for w in ins) or outside[k] in joined:
            continue
        q = _mk('absent',
                title='扫读辨词',
                prompt='本文に出てこない語はどれか',
                context='（本文全体を参照）',
                options=ins + [outside[k]], answer=outside[k],
                objectivity='verbatim',
                evidence=['三个干扰项都能在本文中逐字找到（出现次数：'
                          + '、'.join(f'{w}×{P.freq[w]}' for w in ins) + '）',
                          f'答案「{outside[k]}」在本文全文中字符串检索为 0 次，取自语料库其它句子'],
                explain='纯扫读题：能否在限定时间里确认一个词「不在」文中。',
                sent_idx=0)
        if _valid(q):
            out.append(q)
    return out


def g_headword(P, rng):
    """复现词链：全篇高频实词被全部挖空，考「这篇文章到底在反复说什么」。"""
    top = [w for w, n in P.freq.most_common(6) if n >= 3 and len(w) >= 2]
    if not top:
        return []
    key = top[0]
    hits = [i for i, s in enumerate(P.sents) if key in s][:3]
    if len(hits) < 2:
        return []
    cand = [w for w, n in P.freq.items() if n == 1 and len(w) >= 2 and w != key]
    rng.shuffle(cand)
    if len(cand) < 3:
        return []
    ctx = '\n'.join(P.sents[i].replace(key, '＿＿') for i in hits)
    q = _mk('headword',
            title='复现词链',
            prompt='下の複数の文に共通して入る語を選べ',
            context=ctx,
            options=cand[:3] + [key], answer=key,
            objectivity='verbatim',
            evidence=[f'答案「{key}」是原文用词，全篇出现 {P.freq[key]} 次，是贯穿全篇的复现主词',
                      f'三个干扰项全篇各只出现 1 次，不可能同时填入这 {len(hits)} 个位置'],
            explain='能同时填进多处空的只有全篇的复现主词——这正是把握文章话题的抓手。',
            sent_idx=hits[0])
    return [q] if _valid(q) else []


# ================================================================
# 7b. 进阶题型（面向新闻体 / 说明文 / 长篇）
# ================================================================
# 自他动词对（左＝自动词，右＝他动词）
JITA_PAIRS = [
    ('崩れる', '崩す'), ('増える', '増やす'), ('集まる', '集める'), ('変わる', '変える'),
    ('進む', '進める'), ('始まる', '始める'), ('終わる', '終える'), ('上がる', '上げる'),
    ('下がる', '下げる'), ('続く', '続ける'), ('決まる', '決める'), ('出る', '出す'),
    ('入る', '入れる'), ('開く', '開ける'), ('閉まる', '閉める'), ('落ちる', '落とす'),
    ('残る', '残す'), ('止まる', '止める'), ('動く', '動かす'), ('育つ', '育てる'),
    ('広がる', '広げる'), ('深まる', '深める'), ('高まる', '高める'), ('強まる', '強める'),
    ('弱まる', '弱める'), ('伝わる', '伝える'), ('直る', '直す'), ('流れる', '流す'),
    ('壊れる', '壊す'), ('割れる', '割る'), ('届く', '届ける'), ('見つかる', '見つける'),
    ('消える', '消す'), ('生まれる', '生む'), ('立つ', '立てる'), ('回る', '回す'),
]
_JITA = {}
for _a, _b in JITA_PAIRS:
    _JITA[_a] = ('自', _b)
    _JITA[_b] = ('他', _a)


def _clause_particles(toks, vi):
    """取谓语 vi 之前、到上一个句读/接续助词为止的格助词集合。"""
    ps, k = [], vi - 1
    while k >= 0:
        t = toks[k]
        if t['p1'] == '補助記号' or (t['p2'] == '接続助詞'):
            break
        if t['p1'] == '助詞' and t['p2'] in ('格助詞', '係助詞'):
            ps.append(t['s'])
        k -= 1
    return ps


def g_transitivity(P, rng):
    """自他动词 × 文体 的 2×2。
    自他轴证据：小句里只有が/は标记的主体、没有を宾语 → 必须用自动词（反之亦然）；
    文体轴证据：全篇文体一致（与 polite_tense 同一条规则）。"""
    style = _style_of(P)
    if style is None:
        return []
    out = []
    for i, toks in enumerate(P.toks):
        for vi, t in enumerate(toks):
            if t['p1'] != '動詞' or t['lemma'] not in _JITA:
                continue
            kind, mate = _JITA[t['lemma']]
            ps = _clause_particles(toks, vi)
            if not ps:
                continue
            has_wo, has_ga = 'を' in ps, ('が' in ps or 'は' in ps)
            if kind == '自' and (has_wo or not has_ga):
                continue
            if kind == '他' and not has_wo:
                continue
            f_ans = conj_forms(t['lemma'], t['ct'])
            f_mate = conj_forms(mate, _mate_ctype(mate))
            if not f_ans or not f_mate:
                continue
            tail = ''.join(x['s'] for x in toks[vi:]).rstrip('。！？!?')
            past = tail in (f_ans['mashita'], f_ans['ta'])
            if tail == (f_ans['mashita'] if past else f_ans['masu']):
                polite = True
            elif tail == (f_ans['ta'] if past else f_ans['dict']):
                polite = False
            else:
                continue                      # 活用自校验没通过 → 不出题
            if (polite and style != 'polite') or (not polite and style != 'plain'):
                continue
            key = ('mashita' if past else 'masu', 'ta' if past else 'dict')
            opts = [f_ans[key[0]], f_ans[key[1]], f_mate[key[0]], f_mate[key[1]]]
            if len(set(opts)) != 4:
                continue
            ans = f_ans[key[0]] if polite else f_ans[key[1]]
            core = P.sents[i].rstrip('。！？!?')
            if not core.endswith(tail):
                continue
            head = core[:len(core) - len(tail)]
            q = _mk('transitivity',
                    title='自他动词×文体',
                    prompt='空欄に入る形を選べ（自動詞か他動詞か、文体も合わせること）',
                    context=head + '＿＿。',
                    options=opts, answer=ans,
                    objectivity='rule',
                    evidence=[
                        f'自他轴：本小句的格成分是 {"、".join(dict.fromkeys(ps))}，'
                        + (f'只有が/は标记的主体、没有を宾语 → 只能用自动词「{t["lemma"]}」'
                           if kind == '自' else
                           f'存在を宾语 → 只能用他动词「{t["lemma"]}」'),
                        f'自他对：{t["lemma"]}（{kind}動詞） ↔ {mate}（{"他" if kind == "自" else "自"}動詞）',
                        f'文体轴：全篇为{"敬体（です・ます）" if style == "polite" else "简体（だ・である）"}，须保持统一',
                        '答案＝原文原样；四个选项是 自他 × 文体 的 2×2，两轴各自 2:2 平分'],
                    explain=f'「{"〜が" if kind == "自" else "〜を"}」搭配{kind}動詞。答案「{ans}」是原文形式。',
                    sent_idx=i)
            if _valid(q):
                out.append(q)
            break
    return out


def _mate_ctype(lemma):
    """自他对里另一个词的活用型（用表层结尾推断，只用于生成四个选项）。"""
    if lemma.endswith('する'):
        return 'サ行変格'
    if lemma in ('来る',):
        return 'カ行変格'
    if len(lemma) >= 2 and lemma.endswith('る') and lemma[-2] in 'えけせてねへめれげぜでべぺいきしちにひみりぎじびぴ':
        return '下一段-ラ行'
    return '五段-ラ行' if lemma.endswith('る') else '五段-' + 'カ行'


# ---- 複合助詞（機能表現） ----
COMPOUND_P = {
    'について': '主题', 'に関して': '主题', 'をめぐって': '争点',
    'に対して': '对象·对比', 'にとって': '立场',
    'によって': '手段·原因', 'に基づいて': '根据', 'をもとに': '依据',
    'を通じて': '媒介', 'に伴って': '随伴', 'に応じて': '对应',
    'とともに': '共同', 'に向けて': '方向·目标', 'にかけて': '时间跨度',
    'に比べて': '比较', 'に加えて': '追加', 'を除いて': '排除',
}
CP_CONFLICT = [{'主题', '争点'}, {'手段·原因', '根据'}, {'根据', '依据'},
               {'对象·对比', '立场'}, {'随伴', '共同'}, {'依据', '媒介'}]


def g_compound_particle(P, rng):
    """复合助词（机能表现）还原：N2/N1 的核心考点。
    干扰项必须①属于语义不冲突的类别 ②与前接名词在语料库中零共现。"""
    out = []
    keys = sorted(COMPOUND_P, key=len, reverse=True)
    for i, s in enumerate(P.sents):
        hit = next((k for k in keys if k in s), None)
        if not hit:
            continue
        pos = s.index(hit)
        if pos < 2:
            continue
        toks = tag(s[:pos])
        if not toks or toks[-1]['p1'] != '名詞' or len(toks[-1]['s']) < 2:
            continue
        noun = toks[-1]['s']
        base = corpus_count(noun + hit)
        cls = COMPOUND_P[hit]
        distr = []
        for w, c2 in COMPOUND_P.items():
            if w == hit or c2 == cls:
                continue
            if any(c2 in g and cls in g for g in CP_CONFLICT):
                continue
            if w in P.joined() or corpus_count(noun + w) != 0:
                continue
            distr.append(w)
        rng.shuffle(distr)
        if len(distr) < 3:
            continue
        q = _mk('compound_particle',
                title='复合助词还原',
                prompt='空欄に入る表現を選べ（機能表現）',
                context=s[:pos] + '＿＿' + s[pos + len(hit):],
                options=distr[:3] + [hit], answer=hit,
                objectivity='verbatim',
                evidence=[f'答案「{hit}」（{cls}）是原文原样'
                          + (f'，语料库中「{noun}{hit}」另有 {base} 句实证' if base > 0 else ''),
                          '三个干扰项分属 ' + '、'.join(COMPOUND_P[w] for w in distr[:3])
                          + ' 类，与正确类别语义不相邻',
                          f'三个干扰项与前接名词「{noun}」在语料库中共现次数均为 0，'
                          '且在本文其它位置也没出现'],
                explain=f'「{noun}{hit}」＝{cls}。机能表现选错会直接改变句子的逻辑关系。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


# ---- 数值 ----
_KANSUJI = {'〇': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9}


def parse_number(s):
    """把「69.9」「2300」「三千」「7」等解析成数值；解析不了返回 None。"""
    s = s.strip().translate(str.maketrans('０１２３４５６７８９．', '0123456789.'))
    if re.fullmatch(r'\d+(\.\d+)?', s):
        return float(s)
    if not s or any(ch not in '〇零一二三四五六七八九十百千万億' for ch in s):
        return None
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in _KANSUJI:
            num = _KANSUJI[ch]
        elif ch in '十百千':
            unit = {'十': 10, '百': 100, '千': 1000}[ch]
            section += (num or 1) * unit
            num = 0
        elif ch in '万億':
            unit = {'万': 10 ** 4, '億': 10 ** 8}[ch]
            total += (section + num) * unit
            section = num = 0
    return float(total + section + num)


_NUM_UNIT_RE = re.compile(
    r'([0-9０-９]+(?:[.．][0-9０-９]+)?|[〇零一二三四五六七八九十百千万億]+)'
    r'(％|%|パーセント|割|ミリ|メートル|キロ|人|件|か所|箇所|年|月|日|時間|分|'
    r'万円|億円|円|台|棟|校|市|自治体|度)')


def _num_units(P):
    """全篇的 (句号, 数值, 单位, 原样字串)。"""
    out = []
    for i, s in enumerate(P.sents):
        for m in _NUM_UNIT_RE.finditer(s):
            v = parse_number(m.group(1))
            if v is not None:
                out.append((i, v, m.group(2), m.group(0)))
    return out


_COMPARE_UNITS = {'％', '割', 'ミリ', 'メートル', 'キロ', '人', '件', 'か所', '箇所',
                  '万円', '億円', '円', '台', '棟', '校', '度', '自治体', '市'}


def g_compare(P, rng):
    """数值比较：同一单位下谁最大/最小/第二大。答案由算术唯一确定。"""
    items = _num_units(P)
    by = defaultdict(list)
    for i, v, u, raw in items:
        u2 = {'%': '％', 'パーセント': '％'}.get(u, u)
        if u2 not in _COMPARE_UNITS:
            continue           # 年月日属于时间轴，交给 chronology，不做「数值大小」
        if all(abs(v - x[0]) > 1e-9 for x in by[u2]):
            by[u2].append((v, raw, i))
    out = []
    for u, arr in by.items():
        if len(arr) < 4:
            continue
        arr.sort(key=lambda x: -x[0])
        for mode, idx, word in (('max', 0, '最も大きい'), ('min', -1, '最も小さい'),
                                ('2nd', 1, '2番目に大きい')):
            ans = arr[idx][1]
            opts = [x[1] for x in arr[:4]]
            if ans not in opts:
                opts = opts[:3] + [ans]
            opts = list(dict.fromkeys(opts))
            if len(opts) < 4 or ans not in opts:
                continue
            q = _mk('compare',
                    title='数值比较',
                    prompt=f'本文に出てくる「{u}」の数値のうち、{word}ものはどれか',
                    context='（本文全体を参照）',
                    options=opts[:4], answer=ans,
                    objectivity='rule',
                    evidence=['四个选项都是本文原样出现的数值',
                              '排序：' + ' > '.join(f'{x[1]}' for x in arr[:4]),
                              f'规则：数值大小由算术比较唯一确定（{word}＝{ans}）'],
                    explain='扫读全篇把同一单位的数值都找出来再比较——长文报道最常考的信息整合。',
                    sent_idx=arr[idx][2])
            if _valid(q):
                out.append(q)
    return out


_LABEL_PCT_RE = re.compile(
    r'「([^」]{3,40})」と(?:答え|回答し)た[^。「」]{0,14}?'
    r'([0-9０-９]+(?:[.．][0-9０-９]+)?(?:％|%|パーセント))')


def g_pairing(P, rng):
    """项目↔数值对应：调查报道里的表格式信息，必须精确定位到行。"""
    pairs = []
    for i, s in enumerate(P.sents):
        for m in _LABEL_PCT_RE.finditer(s):
            pairs.append((i, m.group(1), m.group(2)))
    labels = list(dict.fromkeys(x[1] for x in pairs))
    if len(pairs) < 3 or len(labels) < 4:
        return []
    out = []
    for i, lab, pct in pairs:
        # 同一句里往往列了好几个「項目＋％」，同句的其它项目不能当干扰项：
        # 它们与该数值「同句共现」，考生无法排除 → 会变成冤案
        same_sent = {l2 for (i2, l2, p2) in pairs if i2 == i}
        dup_pct = {l2 for (i2, l2, p2) in pairs if p2 == pct}
        others = [x for x in labels
                  if x != lab and x not in same_sent and x not in dup_pct
                  and not any(x in s2 and pct in s2 for s2 in P.sents)]
        rng.shuffle(others)
        if len(others) < 3:
            continue
        q = _mk('pairing',
                title='数值项目对应',
                prompt=f'本文で「{pct}」と回答された項目はどれか',
                context='（本文全体を参照。調査結果の数値と項目を突き合わせること）',
                options=others[:3] + [lab], answer=lab,
                objectivity='verbatim',
                evidence=[f'本文原文：「{lab}」と答えたのは{pct}（第 {i+1} 句，逐字可核对）',
                          '三个干扰项都是本文其它项目的原文表述，各自对应的是别的数值'],
                explain='调查类报道的数字与项目必须一一对应，看错行就全错。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


_DATE_RE = re.compile(r'(\d{4})年(?:\s*(\d{1,2})月)?(?:\s*(\d{1,2})日)?|'
                      r'(?:今月|先月|来月)?\s*(\d{1,2})月(\d{1,2})日|今月(\d{1,2})日')


def _dates(P):
    out = []
    for i, s in enumerate(P.sents):
        for m in _DATE_RE.finditer(s):
            g = m.groups()
            if g[0]:
                key = (int(g[0]), int(g[1] or 1), int(g[2] or 1))
            elif g[3]:
                key = (9999, int(g[3]), int(g[4]))
            elif g[5]:
                key = (9999, 99, int(g[5]))
            else:
                continue
            out.append((i, key, m.group(0)))
    return out


def g_chronology(P, rng):
    """时间先后：由显式日期做算术比较，问哪件事最早/最晚发生。"""
    ds = _dates(P)
    uniq, seen = [], set()
    for i, key, raw in ds:
        if i in seen or key[0] == 9999 and key[1] == 99:
            continue
        seen.add(i)
        uniq.append((i, key, raw))
    same_scale = [x for x in uniq if x[1][0] != 9999]
    if len(same_scale) < 4:
        return []
    same_scale.sort(key=lambda x: x[1])
    out = []
    for mode, idx, word in (('first', 0, '最も古い'), ('last', -1, '最も新しい')):
        ans = same_scale[idx][2]
        opts = list(dict.fromkeys([x[2] for x in same_scale[:4]] + [ans]))
        if len(opts) < 4:
            continue
        ev = [f'{x[2]}（第 {x[0]+1} 句）' for x in same_scale[:5]]
        q = _mk('chronology',
                title='时间先后',
                prompt=f'本文に出てくる年月のうち、{word}ものはどれか',
                context='（本文全体を参照）',
                options=opts[:4], answer=ans,
                objectivity='rule',
                evidence=['四个选项都是本文原样出现的日期',
                          '本文日期一览：' + '、'.join(ev),
                          f'规则：日期先后由数值比较唯一确定（{word}＝{ans}）'],
                explain='长篇报道常把不同年份的事件穿插叙述，理清时间线是读懂因果的前提。',
                sent_idx=same_scale[idx][0])
        if _valid(q):
            out.append(q)
    return out


def g_heading(P, rng):
    """小标题匹配：只有当小标题含有「只属于该段落块」的实词时才出题。"""
    if len(P.headings) < 3:
        return []
    blocks = defaultdict(list)
    for i, pa in enumerate(P.para_of):
        blocks[pa].append(i)
    heads = []
    for h in P.headings:
        hw = [w for w in content_words(tag(h['text'])) if len(w) >= 2]
        # 该小标题管辖的块＝它自己所在段及其后、直到下一个小标题之前的段
        nxt = min([x['para'] for x in P.headings if x['para'] > h['para']] or [10 ** 6])
        own = [i for i, pa in enumerate(P.para_of) if h['para'] <= pa < nxt]
        if len(h['text']) < 6:
            continue                     # 「アメリカ」这类栏目标签不是小标题
        if own and hw:
            heads.append({'text': h['text'], 'own': own, 'words': hw})
    if len(heads) < 3:
        return []
    out = []
    for k, h in enumerate(heads):
        others = [x for x in heads if x is not h]
        own_txt = ''.join(P.sents[i] for i in h['own'])
        key = next((w for w in h['words']
                    if w in own_txt and
                    all(w not in ''.join(P.sents[i] for i in o['own']) for o in others)), None)
        if not key or not h['own']:
            continue
        rng.shuffle(others)
        q = _mk('heading',
                title='小标题匹配',
                prompt='次の段落に付く小見出しとして正しいものを選べ',
                context=P.sents[h['own'][0]][:120],
                options=[o['text'] for o in others[:3]] + [h['text']],
                answer=h['text'],
                objectivity='verbatim',
                evidence=[f'该段落与答案小标题共有关键词「{key}」，'
                          '而该关键词在其它小标题所管辖的段落里一次也不出现（唯一性已逐一验证）',
                          '答案＝原文中该段落实际使用的小标题'],
                explain='小标题是作者给出的段落主旨——用它训练"一眼抓住这段在说什么"。',
                sent_idx=h['own'][0])
        if _valid(q):
            out.append(q)
    return out


GENERATORS = {
    'connective': g_connective,
    'anaphora': g_anaphora,
    'particle': g_particle,
    'polite_tense': g_polite_tense,
    'insert': g_insert,
    'order': g_order,
    'truth': g_truth,
    'fact': g_fact,
    'quote': g_quote,
    'absent': g_absent,
    'headword': g_headword,
    'transitivity': g_transitivity,
    'compound_particle': g_compound_particle,
    'compare': g_compare,
    'pairing': g_pairing,
    'chronology': g_chronology,
    'heading': g_heading,
}

TYPE_LABEL = {
    'connective': '接续词还原', 'anaphora': '指示语照应', 'particle': '格助词还原',
    'polite_tense': '文体×时制', 'insert': '句子插入', 'order': '语序重排',
    'truth': '内容一致', 'fact': '数值检索', 'quote': '引语话者',
    'absent': '扫读辨词', 'headword': '复现词链',
    'transitivity': '自他动词×文体', 'compound_particle': '复合助词',
    'compare': '数值比较', 'pairing': '数值项目对应',
    'chronology': '时间先后', 'heading': '小标题匹配',
}

# 难度：easy＝局部一眼可定位；medium＝需要跨句；hard＝需要跨段整合或语法辨析
DIFFICULTY = {
    'absent': 'easy', 'fact': 'easy', 'headword': 'easy',
    'connective': 'medium', 'anaphora': 'medium', 'particle': 'medium',
    'quote': 'medium', 'truth': 'medium', 'pairing': 'medium',
    'chronology': 'medium', 'heading': 'medium',
    'polite_tense': 'hard', 'insert': 'hard', 'order': 'hard',
    'transitivity': 'hard', 'compound_particle': 'hard', 'compare': 'hard',
}

# 是否「开卷题」：扫读/检索类题目本来就该对着原文做（练的是定位速度），
# 闭卷题才是真正要考的记忆与推理，看原文会破坏效度 —— 见 README 反作弊设计。
TEXT_POLICY = {
    'absent': 'open', 'fact': 'open', 'compare': 'open', 'pairing': 'open',
    'chronology': 'open', 'heading': 'open', 'headword': 'open',
}


# ================================================================
# 8. 组卷
# ================================================================
def _gen_all(P, rng, want=None):
    pools = {}
    for t in (want or list(GENERATORS)):
        if t not in GENERATORS:
            continue
        try:
            qs = [q for q in GENERATORS[t](P, rng) if _valid(q)]
        except Exception:
            qs = []
        rng.shuffle(qs)
        if qs:
            pools[t] = qs
    return pools


def _decorate(q, pid, n):
    q['qid'] = f'{pid}-{n}'
    q['type_label'] = TYPE_LABEL.get(q['qtype'], q['qtype'])
    q['difficulty'] = DIFFICULTY.get(q['qtype'], 'medium')
    q['text_policy'] = TEXT_POLICY.get(q['qtype'], 'closed')
    return q


def make_quiz(passage_id, count=10, types=None, seed=None, difficulty=None, P=None):
    """出一套题。difficulty: None/'easy'/'medium'/'hard'/'mixed'（默认混合并向难侧倾斜）。"""
    P = P or load(passage_id)
    if not P:
        return {'ok': False, 'reason': '篇章不存在'}
    if not P.sents:
        return {'ok': False, 'reason': '这篇文章切不出正文句子'}
    if not any(P.toks):
        return {'ok': False, 'reason': '词法分析器不可用（fugashi/unidic 未安装），无法出题'}
    rng = random.Random(seed if seed is not None else time.time())
    pools = _gen_all(P, rng, types)
    if difficulty in ('easy', 'medium', 'hard'):
        pools = {t: v for t, v in pools.items()
                 if DIFFICULTY.get(t, 'medium') == difficulty}
    picked = []
    # 轮转抽取，保证题型多样；难题优先（hard → medium → easy）
    order = sorted(pools, key=lambda t: ({'hard': 0, 'medium': 1, 'easy': 2}[
        DIFFICULTY.get(t, 'medium')], t))
    while len(picked) < count and pools:
        progressed = False
        for t in order:
            if not pools.get(t):
                pools.pop(t, None)
                continue
            picked.append(pools[t].pop())
            progressed = True
            if len(picked) >= count:
                break
        if not progressed:
            break
    rng.shuffle(picked)
    for n, q in enumerate(picked):
        _decorate(q, passage_id, n)
        _finish(q, rng)
    return {'ok': True, 'passage_id': passage_id, 'title': P.title,
            'n_sent': len(P.sents), 'questions': picked,
            'available': {t: len(v) for t, v in pools.items()},
            'coverage': sorted({q['qtype'] for q in picked}),
            'difficulty_mix': dict(Counter(q['difficulty'] for q in picked))}


def preview_types(passage_id, P=None):
    """这篇文章每种题型各能出多少道。"""
    P = P or load(passage_id)
    if not P:
        return {}
    rng = random.Random(7)
    out = {}
    for t, fn in GENERATORS.items():
        try:
            out[t] = len([q for q in fn(P, rng) if _valid(q)])
        except Exception:
            out[t] = 0
    return out


def preview(text, title='', sample=3):
    """**不落库**：粘贴文本 → 解析结构 + 质量体检 + 可出题型统计 + 样题。
    让你先看清楚"系统把这篇文章读成了什么样"再决定要不要录入。"""
    rows = parse_text(text)
    P = Passage(title=title or next((t for _, k, t in rows if k == 'heading'), '')
                or (rows[0][2] if rows else ''), rows=rows)
    counts = preview_types(None, P=P)
    rng = random.Random(11)
    pools = _gen_all(P, rng)
    samples = []
    for t in sorted(pools, key=lambda x: ({'hard': 0, 'medium': 1, 'easy': 2}[
            DIFFICULTY.get(x, 'medium')], x)):
        q = _decorate(dict(pools[t][0]), 0, len(samples))
        _finish(q, rng)
        samples.append(q)
        if len(samples) >= sample:
            break
    return {
        'ok': True,
        'title': P.title,
        'n_para': len({r[0] for r in rows}),
        'n_sent': len(P.sents),
        'n_heading': len(P.headings),
        'n_char': len(text or ''),
        'headings': [h['text'] for h in P.headings],
        'paragraphs': [[t for pa, k, t in rows if pa == g and k == 'body']
                       for g in sorted({r[0] for r in rows})],
        'dropped_lines': _dropped_lines(text),
        'quality': quality_report(rows),
        'counts': counts,
        'total_questions': sum(counts.values()),
        'samples': samples,
    }


def _dropped_lines(text):
    """被当作样板/时间戳丢掉的行，在预览里如实列出，避免"我的正文哪去了"。"""
    out = []
    for raw in normalize(text or '').split('\n'):
        ln = raw.strip()
        if ln and (_BOILER_RE.match(ln) or _TS_RE.match(ln)):
            out.append(ln)
    return out[:20]


def record_results(passage_id, results):
    init()
    rows = [(time.time(), passage_id, r.get('qtype', ''),
             1 if r.get('ok') else 0, 1 if r.get('peeked') else 0)
            for r in (results or [])]
    if not rows:
        return {'ok': True, 'saved': 0}
    with db.get_conn() as c:
        c.executemany('INSERT INTO passage_results(ts,passage_id,qtype,ok,peeked)'
                      ' VALUES(?,?,?,?,?)', rows)
    clean = [r for r in rows if not r[4]]
    db.log('passage_quiz', json.dumps(
        {'passage_id': passage_id, 'n': len(rows), 'ok': sum(r[3] for r in rows),
         'peeked': sum(r[4] for r in rows)}, ensure_ascii=False))
    return {'ok': True, 'saved': len(rows), 'closed_book': len(clean)}


def stats(days=14):
    init()
    since = time.time() - days * 86400
    with db.get_conn() as c:
        rs = c.execute('SELECT qtype, COUNT(*) n, SUM(ok) ok, SUM(peeked) pk'
                       ' FROM passage_results WHERE ts>=? GROUP BY qtype',
                       (since,)).fetchall()
    by = {r['qtype']: {'n': r['n'], 'ok': r['ok'] or 0, 'peeked': r['pk'] or 0,
                       'label': TYPE_LABEL.get(r['qtype'], r['qtype']),
                       'rate': round(100 * (r['ok'] or 0) / r['n']) if r['n'] else 0}
          for r in rs}
    tot = sum(v['n'] for v in by.values())
    ok = sum(v['ok'] for v in by.values())
    pk = sum(v['peeked'] for v in by.values())
    return {'days': days, 'total': tot, 'ok': ok, 'peeked': pk,
            'rate': round(100 * ok / tot) if tot else 0, 'by_type': by}

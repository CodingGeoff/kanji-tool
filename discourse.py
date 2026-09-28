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
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_psents ON passage_sents(passage_id, idx);
CREATE TABLE IF NOT EXISTS passage_results(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL,
    passage_id INTEGER,
    qtype TEXT,
    ok INTEGER
);
CREATE INDEX IF NOT EXISTS idx_presults ON passage_results(ts);
'''


def init():
    with db.get_conn() as c:
        c.executescript(DDL)


_SENT_END_RE = re.compile(r'(?<=[。！？!?])')
_MIN_SENT = 6


def normalize(text):
    t = str(text or '').replace('\r\n', '\n').replace('\r', '\n')
    t = t.replace('\u3000', ' ').replace('\ufeff', '')
    return t


def split_paragraphs(text):
    """空行分段；没有空行时每个非空行视为一段。"""
    t = normalize(text)
    if re.search(r'\n\s*\n', t):
        raw = re.split(r'\n\s*\n+', t)
    else:
        raw = t.split('\n')
    return [re.sub(r'\s*\n\s*', '', p).strip() for p in raw if p.strip()]


def split_sentences(para):
    """段内切句：按句末标点切，保留标点；引号内的句点不切。"""
    s, out, depth, buf = str(para or ''), [], 0, ''
    for ch in s:
        buf += ch
        if ch in '「『（(':
            depth += 1
        elif ch in '」』）)':
            depth = max(0, depth - 1)
        elif ch in '。！？!?' and depth == 0:
            out.append(buf.strip())
            buf = ''
    if buf.strip():
        out.append(buf.strip())
    return [x for x in out if len(x) >= 2]


def import_passage(title, text, source='', level='', note=''):
    """录入一篇文章。返回 {'id','n_para','n_sent','n_char'}。"""
    init()
    text = normalize(text).strip()
    if not text:
        raise ValueError('正文为空')
    paras = split_paragraphs(text)
    title = (str(title or '').strip() or (paras[0][:24] if paras else '未命名篇章'))
    rows, si = [], 0
    for pi, p in enumerate(paras):
        for s in split_sentences(p):
            rows.append((pi, si, s))
            si += 1
    if not rows:
        raise ValueError('切不出任何句子')
    now = time.time()
    with db.get_conn() as c:
        cur = c.execute(
            'INSERT INTO passages(title,source,level,note,text,n_para,n_sent,n_char,created_at,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?)',
            (title, source, level, note, text, len(paras), len(rows), len(text), now, now))
        pid = cur.lastrowid
        c.executemany('INSERT INTO passage_sents(passage_id,para_idx,idx,text) VALUES(?,?,?,?)',
                      [(pid, a, b, t) for a, b, t in rows])
    db.log('passage_import', json.dumps(
        {'id': pid, 'title': title, 'sents': len(rows)}, ensure_ascii=False))
    return {'id': pid, 'title': title, 'n_para': len(paras),
            'n_sent': len(rows), 'n_char': len(text)}


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
        ss = c.execute('SELECT para_idx,idx,text FROM passage_sents WHERE passage_id=?'
                       ' ORDER BY idx', (pid,)).fetchall()
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
    def __init__(self, row):
        self.id = row.get('id')
        self.title = row.get('title', '')
        self.text = row.get('text', '')
        self.sents = [s['text'] for s in row.get('sentences', [])]
        self.para_of = [s['para_idx'] for s in row.get('sentences', [])]
        self.toks = [tag(s) for s in self.sents]
        self.cwords = [content_words(t) for t in self.toks]
        self.freq = Counter(w for ws in self.cwords for w in ws)

    def paras(self):
        d = defaultdict(list)
        for i, p in enumerate(self.para_of):
            d[p].append(i)
        return [d[k] for k in sorted(d)]

    def joined(self):
        return ''.join(self.sents)


def load(pid):
    row = get_passage(pid)
    return Passage(row) if row else None


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
            head = ''.join(x['s'] for x in toks[:j])
            tail = ''.join(x['s'] for x in toks[j + 1:])
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
        head = ''.join(x['s'] for x in toks[:vi])
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
    paras = P.paras()
    for idxs in paras:
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
    for idxs in P.paras():
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
}

TYPE_LABEL = {
    'connective': '接续词还原', 'anaphora': '指示语照应', 'particle': '格助词还原',
    'polite_tense': '文体×时制', 'insert': '句子插入', 'order': '语序重排',
    'truth': '内容一致', 'fact': '数值检索', 'quote': '引语话者',
    'absent': '扫读辨词', 'headword': '复现词链',
}


# ================================================================
# 8. 组卷
# ================================================================
def make_quiz(passage_id, count=10, types=None, seed=None):
    P = load(passage_id)
    if not P:
        return {'ok': False, 'reason': '篇章不存在'}
    if not P.toks or not any(P.toks):
        return {'ok': False, 'reason': '词法分析器不可用（fugashi/unidic 未安装），无法出题'}
    rng = random.Random(seed if seed is not None else time.time())
    want = [t for t in (types or list(GENERATORS)) if t in GENERATORS]
    pools = {}
    for t in want:
        try:
            qs = [q for q in GENERATORS[t](P, rng) if _valid(q)]
        except Exception:
            qs = []
        rng.shuffle(qs)
        if qs:
            pools[t] = qs
    picked, i = [], 0
    while len(picked) < count and pools:
        keys = sorted(pools)
        progressed = False
        for t in keys:
            if not pools[t]:
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
        q['qid'] = f'{passage_id}-{n}'
        _finish(q, rng)
        q['type_label'] = TYPE_LABEL.get(q['qtype'], q['qtype'])
    return {'ok': True, 'passage_id': passage_id, 'title': P.title,
            'n_sent': len(P.sents), 'questions': picked,
            'available': {t: len(v) for t, v in pools.items()},
            'coverage': sorted({q['qtype'] for q in picked})}


def preview_types(passage_id):
    """这篇文章每种题型各能出多少道（录入后立刻反馈可练强度）。"""
    P = load(passage_id)
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


def record_results(passage_id, results):
    init()
    rows = [(time.time(), passage_id, r.get('qtype', ''), 1 if r.get('ok') else 0)
            for r in (results or [])]
    if not rows:
        return {'ok': True, 'saved': 0}
    with db.get_conn() as c:
        c.executemany('INSERT INTO passage_results(ts,passage_id,qtype,ok) VALUES(?,?,?,?)', rows)
    db.log('passage_quiz', json.dumps(
        {'passage_id': passage_id, 'n': len(rows),
         'ok': sum(r[3] for r in rows)}, ensure_ascii=False))
    return {'ok': True, 'saved': len(rows)}


def stats(days=14):
    init()
    since = time.time() - days * 86400
    with db.get_conn() as c:
        rs = c.execute('SELECT qtype, COUNT(*) n, SUM(ok) ok FROM passage_results'
                       ' WHERE ts>=? GROUP BY qtype', (since,)).fetchall()
    by = {r['qtype']: {'n': r['n'], 'ok': r['ok'] or 0,
                       'rate': round(100 * (r['ok'] or 0) / r['n']) if r['n'] else 0}
          for r in rs}
    tot = sum(v['n'] for v in by.values())
    ok = sum(v['ok'] for v in by.values())
    return {'days': days, 'total': tot, 'ok': ok,
            'rate': round(100 * ok / tot) if tot else 0, 'by_type': by}

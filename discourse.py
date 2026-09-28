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
import hashlib
import json
import os
import random
import re
import threading
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
CREATE TABLE IF NOT EXISTS passage_item_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    passage_id INTEGER NOT NULL,
    stem TEXT NOT NULL,
    qtype TEXT,
    ts REAL,
    ok INTEGER,
    mode TEXT DEFAULT 'choice'
);
CREATE INDEX IF NOT EXISTS idx_pitem ON passage_item_log(passage_id, stem);
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


# 说话人标签 / 图片说明常见结尾（新闻正文里大量出现的「非句子行」）
_ROLE_TAIL = re.compile(
    r'(さん|氏|教授|名誉教授|准教授|課長|課長代理|局長|部長|社長|会長|大統領|首相|'
    r'知事|市長|町長|村長|議員|記者|担当|代表|所長|支局|理事長|委員長|監督|選手)$')
_PAREN_ONLY = re.compile(r'^[（(].*[）)]$')
_TAGLINE = re.compile(r'^[^\s]{1,12}$')


def classify_line(line, first=False):
    """把一行归类：body（正文句）/ heading（小标题）/ caption（图注·说话人标签·栏目标签）。
    新闻正文里有大量「不是句子」的行，混为一谈就会出坏题：
      「トランプ大統領」  → 说话人标签，不是小标题
      「電気代の明細書」  → 图片说明
      「クマ被害」        → 栏目标签
      「「AIを止めろ」」  → 独立成段的引语，**是正文**
    """
    if not line:
        return 'caption'
    # 1) **整行都是引语**（开头引号 + 结尾引号）＝ 独立成段的发言，是正文，
    #    往往还是全篇最精彩的部分。而「ハンター「あのようなクマは初めて」」
    #    「3分の2の自治体が「今後に不安」」这种引号只占一部分的，是小标题。
    if line[0] in '「『“' and line[-1] in '」』”':
        return 'body'
    if line[-1] in _SENT_FINAL:
        # 标题行常以「？」结尾（なぜ今進展？）：首行且不含句点时按标题处理
        if first and '。' not in line and len(line) <= 60:
            return 'heading'
        return 'body'
    if len(line) > 44:
        return 'body'          # 太长又没句号：当正文处理，交给后续门禁去筛
    if _PAREN_ONLY.match(line):
        return 'caption'       # （ワシントン支局記者 黒瀬総一郎）
    if _ROLE_TAIL.search(line):
        return 'caption'       # ショウさん / 伊吾田宏正 教授
    if re.search(r'[（(][^（()）]{1,20}[）)]$', line):
        return 'caption'       # 建設中のデータセンター（バージニア州）＝图片说明
    if '・' in line and ' ' not in line and len(line) <= 12:
        return 'caption'       # 文化・芸術・エンタメ
    if len(line) < 10 and _TAGLINE.match(line):
        return 'caption'       # クマ被害 / 深掘りコンテンツ / 長崎県
    if not any(t['p1'] in ('動詞', '形容詞', '助動詞') for t in tag(line)) and len(line) < 10:
        return 'caption'
    return 'heading'


def _is_heading(line):
    return classify_line(line) == 'heading'


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
    kind：'body'（正文句）/ 'heading'（小标题）/ 'caption'（图注·说话人标签·栏目标签）。
    对「一整篇报道」「几段话」「一段话」「一行字」都必须给出合理结果。"""
    rows, pi, first = [], 0, True
    for para in split_paragraphs(text):
        got = False
        for line in para:
            kind = classify_line(line, first=first)
            first = False
            if kind in ('heading', 'caption'):
                rows.append((pi, kind, line))
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
        quoted = t[:1] in '「『“'
        # 体言止め（「…笹木野地区。」）与引语段落是新闻体的正常写法，
        # 保守的语法门禁会大面积误报，这里先识别出来再决定报不报。
        toks = tag(t.rstrip('。！？!?'))
        taigen = bool(toks) and toks[-1]['p1'] in ('名詞', '接尾辞')
        if len(t) > (240 if quoted else 160):
            tags.append('超长句（可能没切干净，或原文本身是长句）')
        if not re.search(r'[ぁ-んァ-ヶ一-龥]', t):
            tags.append('不含日语文字（可能是残留的界面文字）')
        if t.count('「') != t.count('」'):
            tags.append('引号不配对（可能复制时截断）')
        if checker:
            try:
                r = checker(t)
                if not r.get('ok', True):
                    noise = ['随机', '拼接', 'ランダム']
                    if taigen:
                        noise += ['未检测到有效谓语']      # 体言止め
                    if quoted:
                        noise += ['未检测到有效谓语', '文献出处', '括号附注',
                                  '悬空终结']              # 引语原样保留
                    msgs = [m for m in (r.get('issues') or r.get('errors') or [])
                            if not any(k in str(m) for k in noise)]
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


_FURI_CACHE = {}


def furigana_rows(pid):
    """整篇文章的注音（按行返回 tokens），供阅读面板的「ふりがな」开关使用。
    一次算完并缓存——长文章逐句请求会把浏览器打爆。"""
    p = get_passage(pid)
    if not p:
        return []
    key = (pid, p.get('updated_at'))
    if _FURI_CACHE.get('key') == key:
        return _FURI_CACHE['rows']
    try:
        import furigana
    except Exception:
        return []
    rows = []
    for s in p['sentences']:
        try:
            rows.append({'idx': s['idx'], 'kind': s.get('kind') or 'body',
                         'tokens': furigana.annotate(s['text'])})
        except Exception:
            rows.append({'idx': s['idx'], 'kind': s.get('kind') or 'body',
                         'tokens': [{'s': s['text']}]})
    _FURI_CACHE.clear()
    _FURI_CACHE.update({'key': key, 'rows': rows})
    return rows


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
    if n:
        corpus_invalidate()      # 语料变了：倒排索引与实证计数立即作废重算
    return n


# ================================================================
# 0.7 内置篇章种子（samples/*.txt）
# ----------------------------------------------------------------
# 为什么需要它：仓库根目录的 kanji.db 是 Render 的唯一初始数据源，而篇章
# 是在**运行时**录入的 —— 免费实例的磁盘又是临时的（重新部署即抹掉）。
# 结果就是「本地有 8 篇、线上一篇都没有」。
# 所以把随仓库走的 samples/*.txt 当成内置篇章：每次启动幂等补齐，
# 既不依赖数据库文件里有没有 passages 表，也不怕容器重建。
#
# 幂等规则（三重防重复）：
#   1. settings 里记下每个文件的内容指纹 → 录过就不再录；
#      用户删掉某篇后指纹还在，重启也不会「阴魂不散」地回来。
#   2. 库里已存在同样正文 → 跳过（本地手工录过同一篇的情形）。
#   3. 库里已存在同名标题 → 跳过（同一篇文章从网页重复粘贴，正文略有出入）。
# ================================================================
SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'samples')
SEED_SETTING = 'discourse_seed_v1'
_SEED_SOURCES = (('nhk', 'NHK NEWS WEB'),)
_seed_lock = threading.Lock()
_seed_done = False


def _seed_source(fname):
    """按文件名前缀标注出处，未知前缀留空（出处只是展示用，宁缺毋滥）。"""
    stem = os.path.basename(fname).lower()
    for prefix, label in _SEED_SOURCES:
        if stem.startswith(prefix + '_') or stem == prefix + '.txt':
            return label
    return ''


def _seed_meta(path):
    """可选的同名 .meta.json：{"title","source","level"}。
    `dbtool.py export-passages` 导出自己的篇章时会写它，
    这样标题/出处能原样带到云端，而不是只能从正文首行猜。"""
    mpath = path[:-4] + '.meta.json' if path.lower().endswith('.txt') else path + '.meta.json'
    try:
        with open(mpath, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def seed_files(dirpath=None):
    d = dirpath or SEED_DIR
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in sorted(os.listdir(d))
            if n.lower().endswith('.txt') and not n.startswith('_')]


def _fingerprint(text):
    return hashlib.sha1(normalize(text).strip().encode('utf-8')).hexdigest()[:16]


def _seed_state():
    try:
        st = json.loads(db.get_setting(SEED_SETTING) or '{}')
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _save_seed_state(state):
    try:
        db.set_setting(SEED_SETTING, json.dumps(state, ensure_ascii=False))
    except Exception:
        pass


def seed_builtin(dirpath=None, force=False, to_corpus=True):
    """把 samples/*.txt 录入篇章库（可重复执行，不会产生重复篇章）。

    force=True 只忽略「录过」的记号（用于手动重新载入），
    正文/标题撞车的去重依旧生效。返回 {'added': [...], 'skipped': [...]}。
    """
    init()
    files = seed_files(dirpath)
    state = _seed_state()
    added, skipped = [], []
    if not files:
        return {'ok': True, 'added': added, 'skipped': skipped, 'files': 0}
    with db.get_conn() as c:
        rows = c.execute('SELECT title, text FROM passages').fetchall()
    known_text = {_fingerprint(r['text']) for r in rows}
    known_title = {(r['title'] or '').strip() for r in rows}
    for path in files:
        name = os.path.basename(path)
        try:
            with open(path, encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            skipped.append({'file': name, 'reason': '读取失败：%s' % e})
            continue
        fp = _fingerprint(text)
        if not force and state.get(name) == fp:
            skipped.append({'file': name, 'reason': '已录入过'})
            continue
        if fp in known_text:
            state[name] = fp
            skipped.append({'file': name, 'reason': '库中已有同样正文'})
            continue
        meta = _seed_meta(path)
        try:
            r = import_passage(str(meta.get('title') or ''), text,
                               source=str(meta.get('source') or _seed_source(name)),
                               level=str(meta.get('level') or ''),
                               note='内置篇章 · %s' % name, to_corpus=to_corpus)
        except Exception as e:
            skipped.append({'file': name, 'reason': '解析失败：%s' % e})
            continue
        if (r.get('title') or '').strip() in known_title:
            # 同一篇文章已经被手工录过（正文略有出入）→ 撤销本次录入，只留旧的
            delete_passage(r['id'])
            state[name] = fp
            skipped.append({'file': name, 'reason': '库中已有同名篇章'})
            continue
        known_text.add(fp)
        known_title.add((r.get('title') or '').strip())
        state[name] = fp
        added.append({'file': name, 'id': r['id'], 'title': r['title'],
                      'n_sent': r['n_sent'], 'corpus_added': r.get('corpus_added', 0)})
    _save_seed_state(state)
    if added:
        db.log('passage_seed', json.dumps(
            {'added': len(added), 'titles': [a['title'] for a in added]},
            ensure_ascii=False))
    return {'ok': True, 'added': added, 'skipped': skipped, 'files': len(files)}


def ensure_seeded(force=False):
    """进程内只跑一次的补种入口（app 启动时调用，失败绝不影响启动）。"""
    global _seed_done
    if os.environ.get('KANJI_SEED_PASSAGES', '1').strip().lower() in ('0', 'off', 'false', 'no'):
        return {'ok': True, 'added': [], 'skipped': [], 'files': 0, 'disabled': True}
    with _seed_lock:
        if _seed_done and not force:
            return {'ok': True, 'added': [], 'skipped': [], 'files': 0, 'cached': True}
        try:
            r = seed_builtin(force=force)
        except Exception as e:
            return {'ok': False, 'error': str(e), 'added': [], 'skipped': []}
        _seed_done = True
        return r


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
    _PASSAGE_CACHE.pop(pid, None)
    _CAP_CACHE.pop(pid, None)        # 题量/题型统计缓存一并清掉
    _PVT_CACHE.pop(pid, None)
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

# ---- v23 性能：语料倒排索引 -----------------------------------------------
# corpus_count 原来是一条 LIKE '%…%' 全表扫描：一次 capacity() / make_quiz()
# 要扫上千次（每次 ~2.3ms，一篇长文合计约 3 秒）。语料实证只问一件事——
# 「包含某子串的句子有几句」，而子串基本都是「名词+助词」这种短串，
# 所以把整个语料库压成一个字符 bigram → 句子id集合 的倒排索引：
#   1. 查询串的任何一个 bigram 在索引里不存在 → 该串必然零命中，直接返回 0；
#   2. 否则取最短的一张倒排表当候选（真命中一定在里面），再逐句 in 精确核对。
# 实测本库（1.9 万句）1134 个真实查询 2.8s → 0.004s，结果与 SQL 完全一致；
# 倒排不可用时（读库失败 / 语料大到内存放不下）自动退回原 SQL 扫描。
_CORPUS_IDX = None            # None=未构建  False=不可用(退回SQL)  (texts, postings)=就绪
_CORPUS_IDX_MAX = 80000       # 语料句数超过这个值就不再建索引（保护小内存容器）
_CORPUS_IDX_LOCK = threading.Lock()
_CORPUS_STAMP = None          # (MAX(rowid), COUNT(*))：语料版本戳
_CORPUS_STAMP_AT = 0.0        # 版本戳上次核对时间：限频，每秒最多查一次


def corpus_invalidate():
    """语料变动后立即作废倒排索引与计数缓存（add_to_corpus 等入库路径调用）。
    交给时间限频的版本戳也能兜住，这里只是让「刚录入的句子立刻参与实证」。"""
    global _CORPUS_IDX, _CORPUS_STAMP, _CORPUS_STAMP_AT
    with _CORPUS_IDX_LOCK:
        _CORPUS_IDX = None
        _CORPUS_STAMP = None
        _CORPUS_STAMP_AT = 0.0
    _CORPUS_CACHE.clear()


def _corpus_index():
    """惰性构建倒排索引；语料有增删（版本戳变化）时自动重建。
    任何一步失败都返回 None，corpus_count 会退回 SQL 扫描，功能不受影响。"""
    global _CORPUS_IDX, _CORPUS_STAMP, _CORPUS_STAMP_AT
    now = time.time()
    idx = _CORPUS_IDX
    if idx and now - _CORPUS_STAMP_AT < 1.0:
        return idx                                   # 热路径：1 秒内核对过版本
    with _CORPUS_IDX_LOCK:
        idx = _CORPUS_IDX
        if idx and now - _CORPUS_STAMP_AT < 1.0:
            return idx                               # 别的线程刚核对过
        # 版本戳：MAX(rowid) 走索引末尾、COUNT(*) 走最小索引，都在微秒级
        if now - _CORPUS_STAMP_AT >= 1.0:
            try:
                with db.get_conn() as c:
                    r = c.execute('SELECT MAX(rowid) m, COUNT(*) n FROM sentences').fetchone()
                stamp = (r['m'], r['n'])
            except Exception:
                return idx or None
            _CORPUS_STAMP_AT = now
            if _CORPUS_STAMP is not None and stamp != _CORPUS_STAMP:
                _CORPUS_STAMP = stamp                # 语料变了：旧索引/旧计数全部作废
                _CORPUS_IDX = None
                _CORPUS_CACHE.clear()
                idx = None
            else:
                _CORPUS_STAMP = stamp
        if _CORPUS_IDX is False:
            return None                              # 语料太大：内存优先，退回 SQL
        if _CORPUS_IDX is not None:
            return _CORPUS_IDX
        try:
            with db.get_conn() as c:
                n = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
                if n > _CORPUS_IDX_MAX:
                    _CORPUS_IDX = False
                    return None
                texts = [r[0] for r in c.execute('SELECT text FROM sentences')]
        except Exception:
            return None
        postings = {}
        for i, t in enumerate(texts):
            for j in range(len(t) - 1):
                g = t[j:j + 2]
                s = postings.get(g)
                if s is None:
                    postings[g] = {i}
                else:
                    s.add(i)
        _CORPUS_IDX = (texts, postings)
        return _CORPUS_IDX


def _index_count(sub, texts, postings):
    """倒排求候选 + 原文精确复核：结果与 LIKE 扫描逐条一致。"""
    L = len(sub)
    if L < 2:
        return sum(1 for t in texts if sub in t)
    best = None
    for j in range(L - 1):
        p = postings.get(sub[j:j + 2])
        if not p:
            return 0                                 # 语料里没有这个 bigram → 必然零命中
        if best is None or len(p) < len(best):
            best = p                                 # 最短倒排表：真命中必在其中
    return sum(1 for i in best if sub in texts[i])


def corpus_count(sub):
    """语料库里包含该字符串的句子数；库不可用时返回 -1（表示无法取证）。"""
    if not sub:
        return 0
    hit = _CORPUS_CACHE.get(sub)
    if hit is not None:
        return hit
    n = -1
    idx = _corpus_index()
    if idx is not None:
        n = _index_count(sub, idx[0], idx[1])
    else:
        try:
            with db.get_conn() as c:
                r = c.execute("SELECT COUNT(*) n FROM sentences WHERE text LIKE ? ESCAPE '\\'",
                              ('%' + sub.replace('\\', '\\\\').replace('%', '\\%')
                               .replace('_', '\\_') + '%',)).fetchone()
            n = int(r['n'])
        except Exception:
            n = -1
    if len(_CORPUS_CACHE) > 4000:      # 防抖动：丢最旧的一半，而不是全清重来
        for k in list(_CORPUS_CACHE)[:2000]:
            _CORPUS_CACHE.pop(k, None)
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
    # stem＝这道题的「题干身份」：同一个挖空位置无论换多少套干扰项、
    # 换选择还是填空，stem 都相同。曝光调度按 stem 记账，
    # 这样「这篇文章还有多少题没做过」才是诚实的数字。
    q.setdefault('stem', f"{qtype}:{q.get('sent_idx', 0)}:"
                         f"{str(q.get('answer', ''))[:12]}")
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
        self.captions = []
        for pa, kind, t in rows:
            if kind == 'heading':
                self.headings.append({'para': pa, 'text': t})
            elif kind == 'caption':
                self.captions.append({'para': pa, 'text': t})
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


_PASSAGE_CACHE = {}
_CAP_CACHE = {}       # pid -> (key, 题量统计的静态部分)   内容/语料不变就不再重算
_PVT_CACHE = {}       # pid -> (key, 各题型可出题数)       同上


def load(pid, refresh=False):
    """读一篇文章（带缓存）。万字级长文的形态素分析约 1~3 秒，
    组卷/预览/统计会反复用到同一篇，缓存后只付一次代价。"""
    row = get_passage(pid)
    if not row:
        _PASSAGE_CACHE.pop(pid, None)
        return None
    key = (row.get('updated_at'), row.get('n_sent'))
    if not refresh:
        hit = _PASSAGE_CACHE.get(pid)
        if hit and hit[0] == key:
            return hit[1]
    rows = [(s['para_idx'], s.get('kind') or 'body', s['text'])
            for s in row['sentences']]
    P = Passage(title=row.get('title', ''), rows=rows, pid=pid)
    P.cache_key = key                # 题量/题型统计的缓存键（内容变了统计才要重算）
    if len(_PASSAGE_CACHE) > 12:
        _PASSAGE_CACHE.clear()
    _PASSAGE_CACHE[pid] = (key, P)
    return P


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
                sent_idx=i, pool_n=len(pool))
        if _valid(q):
            out.append(q)
    return out


# 「そのうえ/そのため/そのほか…」是固定接续表达，不是照应；
# 「多く/一部/ほとんど」是量化表达，填回去也不构成指代链。
_FIXED_DEM = {'そのうえ', 'そのため', 'そのほか', 'そのころ', 'そのまま', 'そのあと',
              'そのとき', 'その後', 'その間', 'その際', 'そのほう', 'この間',
              'このため', 'このほか', 'このころ', 'このとき', 'このうち', 'その一方'}
_ANA_STOP = {'多く', '一部', 'ほとんど', '全部', '半分', '結果', '通り', '以上',
             '以下', '前後', '程度', '場合', '状態'}


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
            if nx['p1'] != '名詞' or nx['p2'] != '普通名詞' or len(nx['s']) < 2:
                continue
            if nx['p3'] not in ('一般', 'サ変可能'):
                continue
            noun = nx['s']
            if noun in _ANA_STOP or (t['s'] + noun) in _FIXED_DEM:
                continue
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
                    evidence=[f'答案「{noun}」为原文用词；在本句之前的正文中逐字检索到 '
                              f'{before.count(noun)} 次（第 {P.sents.index(next(x for x in P.sents[:i] if noun in x)) + 1} 句起），'
                              '构成指示语照应链',
                              '三个干扰项在全篇仅出现 1 次、且不在本句中，不存在可被「' + t['s'] + '」回指的先行词'],
                    explain=f'「{t["s"]}＋名詞」必须回指前文已提到的事物，这里指的是前文的「{noun}」。',
                    sent_idx=i, stem=f'anaphora:{i}:{j}', pool_n=len(cand))
            if _valid(q):
                out.append(q)
    return out


_CASE_P = ['が', 'を', 'に', 'で', 'へ', 'と', 'から', 'まで', 'より']
_EQUIV = [{'は', 'が'}, {'に', 'へ'}, {'は', 'も'}, {'が', 'も'}, {'に', 'で'}, {'から', 'より'}]


def _equiv(a, b):
    return any({a, b} <= g for g in _EQUIV)


# 形式上是名词、实际已固化为副词/接续表达的词：它们后面的「に/と/で」
# 不是格关系，挖空会变成无解的怪题
_ADV_FOSSIL = {'とも', 'ため', 'ほか', 'うえ', 'ころ', 'まま', 'とおり', 'ごと',
               'ぶり', '以上', '以下', '以外', '以来', '一方', 'あまり', 'ほど',
               'かぎり', 'うち', 'さい', 'とき', 'ばあい', 'もと', 'なか'}


def g_particle(P, rng):
    """格助词还原：干扰项必须在语料库里与该名词「零共现」，否则不出题。"""
    out = []
    for i, toks in enumerate(P.toks):
        for j, t in enumerate(toks):
            if t['p1'] != '助詞' or t['p2'] != '格助詞' or t['s'] not in _CASE_P:
                continue
            if j == 0 or len(toks[j - 1]['s']) < 2:
                continue
            prev = toks[j - 1]
            if prev['p1'] != '名詞' or prev['p2'] not in ('普通名詞', '固有名詞'):
                continue
            if prev['s'] in _ADV_FOSSIL:
                continue      # 「下院ともに」「そのうえに」这类固化副词表达不是格关系
            noun, ans = prev['s'], t['s']
            # 名词若是更长复合词的一部分（データ|センター），取完整的名词串做检索键，
            # 否则「センターに」这种半截词会让语料检索失真
            k0 = j - 1
            while k0 > 0 and toks[k0 - 1]['p1'] == '名詞' and \
                    toks[k0 - 1]['p2'] in ('普通名詞', '固有名詞'):
                k0 -= 1
            full_noun = ''.join(x['s'] for x in toks[k0:j])
            if corpus_count(full_noun + ans) >= 1:
                noun = full_noun
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
                    sent_idx=i, stem=f'particle:{i}:{j}', pool_n=len(distr),
                    probe=noun)
            if _valid(q):
                out.append(q)
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
_DIGIT_RE = re.compile(r'^[0-9０-９][0-9０-９,，]*$')


def _num_value(tok):
    """数詞的字面数值；不是纯数字（「数」「何」「十数」等）返回 None。
    只有纯数字才适合互换：把「数年」换成「3年」不构成矛盾（3 年本来就是数年），
    换出来的不是错误项，是送分项。"""
    s = tok.replace(',', '').replace('，', '')
    if not _DIGIT_RE.match(tok):
        return None
    try:
        return int(s.translate(str.maketrans('０１２３４５６７８９', '0123456789')))
    except ValueError:
        return None


def _num_swappable(a, b):
    """两个数值能否互换：都得是纯数字，且量级同档。
    「3年前」的 3 和「2023年」的 2023 共用量词「年」，直接换会造出
    「2023年前」这种不成话的说法——量级门禁就是拦它的。"""
    va, vb = _num_value(a), _num_value(b)
    if va is None or vb is None:
        return False
    return (va >= 1000) == (vb >= 1000)


def _swap_number(s, toks, numbank, skip=0, used=()):
    """把句中「数詞＋量词」的数值换成本文别处**同一量词**下的另一个数值。
    只换同量词，保证改写后依然是合法的日语数量表达，错在事实而不是语法。

    skip / used：同一句里可能有多处数量表达，换不同的位置或换成不同的值，
    就能从一句里稳定产出两个互不相同、且都自然的错误项。
    """
    hit = 0
    for j, t in enumerate(toks):
        if t['p2'] != '数詞' or j + 1 >= len(toks):
            continue
        nxt = toks[j + 1]
        if not (nxt['p3'] in ('助数詞可能', '助数詞') or
                (nxt['p1'] == '接尾辞' and nxt['p2'] == '名詞的')):
            continue
        alts = [n for n in numbank.get(nxt['s'], [])
                if n != t['s'] and n not in used and _num_swappable(t['s'], n)]
        if not alts:
            continue
        if hit < skip:
            hit += 1
            continue
        for rep in alts:
            new = ''.join(x['s'] for x in toks[:j]) + rep + \
                ''.join(x['s'] for x in toks[j + 1:])
            # 「2メートルから3メートル」换成「2メートルから2メートル」这种
            # 上下限相同的区间是坏说法，不是错事实，换下一个候选值。
            if f'{rep}{nxt["s"]}から{rep}{nxt["s"]}' in new:
                continue
            return (new,
                    f'数量「{t["s"]}{nxt["s"]}」→「{rep}{nxt["s"]}」，与原文陈述的数量矛盾')
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
    """把主语与宾语互换，制造「施受关系相反」的错误项。

    互换后的两个格关系都必须有语料实证，否则造出的是**坏句**而不是**错句**：
    「日本擁壁保証協会は…調査を行いました」互换成「…協会を行いました」——
    考生不用回原文，靠语感就知道这句不像话，题目失去区分度。
    门禁：换到宾语位的名词必须在语料库里出现过「N を」，
    换到主语位的名词必须出现过「N が/は」。一个不满足就不出这个错误项。
    """
    ga = wo = None
    for j, t in enumerate(toks):
        if t['p1'] == '助詞' and t['s'] in ('が', 'は') and j and _plain_noun(toks, j - 1):
            if ga is None:
                ga = (j - 1, toks[j - 1]['s'], t['s'])
        if t['p1'] == '助詞' and t['s'] == 'を' and j and _plain_noun(toks, j - 1):
            if wo is None:
                wo = (j - 1, toks[j - 1]['s'], t['s'])
    if not ga or not wo or ga[1] == wo[1]:
        return None, None
    if corpus_count(wo[1] + ga[2]) < 1:          # 原宾语能否当主语
        return None, None
    if corpus_count(ga[1] + 'を') < 1:           # 原主语能否当宾语
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
            f'把动作主体「{ga[1]}」与对象「{wo[1]}」互换，施受关系与原文相反'
            f'（「{wo[1]}{ga[2]}」「{ga[1]}を」在语料库中都有实证，'
            f'错在事实而不是语法）')


_PROPER_KIND = {'地名': '地点', '人名': '人物'}
_GLUE = ('名詞', '接尾辞', '接頭辞')


def _proper_standalone(toks, j):
    """toks[j] 这个固有名詞是不是**独立**的一个名词短语——
    左右都不粘着别的名词性成分。否则换掉它只是改了复合名的一半：
    「NTT西日本」会变成「NTT西長崎」、「首都ワシントン」会变成
    「首都アメリカ」，那是坏词，不是错事实。"""
    prv = toks[j - 1] if j else None
    nxt = toks[j + 1] if j + 1 < len(toks) else None
    if prv and prv['p1'] in _GLUE:
        return False
    if nxt and nxt['p1'] in _GLUE:
        return False
    return True


def _proper_bank(P):
    """全篇的固有名詞，按子类（地名/人名/一般）分桶，供「同类替换」造错误项。
    只收「后面直接跟助词/句读点」的，避免把复合名的一半换掉造出假名字。"""
    bank = defaultdict(list)
    for toks in P.toks:
        for j, t in enumerate(toks):
            if t['p1'] != '名詞' or t['p2'] != '固有名詞' or len(t['s']) < 2:
                continue
            if not _proper_standalone(toks, j):
                continue
            if t['s'] not in bank[t['p3'] or '一般']:
                bank[t['p3'] or '一般'].append(t['s'])
    return bank


def _swap_proper(s, toks, bank, used=()):
    """把句中的固有名詞换成本文别处出现的**同类**固有名詞（地名↔地名、人名↔人名）。
    改写后依然是合法日语，只是把事实说错了——正是内容一致题需要的错误项。"""
    for j, t in enumerate(toks):
        if t['p1'] != '名詞' or t['p2'] != '固有名詞' or len(t['s']) < 2:
            continue
        if not _proper_standalone(toks, j):
            continue
        kind = t['p3'] or '一般'
        alts = [x for x in bank.get(kind, []) if x != t['s'] and x not in used]
        if not alts:
            continue
        rep = alts[0]
        new = ''.join(x['s'] for x in toks[:j]) + rep + \
            ''.join(x['s'] for x in toks[j + 1:])
        label = _PROPER_KIND.get(kind, '名称')
        return new, (f'把{label}「{t["s"]}」换成本文其它位置出现的「{rep}」，'
                     f'与原文陈述的{label}矛盾')
    return None, None


def _grammar_ok(text):
    """改写句必须仍然是合法日语：错要错在「与原文矛盾」，不能错在「不像话」，
    否则考生靠语感就能挑出唯一通顺的那句，题目失去区分度。"""
    try:
        import grammar
        return bool(grammar.is_sentence_grammatically_sound(text))
    except Exception:
        return True


def _swap_number2(s, toks, numbank, variants):
    """第二个数值型错误项：优先换**另一处**数量表达，没有第二处就把同一处
    换成**另一个**数值，两条路都要保证结果与已有错误项不同。"""
    v, note = _swap_number(s, toks, numbank, skip=1)
    if v and v not in variants:
        return v, note
    used = [n for ns in numbank.values() for n in ns
            if any(n in x for x in variants) and n not in s]
    return _swap_number(s, toks, numbank, used=tuple(used))


def _used_propers(variants, bank):
    """已经被用作替换词的固有名詞，避免两个错误项换成同一个词。"""
    used = []
    for names in bank.values():
        for n in names:
            if any(n in v for v in variants):
                used.append(n)
    return tuple(used)


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
    bank = _proper_bank(P)
    for i, s in enumerate(P.sents):
        if not (12 <= len(s) <= 70):
            continue
        toks = P.toks[i]
        variants, notes = [], []
        # 改写器按「错得干净」的程度排序：肯否定翻转最稳，数值/专有名词替换次之，
        # 施受互换最容易造出坏句（已加语料实证门禁，过不了就不用）。
        for fn in (lambda: _flip_polarity(s, toks),
                   lambda: _swap_number(s, toks, numbank),
                   lambda: _swap_proper(s, toks, bank),
                   lambda: _swap_number2(s, toks, numbank, variants),
                   lambda: _swap_proper(s, toks, bank,
                                        used=_used_propers(variants, bank)),
                   lambda: _swap_args(s, toks)):
            v, note = fn()
            if v and v != s and v not in variants and v not in P.joined() \
                    and _grammar_ok(v):
                variants.append(v)
                notes.append(note)
            if len(variants) >= 3:
                break
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
                        '只在肯否定 / 数值 / 专有名词 / 施受关系上与原文矛盾。',
                sent_idx=i)
        if _valid(q):
            out.append(q)
    return out


def g_fact(P, rng):
    """数值检索：挖掉句中的「数值＋量词」，干扰项为文中出现的其它数量表达。
    用正则在**原句字符串**上定位（而不是按形态素拼接），
    否则 69.9％ 会被切成「69」「.」「9」，挖出「9％」这种根本不存在的答案。"""
    items = []      # (句号, start, end, 原样, 数值部分, 单位)
    for i, s in enumerate(P.sents):
        for m in _NUM_UNIT_RE.finditer(s):
            items.append((i, m.start(), m.end(), m.group(0), m.group(1), m.group(2)))
    if len(items) < 2:
        return []
    out = []
    for (i, a, b, full, num, unit) in items:
        same = [x[3] for x in items if x[5] == unit and x[3] != full]
        other = [x[3] for x in items if x[5] != unit and x[3] != full]
        built = [x[4] + unit for x in items
                 if x[4] != num and (x[4] + unit) not in P.joined()]
        alts = [x for x in dict.fromkeys(same + other + built) if x != full]
        if len(alts) < 3:
            continue
        attested = set(same + other)
        src = P.sents[i]
        q = _mk('fact',
                title='数值检索',
                prompt='本文によると、空欄に入る数量表現はどれか',
                context=src[:a] + '＿＿' + src[b:],
                options=alts[:3] + [full], answer=full,
                objectivity='verbatim',
                evidence=[f'答案「{full}」是本文第 {i+1} 句原文原样',
                          '干扰项构成：' + '、'.join(
                              f'{x}（{"文中他处出现" if x in attested else "本文从未出现的数量组合"}）'
                              for x in alts[:3]),
                          '任一干扰项都可以回原句逐字核对排除，判定不依赖理解'],
                explain='回到原句逐字核对即可，训练的是定位与看清量词。',
                sent_idx=i, stem=f'fact:{i}:{a}', pool_n=len(alts))
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
    for k in range(min(8, len(outside), len(inside) // 3)):
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
                sent_idx=0, stem=f'absent:{outside[k]}', pool_n=len(inside))
        if _valid(q):
            out.append(q)
    return out


def g_headword(P, rng):
    """复现词链：全篇高频实词被全部挖空，考「这篇文章到底在反复说什么」。"""
    top = [w for w, n in P.freq.most_common(8) if n >= 3 and len(w) >= 2]
    out = []
    for key in top[:4]:
        q = _headword_item(P, rng, key)
        if q:
            out.append(q)
    return out


def _blank_token(P, i, key):
    """只把「独立成词」的那个 key 挖掉；若 key 只是更长词的一部分，返回 None。"""
    toks = P.toks[i]
    if not any(t['s'] == key for t in toks):
        return None
    return ''.join('＿＿' if t['s'] == key else t['s'] for t in toks)


def _headword_item(P, rng, key):
    hits = [i for i, s in enumerate(P.sents)
            if key in s and _blank_token(P, i, key)][:3]
    if len(hits) < 2:
        return None
    cand = [w for w, n in P.freq.items() if n == 1 and len(w) >= 2 and w != key]
    rng.shuffle(cand)
    if len(cand) < 3:
        return None
    ctx = '\n'.join(_blank_token(P, i, key) for i in hits)
    q = _mk('headword',
            title='复现词链',
            prompt='下の複数の文に共通して入る語を選べ',
            context=ctx,
            options=cand[:3] + [key], answer=key,
            objectivity='verbatim',
            evidence=[f'答案「{key}」是原文用词，全篇出现 {P.freq[key]} 次，是贯穿全篇的复现主词',
                      f'三个干扰项全篇各只出现 1 次，不可能同时填入这 {len(hits)} 个位置'],
            explain='能同时填进多处空的只有全篇的复现主词——这正是把握文章话题的抓手。',
            sent_idx=hits[0], stem=f'headword:{key}', pool_n=len(cand))
    return q if _valid(q) else None


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
                    sent_idx=i, stem=f'transitivity:{i}:{vi}')
            if _valid(q):
                out.append(q)
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
    hits = []
    for i, s in enumerate(P.sents):
        for k in keys:
            for m in re.finditer(re.escape(k), s):
                if not any(h[0] == i and h[1] <= m.start() < h[1] + len(h[2])
                           for h in hits):
                    hits.append((i, m.start(), k))
    for i, pos, hit in sorted(hits):
        s = P.sents[i]
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
                sent_idx=i, stem=f'cp:{i}:{pos}', pool_n=len(distr), probe=noun)
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
            # 选项要围着答案取邻居：问「最小」却给三个最大值，既不像题，
            # 也会让下面那行「排序」证据和答案对不上（曾经就是这个 bug）。
            picked = arr[-4:] if mode == 'min' else arr[:4]
            if all(x[1] != ans for x in picked):
                picked = picked[:3] + [arr[idx]]
            picked = list(dict.fromkeys(picked))
            picked.sort(key=lambda x: -x[0])
            opts = list(dict.fromkeys(x[1] for x in picked))
            if len(opts) < 4 or ans not in opts:
                continue
            q = _mk('compare',
                    title='数值比较',
                    prompt=f'本文に出てくる「{u}」の数値のうち、{word}ものはどれか',
                    context='（本文全体を参照）',
                    options=opts[:4], answer=ans,
                    objectivity='rule',
                    evidence=['四个选项都是本文原样出现的数值',
                              # 排序必须覆盖「这四个选项」且含答案，否则依据无法复核
                              '四个选项按大小排序：'
                              + ' > '.join(f'{x[1]}' for x in picked[:4]),
                              f'本文中「{u}」共出现 {len(arr)} 个不同数值，'
                              f'其中{word}的是 {ans}',
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
    # 篇章标题默认取自首个小标题（import_passage 里 title=(head or body)[:40]），
    # 而标题会一直显示在答题页顶栏——若拿它当答案就是当场泄题，这里整体排除。
    title_norm = (getattr(P, 'title', '') or '').strip()
    heads = []
    for h in P.headings:
        hw = [w for w in content_words(tag(h['text'])) if len(w) >= 2]
        # 该小标题管辖的块＝它自己所在段及其后、直到下一个小标题之前的段
        nxt = min([x['para'] for x in P.headings if x['para'] > h['para']] or [10 ** 6])
        own = [i for i, pa in enumerate(P.para_of) if h['para'] <= pa < nxt]
        if len(h['text']) < 6:
            continue                     # 「アメリカ」这类栏目标签不是小标题
        ht = h['text'].strip()
        if title_norm and len(title_norm) >= 4 and (
                ht == title_norm or ht.startswith(title_norm)):
            continue                     # 这个小标题就是篇章标题，顶栏已显示＝泄题，不能当答案
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
    'chronology': '时间先后', 'heading': '小标题匹配', 'multi': '多空还原',
}

# 难度：easy＝局部一眼可定位；medium＝需要跨句；hard＝需要跨段整合或语法辨析
DIFFICULTY = {
    'absent': 'easy', 'fact': 'easy', 'headword': 'easy',
    'connective': 'medium', 'anaphora': 'medium', 'particle': 'medium',
    'quote': 'medium', 'truth': 'medium', 'pairing': 'medium',
    'chronology': 'medium', 'heading': 'medium',
    'polite_tense': 'hard', 'insert': 'hard', 'order': 'hard',
    'transitivity': 'hard', 'compound_particle': 'hard', 'compare': 'hard',
    'multi': 'hard',
}

# 是否「开卷题」：扫读/检索类题目本来就该对着原文做（练的是定位速度），
# 闭卷题才是真正要考的记忆与推理，看原文会破坏效度 —— 见 README 反作弊设计。
TEXT_POLICY = {
    'absent': 'open', 'fact': 'open', 'compare': 'open', 'pairing': 'open',
    'chronology': 'open', 'heading': 'open', 'headword': 'open',
}


# ================================================================
# 7c. 多空题（组合式加难：同一句里同时挖 2 个位置）
# ================================================================
_MULTI_SRC = ('particle', 'compound_particle', 'connective', 'transitivity',
              'polite_tense', 'anaphora')


def make_multi(P, rng, pools, limit=40):
    """把同一句里的两个独立空组合成一道多空题。
    客观性完全继承自两个子题（各自的答案都是原文原样、各自的门禁都通过），
    判分规则：两个空都填对才算对 —— 不存在新的主观判断。
    组合数是 C(n,2)，这是题量从「线性」变「二次方」的关键。"""
    by_sent = defaultdict(list)
    for t in _MULTI_SRC:
        for q in pools.get(t, []):
            by_sent[q.get('sent_idx', -1)].append(q)
    out = []
    for si, qs in by_sent.items():
        if len(qs) < 2:
            continue
        cand = []
        for a in range(len(qs)):
            for b in range(a + 1, len(qs)):
                q1, q2 = qs[a], qs[b]
                if q1['answer'] == q2['answer']:
                    continue
                cand.append((q1, q2))
        rng.shuffle(cand)
        for q1, q2 in cand[:3]:
            ctx, order = _merge_context(P, si, q1, q2)
            if not ctx:
                continue
            if order[0] != q1['answer']:      # ① 在句中更靠前 → 保证 q1 对应 ①
                q1, q2 = q2, q1
            q = _mk('multi',
                    title='多空还原',
                    prompt='①②の空欄に入る組み合わせとして正しいものを選べ',
                    context=ctx,
                    options=[], answer='',
                    objectivity=('verbatim' if q1['objectivity'] == q2['objectivity'] == 'verbatim'
                                 else 'rule'),
                    evidence=['① ' + q1['evidence'][0], '② ' + q2['evidence'][0],
                              '两个空各自的门禁与单空题完全相同；本题判分＝两空都对才算对，'
                              '没有引入任何新的判断标准'],
                    explain=f'①＝{q1["answer"]}（{q1.get("title", "")}）；'
                            f'②＝{q2["answer"]}（{q2.get("title", "")}）。',
                    sent_idx=si,
                    stem=f'multi:{q1.get("stem")}+{q2.get("stem")}')
            # 选项＝两个空的答案/干扰项的 2×2 组合
            d1 = [o for o in q1['options'] if o != q1['answer']]
            d2 = [o for o in q2['options'] if o != q2['answer']]
            if not d1 or not d2:
                continue
            rng.shuffle(d1)
            rng.shuffle(d2)
            combos = [(q1['answer'], q2['answer']), (d1[0], q2['answer']),
                      (q1['answer'], d2[0]), (d1[0], d2[0])]
            q['options'] = [f'① {a} ／ ② {b}' for a, b in combos]
            q['answer'] = q['options'][0]
            q['sub_answers'] = [q1['answer'], q2['answer']]
            q['difficulty'] = 'hard'
            if _valid(q):
                out.append(q)
            if len(out) >= limit:
                return out
    return out


def _merge_context(P, si, q1, q2):
    """把两道单空题的挖空合并到同一句上。
    **① 永远是句中靠前的那个空**（返回的顺序同时决定 sub_answers 的顺序），
    否则题面会出现「（②）…（①）」这种读起来别扭的编号。位置算不准就放弃。"""
    src = P.sents[si] if 0 <= si < len(P.sents) else ''
    if not src:
        return None, None
    a1, a2 = q1['answer'], q2['answer']
    p1, p2 = src.find(a1), src.find(a2)
    if p1 < 0 or p2 < 0 or abs(p1 - p2) < max(len(a1), len(a2)):
        return None, None
    (pa, wa), (pb, wb) = sorted([(p1, a1), (p2, a2)])
    ctx = src[:pa] + '（①）' + src[pa + len(wa):pb] + '（②）' + src[pb + len(wb):]
    return ctx, (wa, wb)


# ================================================================
# 7d. 填空（自由输入）模式：同一个空的「困难版」
# ================================================================
# 只有答案短、且客观性为 verbatim（答案＝原文原样）的题才允许改成填空，
# 判分是字符串精确比对（做一次全角/半角、空白、引号的归一化），
# 不做任何"意思差不多就算对"的模糊判断。
_INPUT_OK_TYPES = ('particle', 'connective', 'compound_particle', 'anaphora',
                   'headword', 'fact', 'transitivity', 'polite_tense')


def normalize_answer(t):
    t = str(t or '').strip()
    t = t.translate(str.maketrans('０１２３４５６７８９％．　', '0123456789%. '))
    t = re.sub(r'[\s「」『』（）()]', '', t)
    return t


def can_input(q):
    return (q['qtype'] in _INPUT_OK_TYPES
            and q['objectivity'] in ('verbatim', 'rule')
            and 1 <= len(q['answer']) <= 10
            and '＿' not in q['answer'])


def to_input(q):
    """把一道选择题转成填空题（同一个 stem 的困难版）。"""
    q = dict(q)
    q['answer_format'] = 'input'
    q['difficulty'] = 'hard'
    q['hint'] = f'{len(q["answer"])} 文字'
    q['options'] = []
    q['stem'] = q.get('stem', '') + '#input'
    return q

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
    # 填空形态（to_input）已经把难度提到 hard，这里不覆盖
    q['difficulty'] = q.get('difficulty') or DIFFICULTY.get(q['qtype'], 'medium')
    q['text_policy'] = TEXT_POLICY.get(q['qtype'], 'closed')
    return q


def seen_stems(passage_id, days=None):
    """这篇文章里「已经做过」的 stem → 最近一次做的时间。"""
    init()
    try:
        with db.get_conn() as c:
            rs = c.execute('SELECT stem, MAX(ts) t, COUNT(*) n FROM passage_item_log'
                           ' WHERE passage_id=? GROUP BY stem', (passage_id,)).fetchall()
        return {r['stem']: (r['t'], r['n']) for r in rs}
    except Exception:
        return {}


def make_quiz(passage_id, count=10, types=None, seed=None, difficulty=None,
              P=None, mode='mixed', fresh_first=True, secure=False):
    """出一套题。
    mode      : 'choice'（全选择）/ 'input'（能填空的都填空）/ 'mixed'（默认：约 1/3 填空）
    fresh_first: 优先出这篇文章里你还没做过的题（做过的按最久未做排序）
    secure    : True 时返回的题目**不含答案/解析**，判分走 grade()（防止在页面源码里偷看）
    """
    P = P or load(passage_id)
    if not P:
        return {'ok': False, 'reason': '篇章不存在'}
    if not P.sents:
        return {'ok': False, 'reason': '这篇文章切不出正文句子'}
    if not any(P.toks):
        return {'ok': False, 'reason': '词法分析器不可用（fugashi/unidic 未安装），无法出题'}
    rng = random.Random(seed if seed is not None else time.time())
    pools = _gen_all(P, rng, types)
    multi = make_multi(P, rng, pools)
    if multi and (not types or 'multi' in types):
        pools['multi'] = multi
    if difficulty in ('easy', 'medium', 'hard'):
        pools = {t: [q for q in v] for t, v in pools.items()
                 if DIFFICULTY.get(t, 'medium') == difficulty or t == 'multi'}
        if difficulty != 'hard':
            pools.pop('multi', None)

    seen = seen_stems(passage_id) if fresh_first else {}
    for t in pools:
        pools[t].sort(key=lambda q: (seen.get(base_stem(q.get('stem', '')), (0, 0))[1],
                                     seen.get(base_stem(q.get('stem', '')), (0, 0))[0]))
        pools[t] = pools[t][::-1]          # pop() 从尾部取 → 先取没做过的

    picked = []
    order = sorted(pools, key=lambda t: ({'hard': 0, 'medium': 1, 'easy': 2}[
        DIFFICULTY.get(t, 'medium')], t))

    # 题型配额：一套题里单一题型最多占 1/4，避免短文出来的 20 道题里
    # 格助词就占了 5 道、剩下来回考同样的技能。轮转本身已经打散了题型，
    # 配额负责兜住「别的题型先用光、剩下的全由一种题型填满」这种情况。
    # 文章本身出不了那么多题型时再逐级放宽，宁可出满题数，并在返回值里
    # 如实标记放宽过（type_relaxed），页面据此提示「本篇可出题型有限」。
    strict = max(2, -(-count // 4))
    counts = Counter()
    cap_used = strict
    for cap in (strict, max(3, -(-count // 2)), count):
        cap_used = cap
        while len(picked) < count:
            progressed = False
            for t in order:
                if len(picked) >= count:
                    break
                if counts[t] >= cap or not pools.get(t):
                    continue
                picked.append(pools[t].pop())
                counts[t] += 1
                progressed = True
            if not progressed:
                break
        if len(picked) >= count:
            break
    pools = {t: v for t, v in pools.items() if v}

    # 选择 / 填空 分配
    n_input = 0
    for k, q in enumerate(picked):
        q['answer_format'] = 'choice'
        if mode == 'input' and can_input(q):
            picked[k] = to_input(q)
            n_input += 1
        elif mode == 'mixed' and can_input(q) and rng.random() < 0.35:
            picked[k] = to_input(q)
            n_input += 1

    rng.shuffle(picked)
    for n, q in enumerate(picked):
        _decorate(q, passage_id, n)
        if q.get('answer_format') != 'input':
            _finish(q, rng)
        else:
            q['answer_index'] = -1

    quiz_id = f'{passage_id}-{int(time.time()*1000)}-{rng.randrange(1 << 20)}'
    out_qs = [_strip_answers(q) for q in picked] if secure else picked
    if secure:
        _QUIZ_CACHE[quiz_id] = {'ts': time.time(), 'pid': passage_id,
                                'qs': {q['qid']: q for q in picked}}
        if len(_QUIZ_CACHE) > 60:
            for k2 in sorted(_QUIZ_CACHE, key=lambda x: _QUIZ_CACHE[x]['ts'])[:20]:
                _QUIZ_CACHE.pop(k2, None)
    fresh = sum(1 for q in picked if base_stem(q.get('stem')) not in seen)
    # rows：整篇文章的行（含小标题/图注），随卷一并下发——前端不用再发第二个
    # 请求去拉原文（那个接口还要算一遍各题型题量，冷启动时是又一个三秒）。
    row = get_passage(passage_id) or {}
    rows = [{'idx': s['idx'], 'para_idx': s['para_idx'],
             'kind': s.get('kind') or 'body', 'text': s['text']}
            for s in (row.get('sentences') or [])]
    return {'ok': True, 'quiz_id': quiz_id, 'passage_id': passage_id, 'title': P.title,
            'n_sent': len(P.sents), 'questions': out_qs, 'rows': rows,
            'available': {t: len(v) for t, v in pools.items()},
            'coverage': sorted({q['qtype'] for q in picked}),
            'n_input': n_input, 'n_fresh': fresh, 'secure': bool(secure),
            'type_mix': dict(Counter(q['qtype'] for q in picked)),
            'type_cap': strict, 'type_relaxed': cap_used > strict,
            'difficulty_mix': dict(Counter(q['difficulty'] for q in picked))}


_QUIZ_CACHE = {}


def _strip_answers(q):
    """secure 模式下发给前端的题面：不含答案、不含证据、不含解析。"""
    drop = ('answer', 'answer_index', 'evidence', 'explain', 'sub_answers', 'stem')
    return {k: v for k, v in q.items() if k not in drop}


def grade(quiz_id, qid, response):
    """服务端判分。返回 {ok, answer, evidence, explain}。
    选择题传选项文本或下标；填空题传输入的字符串。"""
    box = _QUIZ_CACHE.get(quiz_id)
    if not box or qid not in box['qs']:
        return {'ok': False, 'error': 'quiz_expired',
                'message': '这套题的服务端记录已过期（重开一套即可）'}
    q = box['qs'][qid]
    if q.get('answer_format') == 'input':
        ok = normalize_answer(response) == normalize_answer(q['answer'])
    else:
        if isinstance(response, int) or (isinstance(response, str) and response.isdigit()):
            idx = int(response)
            ok = 0 <= idx < len(q['options']) and q['options'][idx] == q['answer']
        else:
            ok = str(response).strip() == q['answer']
    log_item(box['pid'], q, ok)
    # sub_answers：多空题的两个正解（判分后回传，前端把它们分别填回 ①② 空框）
    return {'ok': True, 'correct': bool(ok), 'answer': q['answer'],
            'sub_answers': q.get('sub_answers') or None,
            'evidence': q['evidence'], 'explain': q.get('explain', ''),
            'objectivity': q['objectivity']}


def base_stem(stem):
    """填空形态的 stem 带 '#input' 后缀，曝光要记在同一个题干上。"""
    return str(stem or '').split('#')[0]


def log_item(passage_id, q, ok, mode=None):
    """按 stem 记录曝光：用于「还有多少题没做过」与优先出新题。"""
    init()
    try:
        with db.get_conn() as c:
            c.execute('INSERT INTO passage_item_log(passage_id,stem,qtype,ts,ok,mode)'
                      ' VALUES(?,?,?,?,?,?)',
                      (passage_id, base_stem(q.get('stem', '')), q.get('qtype', ''), time.time(),
                       1 if ok else 0, mode or q.get('answer_format', 'choice')))
    except Exception:
        pass


def capacity(passage_id, P=None):
    """诚实统计这篇文章的「题量天花板」：
      stems        —— 独立题干数（挖空位置数）
      deliveries   —— 计入「选择/填空」两种形态后的可交付题数
      variants     —— 再计入干扰项可替换组合后的不同题面数（下界估计）
      done / fresh —— 已做过 / 还没做过的题干数
    v23 性能：生成器跑出来的静态部分（stems/deliveries/variants/per_type）
    按篇章内容 + 语料版本缓存，列表页/反复打开不再重算；done/fresh 走
    曝光日志实时算，做完题立刻变。"""
    P = P or load(passage_id)
    if not P:
        return {}
    key = (P.id, getattr(P, 'cache_key', None), _CORPUS_STAMP)
    hit = _CAP_CACHE.get(passage_id) if P.id == passage_id else None
    if not hit or hit[0] != key:
        rng = random.Random(3)
        pools = _gen_all(P, rng)
        pools['multi'] = make_multi(P, rng, pools)
        stems, deliveries, variants = 0, 0, 0
        per_type = {}
        all_stems = set()
        for t, qs in pools.items():
            stems += len(qs)
            d = sum(2 if can_input(q) else 1 for q in qs)
            deliveries += d
            v = 0
            for q in qs:
                k = max(1, len(q['options']) - 1)
                n_pool = int(q.get('pool_n') or k)      # 只有明确知道候选池大小时才算组合
                v += max(1, _choose(max(n_pool, k), k))
            variants += v
            per_type[t] = {'stems': len(qs), 'deliveries': d}
            all_stems.update(base_stem(q.get('stem')) for q in qs)
        hit = (key, {'stems': stems, 'deliveries': deliveries, 'variants': variants,
                     'per_type': per_type, 'all_stems': all_stems})
        if P.id == passage_id:
            if len(_CAP_CACHE) > 24:
                for k2 in list(_CAP_CACHE)[:12]:
                    _CAP_CACHE.pop(k2, None)
            _CAP_CACHE[passage_id] = hit
    static = hit[1]
    seen = {base_stem(k) for k in seen_stems(passage_id)}
    all_stems = static['all_stems']
    return {'stems': static['stems'], 'deliveries': static['deliveries'],
            'variants': static['variants'], 'per_type': static['per_type'],
            'done': len(all_stems & seen), 'fresh': len(all_stems - seen)}


def all_capacities():
    """所有篇章的题量统计：列表页一次拿全，代替「每篇一个请求」的逐个慢加载。"""
    return {p['id']: capacity(p['id']) for p in list_passages()}


_warm_lock = threading.Lock()
_warm_on = {'v': False}


def warm_async(pids=None):
    """后台预热篇章统计（组卷用的生成器 + 语料倒排 + 题量/题型缓存）。
    列表页一打开就触发，等用户真点「开考 / 题量 / 题型」时已是热路径。"""
    with _warm_lock:
        if _warm_on['v']:
            return
        _warm_on['v'] = True

    def _w():
        try:
            if pids:
                for pid in pids:
                    capacity(pid)
                    preview_types(pid)
            else:
                all_capacities()
                for p in list_passages():
                    preview_types(p['id'])
        except Exception:
            pass
        finally:
            with _warm_lock:
                _warm_on['v'] = False

    threading.Thread(target=_w, daemon=True).start()


def _choose(n, k):
    from math import comb
    try:
        return comb(n, k)
    except Exception:
        return 1


def preview_types(passage_id, P=None):
    """这篇文章每种题型各能出多少道。
    v23 性能：结果按篇章内容缓存（固定随机种子，本身是确定性的）。"""
    P = P or load(passage_id)
    if not P:
        return {}
    cacheable = P.id == passage_id and getattr(P, 'cache_key', None) is not None
    if cacheable:
        hit = _PVT_CACHE.get(passage_id)
        if hit and hit[0] == P.cache_key:
            return dict(hit[1])
    rng = random.Random(7)
    out = {}
    for t, fn in GENERATORS.items():
        try:
            out[t] = len([q for q in fn(P, rng) if _valid(q)])
        except Exception:
            out[t] = 0
    if cacheable:
        if len(_PVT_CACHE) > 24:
            for k in list(_PVT_CACHE)[:12]:
                _PVT_CACHE.pop(k, None)
        _PVT_CACHE[passage_id] = (P.cache_key, out)
    return dict(out)


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

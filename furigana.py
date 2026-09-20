# -*- coding: utf-8 -*-
"""
汉字注音核心模块 v2 —— 五层防错架构
================================================================
第1层  MeCab(fugashi)+UniDic 词格Viterbi解码 —— 上下文决定读音
第2层  数词+助数词规则引擎 —— 修正 UniDic 对「10分/3本/1日」类的系统性错误
第3层  N-best 歧义检测 —— 同形异音词(行った/辛い)多路径读音分歧 → 标警示+给候选
第4层  Sudachi 第二引擎交叉验证 —— 双引擎一致=高置信；分歧=降置信并给出对方读音
第5层  未知词零猜测原则 —— 词典无据的词先用Sudachi兜底，仍未知则明确标"读音未知"
================================================================
token 结构:
  s   表面形          r    平假名注音(None=无需注音)
  w   所属词          wr   词整体读音
  c   置信度 'high'(双引擎一致) / 'mid'(单引擎/规则) / 'low'(存在读音分歧)
  alt 候选读音列表(仅歧义时)      unk  True=词典未收录
"""
import re
import functools
import fugashi

_tagger = fugashi.Tagger()

# ---- Sudachi 第二引擎（可选，装了就启用交叉验证）----
try:
    from sudachipy import dictionary as _sudachi_dict, tokenizer as _sudachi_tok
    _sudachi = _sudachi_dict.Dictionary(dict='core').create()
    _SUDACHI_MODE = _sudachi_tok.Tokenizer.SplitMode.C
except Exception:
    _sudachi = None

_EXTRA_KANJI = set('々〆ヶ')


def is_kanji(ch: str) -> bool:
    code = ord(ch)
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or
            0xF900 <= code <= 0xFAFF or ch in _EXTRA_KANJI)


def has_kanji(text: str) -> bool:
    return any(is_kanji(c) for c in text)


def kata_to_hira(s: str) -> str:
    return ''.join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s)


# ================================================================
# 第2层：数词 + 助数词规则引擎
# ================================================================
_DIGIT_MAP = str.maketrans('０１２３４５６７８９，', '0123456789,')

_ONES = ['', 'いち', 'に', 'さん', 'よん', 'ご', 'ろく', 'なな', 'はち', 'きゅう']
_TENS = ['', 'じゅう', 'にじゅう', 'さんじゅう', 'よんじゅう', 'ごじゅう',
         'ろくじゅう', 'ななじゅう', 'はちじゅう', 'きゅうじゅう']
_HUNDREDS = ['', 'ひゃく', 'にひゃく', 'さんびゃく', 'よんひゃく', 'ごひゃく',
             'ろっぴゃく', 'ななひゃく', 'はっぴゃく', 'きゅうひゃく']
_THOUSANDS = ['', 'せん', 'にせん', 'さんぜん', 'よんせん', 'ごせん',
              'ろくせん', 'ななせん', 'はっせん', 'きゅうせん']


def _num_under_10000(n: int) -> str:
    if n == 0:
        return 'ゼロ'
    return _THOUSANDS[n // 1000] + _HUNDREDS[n // 100 % 10] + _TENS[n // 10 % 10] + _ONES[n % 10]


def num_to_kana(n: int) -> str:
    """整数 → 平假名普通读法（支持到千亿级）"""
    if n == 0:
        return 'ゼロ'
    parts = []
    oku, rest = divmod(n, 10 ** 8)
    man, under = divmod(rest, 10 ** 4)
    if oku:
        parts.append(('いち' if oku == 1 else _num_under_10000(oku)) + 'おく')
    if man:
        parts.append(('いち' if man == 1 else _num_under_10000(man)) + 'まん')
    if under:
        parts.append(_num_under_10000(under))
    return ''.join(parts)


# 常见助数词特殊读音表：{助数词: {尾数: 完整读法(数字部分+助数词)}}
# 键 'base' 为默认助数词读音（与普通数字读法直接拼接）
_COUNTERS = {
    '分': {'base': 'ふん', 1: 'いっぷん', 3: 'さんぷん', 4: 'よんぷん',
           6: 'ろっぷん', 8: 'はっぷん', 10: 'じゅっぷん'},
    '本': {'base': 'ほん', 1: 'いっぽん', 3: 'さんぼん', 6: 'ろっぽん',
           8: 'はっぽん', 10: 'じゅっぽん'},
    '匹': {'base': 'ひき', 1: 'いっぴき', 3: 'さんびき', 6: 'ろっぴき',
           8: 'はっぴき', 10: 'じゅっぴき'},
    '杯': {'base': 'はい', 1: 'いっぱい', 3: 'さんばい', 6: 'ろっぱい',
           8: 'はっぱい', 10: 'じゅっぱい'},
    '回': {'base': 'かい', 1: 'いっかい', 6: 'ろっかい', 8: 'はっかい', 10: 'じゅっかい'},
    '階': {'base': 'かい', 1: 'いっかい', 3: 'さんがい', 6: 'ろっかい',
           8: 'はっかい', 10: 'じゅっかい'},
    '個': {'base': 'こ', 1: 'いっこ', 6: 'ろっこ', 8: 'はっこ', 10: 'じゅっこ'},
    '歳': {'base': 'さい', 1: 'いっさい', 8: 'はっさい', 10: 'じゅっさい', 20: 'はたち'},
    '冊': {'base': 'さつ', 1: 'いっさつ', 8: 'はっさつ', 10: 'じゅっさつ'},
    '足': {'base': 'そく', 1: 'いっそく', 8: 'はっそく', 10: 'じゅっそく'},
    '軒': {'base': 'けん', 1: 'いっけん', 3: 'さんげん', 6: 'ろっけん',
           8: 'はっけん', 10: 'じゅっけん'},
    '件': {'base': 'けん', 1: 'いっけん', 6: 'ろっけん', 8: 'はっけん', 10: 'じゅっけん'},
    '頭': {'base': 'とう', 1: 'いっとう', 8: 'はっとう', 10: 'じゅっとう'},
    '通': {'base': 'つう', 1: 'いっつう', 8: 'はっつう', 10: 'じゅっつう'},
    '曲': {'base': 'きょく', 1: 'いっきょく', 6: 'ろっきょく', 8: 'はっきょく', 10: 'じゅっきょく'},
    '泊': {'base': 'はく', 1: 'いっぱく', 3: 'さんぱく', 4: 'よんぱく',
           6: 'ろっぱく', 8: 'はっぱく', 10: 'じゅっぱく'},
    '発': {'base': 'はつ', 1: 'いっぱつ', 3: 'さんぱつ', 6: 'ろっぱつ',
           8: 'はっぱつ', 10: 'じゅっぱつ'},
    '票': {'base': 'ひょう', 1: 'いっぴょう', 3: 'さんびょう', 6: 'ろっぴょう',
           8: 'はっぴょう', 10: 'じゅっぴょう'},
    '秒': {'base': 'びょう'},
    '晩': {'base': 'ばん', 1: 'ひとばん', 2: 'ふたばん'},
    '円': {'base': 'えん', 4: 'よえん'},
    '年': {'base': 'ねん', 4: 'よねん'},
    '枚': {'base': 'まい'},
    '台': {'base': 'だい'},
    '番': {'base': 'ばん'},
    '度': {'base': 'ど'},
    '点': {'base': 'てん', 1: 'いってん', 8: 'はってん', 10: 'じゅってん'},
    '時': {'base': 'じ', 4: 'よじ', 7: 'しちじ', 9: 'くじ'},
    '時間': {'base': 'じかん', 4: 'よじかん', 9: 'くじかん'},
    '月': {'base': 'がつ', 4: 'しがつ', 7: 'しちがつ', 9: 'くがつ'},
    '人': {'base': 'にん', 1: 'ひとり', 2: 'ふたり', 4: 'よにん'},
    '日': {'base': 'にち', 1: 'ついたち', 2: 'ふつか', 3: 'みっか', 4: 'よっか',
           5: 'いつか', 6: 'むいか', 7: 'なのか', 8: 'ようか', 9: 'ここのか',
           10: 'とおか', 14: 'じゅうよっか', 20: 'はつか', 24: 'にじゅうよっか'},
    'ヶ月': {'base': 'かげつ', 1: 'いっかげつ', 6: 'ろっかげつ', 8: 'はっかげつ', 10: 'じゅっかげつ'},
    'か月': {'base': 'かげつ', 1: 'いっかげつ', 6: 'ろっかげつ', 8: 'はっかげつ', 10: 'じゅっかげつ'},
    'カ月': {'base': 'かげつ', 1: 'いっかげつ', 6: 'ろっかげつ', 8: 'はっかげつ', 10: 'じゅっかげつ'},
    '年間': {'base': 'ねんかん', 4: 'よねんかん', 9: 'くねんかん'},
    '週間': {'base': 'しゅうかん', 1: 'いっしゅうかん', 8: 'はっしゅうかん', 10: 'じゅっしゅうかん'},
    '歳月': {'base': 'さいげつ'},
    'ヶ所': {'base': 'かしょ', 1: 'いっかしょ', 6: 'ろっかしょ', 8: 'はっかしょ', 10: 'じゅっかしょ'},
    'か所': {'base': 'かしょ', 1: 'いっかしょ', 6: 'ろっかしょ', 8: 'はっかしょ', 10: 'じゅっかしょ'},
    'カ所': {'base': 'かしょ', 1: 'いっかしょ', 6: 'ろっかしょ', 8: 'はっかしょ', 10: 'じゅっかしょ'},
    'ヶ国': {'base': 'かこく', 1: 'いっかこく', 6: 'ろっかこく', 8: 'はっかこく', 10: 'じゅっかこく'},
    'か国': {'base': 'かこく', 1: 'いっかこく', 6: 'ろっかこく', 8: 'はっかこく', 10: 'じゅっかこく'},
    'つ': {'base': 'つ', 1: 'ひとつ', 2: 'ふたつ', 3: 'みっつ', 4: 'よっつ', 5: 'いつつ',
           6: 'むっつ', 7: 'ななつ', 8: 'やっつ', 9: 'ここのつ'},
}
# 日間 由 日 派生（3日間=みっかかん）
_COUNTERS['日間'] = {'base': 'にちかん'}


# 融合读法（数字与助数词无法拆分的熟字训式读音）
_FUSED = {
    '人': {1, 2},
    '晩': {1, 2},
    '日': {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 20, 24},
    '歳': {20},
    'つ': {1, 2, 3, 4, 5, 6, 7, 8, 9},
    '日間': {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 20, 24},
}
for _k, _v in list(_COUNTERS['日'].items()):
    if _k != 'base':
        _COUNTERS['日間'][_k] = _v + 'かん'


def number_with_counter(n: int, counter: str):
    """
    数字+助数词 → ('FUSED', 整体读音) 或 (数字部分读音, 助数词部分读音)
    无规则返回 None
    """
    tbl = _COUNTERS.get(counter)
    if tbl is None:
        return None
    base = tbl['base']
    fused = _FUSED.get(counter, frozenset())

    # 完全命中特殊形（1分=いっぷん、14日=じゅうよっか、20歳=はたち）
    if n in tbl:
        full = tbl[n]
        if n in fused:
            return ('FUSED', full)
        cut = len(full) - len(base)
        return (full[:cut], full[cut:])
    # 尾数决定音便：21分 = にじゅう + いっぷん
    tail = n % 10
    if n > 10 and tail != 0 and tail in tbl and tail not in fused:
        full = tbl[tail]
        cut = len(full) - len(base)
        return (num_to_kana(n - tail) + full[:cut], full[cut:])
    # 整十结尾：30分 = さん + じゅっぷん
    if n > 10 and n % 10 == 0 and n % 100 != 0 and 10 in tbl and 10 not in fused:
        full10 = tbl[10]
        cut = len(full10) - len(base)
        head = num_to_kana(n)
        if head.endswith('じゅう'):
            return (head[:-3] + full10[:cut], full10[cut:])
    # 无特殊音便：普通读法 + 基本读音
    return (num_to_kana(n), base)


_NUM_RE = re.compile(r'^[0-9]+$')

# 「〜中」读じゅう的前接时间/范围词（一日中・今日中・世界中・体中…）
_JUU_BEFORE = {'今日', '明日', '昨日', '一日', '日', '年', '一年', '半年',
               '晩', '一晩', '夜', '一夜', '世界', '国', '家', '町', '村',
               '街', '体', '身体', '部屋', '学校', '会社'}

# 汉字数词解析（一〜九千亿）
_KDIGIT = {'〇': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
           '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
_KUNIT = {'十': 10, '百': 100, '千': 1000}
_KBIG = {'万': 10 ** 4, '億': 10 ** 8}


def kanji_num_to_int(s: str):
    if not s or any(ch not in _KDIGIT and ch not in _KUNIT and ch not in _KBIG for ch in s):
        return None
    total, section, digit = 0, 0, 0
    for ch in s:
        if ch in _KDIGIT:
            digit = _KDIGIT[ch]
        elif ch in _KUNIT:
            section += (digit if digit else 1) * _KUNIT[ch]
            digit = 0
        else:  # 万/億
            total += (section + digit if (section + digit) else 1) * _KBIG[ch]
            section = digit = 0
    return total + section + digit


_MIXED_RE = re.compile(r'^([0-9]+)(万|億|千)$')


def _parse_number(surface: str):
    s = surface.translate(_DIGIT_MAP).replace(',', '')
    if _NUM_RE.match(s):
        return int(s)
    m = _MIXED_RE.match(s)
    if m:
        return int(m.group(1)) * {'千': 1000, '万': 10 ** 4, '億': 10 ** 8}[m.group(2)]
    return kanji_num_to_int(surface)


def _is_digit_token(surface: str) -> bool:
    return bool(_NUM_RE.match(surface.translate(_DIGIT_MAP).replace(',', '')))


# ================================================================
# 伪歧义降噪：清浊音(连浊)变体判定
# 第二引擎/N-best 常在连浊上与主读音有细微出入(かようび/かようひ)，
# 这类不是真歧义，静默归一，避免警示噪音淹没真正的多音字歧义。
# ================================================================
_DEVOICE = {}
for _v, _b in [('がぎぐげご', 'かきくけこ'), ('ざじずぜぞ', 'さしすせそ'),
               ('だぢづでど', 'たちつてと'), ('ばびぶべぼ', 'はひふへほ'),
               ('ぱぴぷぺぽ', 'はひふへほ')]:
    for _x, _y in zip(_v, _b):
        _DEVOICE[_x] = _y


def _devoice(s: str) -> str:
    return ''.join(_DEVOICE.get(ch, ch) for ch in s)


def is_rendaku_variant(a: str, b: str) -> bool:
    """两个读音仅有清浊差异（伪歧义）"""
    return a != b and _devoice(a) == _devoice(b)


# 语体/发音等价变体（两读皆正确，不构成歧义）
_EQUIV_PAIRS = {
    frozenset(p) for p in [
        ('わたくし', 'わたし'), ('ほんとう', 'ほんと'), ('おなじ', 'おんなじ'),
        ('いう', 'ゆう'), ('いく', 'ゆく'), ('いき', 'ゆき'), ('いっ', 'ゆっ'),
        ('にほん', 'にっぽん'), ('だれ', 'たれ'), ('あす', 'あした'),
        ('よい', 'いい'), ('やはり', 'やっぱり'), ('ふたたび', 'また'),
    ]
}


def is_equiv_reading(a: str, b: str) -> bool:
    """清浊变体或语体变体 → 视为同一读音，不警示"""
    if is_rendaku_variant(a, b):
        return True
    return frozenset((a, b)) in _EQUIV_PAIRS


def is_fragment_alt(alt: str, reading: str) -> bool:
    """nbest 切分残段噪音：候选是主读音的短前缀（彼=かれ vs か、誰=だれ vs た）"""
    da, dr = _devoice(alt), _devoice(reading)
    return len(da) < len(dr) and dr.startswith(da)


# ================================================================
# 送り仮名对齐（第1层的输出细化）
# ================================================================
def _segment_word(surface: str):
    segs, cur, cur_k = [], '', None
    for ch in surface:
        k = is_kanji(ch)
        if cur_k is None or k == cur_k:
            cur, cur_k = cur + ch, k
        else:
            segs.append((cur, cur_k))
            cur, cur_k = ch, k
    if cur:
        segs.append((cur, cur_k))
    return segs


def _align(surface: str, reading_hira: str):
    segs = _segment_word(surface)
    n_kanji_seg = sum(1 for _, k in segs if k)
    pattern, seen = '', 0
    for text, k in segs:
        if k:
            seen += 1
            pattern += '(.+?)' if seen < n_kanji_seg else '(.+)'
        else:
            pattern += re.escape(kata_to_hira(text))
    m = re.fullmatch(pattern, reading_hira)
    if not m:
        return None
    out, gi = [], 1
    for text, k in segs:
        if k:
            out.append((text, m.group(gi)))
            gi += 1
        else:
            out.append((text, None))
    return out


# ================================================================
# 第3层：N-best 歧义检测
# ================================================================
def _nbest_alternatives(text: str, n=4):
    """返回 {(start,end): {读音1, 读音2..}} —— 同一表面片段在不同路径下的读音集合"""
    spans = {}
    try:
        paths = _tagger.nbestToNodeList(text, n)
    except Exception:
        return spans
    for path in paths:
        pos = 0
        for w in path:
            start = text.find(w.surface, pos)
            if start < 0:
                break
            end = start + len(w.surface)
            pos = end
            if not has_kanji(w.surface):
                continue
            kana = w.feature.kana
            if kana and kana != '*':
                spans.setdefault((start, end), set()).add(kata_to_hira(kana))
    return spans


# ================================================================
# 第4层：Sudachi 交叉验证
# ================================================================
def _sudachi_readings(text: str):
    """返回 {(start,end): 平假名读音}"""
    out = {}
    if _sudachi is None:
        return out
    try:
        for m in _sudachi.tokenize(text, _SUDACHI_MODE):
            if has_kanji(m.surface()):
                r = m.reading_form()
                if r and r != '*':
                    out[(m.begin(), m.end())] = kata_to_hira(r)
    except Exception:
        pass
    return out


# ================================================================
# 第4层增强：跨引擎长词仲裁
# Sudachi C 模式以「词典收录的最长复合词」为单位给读音（如 日本人=ニホンジン），
# 比 MeCab 短单位逐词拼接更不易在复合词连接处出错（にっぽん+にん ✗）。
# 规则：
#   Sudachi 长词恰好覆盖多个 MeCab 词块时——
#     两边读音拼接一致 → 该区间置信度升为 high
#     不一致          → 采用词典级整词读音，同时保留 MeCab 拼读作候选并标警示
# ================================================================
def _build_merge_plan(text, words, positions, sud):
    word_span = {positions[j]: j for j in range(len(words))}
    merges, boosts = {}, set()
    for (b, e), sr in sud.items():
        if (b, e) in word_span:
            continue
        idxs = [j for j, (s2, e2) in enumerate(positions) if s2 >= b and e2 <= e]
        if len(idxs) < 2:
            continue
        if positions[idxs[0]][0] != b or positions[idxs[-1]][1] != e:
            continue
        if any(words[j].feature.pos2 == '数詞' for j in idxs):
            continue  # 数词区间交给助数词规则引擎
        concat, ok = '', True
        for j in idxs:
            k = words[j].feature.kana
            if k and k != '*':
                concat += kata_to_hira(k)
            elif not has_kanji(words[j].surface):
                concat += kata_to_hira(words[j].surface)
            else:
                ok = False
                break
        if not ok:
            continue
        if concat == sr:
            boosts.update(idxs)
            # 词组归属合并：全为无活用词的复合词（立候補/市長選）→ 整词收录，
            # 消灭「立(りっ)」这类孤字促音残段进入词组索引
            if all(not (words[j].feature.cType or '').strip('*') for j in idxs):
                merges[idxs[0]] = (idxs[-1] + 1, sr, concat)
        else:
            merges[idxs[0]] = (idxs[-1] + 1, sr, concat)
    return merges, boosts


# ================================================================
# 四字熟语读音表：UniDic 与 Sudachi 双双误读的成语（一石二鳥→いち・こく✗）
# 表优先级最高，整词注音
# ================================================================
IDIOMS = {
    '一石二鳥': 'いっせきにちょう', '一期一会': 'いちごいちえ',
    '一朝一夕': 'いっちょういっせき', '十人十色': 'じゅうにんといろ',
    '一日千秋': 'いちじつせんしゅう', '一喜一憂': 'いっきいちゆう',
    '一挙両得': 'いっきょりょうとく', '三日坊主': 'みっかぼうず',
    '八方美人': 'はっぽうびじん', '七転八倒': 'しちてんばっとう',
    '四苦八苦': 'しくはっく', '自業自得': 'じごうじとく',
    '以心伝心': 'いしんでんしん', '温故知新': 'おんこちしん',
    '疑心暗鬼': 'ぎしんあんき', '切磋琢磨': 'せっさたくま',
    '単刀直入': 'たんとうちょくにゅう', '優柔不断': 'ゆうじゅうふだん',
    '臨機応変': 'りんきおうへん', '天真爛漫': 'てんしんらんまん',
    '正々堂々': 'せいせいどうどう', '興味津々': 'きょうみしんしん',
    '半信半疑': 'はんしんはんぎ', '無我夢中': 'むがむちゅう',
    '猪突猛進': 'ちょとつもうしん', '傍若無人': 'ぼうじゃくぶじん',
    '弱肉強食': 'じゃくにくきょうしょく', '適材適所': 'てきざいてきしょ',
    '一生懸命': 'いっしょうけんめい', '他力本願': 'たりきほんがん',
}


def _idiom_merges(text, positions, merges):
    """四字熟语命中 → 强制整词读音（覆盖引擎裁决）"""
    for idiom, reading in IDIOMS.items():
        start = text.find(idiom)
        while start != -1:
            end = start + len(idiom)
            idxs = [j for j, (s2, e2) in enumerate(positions) if s2 >= start and e2 <= end]
            if idxs and positions[idxs[0]][0] == start and positions[idxs[-1]][1] == end:
                merges[idxs[0]] = (idxs[-1] + 1, reading, reading)
                for j in idxs[1:]:
                    merges.pop(j, None)
            start = text.find(idiom, end)


# ================================================================
# 主流程
# ================================================================
def annotate(text: str):
    words = list(_tagger(text))
    nbest = _nbest_alternatives(text)
    sud = _sudachi_readings(text)

    # 先按表面形定位每个词在原文中的 span
    positions, pos = [], 0
    for w in words:
        start = text.find(w.surface, pos)
        if start < 0:
            start = pos
        positions.append((start, start + len(w.surface)))
        pos = start + len(w.surface)

    merges, boosts = _build_merge_plan(text, words, positions, sud)
    _idiom_merges(text, positions, merges)

    tokens = []
    i = 0
    while i < len(words):
        w = words[i]
        surface = w.surface
        if not surface:
            i += 1
            continue

        # ---- 第4层增强：词典级复合词整词仲裁 ----
        if i in merges:
            end, sr, mecab_concat = merges[i]
            whole = ''.join(words[j].surface for j in range(i, end))
            aligned = _align(whole, sr)
            # 词典级整词读音获胜；若与MeCab拼读仅清浊之差则视为一致（无需警示）
            if mecab_concat == sr or is_rendaku_variant(mecab_concat, sr):
                extra = {'c': 'high'}
            else:
                extra = {'c': 'mid', 'alt': [mecab_concat]}
            if aligned is None:
                tokens.append({'s': whole, 'r': sr, 'w': whole, 'wr': sr, **extra})
            else:
                for seg, ruby in aligned:
                    tokens.append({'s': seg, 'r': ruby, 'w': whole, 'wr': sr, **extra})
            i = end
            continue

        # ---- 第2层：数词 + 助数词 ----
        if w.feature.pos2 == '数詞':
            is_digit = _is_digit_token(surface)
            # 千分位合并：1 , 000 → 1,000
            merged_surface, j = surface, i
            if is_digit:
                while (j + 2 < len(words) and words[j + 1].surface in (',', '，')
                       and words[j + 2].feature.pos2 == '数詞'
                       and _is_digit_token(words[j + 2].surface)
                       and len(words[j + 2].surface) == 3):
                    merged_surface += words[j + 1].surface + words[j + 2].surface
                    j += 2
            num = _parse_number(merged_surface)
            # 连续数詞合并：一+万→一万(10000)、10+万→10万
            while num is not None and j + 1 < len(words) and words[j + 1].feature.pos2 == '数詞':
                cand = merged_surface + words[j + 1].surface
                val = _parse_number(cand)
                if val is None:
                    break
                merged_surface, num, j = cand, val, j + 1
            nxt = words[j + 1] if j + 1 < len(words) else None
            if num is not None and nxt is not None:
                # 汉字数词的「日」类日期交给词典（一日中≠ついたち中）
                date_guard = (not is_digit) and nxt.surface in ('日', '日間')
                res = None if date_guard else number_with_counter(num, nxt.surface)
                if res:
                    num_r, ctr_r = res
                    whole = merged_surface + nxt.surface
                    if num_r == 'FUSED':
                        tokens.append({'s': whole, 'r': ctr_r, 'w': whole, 'wr': ctr_r, 'c': 'mid'})
                    else:
                        whole_r = num_r + ctr_r
                        tokens.append({'s': merged_surface, 'r': num_r, 'w': whole,
                                       'wr': whole_r, 'c': 'mid'})
                        tokens.append({'s': nxt.surface,
                                       'r': ctr_r if has_kanji(nxt.surface) else None,
                                       'w': whole, 'wr': whole_r, 'c': 'mid'})
                    i = j + 2
                    continue
            if is_digit:
                # 纯阿拉伯数字（无匹配助数词）：不含汉字，无需注音
                tokens.append({'s': merged_surface, 'r': None, 'w': None, 'wr': None})
                i = j + 1
                continue
            if j > i and num is not None:
                # 已合并的汉字数词（一万）：整体给普通读法
                r = num_to_kana(num)
                tokens.append({'s': merged_surface, 'r': r, 'w': merged_surface,
                               'wr': r, 'c': 'mid'})
                i = j + 1
                continue
            # 单个汉字数词无助数词规则 → 落回词典正常注音流程（一日=ついたち/いちにち 由词格决定）

        kana = w.feature.kana
        if (not kana or kana == '*') and w.feature.pron and w.feature.pron != '*':
            kana = w.feature.pron

        if not has_kanji(surface):
            tokens.append({'s': surface, 'r': None, 'w': None, 'wr': None})
            i += 1
            continue

        span = positions[i]

        # ---- 第5层：未知词 → Sudachi 兜底，仍未知则明确标注 ----
        if not kana or kana == '*':
            sd = sud.get(span)
            if sd:
                tokens.append({'s': surface, 'r': sd, 'w': surface, 'wr': sd, 'c': 'mid'})
            else:
                tokens.append({'s': surface, 'r': None, 'w': surface, 'wr': None, 'unk': True})
            i += 1
            continue

        reading = kata_to_hira(kana)

        # ---- 第2.5层a：単独「私」→ わたし（现代字幕语体；わたくし为等价变体）----
        if surface == '私' and w.feature.pos1 == '代名詞' and reading == 'わたくし':
            reading = 'わたし'

        # ---- 第2.5层b：「何」+ 格助词 → なに（何を/何が/何か/何も）----
        if (surface == '何' and reading == 'なん' and i + 1 < len(words)
                and words[i + 1].surface in ('を', 'が', 'か', 'も', 'から', 'まで', 'より')):
            reading = 'なに'

        # ---- 第2.5层c：範囲の「中」→ じゅう（一日中・今日中・世界中）----
        if (surface == '中' and reading == 'ちゅう' and i > 0
                and words[i - 1].surface in _JUU_BEFORE):
            reading = 'じゅう'
            # 连带纠正前接词读音（今日中=きょうじゅう、体中=からだじゅう）
            _fix = {'今日': 'きょう', '体': 'からだ', '身体': 'からだ'}.get(words[i - 1].surface)
            if _fix:
                for t in reversed(tokens):
                    if t.get('w') == words[i - 1].surface:
                        t['r'] = t['wr'] = _fix
                        t.pop('alt', None)
                        t['c'] = 'mid'
                    else:
                        break
            tokens.append({'s': surface, 'r': reading, 'w': surface, 'wr': reading, 'c': 'mid'})
            i += 1
            continue

        # 词典原形（贫しかっ→貧しい），供词组展示/索引使用，避免活用残段
        dw = w.feature.orthBase if (w.feature.orthBase and w.feature.orthBase != '*') else surface
        dk = w.feature.kanaBase if (w.feature.kanaBase and w.feature.kanaBase != '*') else kana
        dr = kata_to_hira(dk)

        # ---- 第3层 + 第4层：置信度评定（噪音归一，只留真歧义）----
        conf, alts = ('high' if i in boosts else 'mid'), set()
        nb = nbest.get(span)
        if nb and len(nb) > 1:
            alts |= {a for a in nb
                     if a != reading and not is_equiv_reading(a, reading)
                     and not is_fragment_alt(a, reading)}
        sd = sud.get(span)
        if sd is not None:
            if sd == reading or is_equiv_reading(sd, reading):
                conf = 'high'
                alts.clear()   # 双引擎共识 > nbest 次优路径
            else:
                alts.add(sd)
        if alts:
            conf = 'low'

        extra = {'c': conf}
        if alts:
            extra['alt'] = sorted(alts)

        aligned = _align(surface, reading)
        if aligned is None:
            tokens.append({'s': surface, 'r': reading, 'w': surface, 'wr': reading,
                           'dw': dw, 'dr': dr, **extra})
        else:
            for seg, ruby in aligned:
                tokens.append({'s': seg, 'r': ruby, 'w': surface, 'wr': reading,
                               'dw': dw, 'dr': dr, **extra})
        i += 1
    return tokens


def extract_kanji_words(tokens):
    out = []
    for t in tokens:
        if t.get('r') is None and not t.get('unk'):
            continue
        # 优先词典原形（貧しかっ→貧しい），避免活用残段进入词组索引
        word = t.get('dw') or t.get('w') or t['s']
        wr = t.get('dr') or t.get('wr')
        # 原形若不含该汉字（表记差异），回退表面形
        for ch in t['s']:
            if is_kanji(ch) and ch not in '々〆ヶ':
                if ch in word:
                    out.append((ch, word, wr))
                else:
                    out.append((ch, t.get('w') or t['s'], t.get('wr')))
    return out


# ================================================================
# 字读音提取（课本「字」索引的单字假名标注）
# ================================================================
# 常用汉字音读表：nbest 单字切分拿不到复合词音读时的兜底。
# 只列音读（音読み）；训读字（带送假名）已由 annotate 的 token.r 正确对齐。
# 值含常见促音/连浊变体，DP 对齐时再做清浊归一。
_ON_YOMI = {
    '一': ['いち', 'いっ', 'いつ', 'ひと'], '二': ['に'], '三': ['さん'], '四': ['し'],
    '五': ['ご'], '六': ['ろく', 'ろっ'], '七': ['しち'], '八': ['はち', 'はっ'],
    '九': ['きゅう', 'く'], '十': ['じゅう', 'じゅっ', 'じっ'], '百': ['ひゃく', 'びゃく', 'ぴゃく'],
    '千': ['せん', 'ぜん'], '万': ['まん', 'ばん'], '円': ['えん'], '年': ['ねん'],
    '月': ['げつ', 'がつ'], '日': ['にち', 'じつ', 'に', 'にっ'], '時': ['じ'],
    '分': ['ぶん', 'ふん', 'ぶ', 'ぷん'], '間': ['かん', 'けん', 'ま'], '今': ['こん', 'きん'],
    '人': ['にん', 'じん', 'ひと', 'り'], '男': ['だん', 'なん'], '女': ['じょ', 'にょ', 'おんな'], '子': ['し', 'す'],
    '学': ['がく', 'がっ'], '校': ['こう'], '生': ['せい', 'しょう', 'じょう'], '先': ['せん'],
    '友': ['ゆう'], '本': ['ほん', 'ぼん', 'ぽん'], '文': ['ぶん', 'もん', 'も'], '字': ['じ'],
    '書': ['しょ'], '図': ['ず', 'と'], '大': ['だい', 'たい', 'おお'], '小': ['しょう'],
    '中': ['ちゅう', 'じゅう'], '上': ['じょう', 'しょう'], '下': ['か', 'げ'], '左': ['さ'],
    '右': ['う', 'ゆう'], '前': ['ぜん'], '後': ['ご', 'こう'], '外': ['がい', 'げ'],
    '内': ['ない', 'だい'], '出': ['しゅつ', 'しゅっ'], '入': ['にゅう', 'にゅっ'],
    '見': ['けん'], '聞': ['ぶん', 'もん'], '言': ['げん', 'ごん'], '話': ['わ'],
    '読': ['どく', 'とく', 'とう'], '手': ['しゅ', 'ず'], '足': ['そく'], '目': ['もく', 'ぼく', 'め'],
    '耳': ['じ'], '口': ['こう', 'く'], '心': ['しん'], '気': ['き', 'け'],
    '力': ['りょく', 'りき'], '休': ['きゅう', 'やす'], '体': ['たい', 'てい'], '行': ['こう', 'ぎょう'],
    '来': ['らい'], '帰': ['き'], '食': ['しょく', 'じき', 'しょっ'], '飲': ['いん'],
    '買': ['ばい'], '国': ['こく', 'こっ', 'ごく'], '語': ['ご'], '京': ['きょう', 'けい'],
    '東': ['とう'], '西': ['せい', 'さい'], '南': ['なん', 'な'], '北': ['ほく'],
    '駅': ['えき'], '電': ['でん'], '車': ['しゃ'], '道': ['どう', 'とう'], '地': ['ち', 'じ'],
    '方': ['ほう'], '場': ['じょう'], '所': ['しょ'], '家': ['か', 'け'], '屋': ['おく'],
    '店': ['てん'], '社': ['しゃ'], '会': ['かい', 'え'], '員': ['いん'], '長': ['ちょう'],
    '高': ['こう'], '安': ['あん'], '新': ['しん'], '古': ['こ'], '多': ['た'],
    '少': ['しょう'], '早': ['そう', 'さっ'], '短': ['たん'], '低': ['てい'], '近': ['きん'],
    '遠': ['えん', 'おん'], '速': ['そく'], '明': ['めい', 'みょう'], '暗': ['あん'],
    '白': ['はく', 'びゃく'], '黒': ['こく'], '赤': ['せき', 'しゃく'], '青': ['せい', 'しょう'],
    '色': ['しき', 'しょく'], '水': ['すい'], '火': ['か'], '山': ['さん', 'ざん'],
    '川': ['せん'], '田': ['でん'], '土': ['ど', 'と'], '石': ['せき', 'しゃく', 'こく'],
    '金': ['きん', 'こん'], '木': ['もく', 'ぼく'], '林': ['りん'], '森': ['しん'],
    '空': ['くう'], '天': ['てん'], '雨': ['う'], '雪': ['せつ'], '風': ['ふう', 'ふ'],
    '音': ['おん', 'いん'], '声': ['せい', 'しょう'], '名': ['めい', 'みょう'],
    '海': ['かい'], '池': ['ち'], '谷': ['こく'], '野': ['や'], '原': ['げん'],
    '里': ['り'], '町': ['ちょう'], '村': ['そん'], '市': ['し'], '区': ['く'],
    '県': ['けん'], '都': ['と', 'つ'], '府': ['ふ'], '島': ['とう'], '港': ['こう'],
    '橋': ['きょう'], '通': ['つう', 'とお', 'どお', 'ずう'], '歩': ['ほ', 'ぶ', 'ぽ'], '走': ['そう'],
    '立': ['りつ', 'りゅう'], '座': ['ざ'], '乗': ['じょう'], '降': ['こう'],
    '動': ['どう'], '作': ['さく', 'さっ', 'さ'], '使': ['し'], '始': ['し'], '終': ['しゅう'],
    '開': ['かい'], '閉': ['へい'], '止': ['し'], '待': ['たい'], '持': ['じ'],
    '取': ['しゅ'], '置': ['ち'], '建': ['けん', 'こん'], '売': ['ばい'], '払': ['ふつ'],
    '知': ['ち'], '考': ['こう'], '思': ['し'], '覚': ['かく'], '忘': ['ぼう'],
    '習': ['しゅう'], '勉': ['べん'], '強': ['きょう', 'ごう'], '教': ['きょう'],
    '育': ['いく'], '研': ['けん'], '究': ['きゅう'], '試': ['し'], '験': ['けん'],
    '答': ['とう'], '問': ['もん'], '題': ['だい'], '理': ['り'], '由': ['ゆう', 'ゆ'],
    '科': ['か'], '数': ['すう'], '算': ['さん'], '合': ['ごう', 'がっ', 'かっ'],
    '計': ['けい'], '形': ['けい', 'ぎょう'], '表': ['ひょう'], '式': ['しき'],
    '就': ['しゅう'], '職': ['しょく'], '慣': ['かん'], '庭': ['てい'], '彼': ['ひ', 'かの'],
    '練': ['れん'], '清': ['せい', 'しょう'], '和': ['わ'], '発': ['はつ', 'はっ', 'ほっ'],
    '役': ['やく', 'えき'], '普': ['ふ'], '化': ['か', 'け'], '粧': ['しょう'],
    '携': ['けい'], '帯': ['たい'], '傍': ['ぼう'], '若': ['じゃく', 'にゃく'],
    '無': ['む', 'ぶ'], '平': ['へい', 'びょう'], '甲': ['こう', 'かん'], '斐': ['ひ'],
    '過': ['か'], '去': ['こ', 'きょ'], '与': ['よ'], '謝': ['しゃ'], '太': ['たい'],
    '陽': ['よう'], '果': ['か'], '敢': ['かん'], '掲': ['けい'], '示': ['じ', 'し'],
    '冬': ['とう', 'ふゆ'], '基': ['き'], '礎': ['そ'], '指': ['し', 'さ', 'ざ'], '頑': ['がん'],
    '張': ['ちょう'], '身': ['しん'], '好': ['こう', 'す'], '趣': ['しゅ'], '味': ['み'],
    '部': ['ぶ'], '代': ['だい', 'たい'], '仕': ['し', 'じ'], '送': ['そう', 'おく'],
    '遣': ['けん'], '演': ['えん'], '準': ['じゅん'], '備': ['び'], '貿': ['ぼう'],
    '易': ['えき', 'い'], '政': ['せい'], '次': ['じ', 'し'], '寝': ['しん'],
    '室': ['しつ'], '設': ['せつ', 'せっ'], '工': ['こう', 'く'], '夫': ['ふ', 'ふう', 'ぶ'],
    '丈': ['じょう'], '失': ['しつ', 'しっ'], '敗': ['はい'], '反': ['はん', 'たん'],
    '応': ['おう', 'のう'], '器': ['き'], '握': ['あく'], '違': ['い', 'ちが'], '潮': ['ちょう'],
    '各': ['かく', 'かっ'], '缶': ['かん'], '更': ['こう'], '衣': ['い'], '接': ['せつ', 'せっ'],
    '触': ['しょく'], '錯': ['さく', 'さっ'], '息': ['そく', 'いき'], '苦': ['く', 'ぐる'], '勝': ['しょう'],
    '喫': ['きつ', 'きっ'], '茶': ['ちゃ', 'さ'], '融': ['ゆう'], '追': ['つい'], '随': ['ずい'],
    '吸': ['きゅう'], '殻': ['かく'], '揮': ['き'], '競': ['きょう', 'けい'],
    '争': ['そう'], '光': ['こう'], '切': ['せつ', 'せっ', 'さい'],
}


@functools.lru_cache(maxsize=4096)
def _char_candidates(ch):
    """单字候选读音：音读表 + MeCab nbest 单字读音（含训读）。"""
    cands = list(_ON_YOMI.get(ch) or [])
    try:
        for p in _tagger.nbestToNodeList(ch, 12):
            for w in p:
                k = w.feature.kana
                if k and k != '*':
                    h = kata_to_hira(k)
                    if h and h not in cands:
                        cands.append(h)
    except Exception:
        pass
    return tuple(cands)


def _dp_align(chars, reading, prefix=False):
    """把整词读音切分到每个汉字（回溯 + 清浊归一匹配）。

    prefix=False：候选读音须与原文片段等长精确匹配（音读对齐）。
    prefix=True：额外允许候选读音是原文片段的前缀扩展（处理训读词干
    被送假名截断的情况，如 気持=きも → 気=き / 持=も）。

    返回与 chars 一一对应的读音列表（保留原文连浊/促音），失败返回 None。
    """
    n = len(chars)
    cands = [_char_candidates(ch) for ch in chars]
    if any(not c for c in cands):
        return None
    L = len(reading)
    result = [None] * n

    def dfs(i, pos):
        if i == n:
            return pos == L
        for c in cands[i]:
            clen = len(c)
            if not prefix:
                if pos + clen > L:
                    continue
                sub = reading[pos:pos + clen]
                if _devoice(sub) == _devoice(c):
                    result[i] = sub
                    if dfs(i + 1, pos + clen):
                        return True
            else:
                for elen in range(1, clen + 1):
                    if pos + elen > L:
                        break
                    sub = reading[pos:pos + elen]
                    if _devoice(c[:elen]) == _devoice(sub):
                        result[i] = sub
                        if dfs(i + 1, pos + elen):
                            return True
        return False

    return result if dfs(0, 0) else None


_UNIT_READINGS = {'千': 'せん', '百': 'ひゃく', '十': 'じゅう', '万': 'まん', '億': 'おく'}


def _split_mixed_number(surface, reading):
    """处理「数字+单位汉字」混合数词（6千=ろくせん、1万6千=いちまんろくせん）。

    数字段读音由规则引擎给出，单位段（千/万/億…）读音固定，逐段拼接
    与整词读音核对一致后，返回 surface 中各单位汉字的读音列表（不含数字）。
    无法处理时返回 None。
    """
    if not any(ch.isdigit() for ch in surface):
        return None
    segs = re.findall(r'[0-9]+|[^0-9]+', surface)
    expected = ''
    han_readings = []
    for seg in segs:
        if seg.isdigit():
            expected += num_to_kana(int(seg))
        else:
            for ch in seg:
                if is_kanji(ch) and ch not in '々〆ヶ':
                    u = _UNIT_READINGS.get(ch)
                    if not u:
                        return None
                    expected += u
                    han_readings.append(u)
                else:
                    expected += ch
    if han_readings and _devoice(expected) == _devoice(reading):
        return han_readings
    return None


@functools.lru_cache(maxsize=8192)
def _split_kanji_reading(surface, reading):
    """多汉字词的整词读音 → 每个汉字各自的读音（字素对齐）。

    利用 MeCab nbest 的单字切分路径：只有当「逐字切分后的读音拼接」
    与整词读音一致（清浊归一后比较）时才采纳，避免把词读音整段
    误标到单个字上（如「合計=ごうけい」应拆成 合=ごう / 計=けい）。

    返回与 surface 中汉字一一对应的读音列表；无法可靠切分返回 None。
    """
    if not surface or not reading:
        return None
    mixed = _split_mixed_number(surface, reading)
    if mixed is not None:
        return mixed
    chars = [c for c in surface if is_kanji(c) and c not in '々〆ヶ']
    n = len(chars)
    if n == 0:
        return None
    if n == 1:
        return [reading]
    target = _devoice(reading)
    try:
        paths = _tagger.nbestToNodeList(surface, 20)
    except Exception:
        paths = []
    for path in paths:
        words = list(path)
        if len(words) != n:
            continue
        rs = []
        ok = True
        for i, w in enumerate(words):
            if w.surface != chars[i]:
                ok = False
                break
            k = w.feature.kana
            if not k or k == '*':
                ok = False
                break
            rs.append(kata_to_hira(k))
        if not ok:
            continue
        if _devoice(''.join(rs)) == target:
            return rs
    r = _dp_align(chars, reading, prefix=False)
    if r:
        return r
    return _dp_align(chars, reading, prefix=True)


def extract_char_readings(tokens):
    """从注音 tokens 提取每个汉字自身的读音（用于课本单字假名标注）。

    返回 [(汉字, 字读音)]，按 tokens 顺序；字读音无法确定时退回整词读音
    兜底（至少保留读音显示，不至于空白）。"""
    out = []
    for t in tokens:
        r = t.get('r')
        if r is None and not t.get('unk'):
            continue
        s = t['s'] or ''
        chars = [c for c in s if is_kanji(c) and c not in '々〆ヶ']
        if not chars:
            continue
        # 仅当 s 就是单个汉字时直接取 r；若混有数字等其它字符（如 6千）
        # 仍需走字素对齐，把数字读音从整段读音中剥离。
        if len(chars) == 1 and s == chars[0]:
            if r:
                out.append((chars[0], r))
            continue
        split = _split_kanji_reading(s, r)
        for i, ch in enumerate(chars):
            cr = (split[i] if split and i < len(split) and split[i] else None) or r
            out.append((ch, cr))
    return out

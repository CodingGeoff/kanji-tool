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
    'つ': {'base': 'つ', 1: 'ひとつ', 2: 'ふたつ', 3: 'みっつ', 4: 'よっつ', 5: 'いつつ',
           6: 'むっつ', 7: 'ななつ', 8: 'やっつ', 9: 'ここのつ'},
}
# 日間 由 日 派生（3日間=みっかかん）
_COUNTERS['日間'] = {'base': 'にちかん'}


# 融合读法（数字与助数词无法拆分的熟字训式读音）
_FUSED = {
    '人': {1, 2},
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


def _parse_number(surface: str):
    s = surface.translate(_DIGIT_MAP).replace(',', '')
    return int(s) if _NUM_RE.match(s) else None


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
        else:
            merges[idxs[0]] = (idxs[-1] + 1, sr, concat)
    return merges, boosts


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
            # 词典级整词读音获胜，MeCab 拼读保留为候选供核对
            extra = {'c': 'mid', 'alt': [mecab_concat]}
            if aligned is None:
                tokens.append({'s': whole, 'r': sr, 'w': whole, 'wr': sr, **extra})
            else:
                for seg, ruby in aligned:
                    tokens.append({'s': seg, 'r': ruby, 'w': whole, 'wr': sr, **extra})
            i = end
            continue

        # ---- 第2层：数词 + 助数词 ----
        num = _parse_number(surface) if w.feature.pos2 == '数詞' else None
        if num is not None and i + 1 < len(words):
            nxt = words[i + 1]
            res = number_with_counter(num, nxt.surface)
            if res:
                num_r, ctr_r = res
                whole = surface + nxt.surface
                if num_r == 'FUSED':
                    # 融合读法（1日=ついたち、2人=ふたり）→ 合并为单 token 整体注音
                    tokens.append({'s': whole, 'r': ctr_r, 'w': whole, 'wr': ctr_r, 'c': 'mid'})
                else:
                    whole_r = num_r + ctr_r
                    tokens.append({'s': surface, 'r': num_r, 'w': whole, 'wr': whole_r, 'c': 'mid'})
                    tokens.append({'s': nxt.surface,
                                   'r': ctr_r if has_kanji(nxt.surface) else None,
                                   'w': whole, 'wr': whole_r, 'c': 'mid'})
                i += 2
                continue
            # 无助数词规则：数字本身不含汉字，不注音
            tokens.append({'s': surface, 'r': None, 'w': None, 'wr': None})
            i += 1
            continue

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

        # ---- 第3层 + 第4层：置信度评定 ----
        conf, alts = ('high' if i in boosts else 'mid'), set()
        nb = nbest.get(span)
        if nb and len(nb) > 1:
            alts |= (nb - {reading})
        sd = sud.get(span)
        if sd is not None:
            if sd == reading:
                conf = 'high'
            else:
                alts.add(sd)
        if alts:
            conf = 'low'

        extra = {'c': conf}
        if alts:
            extra['alt'] = sorted(alts)

        aligned = _align(surface, reading)
        if aligned is None:
            tokens.append({'s': surface, 'r': reading, 'w': surface, 'wr': reading, **extra})
        else:
            for seg, ruby in aligned:
                tokens.append({'s': seg, 'r': ruby, 'w': surface, 'wr': reading, **extra})
        i += 1
    return tokens


def extract_kanji_words(tokens):
    out = []
    for t in tokens:
        if t.get('r') is None and not t.get('unk'):
            continue
        word = t.get('w') or t['s']
        wr = t.get('wr')
        for ch in t['s']:
            if is_kanji(ch) and ch not in '々〆ヶ':
                out.append((ch, word, wr))
    return out

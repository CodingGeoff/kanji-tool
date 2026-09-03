# -*- coding: utf-8 -*-
"""KTV 歌词模块：批量导入 → 自动整理成歌（切分/标题识别/分段）→ 复用注音引擎逐行注音

设计目标（用户在移动端去 KTV 前背歌词）：
- 一次粘贴一首或多首歌词也能自动整理；
- 汉字全部标注平假名（复用 furigana 引擎，多音字按上下文取音）；
- 纯罗马音行可转片假名显示（可选）；
- 与字幕注音共用 token 协议 {s,r,w,wr,dw,dr,c,alt,unk}。
"""
import re
import json

import furigana

# ---------------------------------------------------------------
# 歌词规整
# ---------------------------------------------------------------

def normalize_lyrics(text: str) -> str:
    """统一换行、去行尾空白、空行压缩为单行（=段落分隔），去掉首尾空行。"""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\ufeff', '')
    lines = [l.rstrip() for l in text.split('\n')]
    out, blank = [], 0
    for l in lines:
        if l.strip():
            out.append(l)
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


# ---------------------------------------------------------------
# 罗马音 → 片假名（显示辅助，按音节直转）
# ---------------------------------------------------------------

_RK_MAP = {
    'a': 'ア', 'i': 'イ', 'u': 'ウ', 'e': 'エ', 'o': 'オ',
    'ka': 'カ', 'ki': 'キ', 'ku': 'ク', 'ke': 'ケ', 'ko': 'コ',
    'ga': 'ガ', 'gi': 'ギ', 'gu': 'グ', 'ge': 'ゲ', 'go': 'ゴ',
    'sa': 'サ', 'shi': 'シ', 'si': 'シ', 'su': 'ス', 'se': 'セ', 'so': 'ソ',
    'sha': 'シャ', 'shu': 'シュ', 'sho': 'ショ', 'sya': 'シャ', 'syu': 'シュ', 'syo': 'ショ',
    'za': 'ザ', 'ji': 'ジ', 'zi': 'ジ', 'zu': 'ズ', 'ze': 'ゼ', 'zo': 'ゾ',
    'ja': 'ジャ', 'ju': 'ジュ', 'jo': 'ジョ', 'jya': 'ジャ', 'jyu': 'ジュ', 'jyo': 'ジョ',
    'zya': 'ジャ', 'zyu': 'ジュ', 'zyo': 'ジョ',
    'ta': 'タ', 'chi': 'チ', 'ti': 'チ', 'tsu': 'ツ', 'tu': 'ツ', 'te': 'テ', 'to': 'ト',
    'cha': 'チャ', 'chu': 'チュ', 'cho': 'チョ', 'che': 'チェ', 'tya': 'チャ', 'tyu': 'チュ', 'tyo': 'チョ',
    'tch': 'ッチ',
    'da': 'ダ', 'di': 'ディ', 'du': 'ドゥ', 'de': 'デ', 'do': 'ド',
    'na': 'ナ', 'ni': 'ニ', 'nu': 'ヌ', 'ne': 'ネ', 'no': 'ノ',
    'nya': 'ニャ', 'nyu': 'ニュ', 'nyo': 'ニョ',
    'ha': 'ハ', 'hi': 'ヒ', 'fu': 'フ', 'hu': 'フ', 'he': 'ヘ', 'ho': 'ホ',
    'fa': 'ファ', 'fi': 'フィ', 'fe': 'フェ', 'fo': 'フォ',
    'hya': 'ヒャ', 'hyu': 'ヒュ', 'hyo': 'ヒョ',
    'ba': 'バ', 'bi': 'ビ', 'bu': 'ブ', 'be': 'ベ', 'bo': 'ボ',
    'bya': 'ビャ', 'byu': 'ビュ', 'byo': 'ビョ',
    'pa': 'パ', 'pi': 'ピ', 'pu': 'プ', 'pe': 'ペ', 'po': 'ポ',
    'pya': 'ピャ', 'pyu': 'ピュ', 'pyo': 'ピョ',
    'ma': 'マ', 'mi': 'ミ', 'mu': 'ム', 'me': 'メ', 'mo': 'モ',
    'mya': 'ミャ', 'myu': 'ミュ', 'myo': 'ミョ',
    'ya': 'ヤ', 'yu': 'ユ', 'yo': 'ヨ', 'ye': 'イェ',
    'ra': 'ラ', 'ri': 'リ', 'ru': 'ル', 're': 'レ', 'ro': 'ロ',
    'rya': 'リャ', 'ryu': 'リュ', 'ryo': 'リョ',
    'wa': 'ワ', 'wi': 'ウィ', 'we': 'ウェ', 'wo': 'ヲ',
    'va': 'ヴァ', 'vi': 'ヴィ', 'vu': 'ヴ', 've': 'ヴェ', 'vo': 'ヴォ',
    'kya': 'キャ', 'kyu': 'キュ', 'kyo': 'キョ',
    'gya': 'ギャ', 'gyu': 'ギュ', 'gyo': 'ギョ',
    'la': 'ラ', 'li': 'リ', 'lu': 'ル', 'le': 'レ', 'lo': 'ロ',
    'tcha': 'ッチャ', 'tchu': 'ッチュ', 'tcho': 'ッチョ', 'tche': 'ッチェ',
    'xtu': 'ッ', 'xa': 'ァ', 'xi': 'ィ', 'xu': 'ゥ', 'xe': 'ェ', 'xo': 'ォ',
    '-': 'ー', '─': 'ー', '−': 'ー',
}

_RK_MACRON = str.maketrans({'ō': 'o-', 'Ū': 'u-', 'ū': 'u-', 'Ā': 'a-', 'ā': 'a-',
                            'Ē': 'e-', 'ē': 'e-', 'Ī': 'i-', 'ī': 'i-'})
_RK_CONSONANTS = set('bcdfghjklmnpqrstvwxyz')


def romaji_to_kana(s: str) -> str:
    """Hepburn/Kunrei 罗马音 → 片假名（促音・ン・拗音・长音符均处理；未识别字符原样保留）。"""
    s = s.translate(_RK_MACRON).lower()
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == 'n':
            m4, m3, m2 = s[i:i + 4], s[i:i + 3], s[i:i + 2]
            if m4 in _RK_MAP:
                out.append(_RK_MAP[m4]); i += 4; continue
            if m3 in _RK_MAP:
                out.append(_RK_MAP[m3]); i += 3; continue
            if m2 in _RK_MAP:                       # na/ni/nu/ne/no/nya...
                out.append(_RK_MAP[m2]); i += 2; continue
            if i + 1 >= n or s[i + 1] in _RK_CONSONANTS or s[i + 1] in ("'", '’'):
                out.append('ン')
                i += 1
                if i < n and s[i] in ("'", '’'):
                    i += 1
                continue
        # 促音：同辅音重复（kk/tt/ss/pp/...）
        if ch in _RK_CONSONANTS and i + 1 < n and s[i + 1] == ch:
            out.append('ッ'); i += 1; continue
        for L in (4, 3, 2, 1):
            seg = s[i:i + L]
            if seg in _RK_MAP:
                out.append(_RK_MAP[seg]); i += L; break
        else:
            out.append(ch); i += 1
    return ''.join(out)


_ROMAJI_LINE_RE = re.compile(r"^[A-Za-z'’\-.,!?~;: ()&0-9]+$")


def is_romaji_line(line: str) -> bool:
    """整行仅 ASCII 字母/标点（≥2 个字母）→ 视为罗马音行。"""
    t = line.strip()
    if not t or not _ROMAJI_LINE_RE.match(t):
        return False
    return len(re.findall(r'[A-Za-z]', t)) >= 2


# ---------------------------------------------------------------
# 导入解析：一大段文本 → 多首歌 [{title, artist, lyrics}]
# ---------------------------------------------------------------

_SEP_RE = re.compile(r'^\s*[-=*_~—─•·\^#]{3,}\s*$')
_LABEL_RE = re.compile(r'^\s*(?:曲名|タイトル|歌名|题目|标题)\s*[:：]\s*(.+?)\s*$')
_ARTIST_RE = re.compile(r'^\s*(?:歌手|アーティスト|演唱者|演唱|歌手名|演唱者名)\s*[:：]\s*(.+?)\s*$')
_NUM_TITLE_RE = re.compile(r'^\s*\d{1,2}\s*[.、)）]\s*(\S.{0,28}?)\s*$')
_TITLE_DASH_RE = re.compile(r'^\s*([^\s。！？!?、:：]{1,28}?)\s*[-–—―]\s*([^\s。！？!?、]{1,28})\s*$')
_CJK_RE = re.compile(r'[一-鿿぀-ヿ]')


_BRACKET_TAIL_RE = re.compile(
    r'^\s*[【《『]([^【《『】》』]{1,60})[】》』]\s*(?:[-–—―]\s*(.{1,40}?)\s*)?$')


def _bracket_title(line: str):
    """『』《》【】 整行（可带「 - 歌手」尾注）→ (歌名, 歌手|None)；「」不用于标题（歌词常用「」引用台词）。"""
    m = _BRACKET_TAIL_RE.match(line)
    if m:
        inner = m.group(1).strip()
        if 0 < len(inner) <= 60:
            return inner, (m.group(2) or '').strip() or None
    return None, None


def _looks_like_title(line: str) -> bool:
    """无标记时借用首行为歌名的判据：短 CJK 行，或短罗马音行（≤4 词）。"""
    t = line.strip()
    if not (1 <= len(t) <= 22) or any(x in t for x in '。！？!?！'):
        return False
    if _CJK_RE.search(t):
        return True
    if is_romaji_line(t) and len(t) <= 30 and len(t.split()) <= 4:
        return True
    return False


def _first_title(lines):
    """从 chunk 头部剥出 (title, artist, 已消费的行号集合)。

    只认 chunk 前 3 个非空行内的明确标记：曲名：/歌手：/《》【】『』整行/
    编号标题/「歌名 - 歌手」。歌词正文（即使短）绝不会被当成标题。
    """
    title, artist = None, ''
    used = set()
    seen = 0
    for i, l in enumerate(lines):
        if not l.strip():
            if seen:
                break
            continue
        seen += 1
        if seen > 3:
            break
        m = _LABEL_RE.match(l)
        if m and title is None:
            title, used = m.group(1), used | {i}
            continue
        m = _ARTIST_RE.match(l)
        if m and not artist:
            artist, used = m.group(1), used | {i}
            continue
        bt, ba = _bracket_title(l)
        if bt and title is None:
            title, used = bt, used | {i}
            if ba and not artist:
                artist = ba
            continue
        if title is None and not artist:
            m = _NUM_TITLE_RE.match(l)
            if m:
                title, used = m.group(1), used | {i}
                # 「1. 歌名 - 歌手」编号后仍可再拆歌手
                m2 = _TITLE_DASH_RE.match(title)
                if m2 and _CJK_RE.search(title) and ',' not in title:
                    title, artist = m2.group(1), m2.group(2)
                continue
            m = _TITLE_DASH_RE.match(l)
            # 「歌名 - 歌手」：需含 CJK 且两侧不像歌词短句（无逗号顿号）
            if m and _CJK_RE.search(l) and ',' not in l and '、' not in l:
                title, artist = m.group(1), m.group(2)
                used |= {i}
                continue
        break
    return title, artist, used


def _num_title_line(l):
    """独立成行的「1. 歌名」编号标题（曲目表常见）。"""
    t = l.strip()
    if not _NUM_TITLE_RE.match(t) or len(t) > 42 or any(x in t for x in '。！？!?，,'):
        return False
    return True


def _split_by_inline_titles(lines):
    """chunk 内部出现独立成行的《》【】标题行或「1. 歌名」编号行 → 从该行起切成新歌。"""
    parts, cur = [], []
    for l in lines:
        if (l.strip()[:1] in ('《', '【') and _bracket_title(l)[0]) or _num_title_line(l):
            if cur:
                parts.append(cur)
            cur = [l]
        else:
            cur.append(l)
    if cur:
        parts.append(cur)
    return parts


def parse_import(text: str):
    """自动整理：返回 [{title, artist, lyrics}]。"""
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\ufeff', '')
    raw = [l.rstrip() for l in text.split('\n')]

    # 1) 分隔线（--- /***===）切块，每块一首（或再按内嵌《》标题行细分）
    chunks, cur = [], []
    for l in raw:
        if _SEP_RE.match(l):
            if any(x.strip() for x in cur):
                chunks.append(cur)
            cur = []
        else:
            cur.append(l)
    if any(x.strip() for x in cur):
        chunks.append(cur)
    if not chunks:
        return []

    unnamed = 0
    songs = []
    for chunk in chunks:
        for part in _split_by_inline_titles(chunk):
            title, artist, used = _first_title(part)
            explicit = title is not None
            body = [l for i, l in enumerate(part) if i not in used]
            nonempty = sum(1 for l in body if l.strip())
            if not title:
                # 无任何标记：短 CJK/罗马音首行 → 借用为歌名（保留在歌词中，不删行防丢内容）
                first = next((l for l in body if l.strip()), '')
                if nonempty >= 2 and _looks_like_title(first):
                    title = first.strip()
                else:
                    unnamed += 1
                    title = f'未命名歌曲{unnamed if unnamed > 1 else ""}'.strip()
            lyrics = normalize_lyrics('\n'.join(body))
            if not lyrics:
                continue
            songs.append({'title': title.strip(), 'artist': (artist or '').strip(),
                          'lyrics': lyrics, '_explicit': explicit})
    # 无任何明确标记的多块 → 合并为一首（--- 被歌词内部分段误用时不产生碎片）
    if len(songs) > 1 and not any(s['_explicit'] for s in songs):
        title = next((s['title'] for s in songs if not s['title'].startswith('未命名歌曲')),
                     '未命名歌曲')
        merged = '\n\n'.join(s['lyrics'] for s in songs)
        songs = [{'title': title, 'artist': '', 'lyrics': normalize_lyrics(merged)}]
    else:
        for s in songs:
            s.pop('_explicit', None)
    for s in songs:
        s.pop('_explicit', None)
    return songs


# ---------------------------------------------------------------
# 注音：复用字幕注音引擎，逐行处理
# ---------------------------------------------------------------

_KANJI_RE = re.compile(r'[一-鿿]')


def annotate_lyrics(lyrics: str):
    """返回 (tokens, kanji_count)。tokens 与 lyrics.split('\\n') 逐行对齐：空行=None；
    普通行=furigana token 列表；纯罗马音行=[{s:原行, k:片假名}]。"""
    lines = lyrics.split('\n')
    tokens, kanji = [], set()
    for ln in lines:
        if not ln.strip():
            tokens.append(None)
            continue
        kanji.update(_KANJI_RE.findall(ln))
        if is_romaji_line(ln):
            tokens.append([{'s': ln, 'k': romaji_to_kana(ln)}])
            continue
        if len(ln) > 160:            # 超长行（整段糊成一行）不注音，原样保留
            tokens.append([{'s': ln}])
            continue
        try:
            tokens.append(furigana.annotate(ln))
        except Exception:
            tokens.append([{'s': ln}])
    return tokens, len(kanji)

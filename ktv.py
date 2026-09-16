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

# 高频英文词表（歌词场景）：整词命中 → 判定英文行（第一层，最强证据）
_ENGLISH_WORDS = frozenset('''
the you your yours my me mine i a an and or but so if to of in on at for with from by as is are was were be been being
do does did don cant can will would shall should may might must have has had
this that these those there here what who whom when where why how not no yes
night stay save shine brave break breaking broken dawn down up out off back
life live love loved lover heart hand hands eye eyes dream dreams light dark
never ever always again still just only all both each some any
one two three first last long short new old day days today tonight tomorrow yesterday
time world star stars moon sun sky rain snow fire water wind sea
true real come came go went going know knew say said see saw seen feel felt
need want take took make made keep kept hold held find found give gave get got
lose lost win won stop start end begin walk run fly fall rise sing song dance
music baby darling dear kiss touch away over under near far high low close open
black white red blue green deep free mind soul face head voice word words
land ground floor door room home house boy girl man men woman women
smile cry tears laugh goodbye hello forever memory alone together
'''.split())


def _latin_words(line):
    return re.findall(r"[A-Za-z'’]+", line)


def classify_latin_line(line: str) -> str:
    """纯拉丁字母行 → 'english' / 'romaji' / 'other'。多层保底：
    第1层 高频英文词典整词命中（≥3字母）→ english
    第2层 音系规则：罗马音词只能以元音或 n 结尾、绝不以 y/辅音结尾 → 违反即 english
    第3层 完全可转换性：逐音节转换后仍残留拉丁字母 → english
    全部通过才算罗马音（任何一层否决都安全落到 english，绝不乱转片假名）。"""
    t = line.strip()
    if not t or not _ROMAJI_LINE_RE.match(t):
        return 'other'
    if len(re.findall(r'[A-Za-z]', t)) < 2:
        return 'other'
    words = [w.lower() for w in _latin_words(t)]
    # 第1层：英文词典（含撇号拆分: you're → you/re）
    for w in words:
        parts = re.split(r"['’]", w)
        for part in ([w] + parts):
            if len(part) >= 3 and part in _ENGLISH_WORDS:
                return 'english'
    # 第2层：罗马音音系（词尾必须是元音或 n；y 只能出现在 ya/yu/yo，不在词尾）
    for w in words:
        w2 = w.rstrip("n'’")
        if not w2:
            continue
        if w2[-1] not in 'aeiou':
            return 'english'
    # 第3层：完全可转换（残留任何拉丁字母 → 英文）
    kana = romaji_to_kana(t)
    if re.search(r'[A-Za-z]', kana):
        return 'english'
    return 'romaji'


def is_romaji_line(line: str) -> bool:
    """真·罗马音行（多层判别后确认是罗马音，而非英文）。"""
    return classify_latin_line(line) == 'romaji'


def is_latin_line(line: str) -> bool:
    """纯拉丁字母行（罗马音或英文都算，用于歌名借用等）。"""
    return classify_latin_line(line) in ('romaji', 'english')


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
    if is_latin_line(t) and len(t) <= 30 and len(t.split()) <= 4:
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

# ---------------------------------------------------------------
# 简体字 → 日本汉字（歌词里中文转录常见字；自动转换用于词典查找，显示保留原字）
# ---------------------------------------------------------------
_S2J = {
    '凉': '涼', '风': '風', '龙': '竜', '丰': '豊', '广': '広', '庄': '荘',
    '庆': '慶', '应': '応', '库': '庫', '战': '戦', '归': '帰', '带': '帯',
    '岁': '歳', '岛': '島', '变': '変', '泪': '涙', '满': '満', '灵': '霊',
    '热': '熱', '爱': '愛', '牵': '牽', '碎': '砕', '节': '節', '纯': '純',
    '纱': '紗', '线': '線', '组': '組', '终': '終', '经': '経', '结': '結',
    '绝': '絶', '给': '給', '继': '継', '绿': '緑', '胜': '勝', '苍': '蒼',
    '荣': '栄', '蓝': '藍', '藏': '蔵', '许': '許', '诗': '詩', '语': '語',
    '说': '説', '请': '請', '读': '読', '谁': '誰', '谣': '謡', '转': '転',
    '轮': '輪', '轻': '軽', '辉': '輝', '边': '辺', '达': '達', '过': '過',
    '运': '運', '还': '還', '远': '遠', '连': '連', '迟': '遅', '选': '選',
    '乡': '郷', '银': '銀', '铁': '鉄', '铃': '鈴', '长': '長', '门': '門',
    '问': '問', '间': '間', '阳': '陽', '阴': '陰', '隐': '隠', '难': '難',
    '雾': '霧', '韵': '韻', '须': '須', '飞': '飛', '饭': '飯', '饮': '飲',
    '鸟': '鳥', '鱼': '魚', '车': '車', '马': '馬', '齐': '斉', '无': '無',
    '时': '時', '实': '実', '乐': '楽', '举': '挙', '传': '伝', '卖': '売',
    '买': '買', '华': '華', '单': '単', '严': '厳', '丽': '麗', '剑': '剣',
    '図': None, '图': '図', '圆': '円', '坏': '壊', '处': '処', '备': '備',
    '复': '復', '头': '頭', '奋': '奮', '宁': '寧', '将': '将', '师': '師',
    '扫': '掃', '气': '気', '樱': '桜', '乘': '乗', '剧': '劇', '势': '勢',
    '团': '団', '园': '園', '场': '場', '卷': '巻', '关': '関', '兴': '興',
    '恶': '悪', '愿': '願', '户': '戸', '扩': '拡', '摇': '揺', '杀': '殺',
    '树': '樹', '欢': '歓', '决': '決', '泽': '沢', '红': '紅', '约': '約',
    '纸': '紙', '编': '編', '缘': '縁', '闻': '聞', '叶': '葉', '后': '後',
    '从': '従', '怀': '懐', '姬': '姫', '窗': '窓', '发': '髪', '丝': '糸',
    '净': '浄', '机': '機', '种': '種', '东': '東', '现': '現', '动': '動',
    '静': '静', '争': '争', '音': '音', '咲': '咲',
}
_S2J = {k: v for k, v in _S2J.items() if v and k != v}

_ASCII_WORD_RE = re.compile(r'^[A-Za-z0-9\'’\-\.]+$')
_ASCII_HAS_LETTER_RE = re.compile(r'[A-Za-z]')


def _to_jp(line: str) -> str:
    return ''.join(_S2J.get(ch, ch) for ch in line)


def _restore_original_chars(toks, jp_line, orig_line):
    """把转换掉的简体字还原为用户原文写法（读音保留日文字形查到的结果）。"""
    if jp_line == orig_line:
        return
    off = 0
    for t in toks:
        s = t.get('s') or ''
        n = len(s)
        if n and len(orig_line) >= off + n and jp_line[off:off + n] != orig_line[off:off + n]:
            t['s'] = orig_line[off:off + n]
        off += n


def _restore_spaces(toks, line):
    """补全分词时丢失的原文空格：token 表面在原文中定位，缺口以空格 token 填充。"""
    out, off = [], 0
    for t in toks:
        s = t.get('s') or ''
        if not s:
            out.append(t)
            continue
        if line.startswith(s, off):
            out.append(t)
            off += len(s)
            continue
        idx = line.find(s, off)
        if idx < 0:                       # 表面异常（如数字融合），尽力前进
            out.append(t)
            off = min(len(line), off + len(s))
            continue
        gap = line[off:idx]
        if gap.strip() == '':             # 纯空白缺口 → 空格 token
            out.append({'s': gap, 'r': None})
        else:
            out.append({'s': gap})
        out.append(t)
        off = idx + len(s)
    if off < len(line) and line[off:].strip() == '':
        out.append({'s': line[off:], 'r': None})
    return out



def _protect_ascii(toks):
    """英文单词绝不注音：去掉读音/候选/未知标记。"""
    for t in toks:
        s = t.get('s') or ''
        if _ASCII_HAS_LETTER_RE.search(s) and _ASCII_WORD_RE.match(s.strip()):
            t['r'] = None
            t.pop('alt', None)
            t.pop('unk', None)
    return toks


def _backfill_ruby(toks):
    """注音一致性：同一行内同一汉字，别处有注音而此处缺失 → 回填（保守：仅单字词）。"""
    known = {}
    for t in toks:
        r = t.get('r')
        if r and len(t.get('s') or '') == 1 and _KANJI_RE.match(t['s']):
            known.setdefault(t['s'], r)
    for t in toks:
        if t.get('r'):
            continue
        s = t.get('s') or ''
        if len(s) == 1 and s in known:
            t['r'] = known[s]
            t['c'] = 'mid'
            t.pop('unk', None)
    return toks


def annotate_lyrics(lyrics: str):
    """返回 (tokens, kanji_count)。tokens 与 lyrics.split('\n') 逐行对齐：空行=None；
    普通行=furigana token 列表（含分词标记 sp / 空格 token / 简体字还原）；
    纯罗马音行=[{s:原行, k:片假名}]。"""
    lines = lyrics.split('\n')
    tokens, kanji = [], set()
    for ln in lines:
        if not ln.strip():
            tokens.append(None)
            continue
        kanji.update(_KANJI_RE.findall(ln))
        cls = classify_latin_line(ln)
        if cls == 'romaji':
            tokens.append([{'s': ln, 'k': romaji_to_kana(ln)}])
            continue
        if cls == 'english':
            tokens.append([{'s': ln, 'en': True}])
            continue
        if len(ln) > 160:            # 超长行（整段糊成一行）不注音，原样保留
            tokens.append([{'s': ln}])
            continue
        try:
            jp = _to_jp(ln)                  # 简体字 → 日本汉字（查词典用）
            toks = furigana.annotate(jp)
            _restore_original_chars(toks, jp, ln)   # 显示还原为原文写法
            toks = _restore_spaces(toks, ln)        # 补回丢失的空格
            _protect_ascii(toks)                     # 英文不注音
            _backfill_ruby(toks)                     # 同字注音一致性
            _seg_mark(toks, ln)                      # 学习模式：意思群标记
            tokens.append(toks)
        except Exception:
            tokens.append([{'s': ln}])
    return tokens, len(kanji)

# ---------------------------------------------------------------
# 学习模式：意思群切分（分かち書き）
# 用 MeCab 形态素合并成「意思群」：内容词开头断开、助词/助动词/接尾辞跟随前词、
# 连续名词性成分合并为一个群（如 一筋縄／夜空に），行内以空格分隔、只在群间换行
# ---------------------------------------------------------------

_tagger = None


def _get_tagger():
    global _tagger
    if _tagger is None:
        import fugashi
        _tagger = fugashi.Tagger()
    return _tagger

# 能开启新意思群的词类
_HEAD_POS1 = {'名詞', '代名詞', '動詞', '形容詞', '形状詞', '副詞', '接続詞',
              '感動詞', '連体詞', 'フィラー', '接頭辞'}
# 名词性成分（连续出现时合并为一个群：数詞+助数詞、名詞+接尾辞、接頭辞+名詞）
_NOUNY_POS1 = {'名詞', '代名詞', '接頭辞', '接尾辞', '連体詞'}
# 复合动词第二要素（前接动词连用形时不开新群）：結び直す／走り込む／駆け上がる…
_COMPOUND_V2 = {'直す', '込む', '出す', '上げる', '上がる', '下ろす', '返す', '合う',
                '合わせる', '切る', '切れる', '付く', '付ける', '取る', '回す',
                '果たす', '落とす', '過ぎる', '終える', '終わる', '始める'}
# 形式名詞（軽名詞）：接在用言（动词/形容词/助动词等）后时属于前面的句节，
# 不自立成群 —— 見る事／ない時／温めること／言う通り…
_FORMAL_NOUNS = {
    '事', 'こと', 'コト', '物', 'もの', 'モノ', '物事', '為', 'ため', 'タメ',
    '訳', 'わけ', 'ワケ', '筆', 'はず', 'ハズ', '積り', 'つもり', 'ツモリ',
    '所', 'ところ', 'トコ', '時', 'とき', 'トキ', '次第', 'しだい', '儘', 'まま',
    '通り', 'とおり', 'トオリ', '度', 'たび', 'タビ', '際', 'さい', '毎', 'ごと',
    '内', 'うち', '後', 'あと', '他', 'ほか', '下', 'もと', '元', '向こう', '向う',
    '傍ら', 'かたわら', '代わり', 'かわり', '所為', 'せい', 'お陰', 'おかげ',
    '陰', 'かげ', '故', 'ゆえ', '一方', 'いっぽう', '反面', 'はんめん',
    '以上', 'いじょう', '以外', 'いがい', '前', 'まえ', '先', 'さき',
}
# 用言（可后接形式名詞的词类）
_YOGEN_POS1 = {'動詞', '形容詞', '形状詞', '助動詞'}


def chunk_starts(line: str):
    """返回各意思群的起始字符偏移集合（不含 0）——多层安全网，全部通过才开新群：
      - 英文连续段是一个群（I love you）；英文段结束回到日文 → 新群
      - 未知汉字（記号）连续段可开群，其后送假名跟随（啄ば|んで 不拆）
      - 補助動詞跟随：て/で + 非自立可能动词（ている/てしまう/ていく/てみる…）
      - 复合动词跟随：动词连用形 + 直す/込む/上がる…（結びなおす/立ち上がる）
      - 形式名詞跟随：用言后的 事/物/時/ため… 与前句同群（見る事/ない時 不拆）
      - なさい（為さる命令形）接名词（ごめんなさい）
      - 連体詞与名词性成分合并（あの日の）
    偏移约定：与 _offset_words 一致，为原文的逐字偏移（空白独立成群边界时不位移）。"""
    ms = [(off, w.surface, w.feature.pos1 or '', w.feature.pos2 or '',
           w.feature.cForm or '', (w.feature.lemma or '').split('-')[0])
          for off, w in _offset_words(line)]
    starts = set()
    for k in range(1, len(ms)):
        off, surf, p1, p2, cf, lemma = ms[k]
        poff, psurf, pp1, pp2, pcf, plemma = ms[k - 1]
        prev_ascii = bool(_ASCII_WORD_RE.match(psurf or ''))
        # 英文连续段内部：不断开
        if _ASCII_HAS_LETTER_RE.search(surf) and _ASCII_WORD_RE.match(surf):
            if k + 1 < len(ms) and _ASCII_WORD_RE.match(ms[k + 1][1] or ''):
                continue
            if prev_ascii:
                continue
        # 英文段结束、回到日文词 → 新群
        if prev_ascii and _CJK_RE.search(surf):
            starts.add(off)
            continue
        # 未知汉字段：自身可开群，但连续未知汉字/其送假名跟随
        if p1 == '記号' and _CJK_RE.search(surf):
            if pp1 == '記号':
                continue
            starts.add(off)
            continue
        if pp1 == '記号':
            continue
        if p1 not in _HEAD_POS1:
            continue
        # 補助動詞：て/で + 非自立可能（いる/しまう/いく/みる/おく…）
        if pp1 == '助詞' and pp2 == '接続助詞' and psurf in ('て', 'で') \
                and p2 == '非自立可能':
            continue
        # 复合动词第二要素
        if pp1 == '動詞' and pcf.startswith('連用形') and lemma in _COMPOUND_V2:
            continue
        # 形式名詞跟随：用言（连体修饰）后的 事/物/時/ため… 与前句同群（見る事 不拆）
        if p1 in ('名詞', '接尾辞') and (surf in _FORMAL_NOUNS or lemma in _FORMAL_NOUNS) \
                and pp1 in _YOGEN_POS1:
            continue
        # ごめんなさい（為さる命令形接名词）
        if lemma == '為さる' and pp1 in ('名詞', '代名詞', '接尾辞'):
            continue
        if p1 in _NOUNY_POS1 and pp1 in _NOUNY_POS1:
            continue
        starts.add(off)
    return starts


def _offset_words(line):
    """形态素真实字符偏移（用于与注音 token 逐字对齐）。
    优先按「表面串与原文逐字吻合」定位真实偏移；分词器吞掉空白时才退回跳过空白，
    保证同一行内所有偏移与注音 token 的连续偏移一致（否则 歌名行 sp 标记会错位）。"""
    off, n = 0, len(line)
    for w in _get_tagger()(line):
        s = w.surface
        if not s:
            continue
        if not (off < n and line[off:off + len(s)] == s):
            while off < n and line[off].isspace():    # 兜底：分词器未输出空白 token
                off += 1
        yield off, w
        off += len(s)


def _seg_mark(tokens, line):
    """给 furigana token 列表打 sp=True 标记（该 token 前应有意思群空格）。
    多层安全网：
      1) 先清除旧版算法遗留的错位 sp —— 旧歌打开即自愈；
      2) token 逐字重建必须与原行完全一致，否则放弃分词（宁可不分，绝不分错）。"""
    changed = False
    for t in tokens:
        if isinstance(t, dict) and t.pop('sp', None):
            changed = True
    starts = chunk_starts(line)
    recon = ''.join(t.get('s') or '' for t in tokens if isinstance(t, dict))
    if not starts or recon != line:
        return changed
    off = 0
    for t in tokens:
        if off > 0 and off in starts and not t.get('sp'):
            t['sp'] = True
            changed = True
        off += len(t.get('s') or '')
    return changed


def ensure_seg(song_row):
    """兼容旧数据：没有分词标记的歌词 token 即时补算并回写。返回 token 列表。"""
    toks = json.loads(song_row['tokens']) if song_row['tokens'] else []
    lyrics = song_row['lyrics']
    lines = lyrics.split('\n')
    if len(toks) != len(lines):
        return toks
    changed = False
    for ln, t in zip(lines, toks):
        if t and isinstance(t, list) and t and 'k' not in t[0] and 's' in t[0]:
            changed |= _seg_mark(t, ln)
    if changed:
        import db as _db
        _db.update_song_tokens(song_row['id'], toks)
    return toks

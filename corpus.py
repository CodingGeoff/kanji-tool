# -*- coding: utf-8 -*-
"""
语料抓取模块：对接公开免费渠道，持续扩充本地语料库。
渠道:
  1. Tatoeba  —— 海量日语例句 + 中/英翻译 (CC协议, 官方API)
  2. ja.Wikipedia —— 随机条目摘要 (CC BY-SA, 官方API)
  3. ja.Wikinews  —— 随机新闻 (官方API)
抓到的句子经形态素分析注音后写入本地 SQLite 缓存，已有句子自动去重，
后续学习复习均优先读本地库。
"""
import re
import requests
import db
import furigana

UA = {'User-Agent': 'Mozilla/5.0 (KanjiLearningTool/1.0; personal study use)'}
_SENT_SPLIT = re.compile(r'(?<=[。！？!?])')


def _clean(s):
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'（[ぁ-んァ-ヶー・、\s]+）', '', s)  # 去掉括号里的假名注音
    return s.strip()


# ---------------- 脏数据防御 ----------------
_JUNK_RE = re.compile(r'[_＿]|\d{7,}|テスト文|[A-Za-z]{25,}')
_KANJI_KANA_RE = re.compile(r'([一-龥々〆ヶ]+)([ぁ-んー]+)')


def is_junk(text: str) -> bool:
    """明显的垃圾文本：下划线/超长数字串(时间戳)/测试标记"""
    return bool(_JUNK_RE.search(text))


def repair_inline_furigana(text: str):
    """
    修复「内嵌注音」文本（从注音网页复制出来的 日本にっぽん語ご 形式）。
    原理：对每个 [汉字段+假名段]，尝试把假名段前缀作为该汉字段的注音剥离——
    仅当「汉字段+剩余假名」整体的词典读音 == 被剥离注音+剩余假名 时才剥离，
    且整句至少发生 2 处剥离才认定为内嵌注音文本（防止误伤正常句子）。
    返回 (修复后文本, 剥离次数)
    """
    strips = 0

    def _sub(m):
        nonlocal strips
        kanji, kana = m.group(1), m.group(2)
        for L in range(1, len(kana) + 1):   # 最小剥离原则，防止过度剥离
            ruby, rest = kana[:L], kana[L:]
            candidate = kanji + rest
            try:
                readings = set()
                for path in furigana._tagger.nbestToNodeList(candidate, 3):
                    r, ok = '', True
                    for w in path:
                        k = w.feature.kana
                        if not k or k == '*':
                            ok = False
                            break
                        r += furigana.kata_to_hira(k)
                    if ok:
                        readings.add(r)
            except Exception:
                readings = set()
            if (ruby + rest) in readings:
                strips += 1
                return candidate
        return m.group(0)

    fixed = _KANJI_KANA_RE.sub(_sub, text)
    if strips >= 2:
        return fixed, strips
    return text, 0


_OLD_KANA_RE = re.compile(r'[ゐゑヰヱ]')          # 旧假名遣（战前正字法）
_DATA_ROW_RE = re.compile(r'[A-Za-z]')


_OLD_PHRASES = [  # 旧仮名遣 → 现代写法（固定短语先长后短）
    ('であらう', 'であろう'), ('なからう', 'なかろう'), ('でせう', 'でしょう'),
    ('ませう', 'ましょう'), ('だらう', 'だろう'),
    ('さうです', 'そうです'), ('さうだ', 'そうだ'), ('さう', 'そう'),
    ('のやうに', 'のように'), ('のやうな', 'のような'),
    ('やうに', 'ように'), ('やうな', 'ような'), ('やうだ', 'ようだ'),
    ('けふ', 'きょう'), ('てふてふ', 'ちょうちょう'),
    # 旧促音副词（大つ）
    ('そつと', 'そっと'), ('きつと', 'きっと'), ('じつと', 'じっと'),
    ('ずつと', 'ずっと'), ('ほつと', 'ほっと'), ('やつと', 'やっと'),
    ('もつと', 'もっと'), ('ちよつと', 'ちょっと'),
    # 旧ハ行転呼（高频動詞）
    ('思ふ', '思う'), ('思は', '思わ'), ('思ひ', '思い'), ('思へ', '思え'),
    ('言ふ', '言う'), ('言は', '言わ'), ('言ひ', '言い'), ('言へ', '言え'),
    ('いふ', 'いう'), ('いは', 'いわ'), ('笑ふ', '笑う'), ('買ふ', '買う'),
    ('会ふ', '会う'), ('使ふ', '使う'), ('違ふ', '違う'), ('向ふ', '向こう'),
    ('行はれ', '行われ'), ('云ふ', '云う'), ('雖も', 'いえども'),
]
_OLD_KANA_TRANS = str.maketrans('ゐゑヰヱ', 'いえイエ')


def modernize_old_kana(text):
    """旧假名遣（1946年前正字法）→ 现代假名。
    仅当句中出现废止假名 ゐゑヰヱ（确证旧文体）时才激活积极转换，
    避免误伤现代文。返回 (转换后文本, 原文或None)。"""
    if not _OLD_KANA_RE.search(text):
        return text, None
    orig = text
    s = text
    for a, b in _OLD_PHRASES:
        s = s.replace(a, b)
    s = s.translate(_OLD_KANA_TRANS)                       # ゐ→い ゑ→え
    s = re.sub(r'(?<=[぀-ヿ一-鿿])つ(?=[てた])', 'っ', s)   # 旧促音：泊つて→泊って
    if '食らう' not in s and '食らわ' not in s:
        s = re.sub(r'(?<=[一-鿿])らう', 'ろう', s)          # 旧意志形：寄らう→寄ろう
    return s, orig


def _good_sentence(s):
    if not (4 <= len(s) <= 90):
        return False
    if not furigana.has_kanji(s):
        return False
    if re.search(r'[<>{}\[\]=|]', s):
        return False
    # 传记资料句（中西立太（なかにしりった、1934年3月18日-2009年…））：生卒日期括注
    # 兼容夹注纪年写法：1880年〈明治13年〉7月16日-1942年（月日- 连排）、1880年-1942年（年份区间）
    if re.search(r'\d+年\d+月\d+日\s*[-−–—]', s) or \
       re.search(r'\d{1,2}月\d{1,2}日\s*[-−–—]\s*\d', s) or \
       re.search(r'\d{3,4}年\s*[-−–—]\s*\d{3,4}年', s):
        return False
    # 资料碎片（身長157cm / 血液型A型）：ASCII字母≥2 且假名≤2 → 非自然语句
    kana_n = sum(1 for ch in s if 'ぁ' <= ch <= 'ん' or 'ァ' <= ch <= 'ヶ')
    ascii_alpha = sum(1 for ch in s if ch.isascii() and ch.isalpha())
    if ascii_alpha >= 2 and kana_n <= 2:
        return False
    return True


def _store(text, translation, source, url, results):
    text = _clean(text)
    if is_junk(text):
        return
    text, _n = repair_inline_furigana(text)
    text, orig = modernize_old_kana(text)   # 旧假名句转现代写法、保留原文
    if not _good_sentence(text) or db.sentence_exists(text):
        return
    tokens = furigana.annotate(text)
    kw = furigana.extract_kanji_words(tokens)
    if not kw:
        return
    sid = db.add_sentence(text, translation, source, url, tokens, kw, orig_text=orig)
    if sid:
        results.append(text)


def fetch_tatoeba(pages=2, results=None):
    """Tatoeba 随机例句，优先取中文翻译，其次英文"""
    results = results if results is not None else []
    for _ in range(pages):
        try:
            r = requests.get(
                'https://tatoeba.org/en/api_v0/search',
                params={'from': 'jpn', 'sort': 'random', 'limit': 30, 'orphans': 'no'},
                headers=UA, timeout=25)
            data = r.json()
        except Exception:
            continue
        for item in data.get('results', []):
            text = item.get('text', '')
            trans_cmn, trans_eng = None, None
            for group in item.get('translations', []):
                for t in group:
                    if t.get('lang') == 'cmn' and not trans_cmn:
                        trans_cmn = t.get('text')
                    elif t.get('lang') == 'eng' and not trans_eng:
                        trans_eng = t.get('text')
            _store(text, trans_cmn or trans_eng,
                   'tatoeba', f"https://tatoeba.org/sentences/show/{item.get('id','')}", results)
    return results


def _fetch_wiki_api(api, source, batches=1, per=5, results=None):
    results = results if results is not None else []
    for _ in range(batches):
        try:
            r = requests.get(api, params={
                'action': 'query', 'generator': 'random', 'grnnamespace': 0,
                'grnlimit': per, 'prop': 'extracts', 'exintro': 1,
                'explaintext': 1, 'format': 'json'}, headers=UA, timeout=25)
            pages = r.json().get('query', {}).get('pages', {})
        except Exception:
            continue
        for p in pages.values():
            extract = p.get('extract') or ''
            title = p.get('title', '')
            url = f"{api.split('/w/')[0]}/wiki/{title}"
            for sent in _SENT_SPLIT.split(extract)[:6]:
                _store(sent, None, source, url, results)
    return results


def fetch_wikipedia(batches=1, results=None):
    return _fetch_wiki_api('https://ja.wikipedia.org/w/api.php', 'wikipedia', batches, 5, results)


def fetch_wikinews(batches=1, results=None):
    return _fetch_wiki_api('https://ja.wikinews.org/w/api.php', 'wikinews', batches, 5, results)


SOURCES = {
    'tatoeba': lambda: fetch_tatoeba(pages=2),
    'wikipedia': lambda: fetch_wikipedia(batches=2),
    'wikinews': lambda: fetch_wikinews(batches=2),
}


def fetch(source='all'):
    added = []
    if source in ('all', 'tatoeba'):
        added += fetch_tatoeba(pages=2)
    if source in ('all', 'wikipedia'):
        added += fetch_wikipedia(batches=1)
    if source in ('all', 'wikinews'):
        added += fetch_wikinews(batches=1)
    if added:
        db.log('fetch', f'来源[{source}] 新增语料 {len(added)} 句')
    return added

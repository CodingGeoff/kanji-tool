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


def _good_sentence(s):
    if not (4 <= len(s) <= 90):
        return False
    if not furigana.has_kanji(s):
        return False
    if re.search(r'[<>{}\[\]=|]', s):
        return False
    return True


def _store(text, translation, source, url, results):
    text = _clean(text)
    if not _good_sentence(text) or db.sentence_exists(text):
        return
    tokens = furigana.annotate(text)
    kw = furigana.extract_kanji_words(tokens)
    if not kw:
        return
    sid = db.add_sentence(text, translation, source, url, tokens, kw)
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

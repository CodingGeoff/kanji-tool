# -*- coding: utf-8 -*-
"""
汉字注音核心模块
基于 fugashi(MeCab) + UniDic 词典做形态素分析，读音由上下文决定，
能正确处理日语多音字（音读/训读/复合读音）与「纯汉字」「汉字+假名混合」文本。
"""
import re
import fugashi

_tagger = fugashi.Tagger()

# 视作"汉字"的字符（含叠字号々、〆、小ヶ——它们在词中承担读音）
_EXTRA_KANJI = set('々〆ヶ')


def is_kanji(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or
        0x3400 <= code <= 0x4DBF or
        0xF900 <= code <= 0xFAFF or
        ch in _EXTRA_KANJI
    )


def has_kanji(text: str) -> bool:
    return any(is_kanji(c) for c in text)


def kata_to_hira(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:   # ァ..ヶ -> ぁ..ゖ
            out.append(chr(code - 0x60))
        elif ch == 'ー':
            out.append('ー')
        else:
            out.append(ch)
    return ''.join(out)


def _segment_word(surface: str):
    """把单词表面形切成 (片段, 是否汉字段) 的连续段"""
    segs = []
    cur, cur_k = '', None
    for ch in surface:
        k = is_kanji(ch)
        if cur_k is None or k == cur_k:
            cur += ch
            cur_k = k
        else:
            segs.append((cur, cur_k))
            cur, cur_k = ch, k
    if cur:
        segs.append((cur, cur_k))
    return segs


def _align(surface: str, reading_hira: str):
    """
    把整词读音对齐到词内的汉字段（送り仮名对齐）。
    例: 「美味しい」(おいしい) -> [("美味","おい"), ("しい",None)]
    返回 [(片段, ruby或None)]；失败返回 None。
    """
    segs = _segment_word(surface)
    pattern = ''
    kanji_slots = 0
    for text, k in segs:
        if k:
            pattern += '(.+?)' if kanji_slots < sum(1 for _, kk in segs if kk) - 1 else '(.+)'
            kanji_slots += 1
        else:
            pattern += re.escape(kata_to_hira(text))
    m = re.fullmatch(pattern, reading_hira)
    if not m:
        return None
    result = []
    gi = 1
    for text, k in segs:
        if k:
            result.append((text, m.group(gi)))
            gi += 1
        else:
            result.append((text, None))
    return result


def annotate(text: str):
    """
    对任意日文文本注音。
    返回 token 列表: {"s": 表面形, "r": 平假名注音或None, "w": 所属词, "wr": 词整体读音}
    只有含汉字的片段才带注音 r。
    """
    tokens = []
    for w in _tagger(text):
        surface = w.surface
        if not surface:
            continue
        kana = w.feature.kana
        if (not kana or kana == '*') and w.feature.pron and w.feature.pron != '*':
            kana = w.feature.pron
        if not has_kanji(surface):
            tokens.append({'s': surface, 'r': None, 'w': None, 'wr': None})
            continue
        if not kana or kana == '*':
            # 词典未知词：无法保证读音，明确标记而不是猜错
            tokens.append({'s': surface, 'r': None, 'w': surface, 'wr': None, 'unk': True})
            continue
        reading = kata_to_hira(kana)
        aligned = _align(surface, reading)
        if aligned is None:
            # 对齐失败则整词标注（读音仍然正确，只是粒度粗一点）
            tokens.append({'s': surface, 'r': reading, 'w': surface, 'wr': reading})
        else:
            for seg, ruby in aligned:
                tokens.append({'s': seg, 'r': ruby, 'w': surface, 'wr': reading})
    return tokens


def extract_kanji_words(tokens):
    """从注音结果提取 (汉字字符, 所属词, 词读音) 三元组，用于建立汉字索引"""
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


if __name__ == '__main__':
    tests = [
        '今日は日本語の勉強をします。',      # 今日=きょう (熟字训)
        '一人で一つの人形を作った。',        # 一人=ひとり / 一つ=ひとつ / 人形=にんぎょう 多音字
        '生き物の生態を生涯研究した。',      # 生 的三种读法
        '東京都内で大雨が降った。',
        '食べ物が美味しかった。',            # 送り仮名对齐
        '昨日、山田さんは行方不明になった。', # 熟字训 昨日/行方
    ]
    for s in tests:
        print(s)
        print('  ', ' '.join(f"{t['s']}({t['r']})" if t['r'] else t['s'] for t in annotate(s)))

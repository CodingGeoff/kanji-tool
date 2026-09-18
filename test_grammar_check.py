# -*- coding: utf-8 -*-
"""基础语法检查与题干质检专项测试：
覆盖：
1. 真实日本语句子通过率（敬体/简体会话/条件/愿望/推量等）
2. 历史语料库异常句精准拦截（日本語の勉強を始めましたうてえていさねに。）
3. 句尾形态素异常终结（格助词截断/接续助词悬空/连用形未完结句）
4. 合法语用保留（懊恼悔恨「〜のに。」/口语必要「〜ないと。」）
5. 述语缺失/纯标题/人名/日期/版权附注识别
6. 句内助词与活用接续合法性（终助词后连用格助词/敬体断裂/使役非法接续）
7. 课本导入前 analyze 语法体检回显
8. 课本书内 check_book_grammar 审计接口
9. /api/grammar/check 接口契约
"""
import os
import shutil
import sys
import tempfile
import unittest

import db
import grammar
import textbook

# 接口测试一律跑在临时库上：直接动真正的 kanji.db 会留下「テスト課本」课本与历史记录，
# 污染要提交上云的数据库（其它 test_*.py 也是这么做的）。
_TMPDIR = tempfile.mkdtemp(prefix='grammar_check_')
db.DB_PATH = os.path.join(_TMPDIR, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'),
            db.DB_PATH)
import app as appmod

FAILS = []


def check(cond, msg):
    if cond:
        print(f'  [OK]   {msg}')
        return True
    FAILS.append(msg)
    print(f'  [FAIL] {msg}')
    return False


print('== 1. 真实日本语句子标准通过 ==')
GOOD_CASES = [
    '日本語の勉強を始めました。',
    '雨が降っているので、試合は中止になりました。',
    '彼女は毎日図書館で本を読んでいる。',
    'この薬を飲めば、すぐによくなるでしょう。',
    '彼は来ないかもしれないと言っていた。',
    '日本語が上手になるために、毎日練習している。',
    '窓を開けてもいいですか。',
    '昨日買ったばかりのカメラをなくしてしまった。',
    '母に心配をかけないように、早く帰ることにした。',
    '弟は昨日東京に戻ってこなかった。',
    '煙草をやめることにした。',
    '夜10時以降は静かにすること。',
    '学生であるにもかかわらず、働かざるを得ない。',
    '先生によって書かれた本を読みつつ、日本語が上手になっていく。',
    '春は美しい季節です。',
    '今日は良い天気ですね。',
    '東京タワーへ行きました。',
    '桜が咲きました。',
]
for s in GOOD_CASES:
    res = grammar.check_sentence_grammar(s)
    check(res['ok'] and res['score'] >= 0.9, f'好句通过检查(score={res["score"]}): {s}')
    check(textbook._cloze_sentence_ok(s), f'挖空质检放行: {s}')

print('\n== 2. 异常历史语料精准拦截 ==')
# 导致用户遭遇诡异出题的病句
BUG_SENTENCE = '日本語の勉強を始めましたうてえていさねに。'
res_bug = grammar.check_sentence_grammar(BUG_SENTENCE)
check(not res_bug['ok'], f'精准拦截成因句: {BUG_SENTENCE}')
check(res_bug['score'] <= 0.3, f'健康分低分惩罚: score={res_bug["score"]}')
check(any('格助词' in e or '句法结构断裂' in e for e in res_bug['errors']),
      f'准确指出语病原因: {res_bug["errors"]}')
check(not textbook._cloze_sentence_ok(BUG_SENTENCE), '挖空门禁严格拦截成因句')

BUG_SENTENCE_2 = '日本語の勉強を始めましたうあきせこせない。'
res_bug2 = grammar.check_sentence_grammar(BUG_SENTENCE_2)
check(not res_bug2['ok'], f'精准拦截第二变种伪造串: {BUG_SENTENCE_2}')
check(any('接续' in e or '敬体' in e or '伪' in e for e in res_bug2['errors']),
      f'指出非法形态接续: {res_bug2["errors"]}')
check(not textbook._cloze_sentence_ok(BUG_SENTENCE_2), '挖空门禁严格拦截第二变种')

print('\n== 3. 句尾形态素异常终结 ==')
CASE_PARTICLE_BAD = [
    ('学校へ行くに。', '句尾格助词「に」截断'),
    ('美味しいリンゴを。', '句尾格助词「を」截断'),
    ('今日は天気が。', '句尾格助词「が」截断'),
    ('その部屋で。', '句尾格助词「で」截断'),
    ('彼より。', '句尾格助词「より」截断'),
]
for text, desc in CASE_PARTICLE_BAD:
    r = grammar.check_sentence_grammar(text)
    check(not r['ok'] and any('格助词' in e for e in r['errors']), f'{desc}: {text}')
    check(not textbook._cloze_sentence_ok(text), f'挖空门禁拦截: {text}')

CONJ_PARTICLE_BAD = [
    ('薬を飲めば。', '接续助词「ば」悬空'),
    ('雨が降っても。', '接续助词「ても」悬空'),
    ('本を読みつつ。', '接续助词「つつ」悬空'),
    ('テレビを見ながら。', '接续助词「ながら」悬空'),
]
for text, desc in CONJ_PARTICLE_BAD:
    r = grammar.check_sentence_grammar(text)
    check(not r['ok'] and any('接续助词' in e for e in r['errors']), f'{desc}: {text}')
    check(not textbook._cloze_sentence_ok(text), f'挖空门禁拦截: {text}')

DANGLING_STEMS = [
    ('本を読み。', '连用形未完结句'),
    ('そこへ行か。', '未然形无助动词'),
]
for text, desc in DANGLING_STEMS:
    r = grammar.check_sentence_grammar(text)
    check(not r['ok'] and any('连用形' in e or '未然形' in e for e in r['errors']), f'{desc}: {text}')
    check(not textbook._cloze_sentence_ok(text), f'挖空门禁拦截: {text}')

print('\n== 4. 合法语用保留（防误伤） ==')
VALID_COLLOQUIAL = [
    'もっと早く来ればよかったのに。',   # 〜のに
    '早く帰らないと。',                 # 〜ないと
    '夜は静かにすること。',             # 〜こと
    '知らなかったんだもの。',           # 〜もの
    'ちょっと待ってください。',         # てください
]
for s in VALID_COLLOQUIAL:
    r = grammar.check_sentence_grammar(s)
    check(r['ok'], f'合法语用未被误伤: {s} (errors={r["errors"]})')

print('\n== 5. 述语缺失/纯标题/人名/日期/文献出处识别 ==')
NO_PREDICATE = [
    ('（『日本人の法則』株式会社ヤック企画）', '文献出处附注'),
    ('（『光村読書シリーズ4年・9』 光村教育図書）', '丛书出版附注'),
    ('2002年9月20日', '纯日期'),
    ('10月25日', '纯月日'),
    ('敬具', '书信结语'),
    ('清水和夫', '纯人名'),
    ('高校の恩師への手紙', '书信标题'),
]
for text, desc in NO_PREDICATE:
    r = grammar.check_sentence_grammar(text)
    check(not r['ok'], f'{desc}被正确识别为非合规教学例句: {text}')
    check(not textbook._cloze_sentence_ok(text), f'挖空门禁拒绝非例句: {text}')

print('\n== 6. 句内助词与接续连贯性 ==')
INCOHERENT = [
    ('これはペンですねに。', '终助词「ね」后非法连用「に」'),
    ('学校をに行く。', '格助词重叠「をに」'),
    ('日本語を勉強しましたうれしいです。', '敬体终止形后直接拼接实词'),
]
for text, desc in INCOHERENT:
    r = grammar.check_sentence_grammar(text)
    check(not r['ok'], f'{desc}: {text}')

print('\n== 7. 课本导入前 analyze 语法体检 ==')
SAMPLE_TEXTBOOK = """《テスト課本》
第1課
日本語の勉強を始めました。桜が咲きました。
高校の恩師への手紙
2002年9月20日
（『日本人の法則』株式会社ヤック企画）
"""
analysis = textbook.analyze(SAMPLE_TEXTBOOK)
check('grammar_check' in analysis, 'analyze 返回结果包含 grammar_check 字段')
gc = analysis['grammar_check']
check(gc['valid'] >= 2, f'正确识别合规句数: valid={gc["valid"]}')
check(gc['invalid'] >= 1, f'正确统计存疑片段数: invalid={gc["invalid"]}')
check(0 < gc['rate'] < 100, f'准确计算合规率: rate={gc["rate"]}%')
check(len(gc['issues']) > 0, f'详细提供存疑行原因清单: {len(gc["issues"])} 条')

print('\n== 8. 课本书内全量语法审计 check_book_grammar ==')
client = appmod.app.test_client()
# 导入临时测试课本
r_imp = client.post('/api/books/import', json={'text': SAMPLE_TEXTBOOK})
d_imp = r_imp.get_json()
bid = d_imp['books'][0]['id']
try:
    audit = textbook.check_book_grammar(bid)
    check(audit['book_id'] == bid, f'审计返回 book_id: {audit["book_id"]}')
    check(audit['total'] > 0 and 'rate' in audit, f'审计总览统计: {audit["total"]} 句，合规率 {audit["rate"]}%')
finally:
    client.delete(f'/api/books/{bid}')

print('\n== 9. /api/grammar/check 接口契约 ==')
# 单句检测
r_api = client.post('/api/grammar/check', json={'text': '日本語の勉強を始めました。'})
d_api = r_api.get_json()
check(r_api.status_code == 200 and d_api['ok'] is True and d_api['score'] == 1.0, 'API 单句合规检测')

# 单句异常检测
r_api2 = client.post('/api/grammar/check', json={'text': BUG_SENTENCE})
d_api2 = r_api2.get_json()
check(r_api2.status_code == 200 and d_api2['ok'] is False and len(d_api2['errors']) > 0,
      'API 异常句检测返回详细诊断')

# 批量检测
r_api3 = client.post('/api/grammar/check', json={
    'sentences': ['今日は晴れです。', '日本語の勉強を始めましたうてえていさねに。']
})
d_api3 = r_api3.get_json()
check(r_api3.status_code == 200 and d_api3['total'] == 2 and d_api3['rows'][0]['ok'] and not d_api3['rows'][1]['ok'],
      'API 批量语法检测')

# 空文本处理
r_api4 = client.post('/api/grammar/check', json={'text': '   '})
check(r_api4.status_code == 400, '空文本返回 400')

print()
shutil.rmtree(_TMPDIR, ignore_errors=True)
if FAILS:
    print(f'===== 测试失败 {len(FAILS)} 项 =====')
    for f in FAILS:
        print(f'  - {f}')
    sys.exit(1)
else:
    print('===== 基础语法检查专项测试: 全部通过 =====')
    sys.exit(0)

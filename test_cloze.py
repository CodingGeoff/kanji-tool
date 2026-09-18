# -*- coding: utf-8 -*-
"""挖空测验专项测试（v13）：完整题干 / 碎片剔除 / 混淆干扰项 / 出处与注音。
临时库隔离，不碰真实数据。"""
import os
import sys
import shutil
import random
import sqlite3
import tempfile

sys.path.insert(0, '.')

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


import db
tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    for t in ('books', 'book_lessons', 'book_sentences', 'book_kanji', 'book_words',
              'book_plan', 'book_progress', 'srs', 'sentences', 'fav_sentences'):
        try:
            c0.execute(f'DELETE FROM {t}')
        except sqlite3.OperationalError:
            pass
db.DB_PATH = api_db
import textbook
import app as appmod
client = appmod.app.test_client()

GOOD = [
    ('雨が降っているので、試合は中止になりました。', '因为下雨，比赛中止了。'),
    ('彼女は毎日図書館で本を読んでいる。', '她每天在图书馆看书。'),
    ('この薬を飲めば、すぐによくなるでしょう。', '吃了这药马上就会好吧。'),
    ('彼は来ないかもしれないと言っていた。', '他说也许不来了。'),
    ('日本語が上手になるために、毎日練習している。', '为了提高日语每天练习。'),
    ('窓を開けてもいいですか。', '可以开窗吗。'),
    ('昨日買ったばかりのカメラをなくしてしまった。', '把昨天刚买的相机弄丢了。'),
    ('母に心配をかけないように、早く帰ることにした。', '为了不让妈妈担心决定早点回家。'),
]
# 必须被题干质检拒绝的坏句子（格式瑕疵 + 基本语法严重语病/截断/伪造串）
BAD = [
    '今日は晴れだ。明日も晴れるだろう。',   # 多句拼接
    '寒い。',                                # 过短
    'これはペンです',                        # 无句末标点
    '日本語の勉強を始めましたうてえていさねに。', # 终助词后连用格助词+格助词句尾截断
    '日本語の勉強を始めましたうあきせこせない。', # 敬体终止后断裂+使役非法接续
    '学校へ行くに。',                        # 句尾格助词截断
    '本を読み。',                            # 句尾连用形未完结句
    '（『日本人の法則』株式会社ヤック企画）', # 文献出处附注/无谓语
]
# 句子本身完整、但只能产出屈折碎片候选（てこ / ことにし）→ 应无可用候选、永不被选中
FRAG_SENTS = [
    '弟は昨日東京に戻ってこなかった。',
    'タバコをやめることにした。',
]
FRAG_ANSWERS = {'てこ', 'てこな', 'ことにし', 'れ', 'た', 'なかっ', 'なかったの'}

print('== 1. 题干质检 ==')
for s in GOOD:
    check(textbook._cloze_sentence_ok(s[0]), f'好句应通过质检：{s[0]}')
for s in BAD:
    check(not textbook._cloze_sentence_ok(s), f'坏句应被拒绝：{s}')

for text, tr in GOOD:
    textbook._store_sentence(text, tr)
for s in BAD + FRAG_SENTS:
    # 坏句也入库（模拟脏库），验证出题引擎能主动过滤
    textbook._store_sentence(s, None)

print('== 2. 全库出题：完整性 ==')
random.seed(20260917)
r = client.post('/api/books/cloze', json={'scope': 'corpus', 'min_level': 'N4', 'count': 8})
qz = r.get_json()
check(qz['ok'] and qz['count'] >= 5, f'至少出 5 题，实际 {qz.get("count")}')
for q in qz['questions']:
    check(q['before'] + q['answer'] + q['after'] == q['text'],
          f'题干拼回原文：{q["before"]}【{q["answer"]}】{q["after"]}')
    check(textbook._cloze_sentence_ok(q['text']), f'题干质检通过：{q["text"]}')
    check(len(q['answer']) >= 2 or q['answer'] in ('ば', 'と'),
          f'答案非碎片（ば/と为例外放行）：{q["answer"]}')
    check(q['answer'] not in FRAG_ANSWERS, f'答案非已知碎片：{q["answer"]}')
    check(q['text'].count(q['answer']) == 1, f'答案句中唯一：{q["answer"]} @ {q["text"]}')
    check(len(q['options']) == 4 and q['answer'] in q['options']
          and len(set(q['options'])) == 4, f'4 选项含答案不重复：{q["options"]}')
    check(q['tokens'] and q['tokens_b'] and q['tokens_a'] and q['atokens'],
          '整句/空位前后/答案注音齐全')
    check(''.join(t.get('s', '') for t in q['tokens_b']) == q['before']
          and ''.join(t.get('s', '') for t in q['tokens_a']) == q['after'],
          '前后注音与文本精确对齐（无串位）')
    check(q['origin'] and q['translation'], f'出处与翻译齐全：{q["origin"]}')
    check(q['explain'] and q['structure'] and q['level'], '讲解/接续/等级齐全')

print('== 3. 坏句/碎片句永不出现 ==')
texts = [q['text'] for q in qz['questions']]
for s in BAD + FRAG_SENTS:
    check(s not in texts, f'坏句未被选中：{s}')

print('== 4. 同类混淆干扰项 ==')
node = [q for q in qz['questions'] if q['answer'] == 'ので']
if node:
    q = node[0]
    check('から' in q['options'] and 'ために' in q['options'],
          f'ので的干扰项含 から/ために：{q["options"]}')
else:
    print('  (本轮未抽到 ので，单独测混淆函数)')
    opts = textbook._cloze_distractors('〜ので（原因）', 'ので', 'N4', {})
    check(opts[:3] == ['から', 'ために', 'おかげで'], f'混淆组直出：{opts}')
teiru = [q for q in qz['questions'] if q['answer'] == 'ている']
if teiru:
    q = teiru[0]
    check(any(x in q['options'] for x in ('てある', 'ておく', 'てしまう', 'てみる')),
          f'ている的干扰项为同组：{q["options"]}')
# 空池兜底也必须凑满 3 个
opts = textbook._cloze_distractors('〜ので（原因）', 'ので', 'N4', {})
check(len(opts) == 3 and len(set(opts)) == 3 and 'ので' not in opts, f'兜底 3 项：{opts}')
# 等价形互斥：ている的干扰项绝不能含缩约形 てる（反之亦然）
opts = textbook._cloze_distractors('〜ている（進行・状態）', 'ている', 'N4',
                                   {'N4': ['てる', 'てある', 'ておく', 'てみる']})
check('てる' not in opts and len(opts) == 3, f'ている↔てる互斥：{opts}')
opts = textbook._cloze_distractors('縮約形〜てる／てた（ている）', 'てる', 'N4',
                                   {'N4': ['ている', 'てある', 'ておく']})
check('ている' not in opts and len(opts) == 3, f'てる↔ている互斥：{opts}')

print('== 5. 课本题源：出处标书名课名 ==')
bk = textbook.import_book({'title': '挖空课本', 'author': '', 'level': '',
                           'lessons': [{'title': '第1課', 'sentences': [s[0] for s in GOOD]}]})
random.seed(7)
r = client.post('/api/books/cloze', json={'book_ids': [bk['id']], 'scope': 'book',
                                          'min_level': 'N4', 'count': 4})
qb = r.get_json()
check(qb['ok'] and qb['scope'] == 'book' and qb['count'] >= 1, f'课本出题 {qb.get("count")}')
for q in qb['questions']:
    check(q['book_id'] == bk['id'] and '挖空课本' in (q['origin'] or '')
          and '第1課' in (q['origin'] or ''),
          f'课本出处标注：{q.get("origin")}')
    check(q['before'] + q['answer'] + q['after'] == q['text'], '课本题干完整')

print('== 6. 断定槽位 / 条件形单字 / 候选直测 ==')
opts = textbook._cloze_distractors('〜べきだ（当然）', 'べき', 'N2', {}, after='だ。')
check(opts == ['はず', 'わけ', 'そう'], f'べき|だ 槽位用断定词干：{opts}')
opts = textbook._cloze_distractors('〜ところだ（局面）', 'ところ', 'N3',
                                   {'N3': ['ところだ', 'うちに', 'まま']}, after='だ。')
check('ところだ' not in opts and len(opts) == 3, f'ところ vs ところだ不共存：{opts}')
c = textbook._cloze_candidates('駅に着いたら電話してください。', 1, {})
check(any(x['answer'] == 'たら' for x in c), f'たら完整形可挖：{[x["answer"] for x in c]}')
c = textbook._cloze_candidates('春になれば桜が咲きます。', 1, {})
check(any(x['answer'] == 'ば' for x in c), f'条件ば可挖：{[x["answer"] for x in c]}')
c = textbook._cloze_candidates('このボタンを押すとドアが開きます。', 1, {})
check(any(x['answer'] == 'と' for x in c), f'条件と可挖：{[x["answer"] for x in c]}')
c = textbook._cloze_candidates('弟は昨日東京に戻ってこなかった。', 1, {})
check(all(x['answer'] not in FRAG_ANSWERS for x in c), '碎片句无碎片候选')
c = textbook._cloze_candidates('タバコをやめることにした。', 1, {})
check(all(x['answer'] not in FRAG_ANSWERS for x in c), 'ことにし碎片被过滤')
# 定语槽位：干扰项必须同左接续、同作定语
opts = textbook._cloze_distractors('〜ようだ／みたいだ（比況・推定）', 'ような', 'N3',
                                   {}, after='勤勉な男。', attr=True)
check(opts == ['らしい', 'ごとき', 'に違いない'],
      f'原形类定语（みたいな与ような同义互斥）：{opts}')
opts = textbook._cloze_distractors('〜たい（願望）', 'たい', 'N5', {}, after='ものがある。', attr=True)
check(opts == ['やすい', 'にくい', 'がたい'], f'词干类定语：{opts}')
opts = textbook._cloze_distractors('〜てあげる／てくれる／てもらう（授受）', 'てくれる', 'N4',
                                   {}, after='人がいる。', attr=True)
check(opts == ['てほしい', 'てしまう', 'てみる'],
      f'て形类定语（みたい接て干不合法被拒）：{opts}')
# 非定语槽位不受影响（ので + 名词开头不是定语）
import grammar as _g
pts = [p for p in _g.analyze('雨が降っているので試合は中止です。') if p['name'] == '〜ので（原因）']
check(pts and not pts[0]['attr_slot'], 'ので后跟名词不误判为定语槽位')
pts = [p for p in _g.analyze('彼の様な勤勉な男はいない。') if 'ようだ' in p['name']]
check(pts and pts[0]['attr_slot'], f'ような+名词检出定语槽位：{[p["surface"] for p in pts]}')
# たがる禁挖
c = textbook._cloze_candidates('子供が行きたがっている。', 0, {})
check(all('たがる' not in x['name'] for x in c), 'たがる禁挖')
# 清浊匹配：浊音槽位只收浊音形，清音槽位拒浊音形
opts = textbook._cloze_distractors('〜ている（進行・状態）', 'でいる', 'N4', {})
check(opts == ['である', 'でおく', 'でしまう'], f'浊音槽位浊化：{opts}')
opts = textbook._cloze_distractors('〜ている（進行・状態）', 'ている', 'N4',
                                   {'N4': ['でいる', 'である', 'てある']})
check('でいる' not in opts and 'である' not in opts, f'清音槽位拒浊音：{opts}')
# たら的左接续（た干）与条件同组词（仮定/辞書）互斥：同组全被拒
opts = textbook._cloze_distractors('条件「たら」', 'たら', 'N4', {})
check('ば' not in opts and 'と' not in opts and 'なら' not in opts,
      f'たら条件同组互斥：{opts}')
# たら+结果从句（PRED 右槽）无可用干扰项：应凑不足 3 个而弃题
opts = textbook._cloze_distractors('条件「たら」', 'たら', 'N4', {},
                                   before='駅に着いた',
                                   after='電話してください。')
check(len(opts) < 3, f'たら+PRED 槽应弃题（<3）：{opts}')
# てき|なさい 碎片被截断检测过滤
c = textbook._cloze_candidates('早く帰ってきなさい。', 1, {})
check(all(x['answer'] != 'てき' for x in c),
      f'てき碎片被过滤：{[x["answer"] for x in c]}')
# おかげで挖完整形
c = textbook._cloze_candidates('君のおかげで助かった。', 2, {})
check(any(x['answer'] == 'おかげで' for x in c),
      f'おかげで完整：{[x["answer"] for x in c]}')
# 名词槽位+を：连用形候选被过滤
opts = textbook._cloze_distractors('〜ところ', 'ところ', 'N3',
                                   {'N3': ['たびに', 'うちに', 'ために']},
                                   after='を見た。')
check(all(not o.endswith(('に', 'で', 'へ')) for o in opts),
      f'ところ+を拒连用形：{opts}')
# 屈折半腰+て接续不挖（盗もうとし|て、ようになっ|て）
c = textbook._cloze_candidates('彼女は宝石を盗もうとして捕まった。', 0, {})
check(all(x['answer'] != '盗もうとし' for x in c),
      f'盗もうとし半腰被过滤：{[x["answer"] for x in c]}')
c = textbook._cloze_candidates('日本に住むようになって、どのくらい経ちますか。', 0, {})
check(all(x['answer'] != 'ようになっ' for x in c),
      f'ようになっ半腰被过滤：{[x["answer"] for x in c]}')
# 与碎片区间重叠的误切也不挖（盗もうとして 内的 として≠资格用法）
c = textbook._cloze_candidates('彼女は宝石を盗もうとして捕まった。', 0, {})
check(all(x['answer'] != 'として' for x in c),
      f'碎片内误切として被过滤：{[x["answer"] for x in c]}')

print('== 8. 左右接续金例 ==')
D = textbook._cloze_distractors
# (a) て干授受：同组全收（てほしい只接て形词尾，before 须为行っ）
opts = D('〜てあげる／てくれる／てもらう（授受）', 'てほしい', 'N4', {},
         before='行っ', after='。')
check(opts == ['てあげる', 'てくれる', 'てもらう'],
      f'てほしい|。授受组：{opts}')
# (b) たい→てほしい是合法替换（求人替己愿望），应被收录
# （before 须为食べ：行き|てほしい左接续不合）
opts = D('〜たい（願望）', 'たい', 'N5', {}, before='食べ', after='。')
check('てほしい' in opts, f'食べ|たい|。应收てほしい：{opts}')
# (c) 嬉し|そう|だ：断定同组全被拒（左不合）、无可用项→弃题
opts = D('〜そうだ（様態）', 'そう', 'N4', {}, before='嬉し', after='だ。')
check(len(opts) < 3, f'嬉し|そう|だ应弃题（<3）：{opts}')
# (d) 飲む|べき|だ：伝聞そう合法，应收
opts = D('〜べきだ（当然）', 'べき', 'N2', {}, before='飲む', after='だ。')
check(opts == ['はず', 'わけ', 'そう'], f'飲む|べき|だ：{opts}')
# (e) 食べる|ところ|を：まま/最中/途中被拒、とおり/ばかり收→2 个弃题
opts = D('〜ところだ（局面）', 'ところ', 'N3', {}, before='食べる',
         after='を見た。')
check(opts == ['とおり', 'ばかり'], f'食べる|ところ|を：{opts}')
# (f) してる|ように|見える：みたいに与ように同义互斥、ために/そうに
# 左/右不合→凑不足弃题
opts = D('〜ように（目的・引用）', 'ように', 'N3', {}, before='してる',
         after='見える。')
check(len(opts) < 3, f'してる|ように|見える应弃题：{opts}')
# (g) ておいた|ほうがいい|よ：ものだ/ことだ/かもしれない全收
opts = D('〜ほうがいい（忠告）', 'ほうがいい', 'N4',
         {}, before='入っておいた', after='よ。')
check(opts == ['ものだ', 'ことだ', 'かもしれない'],
      f'ておいた|ほうがいい|よ：{opts}')
# (h) 彼の|ような|男：みたいな与ような同义互斥、並みの左不合被拒，
# らしい/ごとき收→2 个弃题
opts = D('〜ようだ／みたいだ（比況・推定）', 'ような', 'N3', {},
         before='彼の', after='男。', attr=True)
check(opts == ['らしい', 'ごとき', 'に違いない'], f'彼の|ような|男：{opts}')
# (i) 行く|って|、太る：引用答案后不跟引用动词（TEN 逗号）时，と/
# ってば/なんて/ために/ことにする填入全都成立，天生双正解，只能弃题
opts = D('口語「って」（引用・主題）', 'って', 'N3', {}, before='行く',
         after='、太る。')
check(len(opts) < 3, f'行く|って|、太る应弃题：{opts}')
# (i2) 行く|って|言う：引用答案+引用动词是安全槽位，同组互斥后由
# 兜底项成题（ことにする/わけではない填入不成立，是好干扰项）
opts = D('口語「って」（引用・主題）', 'って', 'N3', {}, before='行く',
         after='と言う。')
check(len(opts) == 3, f'行く|って|と言う应成题：{opts}')

print('== 9. 接续词典覆盖 ==')
import collections as _co
missing = _co.Counter()
surfs = set()
for g in textbook._CLOZE_GROUPS:
    surfs.update(g['options'])
surfs.update(textbook._COPULA_STEMS)
surfs.update(textbook._PLAIN_RENTAI)
surfs.update(textbook._STEM_RENTAI)
surfs.update(textbook._TE_RENTAI)
surfs.update(textbook._CLOZE_FILLERS)
for s in sorted(surfs):
    if textbook._lq_left(s) is None:
        missing['LEFT:' + s] += 1
    if textbook._lq_right(s) is None:
        missing['RIGHT:' + s] += 1
check(not missing, f'混淆组/槽位/兜底左+右全覆盖：{dict(missing)}')

print('== 7. 关闭开关 / 计分 ==')
client.post('/api/books/study-cfg', json={'cloze_enabled': False})
r = client.post('/api/books/cloze', json={})
check(r.get_json().get('ok') is False, '关闭后拒绝出题')
client.post('/api/books/study-cfg', json={'cloze_enabled': True})
r = client.post('/api/books/cloze/answer', json={'results': [{'ok': True}, {'ok': False}]})
d = r.get_json()
check(d['ok'] and d['asked'] == 2 and d['correct'] == 1, f'计分 {d}')

shutil.rmtree(tmp, ignore_errors=True)
print()
if FAILS:
    print(f'===== 挖空专项测试: 失败 {len(FAILS)} 项 =====')
    sys.exit(1)
print('===== 挖空专项测试: 全部通过 =====')
sys.exit(0)

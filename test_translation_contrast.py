# -*- coding: utf-8 -*-
"""译文最小对立（translation_contrast）专项测试

这个模块的职责只有一件事：把一条**真实译文**按纯语法规则改写成四个选项，
让「只听懂一个实词」的应试策略失效。因此测试重点全在「不许出错的地方」：

  1. 反泄漏版式：2×2 每条轴上必须 2:2 平分；同槽四选必须互斥且不同义。
  2. 不换话题：除了审计里明确申报的那处语法替换，不许出现新实词。
  3. 有据可依：每处改写都必须能在日文侧找到显式形态素/助词证据。
  4. 宁缺毋滥：证据不足、句子结构吃不准时返回 None，绝不硬造。
  5. 语法正确：改写结果不能是病句（he'm / I is / 把+不 / 不了 …）。

不联网、不读数据库，纯函数测试，单独跑几秒钟结束。
"""
import re
import sys

sys.path.insert(0, '.')

import translation_contrast as tc

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


def build(jp, tr, seed=7):
    import random
    return tc.build_contrast(jp, tr, rng=random.Random(seed))


# ---------------------------------------------------------------- 1
print('== 1. 语言判定 ==')
check(tc.detect_lang('Tom called Mary.') == 'en', '英文译文判为 en')
check(tc.detect_lang('汤姆给玛丽打了电话。') == 'zh', '中文译文判为 zh')
check(tc.detect_lang('她比你大兩歲') == 'zh', '繁体同样判为 zh')

# ---------------------------------------------------------------- 2
print('== 2. 典型句：结构、轴、四选项 ==')
CASES_EN = [
    ('トムはメアリーに電話しました。', 'Tom called Mary.'),
    ('彼女は私に手紙を書いた。', 'She wrote me a letter.'),
    ('私は東京から大阪まで新幹線で行った。', 'I went from Tokyo to Osaka by bullet train.'),
    ('机の上に本があります。', 'There is a book on the desk.'),
    ('彼はいつも遅刻する。', 'He is always late.'),
    ('私は昨日公園へ行きませんでした。', "I didn't go to the park yesterday."),
    ('彼女はそのニュースを聞いて驚いた。', 'She was surprised at the news.'),
]
CASES_ZH = [
    ('彼は私の兄より背が高い。', '他比我哥哥高。'),
    ('彼女は昨日figureを買わなかった。', '她昨天没有买手办。'),
    ('私は毎朝コーヒーを飲みます。', '我每天早上喝咖啡。'),
    ('彼は東京へ行きました。', '他去了东京。'),
]

built = []
for jp, tr in CASES_EN + CASES_ZH:
    got = build(jp, tr)
    if got is None:
        continue
    built.append((jp, tr, got))
    opts = got['options']
    check(len(opts) == 4 and len(set(opts)) == 4, f'{jp}：4 个互不相同的选项 {opts}')
    check(got['answer'] == tr and tr in opts, f'{jp}：正确答案就是原译文，一字不改')
    check(got['structure'] in ('matrix_2x2', 'four_way_slot'),
          f'{jp}：只允许两种反泄漏版式，实得 {got["structure"]}')
    check(len(got['audit']) == 4 and [a['option'] for a in got['audit']] == opts,
          f'{jp}：审计与选项同序等长')
    check(sum(1 for a in got['audit'] if a['is_answer']) == 1, f'{jp}：恰有一个正确答案')
    check(bool(got['evidence']), f'{jp}：必须给出日文侧证据')

check(len(built) >= 8, f'典型句里至少 8 句能出题（实得 {len(built)}/{len(CASES_EN + CASES_ZH)}）')

# ---------------------------------------------------------------- 3
print('== 3. 反泄漏：2×2 每轴 2:2，同槽四选互斥 ==')
for jp, tr, got in built:
    if got['structure'] == 'matrix_2x2':
        check(len(got['axes']) == 2 and got['axes'][0] != got['axes'][1],
              f'{jp}：2×2 必须由两条不同的轴组成 {got["axes"]}')
        for axis in got['axes']:
            n = sum(1 for a in got['audit']
                    if any(c['axis'] == axis for c in a['changes']))
            check(n == 2, f'{jp}：轴 {axis} 必须 2:2 平分，实得 {n}')
        # 两条轴的改动区间不许重叠，否则组合出来的句子会互相覆盖
        both = [a for a in got['audit'] if len(a['changes']) == 2]
        check(len(both) == 1, f'{jp}：2×2 里应恰有一项两条轴都改了')
    else:
        check(len(got['axes']) == 1, f'{jp}：同槽四选只有一条轴 {got["axes"]}')
        n = sum(1 for a in got['audit'] if a['changes'])
        check(n == 3, f'{jp}：同槽四选应有 3 个改写项，实得 {n}')

# ---------------------------------------------------------------- 4
print('== 4. 不换话题：新词必须在审计里申报过 ==')
_FUNC_EN = set('''i you he she it we they me him her us them my your his its our their
am is are was were be been being do does did doing done have has had having will would
shall should can could may might must not no n t a an the this that these those there
here s re ve ll d m to of in on at for from with and or but so if then'''.split())


def content_en(txt):
    out = set()
    for w in re.findall(r"[a-z]+", (txt or '').lower()):
        if w in _FUNC_EN:
            continue
        b = tc.en_base_of(w)
        out.add(b[0] if b else w)
    return out


def content_zh(txt):
    return set(re.findall(r'[\u4e00-\u9fff]', txt or ''))


for jp, tr, got in built:
    fn = content_en if got['lang'] == 'en' else content_zh
    base = fn(tr)
    for a in got['audit']:
        declared = set()
        for ch in a['changes']:
            declared |= fn(ch.get('note') or '')
        extra = fn(a['option']) - base - declared
        check(not extra, f'{jp}：干扰项引入了未申报的新词 {extra} → {a["option"]}')

# ---------------------------------------------------------------- 5
print('== 5. 每处改写都要有日文侧证据 ==')
for jp, tr, got in built:
    for a in got['audit']:
        for ch in a['changes']:
            check(bool(ch.get('axis')) and bool(ch.get('axis_label')),
                  f'{jp}：改动必须标明语法轴 {ch}')
            check(bool(ch.get('evidence')), f'{jp}：改动必须附日文侧证据 {ch}')
            check(bool(ch.get('note')), f'{jp}：改动必须写清改了什么 {ch}')

# ---------------------------------------------------------------- 6
print('== 6. 宁缺毋滥：吃不准就返回 None ==')
check(build('これはペンです。', 'This is a pen.') is None
      or build('これはペンです。', 'This is a pen.')['structure'] in ('matrix_2x2', 'four_way_slot'),
      '证据不足的句子要么不出题，要么出合格版式')
check(build('。', '') is None, '空译文不出题')
check(build('彼は私より背が高い。', 'He is taller than I am.') is None
      or 'person' not in build('彼は私より背が高い。', 'He is taller than I am.')['axes'],
      '比较句两侧含代词时不做人称/比较改写（避免 I is taller than he 这类格错误）')
long_tr = 'I went to the station and then I took the train to the city center where my friend was waiting for me since early morning.'
check(build('長い文です。', long_tr) is None or len(build('長い文です。', long_tr)['options']) == 4,
      '超长句要么放弃要么给出完整四项')

# ---------------------------------------------------------------- 7
print('== 7. 改写结果不得是病句 ==')
BAD_EN = [
    (r"\b(he|she|it|tom|mary)\s+(am|are|were)\b", '主谓不一致（he are / she am）'),
    (r"\b(i)\s+(is|are|was\s+not\s+been)\b", '主谓不一致（I is / I are）'),
    (r"\bhe'm\b|\bshe're\b|\bi's\b", '错误缩合'),
    # need / succeed / proceed 等动词原形本身就以 ed 结尾，排除掉再判
    (r"\bdidn't\s+(?!need|succeed|proceed|exceed|feed|speed|bleed|breed|"
     r"indeed|agreed)\w+ed\b", "didn't + 过去式"),
    (r"\bdoesn't\s+(?!pass|miss|press|cross|discuss|guess|dress|focus)"
     r"\w+s\b", "doesn't + 三单"),
    (r"\bto\s+\w+ed\b", 'to + 过去式'),
    (r"\bnot\s+not\b|\bnever\s+not\b", '双重否定'),
    (r"\s{2,}|\s+[.,?!]", '空格/标点错位'),
]
BAD_ZH = [
    (r'[不没沒][了着過过]', '否定词直接接体标记'),
    (r'把[^，。！？]{0,6}[不没沒]', '把字句里插否定'),
    (r'[很太更最][不没沒]了', '程度副词后乱加否定'),
    (r'的的|了了|是是', '叠字错误'),
    (r'[，。！？]{2,}', '标点重复'),
]
SAMPLE = CASES_EN + CASES_ZH + [
    ('彼女は意地悪女だ。', "She's a big teaser."),
    ('私には助けてくれる誰かが必要だ。', 'I need someone to help me.'),
    ('彼女は昨夜安らかに息を引き取った。', 'She passed away peacefully last night.'),
    ('率直に言って、彼の新しい小説はあまりおもしろくない。',
     'Frankly speaking, his new novel is not very interesting.'),
    ('イヤリングの片方がなくなった。', 'One of my earrings is missing.'),
    ('彼女はちょっとの間も休まない。', 'She does not take a rest for an instant.'),
    ('鮫の皮はマグロの皮より粗い。', '鲨鱼的皮比金枪鱼的皮粗糙多了。'),
    ('雨が降っているので、試合は中止になりました。', '因为下雨，比赛取消了。'),
    ('彼女は私に本をくれた。', '她给了我一本书。'),
    ('この本を読んだことがありますか。', '你读过这本书吗？'),
]
n_opt = 0
for seed in (1, 2, 3):
    for jp, tr in SAMPLE:
        got = build(jp, tr, seed=seed)
        if not got:
            continue
        rules = BAD_EN if got['lang'] == 'en' else BAD_ZH
        for opt in got['options']:
            n_opt += 1
            low = opt.lower()
            for pat, why in rules:
                check(not re.search(pat, low),
                      f'{jp}：改写产出病句（{why}）→ {opt}')
check(n_opt >= 60, f'病句扫描样本量足够（实得 {n_opt} 个选项）')

# ---------------------------------------------------------------- 8
print('== 8. 具体规则回归 ==')
g = build('トムはメアリーに電話しました。', 'Tom called Mary.')
check(g and {'Mary called Tom.'} <= set(g['options']),
      f'施受互换要真的换过来：{g and g["options"]}')

g = build('机の上に本があります。', 'There is a book on the desk.')
check(g and any('under the desk' in o for o in g['options']),
      f'存现句要能改方位：{g and g["options"]}')

g = build('彼女は私に手紙を書いた。', 'She wrote me a letter.')
check(g and all(not re.search(r'\bshe wrote her\b|\bi wrote me\b', o.lower())
                for o in g['options']),
      f'施受互换不许自己给自己（she wrote her / I wrote me）：{g and g["options"]}')

g = build('イヤリングの片方がなくなった。', 'One of my earrings is missing.')
if g:
    for o in g['options']:
        check(not re.search(r'\b(two|three|four|five)\b[^.]*\bis\b', o.lower()),
              f'换数词要顺带改主谓一致：{o}')

g = build('彼女はちょっとの間も休まない。', 'She does not take a rest for an instant.')
if g:
    for o in g['options']:
        check(not re.search(r"\bdoes take\b|\bdo take\b|\bdid take\b", o.lower()),
              f'去掉 not 之后要收回 do-support（does not take → takes）：{o}')

# diff_marks：讲解高亮用，必须能标出差异且不越界
g = build('彼はいつも遅刻する。', 'He is always late.')
if g:
    for opt in g['options']:
        marks = tc.diff_marks(g['answer'], opt)
        for a, b in marks:
            check(0 <= a <= b <= len(opt), f'diff 区间不得越界：{marks} / {opt}')
        check(bool(marks) == (opt != g['answer']),
              f'只有被改过的选项才有高亮：{opt} {marks}')

# ---------------------------------------------------------------- 9
# 本轮新增规则的回归：疑问句、do-support 时制、正反问、多词专名、
# 单复数联动、施受互换后的主谓一致、中文时间状语
print('\n[9] 新增规则回归')

g = build('これは免税店ですか。', 'Is this a tax-free shop?')
check(g and set(g['axes']) == {'polarity', 'tense'}
      and {"Isn't this a tax-free shop?", 'Was this a tax-free shop?'} <= set(g['options']),
      f'倒装疑问句要能做肯否×时制：{g and g["options"]}')

g = build('これ、誰の時計？', 'Whose watch is this?')
if g:
    check(all('is not' not in o and "isn't" not in o for o in g['options']),
          f'whose/what 这类论元疑问句不许加否定：{g["options"]}')

g = build('トムは私たちを信用していない。', "Tom doesn't trust us.")
check(g and {'Tom trusts us.', "Tom didn't trust us."} <= set(g['options']),
      f'do-support 否定式要能翻时制：{g and g["options"]}')

g = build('彼は医者です。', 'He is a doctor.')
check(g and set(g['options']) == {'He is a doctor.', 'He is not a doctor.',
                                  'He was a doctor.', 'He was not a doctor.'},
      f'肯否×时制融合矩阵：{g and g["options"]}')

g = build('朝、シャワーを使ってもいいですか。', '我可不可以早上洗澡？')
if g:
    for o in g['options']:
        check('可不必须' not in o and '可不应该' not in o,
              f'正反问「可不可以」里的第二个成分不许换：{o}')

g = build('彼女はボストンからシカゴ経由でサンフランシスコへ旅行した。',
          'She traveled from Boston to San Francisco via Chicago.')
if g:
    for o in g['options']:
        check('San Francisco' in o and 'Boston' in o,
              f'多词专名要整块搬：{o}')

jf = tc.jp_features('机の上に本が１冊ある。')
tr = 'There is one book on the desk.'
num = [x for x in tc._en_slots(tr, jf) if x['axis'] == 'number']
check(num, '「There is one book」应当能改数量')
for a in (num[0]['alts'] if num else []):
    got = tc._tidy_en(tc._apply_edits(tr, a['edits']))
    check('are' in got and 'books' in got,
          f'跨单复数换数词要连名词和 be 一起改：{got}')

g = build('彼女にそれを言うのは気が引ける。', "I don't feel like telling her about it.")
if g:
    for o in g['options']:
        check(not re.search(r"\bshe don't\b|\bhe don't\b", o.lower()),
              f'施受互换后要修主谓一致：{o}')

g = build('学生のころ私はよく彼女に手紙を書いた。', 'I often wrote to her when I was a student.')
if g:
    for o in g['options']:
        check(not re.search(r'\bto (your|my|his|their)\b\s+(when|because|and|but)', o.lower()),
              f'宾格 her 不许换成属格 your：{o}')

g = build('彼は放課後野球をしました。', '他放学后打棒球。')
if g:
    for o in g['options']:
        check('不放学' not in o and '没放学' not in o,
              f'时间状语「放学后」不是谓语，不许挂否定：{o}')

g = build('彼は来週東京へ行く。', '他下周将去东京。')
if g:
    for o in g['options']:
        check(not re.search(r'(上周|上個月|去年|昨天).{0,4}(将|將)', o),
              f'未来标记在场时不许换成过去时间词：{o}')

print()
if FAILS:
    print(f'===== 译文最小对立测试: {len(FAILS)} 项失败 =====')
    sys.exit(1)
print('===== 译文最小对立测试: 全部通过 =====')

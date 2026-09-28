# -*- coding: utf-8 -*-
"""译文最小对立干扰项引擎（听力 contrast 题型内核）
================================================================
为什么要有这个模块
----------------------------------------------------------------
听力题「听日语→选日语原句」有一个结构性缺陷：四个选项是四条不同的句子，
只要抓住其中一个独有的词（哪怕没听懂整句）就能排除掉另外三个。哪怕干扰项
按字面相似度精挑细选，考生实际用到的能力仍然是「局部音形匹配」，不是
「听懂这句话在说什么」。

「听日语→选译文」好一些，但如果四条译文来自四条不同的真实语料，选项之间
往往仍有话题级差异（出现的名词不同），同样可以只靠听出一个名词秒选。
listening.py 里的 advanced 模式已经尽力检索「共享高信息词」的硬负例，
这在语料能凑齐时确实有含金量，但可遇不可求。

本模块换一条路：**不去别处找干扰项，而是把正确译文本身做纯语法层面的改写**。
四个选项共享全部实词（人、物、地点、动作一个字都不变），只在语法关系上互相
对立——谁对谁做了这件事、做没做、做过还是要做、因为还是虽然、能还是必须、
在上面还是在下面。想选对就必须听懂整句的语法关系，任何「只听见一个名词」
的策略都会均等地落在四个选项上。

正确性怎么保证（这是本模块唯一真正难的地方）
----------------------------------------------------------------
把译文改写成干扰项，风险是改出来的句子**可能碰巧也是原句的合法译文**——
日语大量省略主语、不区分单复数，「彼に電話した」译成 "I called him." 和
"He called me." 只有前者对，但「電話した」译成 "He called" 也不能算错。
所以本模块的每一条改写规则都绑定一个**日文侧证据条件**（`jp_features`）：
只有当被改写的那个语法特征在日文里被形态素或助词**显式标记**时，才允许改写，
否则直接放弃这条规则。例如：

  - 肯否翻转：要求日文全句没有任何否定形态素（ない／ぬ／ません／なし），
    这时任何带否定的译文都一定不是录音的意思；
  - 时态翻转：要求句尾谓语带「た」（或全句无「た」），时制在日文里是显式的；
  - 施受互换：要求两个人名/代词都在日文里出现，且**各自的助词属于不同的格**
    （は/が vs を/に），施受关系被助词钉死，互换后必错；
  - 因果↔逆接：要求日文里有 から/ので（且没有 のに/けど），反之亦然；
  - 数量/时间/方位/频度：要求日文里出现对应的数词、時間名詞、方位名詞、
    副詞，且替换值**没有**出现在日文里。

凑不齐证据就不出题（宁缺毋滥）。这条底线和 listening.py 里 advanced 模式
「找不到三个合格硬负例就放弃」是同一个原则。

选项结构：只用两种「无泄漏」版式
----------------------------------------------------------------
如果四个选项是「原句 + 三处互不相同的单点改动」，那么正确答案恰好是**每个
语法特征上都与多数选项一致**的那一个，考生用排除法（不听录音）就能反推出
答案。这是真实存在的应试漏洞，所以本模块只产出两种平衡版式：

  1. `matrix_2x2`：挑两个互不重叠的语法轴 A、B，四个选项＝A×B 的 2×2 组合。
     每个轴上都是 2:2 平分，没有「多数派」可言；必须同时听懂两个点才能选对。
  2. `four_way_slot`：同一个槽位给四个互斥的值（三个数字/四个时间词/
     四种方位），四个选项在其它位置逐字相同。

两种版式都让「不听录音只比选项」失效。

诚实边界
----------------------------------------------------------------
- 本模块**不生成新的实词**，只重排/替换封闭类语法成分（否定、时体、人称、
  连接词、情态、方位、数词、频度副词）与句中已有的名词短语位置；
- 它**不理解句子**。它的正确性完全来自「日文侧显式标记 + 纯形式改写」这条
  可机械核验的链条，而不是任何语义推断；
- 覆盖率必然不满：结构复杂、多小句、找不到显式证据的句子会被直接跳过，
  调用方（listening.py）会自动改出其它题型，绝不为了凑数降低门槛。
"""
import re
import random
from functools import lru_cache

import sentence_builder as sb

# ================================================================
# 一、日文侧证据抽取
# ================================================================
_NEG_LEMMA = ('ない', 'ぬ', 'ず', '無い')
_CLAUSE_BREAK = ('、', '，', 'が', 'けど', 'けれど', 'けれども', 'ので', 'のに',
                 'から', 'し', 'たら', 'ば', 'ても', 'でも', 'て', 'で')

_JP_PRONOUN = {
    '私': '1sg', 'わたし': '1sg', 'わたくし': '1sg', '僕': '1sg', 'ぼく': '1sg',
    '俺': '1sg', 'おれ': '1sg', 'あたし': '1sg', 'うち': '1sg',
    '私たち': '1pl', '私達': '1pl', '僕たち': '1pl', '僕ら': '1pl', '我々': '1pl',
    'われわれ': '1pl', '俺たち': '1pl',
    'あなた': '2sg', '貴方': '2sg', '君': '2sg', 'きみ': '2sg', 'お前': '2sg',
    'あんた': '2sg', 'あなたたち': '2pl', '君たち': '2pl', 'お前ら': '2pl',
    '彼': '3sgm', '彼女': '3sgf',
    '彼ら': '3pl', '彼女ら': '3pl', '彼女たち': '3pl', '彼等': '3pl',
}

# 日文時間名詞 → 译文里对应的中英文说法（用于时间轴改写与证据核验）
_JP_TIME = {
    '昨日': ('yesterday', '昨天'), '今日': ('today', '今天'),
    '明日': ('tomorrow', '明天'), '明後日': ('the day after tomorrow', '后天'),
    '一昨日': ('the day before yesterday', '前天'),
    '今朝': ('this morning', '今天早上'), '今晩': ('tonight', '今天晚上'),
    '昨夜': ('last night', '昨天晚上'), '夕べ': ('last night', '昨天晚上'),
    '先週': ('last week', '上周'), '今週': ('this week', '这周'),
    '来週': ('next week', '下周'), '先月': ('last month', '上个月'),
    '今月': ('this month', '这个月'), '来月': ('next month', '下个月'),
    '去年': ('last year', '去年'), '今年': ('this year', '今年'),
    '来年': ('next year', '明年'),
    '朝': ('morning', '早上'), '昼': ('noon', '中午'), '夜': ('night', '晚上'),
    '夕方': ('evening', '傍晚'),
    '月曜日': ('Monday', '星期一'), '火曜日': ('Tuesday', '星期二'),
    '水曜日': ('Wednesday', '星期三'), '木曜日': ('Thursday', '星期四'),
    '金曜日': ('Friday', '星期五'), '土曜日': ('Saturday', '星期六'),
    '日曜日': ('Sunday', '星期日'),
}

# 日文方位名詞 → 译文说法
_JP_PLACE = {
    '上': ('on', '上面'), '下': ('under', '下面'), '中': ('in', '里面'),
    '前': ('in front of', '前面'), '後ろ': ('behind', '后面'),
    '隣': ('next to', '旁边'), '外': ('outside', '外面'),
    '左': ('left', '左边'), '右': ('right', '右边'),
}

_JP_NUM_KANJI = {'〇': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                 '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def _kanji_num(s):
    """把「三」「十五」「二十」这类短数词转成 int；复杂数词返回 None。"""
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return None
    if not s or any(ch not in _JP_NUM_KANJI for ch in s):
        return None
    if len(s) == 1:
        return _JP_NUM_KANJI[s]
    if s[0] == '十':
        return 10 + (_JP_NUM_KANJI[s[1]] if len(s) == 2 else 0)
    if len(s) >= 2 and s[1] == '十':
        base = _JP_NUM_KANJI[s[0]] * 10
        return base + (_JP_NUM_KANJI[s[2]] if len(s) == 3 else 0)
    return None


@lru_cache(maxsize=8192)
def jp_features(text):
    """抽取日文句里**显式存在**的语法标记，作为译文改写的证据白名单。

    只记录形态素/助词层面能机械确认的东西；任何需要"理解句意"的判断
    （说话人意图、省略的主语到底是谁）一律不记录，也就不会被规则引擎当成
    改写依据。
    """
    text = (text or '').strip()
    try:
        toks = sb._tag(text)
    except Exception:
        toks = []
    surfaces = [t['s'] for t in toks]

    # --- 否定：全句计数 + 句尾谓语（最后一个小句）的极性 ---
    neg_idx = [i for i, t in enumerate(toks)
               if (t['p1'] in ('助動詞', '形容詞') and t['lemma'] in _NEG_LEMMA)
               or (t['p1'] == '助動詞' and t['s'] in ('ん', 'ぬ') and t['lemma'] == 'ず')]
    # 最后一个小句的起点：最后一个读点或接续助詞之后
    tail_start = 0
    for i, t in enumerate(toks):
        if t['s'] in ('、', '，') or (t['p2'] == '接続助詞' and t['s'] in _CLAUSE_BREAK):
            tail_start = i + 1
    tail_neg = any(i >= tail_start for i in neg_idx)

    # --- 时制：句尾是否带「た」 ---
    past_idx = [i for i, t in enumerate(toks)
                if t['p1'] == '助動詞' and t['lemma'] == 'た']
    tail_past = any(i >= tail_start for i in past_idx)

    # --- 疑问 ---
    question = text.rstrip().endswith(('？', '?')) or any(
        t['p2'] == '終助詞' and t['s'] == 'か' for t in toks[-3:])

    # --- 代词 → 后接助词 ---
    pronouns = {}
    for i, t in enumerate(toks):
        key = _JP_PRONOUN.get(t['s'])
        if not key:
            continue
        nxt = toks[i + 1]['s'] if i + 1 < len(toks) else ''
        pronouns.setdefault(key, set()).add(nxt if nxt in ('は', 'が', 'を', 'に',
                                                           'と', 'へ', 'も', 'の') else '')

    # --- 固有名詞（人名/地名） → 后接助词 + unidic lemma 里的英文注（トム-Thom） ---
    entities = []
    for i, t in enumerate(toks):
        if t['p2'] != '固有名詞':
            continue
        nxt = toks[i + 1]['s'] if i + 1 < len(toks) else ''
        gloss = ''
        lemma = t.get('lemma') or ''
        if '-' in lemma:
            tail = lemma.split('-')[-1]
            if re.fullmatch(r'[A-Za-z][A-Za-z\'\-]*', tail):
                gloss = tail
        entities.append({'surface': t['s'], 'particle': nxt, 'gloss': gloss,
                         'kind': t.get('p3') or ''})

    # --- 数词（含接尾辞计数器） ---
    numbers = set()
    for t in toks:
        if t['p2'] == '数詞':
            v = _kanji_num(t['s'])
            if v is not None:
                numbers.add(v)
    for m in re.finditer(r'\d+', text):
        try:
            numbers.add(int(m.group()))
        except ValueError:
            pass

    # --- 接续/连接词（因果、逆接、条件、前后） ---
    conn = set()
    kara_pred = False
    for i, t in enumerate(toks):
        if t['s'] != 'から' or i == 0:
            continue
        prev = toks[i - 1]
        if prev['s'] in ('て', 'で') or prev['p1'] in ('名詞', '代名詞', '数詞'):
            continue          # 「〜てから」＝先后；「今朝から」＝起点，都不是因果
        kara_pred = True
    if kara_pred or 'ので' in text:
        conn.add('cause')
    if re.search(r'(のに|けれど|けど|しかし|でも|が、)', text):
        conn.add('concession')
    if re.search(r'(前に|まえに)', text):
        conn.add('before')
    if re.search(r'(後で|あとで|てから|た後)', text):
        conn.add('after')
    if re.search(r'(たら|なら|ば、|れば)', text):
        conn.add('if')
    if re.search(r'(ても|でも)', text):
        conn.add('even_if')
    if re.search(r'(とき|時に|時は)', text):
        conn.add('when')

    # --- 情态 ---
    modal = set()
    if re.search(r'(なければ|なきゃ|ねばならない|ないといけない|ないと駄目|必要が)', text):
        modal.add('must')
    if re.search(r'(てもいい|ても良い|て構わない|てもかまわない)', text):
        modal.add('may')
    if re.search(r'(てはいけない|てはだめ|ちゃだめ|ないでください|禁止)', text):
        modal.add('prohibit')
    if re.search(r'(ほうがいい|方がいい|べき)', text):
        modal.add('should')
    if re.search(r'(たい(?!へん)|たがって)', text):
        modal.add('want')
    if re.search(r'(できる|出来る|できます|可能)', text) or any(
            t['p1'] == '助動詞' and t['lemma'] in ('れる', 'られる') for t in toks):
        modal.add('can')
    if re.search(r'(かもしれ|でしょう|だろう|らしい|そうだ|みたい)', text):
        modal.add('maybe')

    # --- 频度・量化・时体副词 ---
    quant = set()
    for word, key in (('いつも', 'always'), ('毎日', 'everyday'), ('よく', 'often'),
                      ('時々', 'sometimes'), ('たまに', 'sometimes'),
                      ('全然', 'never'), ('決して', 'never'), ('まったく', 'never'),
                      ('みんな', 'all'), ('全部', 'all'), ('すべて', 'all'), ('全員', 'all'),
                      ('誰も', 'nobody'), ('何も', 'nothing'),
                      ('もう', 'already'), ('既に', 'already'), ('すでに', 'already'),
                      ('まだ', 'yet'), ('たくさん', 'many'), ('少し', 'little'),
                      ('ちょっと', 'little'), ('だけ', 'only'), ('しか', 'only'),
                      ('ずっと', 'always')):
        if word in text:
            quant.add(key)

    # --- 方位・比较・起讫点 ---
    places = {k for k in _JP_PLACE if any(t['s'] == k for t in toks)}
    times = {k for k in _JP_TIME if k in text}
    # 「昨夜」会同时命中「夜」：短词被长词包含时只保留长的，否则会拿
    # 「夜→noon」去改写 "last night"，造出 "last noon" 这种不存在的说法
    times = {k for k in times if not any(k != o and k in o for o in times)}
    comparative = 'より' in text
    superlative = bool(re.search(r'(一番|最も)', text))
    kara_noun = any(t['s'] == 'から' and i > 0 and toks[i - 1]['p1'] in ('名詞', '代名詞')
                    for i, t in enumerate(toks))
    made = 'まで' in text
    passive = any(t['p1'] == '助動詞' and t['lemma'] in ('れる', 'られる') for t in toks)
    causative = any(t['p1'] == '助動詞' and t['lemma'] in ('せる', 'させる') for t in toks)
    giving = bool(re.search(r'(あげ|くれ|もらい|もらっ|いただ|くださ)', text))
    te_iru = bool(re.search(r'(てい|でい|ています|でいます)', text))

    return {
        'text': text,
        'surfaces': tuple(surfaces),
        'neg_count': len(neg_idx),
        'tail_negative': tail_neg,
        'past_count': len(past_idx),
        'tail_past': tail_past,
        'question': question,
        'pronouns': {k: frozenset(v) for k, v in pronouns.items()},
        'entities': tuple({**e} for e in entities),
        'numbers': frozenset(numbers),
        'conn': frozenset(conn),
        'modal': frozenset(modal),
        'quant': frozenset(quant),
        'places': frozenset(places),
        'times': frozenset(times),
        'comparative': comparative,
        'superlative': superlative,
        'kara_noun': kara_noun,
        'made': made,
        'passive': passive,
        'causative': causative,
        'giving': giving,
        'te_iru': te_iru,
        'ok': bool(toks),
    }


def _role_of(particle):
    """助词 → 粗格（施事 / 受事）。判不了就 None。"""
    if particle in ('は', 'が'):
        return 'subject'
    if particle in ('を', 'に', 'へ'):
        return 'object'
    return None


# ================================================================
# 二、英文形态学（不依赖任何第三方 NLP 库，手写但高精度优先）
# ================================================================
# 不规则动词：base -> (past, past participle)
_IRREG = {}
for _row in '''be:was:been have:had:had do:did:done say:said:said go:went:gone
get:got:gotten make:made:made know:knew:known think:thought:thought
take:took:taken see:saw:seen come:came:come want:wanted:wanted
use:used:used find:found:found give:gave:given tell:told:told
work:worked:worked call:called:called try:tried:tried ask:asked:asked
need:needed:needed feel:felt:felt become:became:become leave:left:left
put:put:put mean:meant:meant keep:kept:kept let:let:let begin:began:begun
seem:seemed:seemed help:helped:helped talk:talked:talked turn:turned:turned
start:started:started show:showed:shown hear:heard:heard play:played:played
run:ran:run move:moved:moved like:liked:liked live:lived:lived
believe:believed:believed hold:held:held bring:brought:brought
happen:happened:happened write:wrote:written provide:provided:provided
sit:sat:sat stand:stood:stood lose:lost:lost pay:paid:paid meet:met:met
include:included:included continue:continued:continued set:set:set
learn:learned:learned change:changed:changed lead:led:led
understand:understood:understood watch:watched:watched follow:followed:followed
stop:stopped:stopped create:created:created speak:spoke:spoken
read:read:read allow:allowed:allowed add:added:added spend:spent:spent
grow:grew:grown open:opened:opened walk:walked:walked win:won:won
offer:offered:offered remember:remembered:remembered love:loved:loved
consider:considered:considered appear:appeared:appeared buy:bought:bought
wait:waited:waited serve:served:served die:died:died send:sent:sent
build:built:built stay:stayed:stayed fall:fell:fallen cut:cut:cut
reach:reached:reached kill:killed:killed remain:remained:remained
suggest:suggested:suggested raise:raised:raised pass:passed:passed
sell:sold:sold require:required:required report:reported:reported
decide:decided:decided pull:pulled:pulled break:broke:broken
pick:picked:picked wear:wore:worn catch:caught:caught draw:drew:drawn
choose:chose:chosen eat:ate:eaten drink:drank:drunk sleep:slept:slept
drive:drove:driven ride:rode:ridden fly:flew:flown swim:swam:swum
sing:sang:sung teach:taught:taught throw:threw:thrown forget:forgot:forgotten
sweep:swept:swept lend:lent:lent borrow:borrowed:borrowed rise:rose:risen
hurt:hurt:hurt hit:hit:hit shut:shut:shut cost:cost:cost feed:fed:fed
fight:fought:fought hang:hung:hung lay:laid:laid lie:lay:lain
quit:quit:quit shake:shook:shaken shine:shone:shone shoot:shot:shot
sink:sank:sunk slide:slid:slid spread:spread:spread steal:stole:stolen
stick:stuck:stuck strike:struck:struck wake:woke:woken wind:wound:wound
bite:bit:bitten blow:blew:blown burn:burned:burned deal:dealt:dealt
dig:dug:dug freeze:froze:frozen hide:hid:hidden hurry:hurried:hurried
marry:married:married study:studied:studied carry:carried:carried
worry:worried:worried enjoy:enjoyed:enjoyed arrive:arrived:arrived
belong:belonged:belonged'''.split():
    _b, _p, _pp = _row.split(':')
    _IRREG[_b] = (_p, _pp)

# 常用规则动词原形（用于「这个词是不是动词」与还原判定；宁可漏掉不可错判）
_REG_VERBS = set('''accept add admire admit advise afford agree announce answer
apologize appear apply argue arrive ask attack attend avoid bake bathe behave
believe belong blame boil borrow bother breathe brush burn calculate call cancel
care carry cause celebrate change charge chat check cheer clean climb close
collect compare complain complete concentrate confirm connect consider contain
continue cook copy correct cough count cover cross cry dance decide decorate
deliver depend describe design destroy develop die disagree discover discuss
divide download drop dry earn eat edit educate encourage end enjoy enter escape
examine exercise exist expect explain express fail fasten fill finish fix flow
fold follow fry gather graduate greet guess guide hand handle happen hate heat
help hesitate hire hope hug hunt hurry identify ignore imagine improve include
increase inform insist install introduce invent invite involve join joke jump
keep kick kiss knock label land last laugh launch learn lift like listen live
lock look love manage mark marry match measure mention mind miss mix move name
need notice obey offer open operate order organize own pack paint park
participate pass perform permit persuade phone pick plan plant play point
practice praise prefer prepare present preserve press pretend prevent print
produce promise pronounce protect prove provide publish pull punish push
question queue race rain raise reach realize receive recognize recommend record
recycle reduce refuse regret relax release remain remember remind remove rent
repair repeat replace reply report request rescue reserve respect rest return
review reward rub ruin rule rush sail save scream search seem select separate
serve settle shop shout sign smell smile smoke solve sound spell spoil stare
start stay stop store stress stretch study succeed suffer suggest supply
support suppose surprise survive suspect talk taste teach thank tie touch train
translate travel treat trust try turn type understand unite use visit vote wait
walk want warm warn wash waste watch water wave welcome whisper wish wonder work
worry wrap yell'''.split())
_VERB_BASES = set(_IRREG) | _REG_VERBS

_BE_FORMS = {'am': ('1sg', 'present'), 'is': ('3sg', 'present'), 'are': ('pl', 'present'),
             'was': ('3sg', 'past'), 'were': ('pl', 'past'),
             "'m": ('1sg', 'present'), "'s": ('3sg', 'present'), "'re": ('pl', 'present')}
_BE_PRES2PAST = {'am': 'was', 'is': 'was', 'are': 'were'}
_BE_PAST2PRES = {'was': 'is', 'were': 'are'}
_HAVE_FORMS = {'have', 'has', 'had', "'ve"}
_DO_FORMS = {'do': 'pl', 'does': '3sg', 'did': 'past'}
_MODALS = {'will', 'would', 'can', 'could', 'shall', 'should', 'may', 'might',
           'must', 'ought', "'ll", "'d"}
# 缩合形（I'm / he's / they've）：人称一换，缩合的助动词也要跟着换
_CONTRACTION = {"'m", "'s", "'re", "'ve", "'ll", "'d"}
_BE_CONTRACTION = {'1sg': "'m", '2sg': "'re", '3sgm': "'s", '3sgf': "'s",
                   '1pl': "'re", '3pl': "'re"}
_HAVE_CONTRACTION = {'1sg': "'ve", '2sg': "'ve", '3sgm': "'s", '3sgf': "'s",
                     '1pl': "'ve", '3pl': "'ve"}
_FREQ_ADVERBS = {'always', 'never', 'often', 'sometimes', 'usually', 'rarely',
                 'seldom', 'ever', 'occasionally', 'frequently'}
_NEG_AUX = {
    "isn't": 'is', "aren't": 'are', "wasn't": 'was', "weren't": 'were',
    "don't": 'do', "doesn't": 'does', "didn't": 'did', "won't": 'will',
    "can't": 'can', 'cannot': 'can', "couldn't": 'could', "shouldn't": 'should',
    "wouldn't": 'would', "mustn't": 'must', "haven't": 'have', "hasn't": 'has',
    "hadn't": 'had', "mightn't": 'might', "shan't": 'shall',
}
_SUBJ_PRON = {'i': '1sg', 'you': 'pl', 'he': '3sg', 'she': '3sg', 'it': '3sg',
              'we': 'pl', 'they': 'pl'}
_OBJ_PRON = {'me': '1sg', 'him': '3sg', 'her': '3sg', 'us': 'pl', 'them': 'pl'}
_SUBJ2OBJ = {'i': 'me', 'he': 'him', 'she': 'her', 'we': 'us', 'they': 'them',
             'you': 'you', 'it': 'it'}
_OBJ2SUBJ = {'me': 'I', 'him': 'he', 'her': 'she', 'us': 'we', 'them': 'they',
             'you': 'you', 'it': 'it'}
_DETERMINERS = {'the', 'a', 'an', 'this', 'that', 'these', 'those', 'my', 'your',
                'his', 'her', 'its', 'our', 'their', 'some', 'every', 'no',
                'both', 'another', 'each'}
# 对称谓词：互换施受后意思几乎不变，绝不可用于施受互换轴
_SYMMETRIC_VERBS = {'meet', 'met', 'marry', 'married', 'resemble', 'resembles',
                    'resembled', 'match', 'matches', 'matched', 'equal', 'equals',
                    'differ', 'differs', 'argue', 'argued', 'chat', 'chatted',
                    'fight', 'fought', 'collide', 'agree', 'agreed', 'disagree',
                    'talk', 'talked', 'speak', 'spoke', 'date', 'dated',
                    'is', 'are', 'was', 'were', 'am', 'be', 'become', 'became',
                    'know', 'knew', 'knows', 'see', 'saw', 'sees'}

_NON_NAME_CAPS = {'i', 'the', 'a', 'an', 'my', 'we', 'you', 'he', 'she', 'it',
                  'they', 'this', 'that', 'there', 'here', 'what', 'who', 'when',
                  'where', 'why', 'how', 'if', 'do', 'does', 'did', 'is', 'are',
                  'was', 'were', 'have', 'has', 'had', 'will', 'would', 'can',
                  'could', 'should', 'must', 'may', 'might', 'let', 'please',
                  'his', 'her', 'their', 'our', 'its', 'no', 'not', 'yes',
                  'mr', 'mrs', 'ms', 'dr', 'english', 'japanese', 'chinese',
                  'frankly', 'actually', 'fortunately', 'unfortunately',
                  'suddenly', 'finally', 'generally', 'personally', 'honestly',
                  'obviously', 'certainly', 'however', 'therefore', 'besides',
                  'moreover', 'anyway', 'well', 'yesterday', 'today',
                  'tomorrow', 'tonight', 'sometimes', 'always', 'never',
                  'often', 'usually', 'first', 'then', 'now', 'later', 'soon',
                  'recently', 'lately', 'once', 'everyone', 'everybody',
                  'everything', 'nobody', 'nothing', 'someone', 'somebody',
                  'something', 'people', 'most', 'many', 'some', 'all', 'both',
                  'each', 'either', 'neither', 'one', 'two', 'three', 'four',
                  'five', 'after', 'before', 'while', 'since', 'although',
                  'because', 'even', 'just', 'only', 'maybe', 'perhaps',
                  'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
                  'saturday', 'sunday', 'january', 'february', 'march', 'april',
                  'may', 'june', 'july', 'august', 'september', 'october',
                  'november', 'december'}


def en_3sg(base):
    if base == 'be':
        return 'is'
    if base == 'have':
        return 'has'
    if base in ('do', 'go'):
        return base + 'es'
    if base.endswith(('s', 'x', 'z', 'ch', 'sh')):
        return base + 'es'
    if base.endswith('y') and len(base) > 1 and base[-2] not in 'aeiou':
        return base[:-1] + 'ies'
    return base + 's'


def _double_final(base):
    return bool(re.fullmatch(r'[^aeiou]*[aeiou][bdgklmnprt]', base)) and base not in (
        'open', 'happen', 'listen', 'visit', 'enter', 'offer', 'answer')


def en_past(base):
    if base in _IRREG:
        return _IRREG[base][0]
    if base.endswith('e'):
        return base + 'd'
    if base.endswith('y') and len(base) > 1 and base[-2] not in 'aeiou':
        return base[:-1] + 'ied'
    if _double_final(base):
        return base + base[-1] + 'ed'
    return base + 'ed'


_PAST2BASE = {}
_PP2BASE = {}
_3SG2BASE = {}
for _b in _VERB_BASES:
    _PAST2BASE.setdefault(en_past(_b), _b)
    _3SG2BASE.setdefault(en_3sg(_b), _b)
for _b, (_p, _pp) in _IRREG.items():
    _PAST2BASE.setdefault(_p, _b)
    _PP2BASE.setdefault(_pp, _b)


def en_base_of(word):
    """把一个动词形还原成原形，返回 (base, form) 或 None（拿不准就放弃）。"""
    w = word.lower()
    if w in _VERB_BASES:
        return (w, 'base')
    if w in _3SG2BASE:
        return (_3SG2BASE[w], '3sg')
    if w in _PAST2BASE:
        return (_PAST2BASE[w], 'past')
    if w in _PP2BASE:
        return (_PP2BASE[w], 'pp')
    return None


# ================================================================
# 三、英文句法浅分析（只认高置信度结构，认不出就跳过）
# ================================================================
_EN_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_SPLITTABLE = re.compile(r"^(i|you|he|she|it|we|they|there|that|who|what)"
                         r"('(?:m|s|re|ve|ll|d))$", re.IGNORECASE)


def _en_words(text):
    """切词；把「I'm / he's / they've」拆成代词 + 助动词两个 token（带正确 span），
    否则「I'm」会被当成一个不认识的词，主语和谓语都识别不出来。"""
    out = []
    for m in _EN_WORD_RE.finditer(text):
        w = m.group().replace('’', "'")
        sp = _SPLITTABLE.match(w)
        if sp:
            head = sp.group(1)
            out.append((head, m.start(), m.start() + len(head)))
            out.append((sp.group(2).lower(), m.start() + len(head), m.end()))
        else:
            out.append((w, m.start(), m.end()))
    return out


def _is_name(word, idx):
    """判断是不是人名/地名式专有名词（句首第一个词也允许，但要排除功能词）。"""
    return (word[:1].isupper() and word.lower() not in _NON_NAME_CAPS
            and len(word) > 1 and word.isalpha())


def _en_verb_complexes(words):
    """把句子切成若干「限定动词复合体」。用于判断是不是单谓语单句。

    返回 [{'i': 起始词下标, 'j': 结束词下标(含), 'kind': ..., 'neg': bool}]。
    kind ∈ {'be','have','modal','do','lex','neg'}。
    """
    out = []
    i = 0
    n = len(words)
    while i < n:
        w = words[i][0].lower()
        prev = words[i - 1][0].lower() if i else ''
        if w == 'to':
            i += 2  # to 不定式：跳过后面的动词
            continue
        kind = None
        if w in _NEG_AUX:
            kind = 'neg'
        elif w in _BE_FORMS:
            kind = 'be'
        elif w in _HAVE_FORMS:
            kind = 'have'
        elif w in _MODALS:
            kind = 'modal'
        elif w in _DO_FORMS:
            kind = 'do'
        elif prev not in ('to',) and en_base_of(w) and en_base_of(w)[1] in ('3sg', 'past'):
            kind = 'lex'
        elif (prev in _SUBJ_PRON and prev != 'he' and prev != 'she' and prev != 'it'
              and en_base_of(w) and en_base_of(w)[1] == 'base'):
            kind = 'lex'
        if kind is None:
            i += 1
            continue
        j = i
        neg = kind == 'neg'
        # 吞掉助动词链：not / never / 副词 / 后续动词形
        k = i + 1
        while k < n:
            nxt = words[k][0].lower()
            if nxt in ('not', 'never'):
                neg = True
                j, k = k, k + 1
                continue
            if nxt.endswith('ly') or nxt in ('also', 'still', 'just', 'already',
                                             'often', 'always', 'ever'):
                j, k = k, k + 1
                continue
            if kind in ('neg', 'be', 'have', 'modal', 'do') and (
                    nxt in ('be', 'been', 'being', 'have', 'has', 'had')
                    or (en_base_of(nxt) and en_base_of(nxt)[1] in ('base', 'pp', 'past'))
                    or nxt.endswith('ing')):
                j, k = k, k + 1
                continue
            break
        out.append({'i': i, 'j': j, 'kind': kind, 'neg': neg})
        i = j + 1
    return out


def _en_subject(words):
    """识别句首主语；返回 {'end': 主语最后一个词下标, 'number': '1sg|3sg|pl'} 或 None。"""
    if not words:
        return None
    w0 = words[0][0].lower()
    if w0 in _SUBJ_PRON:
        return {'end': 0, 'number': _SUBJ_PRON[w0], 'pron': w0}
    if _is_name(words[0][0], 0):
        # Tom / Tom's father …
        end = 0
        if len(words) > 2 and words[1][0].lower() == 's':
            end = 2
        return {'end': end, 'number': '3sg', 'pron': None}
    if w0 == 'there' and len(words) > 1 and words[1][0].lower() in _BE_FORMS:
        return {'end': 0, 'number': _BE_FORMS[words[1][0].lower()][0], 'pron': None}
    if w0 in _DETERMINERS:
        for k in range(1, min(len(words), 5)):
            wk = words[k][0].lower()
            base = en_base_of(wk)
            if (wk in _BE_FORMS or wk in _HAVE_FORMS or wk in _MODALS
                    or wk in _DO_FORMS or wk in _NEG_AUX
                    or (base and base[1] in ('3sg', 'past'))):
                number = 'pl' if wk in ('are', 'were', 'have', 'do', "don't",
                                        "aren't", "weren't", "haven't") else '3sg'
                return {'end': k - 1, 'number': number, 'pron': None}
        return None
    return None


# ================================================================
# 四、改写槽位（slot）的通用表示
# ================================================================
def _slot(axis, label, evidence, alts, quality, span):
    """alts: [{'edits': [(start, end, new)], 'note': str}]"""
    return {'axis': axis, 'label': label, 'evidence': evidence, 'alts': alts,
            'quality': quality, 'span': span}


def _edits_disjoint(edits_a, edits_b):
    """两组改动是否互不重叠（按真实改动区间判断，而不是按槽位的外包围区间：
    「Tom called Mary」里施受互换改的是两端，肯否改的是中间，二者完全可以共存）。"""
    for s1, e1, _ in edits_a:
        for s2, e2, _ in edits_b:
            if s1 < e2 and s2 < e1:
                return False
    return True


def _apply_edits(text, edits):
    out = text
    for s, e, new in sorted(edits, key=lambda x: -x[0]):
        out = out[:s] + new + out[e:]
    return out


def _tidy_en(s):
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s+([,.!?;:])', r'\1', s)
    s = re.sub(r"\bi\b", 'I', s)
    if s and s[0].isalpha():
        s = s[0].upper() + s[1:]
    return s


def _tidy_zh(s):
    return re.sub(r'\s+', '', s).strip() if not re.search(r'[A-Za-z]', s) else s.strip()


# ================================================================
# 五、英文改写规则
# ================================================================
def _strip_leading_adverbial(tr, words):
    """跳过句首状语（"Frankly speaking, …" / "In those days, …"）：
    只有当逗号之前不含任何限定动词时才跳，避免把真正的主句切掉。"""
    comma = tr.find(',')
    if comma < 0:
        return words
    head = [w for w in words if w[2] <= comma]
    if not head or len(head) > 5 or _en_verb_complexes(head):
        return words
    return [w for w in words if w[1] > comma]


def _en_slots(tr, jf):
    slots = []
    words = _en_words(tr)
    if len(words) < 3 or len(words) > 34:
        return slots
    body = _strip_leading_adverbial(tr, words)
    complexes = _en_verb_complexes(body)
    subj = _en_subject(body)
    single = len(complexes) == 1
    main = complexes[0] if complexes else None
    words = body

    # ---------- 轴 1：肯否（听清有没有否定） ----------
    if single and main and subj and main['i'] > subj['end']:
        slots += _en_polarity_slot(tr, words, main, subj, jf)

    # ---------- 轴 2：时制（过去 vs 现在/未来） ----------
    if single and main and subj:
        slots += _en_tense_slot(tr, words, main, subj, jf)

    # ---------- 轴 3：施受互换（谁对谁做） ----------
    slots += _en_role_slot(tr, words, complexes, jf)

    # ---------- 轴 4：起讫点互换（from A to B） ----------
    slots += _en_direction_slot(tr, words, jf)

    # ---------- 轴 5：比较方向（A 比 B → B 比 A） ----------
    slots += _en_comparative_slot(tr, words, jf)

    # ---------- 轴 6~N：封闭类词表替换 ----------
    slots += _lex_table_slots(tr, jf, 'en')
    return slots


def _have_is_aux(words, i):
    """have/has/had 后面跟过去分词才是助动词；「He has a car」里的 has 是实义动词
    （实义 have 不能说 "has not a car"，必须用 do-support）。"""
    if i + 1 >= len(words):
        return False
    nxt = words[i + 1][0].lower()
    if nxt in ('not', 'never', 'been', 'got'):
        return True
    base = en_base_of(nxt)
    return bool(base and base[1] == 'pp')


def _en_polarity_slot(tr, words, main, subj, jf):
    """肯否翻转。日文侧证据：全句否定形态素计数（0 → 只能加否定；≥1 → 只能去否定）。"""
    w = lambda i: words[i][0]
    lw = lambda i: words[i][0].lower()
    i = main['i']
    head = lw(i)
    # 频度副词与否定会互相纠缠（"He always doesn't go" 是病句），直接不碰
    if any(x[0].lower() in _FREQ_ADVERBS for x in words):
        return []

    # (a) 译文是肯定的 → 造否定；要求日文全句没有任何否定形态素
    if not main['neg'] and jf['neg_count'] == 0:
        ev = "日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的"
        aux = (head in _BE_FORMS or head in _MODALS or head in _DO_FORMS
               or (head in _HAVE_FORMS and _have_is_aux(words, i)))
        if aux:
            s, e = words[i][1], words[i][2]
            if head == 'can':
                new = 'cannot'
            elif head == "'ll":
                new = " won't"          # "I'll not go" 生硬，用 "I won't go"
            elif head == 'will':
                new = "won't"
            else:
                new = w(i) + ' not'
            return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                          [{'edits': [(s, e, new)], 'note': f'{w(i)} → {new}'}],
                          0.95, (s, e))]
        # do-support：主语和动词必须紧挨着，中间插了副词会改出病句
        if main['i'] != subj['end'] + 1:
            return []
        base = en_base_of(head)
        if base and main['i'] == main['j']:
            b, form = base
            if b in ('be', 'do'):
                return []
            if form == 'past':
                new = f"didn't {b}"
            elif form == '3sg':
                new = f"doesn't {b}"
            elif form == 'base' and subj['number'] != '3sg':
                new = f"don't {b}"
            else:
                return []
            s, e = words[i][1], words[i][2]
            return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                          [{'edits': [(s, e, new)], 'note': f'{w(i)} → {new}'}],
                          0.95, (s, e))]
        return []

    # (b) 译文是否定的 → 去掉否定；要求日文里确有否定形态素
    if main['neg'] and jf['neg_count'] >= 1:
        ev = "日文句尾谓语带否定形态素（ない／ません／ぬ），录音说的是「没有／不」"
        # not：直接删掉；do-support 要顺手收回去（"does not take" → "takes"）
        for k in range(main['i'], main['j'] + 1):
            if lw(k) == 'not' and k > main['i']:
                if head in _DO_FORMS and k + 1 <= main['j']:
                    nb = en_base_of(lw(k + 1))
                    if nb and nb[1] == 'base':
                        b = nb[0]
                        merged = {'do': b, 'does': en_3sg(b), 'did': en_past(b)}[head]
                        s2, e2 = words[i][1], words[k + 1][2]
                        return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                                      [{'edits': [(s2, e2, merged)],
                                        'note': f'{w(i)} not {w(k+1)} → {merged}'}],
                                      0.95, (s2, e2))]
                s, e = words[k - 1][2], words[k][2]
                return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                              [{'edits': [(s, e, '')], 'note': 'not 被去掉'}],
                              0.95, (s, e))]
        if head in _NEG_AUX:
            plain = _NEG_AUX[head]
            s, e = words[i][1], words[i][2]
            if plain in ('do', 'does', 'did'):
                # doesn't eat → eats；didn't eat → ate
                if main['j'] <= i:
                    return []
                nxt = lw(i + 1)
                base = en_base_of(nxt)
                if not base or base[1] != 'base':
                    return []
                b = base[0]
                new = {'do': b, 'does': en_3sg(b), 'did': en_past(b)}[plain]
                s2, e2 = words[i][1], words[i + 1][2]
                return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                              [{'edits': [(s2, e2, new)],
                                'note': f'{w(i)} {w(i+1)} → {new}'}], 0.95, (s2, e2))]
            return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                          [{'edits': [(s, e, plain)], 'note': f'{w(i)} → {plain}'}],
                          0.95, (s, e))]
    return []


def _en_tense_slot(tr, words, main, subj, jf):
    """时制翻转。日文侧证据：句尾「た」的有无（显式时制标记）。"""
    i, j = main['i'], main['j']
    head = words[i][0].lower()
    s, e = words[i][1], words[i][2]

    # (a) 日文是过去 → 把译文改成现在/未来
    if jf['tail_past'] and jf['past_count'] >= 1:
        ev = "日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事"
        if head in ('was', 'were'):
            new = _BE_PAST2PRES[head]
            return [_slot('tense', '时制（已经发生 vs 还没发生）', ev,
                          [{'edits': [(s, e, new)], 'note': f'{head} → {new}'}],
                          0.82, (s, e))]
        if head == 'had' and j > i:
            return [_slot('tense', '时制（已经发生 vs 还没发生）', ev,
                          [{'edits': [(s, e, 'will have')], 'note': 'had → will have'}],
                          0.7, (s, e))]
        base = en_base_of(head)
        if base and base[1] == 'past' and i == j and base[0] not in ('be', 'have', 'do'):
            b = base[0]
            alts = [{'edits': [(s, e, f'will {b}')], 'note': f'{words[i][0]} → will {b}'}]
            pres = en_3sg(b) if subj['number'] == '3sg' else b
            alts.append({'edits': [(s, e, pres)], 'note': f'{words[i][0]} → {pres}'})
            return [_slot('tense', '时制（已经发生 vs 还没发生）', ev, alts, 0.82, (s, e))]
        return []

    # (b) 日文非过去且全句无「た」 → 把译文改成过去
    if not jf['tail_past'] and jf['past_count'] == 0:
        ev = "日文句里没有过去助動詞「た」，说的不是已经完成的事"
        if head in ('is', 'am', 'are'):
            new = _BE_PRES2PAST[head]
            return [_slot('tense', '时制（已经发生 vs 还没发生）', ev,
                          [{'edits': [(s, e, new)], 'note': f'{head} → {new}'}],
                          0.82, (s, e))]
        if head == 'will' and j > i:
            nxt = words[i + 1][0].lower()
            base = en_base_of(nxt)
            if base and base[1] == 'base':
                new = en_past(base[0])
                s2, e2 = words[i][1], words[i + 1][2]
                return [_slot('tense', '时制（已经发生 vs 还没发生）', ev,
                              [{'edits': [(s2, e2, new)],
                                'note': f'will {nxt} → {new}'}], 0.82, (s2, e2))]
            return []
        base = en_base_of(head)
        if base and base[1] in ('3sg', 'base') and i == j and base[0] not in ('be', 'have', 'do'):
            new = en_past(base[0])
            return [_slot('tense', '时制（已经发生 vs 还没发生）', ev,
                          [{'edits': [(s, e, new)], 'note': f'{words[i][0]} → {new}'}],
                          0.82, (s, e))]
    return []


def _match_entity(name, jf):
    """在日文实体里找这个英文名字，返回 (surface, particle) 或 None。"""
    from difflib import SequenceMatcher
    low = name.lower()
    best = None
    for ent in jf['entities']:
        gloss = (ent.get('gloss') or '').lower()
        if not gloss:
            continue
        r = SequenceMatcher(None, low, gloss).ratio()
        if r >= 0.72 and (best is None or r > best[0]):
            best = (r, ent)
    return best[1] if best else None


def _en_role_slot(tr, words, complexes, jf):
    """施受互换：Tom called Mary → Mary called Tom。四个选项共享全部实词。"""
    if len(complexes) != 1:
        return []
    main = complexes[0]
    low = [w[0].lower() for w in words]
    if 'by' in low or 'and' in low or 'with' in low or 'each' in low:
        return []
    if any(low[k] in _SYMMETRIC_VERBS for k in range(main['i'], main['j'] + 1)):
        return []
    if jf['passive'] or jf['causative']:
        return []

    # (a) 两个专有名词：主语位 + 动词后
    names = [(k, w) for k, (w, s, e) in enumerate(words) if _is_name(w, k)]
    if len(names) == 2 and names[0][0] < main['i'] < names[1][0]:
        k1, n1 = names[0]
        k2, n2 = names[1]
        if n1.lower() == n2.lower():
            return []
        e1, e2 = _match_entity(n1, jf), _match_entity(n2, jf)
        if not e1 or not e2:
            return []
        r1, r2 = _role_of(e1['particle']), _role_of(e2['particle'])
        if not r1 or not r2 or r1 == r2:
            return []
        ev = (f"日文里「{e1['surface']}{e1['particle']}」和「{e2['surface']}{e2['particle']}」"
              f"的助词不同，施受关系被助词钉死，互换后必错")
        edits = [(words[k1][1], words[k1][2], n2), (words[k2][1], words[k2][2], n1)]
        return [_slot('role', '施受关系（谁对谁做）', ev,
                      [{'edits': edits, 'note': f'{n1} ↔ {n2} 互换'}],
                      1.0, (words[k1][1], words[k2][2]))]

    # (b) 主语代词 + 宾语代词
    if low[0] in _SUBJ_PRON and main['i'] == 1:
        for k in range(main['j'] + 1, len(words)):
            if low[k] in _OBJ_PRON:
                s_key = _pron_key(low[0], True)
                o_key = _pron_key(low[k], False)
                if not s_key or not o_key or s_key == o_key:
                    break
                sp = jf['pronouns'].get(s_key)
                op = jf['pronouns'].get(o_key)
                if not op:
                    break
                if not any(_role_of(p) == 'object' for p in op):
                    break
                if sp and not any(_role_of(p) == 'subject' for p in sp):
                    break
                # 动词需要随主语变位时（现在时 3sg），放弃（避免造出病句）
                verb = low[main['i']]
                base = en_base_of(verb)
                if base and base[1] in ('3sg', 'base') and verb not in _BE_FORMS:
                    break
                new_subj = _OBJ2SUBJ[low[k]]
                new_obj = _SUBJ2OBJ[low[0]]
                ev = (f"日文里表示对象的代词带「を/に」格助词，施受方向是显式的")
                edits = [(words[0][1], words[0][2], new_subj),
                         (words[k][1], words[k][2], new_obj)]
                return [_slot('role', '施受关系（谁对谁做）', ev,
                              [{'edits': edits,
                                'note': f'{words[0][0]} ↔ {words[k][0]} 施受互换'}],
                              1.0, (words[0][1], words[k][2]))]
            if low[k] in _SUBJ_PRON:
                break
    return []


def _same_person_group(a, b):
    """两个人称是否可能同指（第一人称单复数视为同组）。"""
    group = {'1sg': 1, '1pl': 1, '2sg': 2, '2pl': 2,
             '3sgm': 3, '3sgf': 4, '3pl': 5}
    return group.get(a) == group.get(b)


def _pron_key(word, subject):
    return {'i': '1sg', 'me': '1sg', 'we': '1pl', 'us': '1pl',
            'you': '2sg', 'he': '3sgm', 'him': '3sgm', 'she': '3sgf',
            'her': '3sgf', 'they': '3pl', 'them': '3pl'}.get(word)


_EN_NP_RE = (r"(?:the |a |an |my |your |his |her |our |their |this |that |these |those )?"
             r"[A-Za-z][A-Za-z'\-]*")
_EN_ALL_PRON = (set(_SUBJ_PRON) | set(_OBJ_PRON)
                | {'my', 'your', 'his', 'her', 'our', 'their', 'its'})


def _en_direction_slot(tr, words, jf):
    """起讫点互换：from A to B → from B to A。证据：日文里有名词＋から。"""
    if not jf['kara_noun']:
        return []
    m = re.search(rf"\bfrom ({_EN_NP_RE}) to ({_EN_NP_RE})\b", tr)
    if not m or m.group(1).lower() == m.group(2).lower():
        return []
    a, b = m.group(1), m.group(2)
    ev = "日文用「〜から」「〜へ／まで」显式标出了起点和终点"
    edits = [(m.start(1), m.end(1), b), (m.start(2), m.end(2), a)]
    return [_slot('direction', '起点终点（从哪到哪）', ev,
                  [{'edits': edits, 'note': f'from {a} to {b} → from {b} to {a}'}],
                  0.95, (m.start(1), m.end(2)))]


def _en_comparative_slot(tr, words, jf):
    """比较方向互换：A is bigger than B → B is bigger than A。证据：日文里有「より」。"""
    if not jf['comparative'] or jf['superlative']:
        return []
    m = re.match(rf"^({_EN_NP_RE}) (is|are|was|were) ([A-Za-z\- ]+?) than ({_EN_NP_RE})\.?$",
                 tr.strip())
    if not m:
        return []
    a, b = m.group(1), m.group(4)
    if a.lower() == b.lower():
        return []
    # 代词参与比较时要改格与一致（"I is taller than he" ✗），规则引擎不碰
    if (a.split()[0].lower() in _EN_ALL_PRON or b.split()[0].lower() in _EN_ALL_PRON):
        return []
    ev = "日文用「〜より」显式标出了比较的基准，互换两侧后意思相反"
    edits = [(m.start(1), m.end(1), b), (m.start(4), m.end(4), a)]
    return [_slot('comparative', '比较方向（谁更…）', ev,
                  [{'edits': edits, 'note': f'{a} ↔ {b} 互换'}],
                  0.95, (m.start(1), m.end(4)))]


# ================================================================
# 六、封闭类词表替换（中英共用一张规则表）
# ================================================================
# 每条规则：(轴, 标签, 译文里的正则, 候选替换列表, 需要的日文证据, 禁止的日文证据)
# 证据用 (字段, 值) 表示；字段 ∈ conn/modal/quant/times/places/numbers
_TABLE = [
    # ---- 因果 / 逆接 / 前后 / 条件 ----
    ('conj', '分句逻辑（因为 / 虽然 / 如果）',
     r'\bbecause\b', ['although', 'even though'], ('conn', 'cause'), ('conn', 'concession')),
    ('conj', '分句逻辑（因为 / 虽然 / 如果）',
     r'\bsince\b', ['although'], ('conn', 'cause'), ('conn', 'after')),
    ('conj', '分句逻辑（因为 / 虽然 / 如果）',
     r'\balthough\b', ['because'], ('conn', 'concession'), ('conn', 'cause')),
    ('conj', '分句逻辑（因为 / 虽然 / 如果）',
     r'\bthough\b', ['because'], ('conn', 'concession'), ('conn', 'cause')),
    ('conj', '分句逻辑（先后顺序）',
     r'\bafter\b', ['before'], ('conn', 'after'), ('conn', 'before')),
    ('conj', '分句逻辑（先后顺序）',
     r'\bbefore\b', ['after'], ('conn', 'before'), ('conn', 'after')),
    ('conj', '分句逻辑（如果 / 就算）',
     r'\beven if\b', ['if'], ('conn', 'even_if'), ('conn', 'if')),
    ('conj', '分句逻辑（如果 / 就算）',
     r'\bif\b', ['even if'], ('conn', 'if'), ('conn', 'even_if')),
    # ---- 情态 ----
    ('modal', '情态（必须 / 可以 / 不可以）',
     r'\bmust\b', ['may', 'should', 'want to'], ('modal', 'must'), ('modal', 'may')),
    ('modal', '情态（必须 / 可以 / 不可以）',
     r'\bhave to\b', ['may', 'want to', 'should'], ('modal', 'must'), ('modal', 'may')),
    ('modal', '情态（必须 / 可以 / 不可以）',
     r'\bhas to\b', ['may', 'wants to', 'should'], ('modal', 'must'), ('modal', 'may')),
    ('modal', '情态（必须 / 可以 / 不可以）',
     r'\bmay\b', ['must', 'should', 'want to'], ('modal', 'may'), ('modal', 'must')),
    ('modal', '情态（应该 / 必须）',
     r'\bshould\b', ['must', 'may'], ('modal', 'should'), ('modal', 'must')),
    ('modal', '情态（想要 / 必须）',
     r'\bwant to\b', ['have to'], ('modal', 'want'), ('modal', 'must')),
    ('modal', '情态（想要 / 必须）',
     r'\bwants to\b', ['has to'], ('modal', 'want'), ('modal', 'must')),
    # ---- 频度 / 量化 ----
    ('quant', '频度（总是 / 从不 / 有时）',
     r'\balways\b', ['never', 'sometimes', 'rarely'], ('quant', 'always'), ('quant', 'never')),
    ('quant', '频度（总是 / 从不 / 有时）',
     r'\bnever\b', ['always', 'often', 'sometimes'], ('quant', 'never'), ('quant', 'always')),
    ('quant', '频度（总是 / 从不 / 有时）',
     r'\boften\b', ['never', 'rarely'], ('quant', 'often'), ('quant', 'never')),
    ('quant', '频度（总是 / 从不 / 有时）',
     r'\bsometimes\b', ['always', 'never'], ('quant', 'sometimes'), ('quant', 'always')),
    ('quant', '范围（全部 / 只有 / 也）',
     r'\bonly\b', ['also', 'even'], ('quant', 'only'), None),
    ('quant', '进程（已经 / 还没）',
     r'\balready\b', ['not yet'], ('quant', 'already'), ('quant', 'yet')),
    ('quant', '进程（已经 / 还没）',
     r'\bstill\b', ['no longer'], ('quant', 'yet'), ('quant', 'already')),
    ('quant', '数量（很多 / 很少）',
     r'\ba lot of\b', ['a little', 'only a few'], ('quant', 'many'), ('quant', 'little')),
    ('quant', '数量（很多 / 很少）',
     r'\bmany\b', ['few'], ('quant', 'many'), ('quant', 'little')),
    # ---- 方位 ----
    ('place', '方位（上下 / 里外 / 前后）',
     r'\bon\b', ['under', 'behind'], ('places', '上'), ('places', '下')),
    ('place', '方位（上下 / 里外 / 前后）',
     r'\bunder\b', ['on', 'behind'], ('places', '下'), ('places', '上')),
    ('place', '方位（上下 / 里外 / 前后）',
     r'\bin front of\b', ['behind', 'next to'], ('places', '前'), ('places', '後ろ')),
    ('place', '方位（上下 / 里外 / 前后）',
     r'\bbehind\b', ['in front of', 'next to'], ('places', '後ろ'), ('places', '前')),
    ('place', '方位（上下 / 里外 / 前后）',
     r'\bnext to\b', ['in front of', 'behind'], ('places', '隣'), ('places', '前')),
    ('place', '方位（左右）',
     r'\bleft\b', ['right'], ('places', '左'), ('places', '右')),
    ('place', '方位（左右）',
     r'\bright\b', ['left'], ('places', '右'), ('places', '左')),
    # ---- 中文：分句逻辑 ----
    ('conj', '分句逻辑（因为 / 虽然）',
     r'因为|因為', ['虽然', '雖然'], ('conn', 'cause'), ('conn', 'concession')),
    ('conj', '分句逻辑（因为 / 虽然）',
     r'虽然|雖然', ['因为', '因為'], ('conn', 'concession'), ('conn', 'cause')),
    ('conj', '分句逻辑（所以 / 但是）',
     r'所以', ['但是'], ('conn', 'cause'), ('conn', 'concession')),
    ('conj', '分句逻辑（先后顺序）',
     r'之后|之後|以后|以後', ['之前', '之前'], ('conn', 'after'), ('conn', 'before')),
    ('conj', '分句逻辑（先后顺序）',
     r'之前|以前', ['之后', '之後'], ('conn', 'before'), ('conn', 'after')),
    ('conj', '分句逻辑（如果 / 就算）',
     r'如果|要是', ['即使', '就算'], ('conn', 'if'), ('conn', 'even_if')),
    ('conj', '分句逻辑（如果 / 就算）',
     r'即使|就算|哪怕', ['如果', '要是'], ('conn', 'even_if'), ('conn', 'if')),
    # ---- 中文：情态 ----
    ('modal', '情态（必须 / 可以）',
     r'必须|必須|得要', ['可以', '想', '应该', '應該'], ('modal', 'must'), ('modal', 'may')),
    ('modal', '情态（必须 / 可以）',
     r'可以', ['必须', '必須', '想', '应该', '應該'], ('modal', 'may'), ('modal', 'must')),
    ('modal', '情态（应该 / 必须）',
     r'应该|應該', ['必须', '必須', '可以'], ('modal', 'should'), ('modal', 'must')),
    ('modal', '情态（想要 / 必须）',
     r'想要|想', ['必须', '必須'], ('modal', 'want'), ('modal', 'must')),
    # ---- 中文：频度 / 量化 ----
    ('quant', '频度（总是 / 从不 / 有时）',
     r'总是|總是|一直', ['从不', '從不', '有时', '有時'], ('quant', 'always'), ('quant', 'never')),
    ('quant', '频度（总是 / 从不 / 有时）',
     r'从不|從不|从来不|從來不', ['总是', '總是'], ('quant', 'never'), ('quant', 'always')),
    ('quant', '频度（总是 / 从不 / 有时）',
     r'经常|經常', ['从不', '從不'], ('quant', 'often'), ('quant', 'never')),
    ('quant', '频度（总是 / 从不 / 有时）',
     r'有时|有時|偶尔|偶爾', ['总是', '總是'], ('quant', 'sometimes'), ('quant', 'always')),
    ('quant', '范围（只有 / 也）',
     r'只有|只是|仅|僅', ['也有', '也'], ('quant', 'only'), None),
    ('quant', '进程（已经 / 还没）',
     r'已经|已經', ['还没', '還沒'], ('quant', 'already'), ('quant', 'yet')),
    ('quant', '数量（很多 / 很少）',
     r'很多|许多|許多', ['很少'], ('quant', 'many'), ('quant', 'little')),
    # ---- 中文：方位 ----
    ('place', '方位（上下 / 里外 / 前后）',
     r'上面|上边|上邊|在上', ['下面', '后面', '後面'], ('places', '上'), ('places', '下')),
    ('place', '方位（上下 / 里外 / 前后）',
     r'下面|下边|下邊', ['上面', '后面', '後面'], ('places', '下'), ('places', '上')),
    ('place', '方位（上下 / 里外 / 前后）',
     r'前面|前边|前邊', ['后面', '後面', '旁边'], ('places', '前'), ('places', '後ろ')),
    ('place', '方位（上下 / 里外 / 前后）',
     r'后面|後面|后边|後邊', ['前面', '旁边', '旁邊'], ('places', '後ろ'), ('places', '前')),
    ('place', '方位（左右）',
     r'左边|左邊|左侧|左側', ['右边', '右邊'], ('places', '左'), ('places', '右')),
    ('place', '方位（左右）',
     r'右边|右邊|右侧|右側', ['左边', '左邊'], ('places', '右'), ('places', '左')),
]


def _lex_table_slots(tr, jf, lang):
    """封闭类词表替换：只在日文侧确有对应显式标记、且替换值在日文里不存在时才允许。"""
    out = []
    zh_trad = _is_trad(tr) if lang == 'zh' else False
    for axis, label, pattern, repls, need, forbid in _TABLE:
        if (lang == 'en') != bool(re.search(r'[A-Za-z]', pattern)):
            continue
        if need:
            field, value = need
            if value not in jf[field]:
                continue
        if forbid:
            field, value = forbid
            if value in jf[field]:
                continue
        m = re.search(pattern, tr, flags=re.IGNORECASE if lang == 'en' else 0)
        if not m:
            continue
        cands = []
        for rep in repls:
            if lang == 'zh':
                if _is_trad(rep) != zh_trad and _zh_pair(rep, zh_trad) is not None:
                    rep = _zh_pair(rep, zh_trad)
                if rep in tr:
                    continue
            elif re.search(rf'\b{re.escape(rep)}\b', tr, flags=re.IGNORECASE):
                continue
            if rep.lower() == m.group().lower():
                continue
            cands.append(rep)
        # 去重（繁简两个写法只留一个）
        uniq, seen = [], set()
        for c in cands:
            if c in seen:
                continue
            seen.add(c)
            uniq.append(c)
        if not uniq:
            continue
        ev = _evidence_text(need, jf, lang)
        alts = [{'edits': [(m.start(), m.end(), c)], 'note': f'{m.group()} → {c}'}
                for c in uniq]
        quality = {'conj': 0.9, 'modal': 0.85, 'quant': 0.8, 'place': 0.8}.get(axis, 0.7)
        out.append(_slot(axis, label, ev, alts, quality, (m.start(), m.end())))
    out += _number_slots(tr, jf, lang)
    out += _time_slots(tr, jf, lang)
    out += _person_slots(tr, jf, lang)
    return out


_TRAD_CHARS = set('這裡們會後來說嗎沒對點國學東時個為電開關實發車門問題買賣寫覺')


def _is_trad(s):
    return any(ch in _TRAD_CHARS for ch in s)


_ZH_PAIRS = [('虽然', '雖然'), ('因为', '因為'), ('之后', '之後'), ('后面', '後面'),
             ('从不', '從不'), ('总是', '總是'), ('已经', '已經'), ('还没', '還沒'),
             ('必须', '必須'), ('应该', '應該'), ('旁边', '旁邊'), ('左边', '左邊'),
             ('右边', '右邊'), ('有时', '有時'), ('他们', '他們'), ('我们', '我們'),
             ('你们', '你們'), ('没有', '沒有'), ('会', '會'), ('吗', '嗎')]
_ZH_S2T = {s: t for s, t in _ZH_PAIRS}
_ZH_T2S = {t: s for s, t in _ZH_PAIRS}


def _zh_pair(word, want_trad):
    if want_trad:
        return _ZH_S2T.get(word)
    return _ZH_T2S.get(word)


def _evidence_text(need, jf, lang):
    if not need:
        return '日文侧存在对应的显式语法标记'
    field, value = need
    label = {
        ('conn', 'cause'): '日文里有表示原因的「から／ので」，没有逆接的「のに／けど」',
        ('conn', 'concession'): '日文里有逆接的「のに／けど／が」，不是原因句',
        ('conn', 'before'): '日文里有「〜前に」，先后顺序是显式的',
        ('conn', 'after'): '日文里有「〜てから／〜後で」，先后顺序是显式的',
        ('conn', 'if'): '日文里有条件形「〜たら／〜ば／〜なら」',
        ('conn', 'even_if'): '日文里有让步的「〜ても」',
        ('modal', 'must'): '日文里有义务表达「〜なければならない／〜ないといけない」',
        ('modal', 'may'): '日文里有许可表达「〜てもいい」',
        ('modal', 'should'): '日文里有建议表达「〜ほうがいい／〜べき」',
        ('modal', 'want'): '日文里有愿望形「〜たい」',
        ('quant', 'always'): '日文里有「いつも／ずっと」',
        ('quant', 'never'): '日文里有「全然／決して」＋否定',
        ('quant', 'often'): '日文里有「よく」',
        ('quant', 'sometimes'): '日文里有「時々／たまに」',
        ('quant', 'only'): '日文里有「だけ／しか」',
        ('quant', 'already'): '日文里有「もう／すでに」',
        ('quant', 'yet'): '日文里有「まだ」',
        ('quant', 'many'): '日文里有「たくさん／多く」',
    }.get((field, value))
    if label:
        return label
    if field == 'places':
        return f'日文里出现方位名词「{value}」，位置关系是显式的'
    return '日文侧存在对应的显式语法标记'


_EN_NUM_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
                 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11,
                 'twelve': 12, 'twenty': 20, 'thirty': 30, 'fifty': 50, 'hundred': 100}
_EN_NUM_REV = {v: k for k, v in _EN_NUM_WORDS.items()}
_ZH_NUM_WORDS = {'一': 1, '两': 2, '兩': 2, '二': 2, '三': 3, '四': 4, '五': 5,
                 '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
_ZH_NUM_REV = {1: '一', 2: '两', 3: '三', 4: '四', 5: '五', 6: '六', 7: '七',
               8: '八', 9: '九', 10: '十'}


def _number_slots(tr, jf, lang):
    """数量轴：日文里出现了这个数词才允许改；替换值不得在日文里出现。"""
    if not jf['numbers']:
        return []
    table = _EN_NUM_WORDS if lang == 'en' else _ZH_NUM_WORDS
    rev = _EN_NUM_REV if lang == 'en' else _ZH_NUM_REV
    out = []
    for word, value in table.items():
        if value not in jf['numbers']:
            continue
        pattern = rf'\b{word}\b' if lang == 'en' else re.escape(word)
        m = re.search(pattern, tr, flags=re.IGNORECASE if lang == 'en' else 0)
        if not m:
            continue
        # 连写数字（「两三把」「十二」「第三」）不能只换一半
        before = tr[max(0, m.start() - 1):m.start()]
        after = tr[m.end():m.end() + 1]
        if lang == 'zh' and (before in _ZH_NUM_WORDS or after in _ZH_NUM_WORDS
                             or before in '第十百千万萬点點分' or after in '十百千万萬分'):
            continue
        if lang == 'en' and re.search(r'\b(one|two|three|four|five|six|seven|eight'
                                      r'|nine|ten|hundred|thousand)\s*$',
                                      tr[:m.start()], flags=re.IGNORECASE):
            continue
        cands = []
        for delta in (1, -1, 2, 3, -2):
            v = value + delta
            if v <= 0 or v in jf['numbers'] or v not in rev:
                continue
            rep = rev[v]
            if lang == 'zh' and v == 2 and _is_trad(tr):
                rep = '兩'
            if re.search(rf'\b{rep}\b' if lang == 'en' else re.escape(rep), tr):
                continue
            cands.append(rep)
            if len(cands) >= 3:
                break
        if not cands:
            continue
        alts = []
        for c in cands:
            edits = [(m.start(), m.end(), c)]
            if lang == 'en':
                fix = _en_number_agreement(tr, m, value, c)
                if fix is None:
                    continue
                edits += fix
            alts.append({'edits': edits, 'note': f'{m.group()} → {c}'})
        if not alts:
            continue
        out.append(_slot('number', '数量（听清几个）',
                         f'日文里出现数词「{value}」，数量是显式的', alts,
                         0.72, (m.start(), m.end())))
    return out


def _en_number_agreement(tr, m, old_value, new_word):
    """单数↔复数换数词时把随后的 be/have 动词改对（One … is → Two … are）。
    改不动（找不到谓语但确实跨了单复数）就返回 None，放弃这个候选。"""
    new_value = _EN_NUM_WORDS.get(new_word.lower())
    if new_value is None or (old_value == 1) == (new_value == 1):
        return []
    tail = tr[m.end():]
    mv = re.search(r"\b(is|was|has|isn't|wasn't|hasn't|are|were|have|aren't|weren't|haven't)\b",
                   tail)
    if not mv or len(re.findall(r'\S+', tail[:mv.start()])) > 4:
        return None
    to_plural = new_value != 1
    table = {'is': 'are', 'was': 'were', 'has': 'have', "isn't": "aren't",
             "wasn't": "weren't", "hasn't": "haven't"}
    rev = {v: k for k, v in table.items()}
    cur = mv.group()
    new = table.get(cur) if to_plural else rev.get(cur)
    if new is None:
        return []
    off = m.end()
    return [(off + mv.start(), off + mv.end(), new)]


def _time_slots(tr, jf, lang):
    """时间轴：日文里出现了该時間名詞，且替换值对应的日文词不在句中。"""
    out = []
    idx = 0 if lang == 'en' else 1
    for jp_word in jf['times']:
        word = _JP_TIME[jp_word][idx]
        pattern = rf'\b{re.escape(word)}\b' if lang == 'en' else re.escape(word)
        m = re.search(pattern, tr, flags=re.IGNORECASE if lang == 'en' else 0)
        if not m:
            continue
        group = [k for k in _TIME_GROUPS if jp_word in k]
        if not group:
            continue
        cands = []
        for other in group[0]:
            if other == jp_word or other in jf['times']:
                continue
            rep = _JP_TIME[other][idx]
            if rep.lower() in tr.lower():
                continue
            cands.append(rep)
            if len(cands) >= 3:
                break
        if not cands:
            continue
        out.append(_slot('time', '时间（什么时候）',
                         f'日文里出现時間名詞「{jp_word}」，时间点是显式的',
                         [{'edits': [(m.start(), m.end(), c)], 'note': f'{m.group()} → {c}'}
                          for c in cands], 0.7, (m.start(), m.end())))
    return out


_TIME_GROUPS = [
    ('昨日', '今日', '明日', '明後日', '一昨日'),
    ('先週', '今週', '来週'),
    ('先月', '今月', '来月'),
    ('去年', '今年', '来年'),
    ('朝', '昼', '夜', '夕方'),
    ('今朝', '昨夜', '今晩'),
    ('月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日', '日曜日'),
]

_EN_PERSON = {'1sg': ('I', 'me', 'my'), '2sg': ('you', 'you', 'your'),
              '3sgm': ('he', 'him', 'his'), '3sgf': ('she', 'her', 'her'),
              '1pl': ('we', 'us', 'our'), '3pl': ('they', 'them', 'their')}
_ZH_PERSON = {'1sg': ('我',), '2sg': ('你',), '3sgm': ('他',), '3sgf': ('她',),
              '1pl': ('我们', '我們'), '3pl': ('他们', '他們')}


def _person_slots(tr, jf, lang):
    """人称轴：只在日文里显式出现了该代词、且替换人称的日文代词不在句中时才允许。"""
    out = []
    present = set(jf['pronouns'])
    if not present:
        return []
    for key in list(present):
        if lang == 'en':
            got = _en_person_slot_for(tr, jf, key, present)
            if got:
                out.append(got)
        else:
            forms = _ZH_PERSON.get(key)
            if not forms or _zh_imperative(tr):
                continue
            want_trad = _is_trad(tr)
            form = forms[-1] if (want_trad and len(forms) > 1) else forms[0]
            m = re.search(re.escape(form), tr)
            if not m or len(re.findall(re.escape(form), tr)) > 1:
                continue
            if key in ('1sg', '2sg', '3sgm', '3sgf') and re.search(
                    re.escape(form) + r'[们們]', tr):
                continue
            # 「他来了没有？」「你吃了吗？」这类正反/语气疑问句，换成第一人称
            # 会变成自己问自己（我来了没有？），不自然，跳过第一人称候选。
            self_q = bool(re.search(r'了\s*(没有|沒有|吗|嗎)?\s*[？?]\s*$', tr))
            cands = []
            for other, other_forms in _ZH_PERSON.items():
                if other == key or other in present:
                    continue
                if (other in ('1pl', '3pl')) != (key in ('1pl', '3pl')):
                    continue
                if self_q and other in ('1sg', '1pl'):
                    continue
                rep = other_forms[-1] if (want_trad and len(other_forms) > 1) else other_forms[0]
                if rep in tr:
                    continue
                cands.append(rep)
                if len(cands) >= 3:
                    break
            if not cands:
                continue
            out.append(_slot('person', '人称（是谁）',
                             f'日文里显式出现了代词（{_pron_jp_label(key)}）',
                             [{'edits': [(m.start(), m.end(), c)],
                               'note': f'{m.group()} → {c}'} for c in cands],
                             0.78, (m.start(), m.end())))
    return out


def _pron_jp_label(key):
    return {'1sg': '私／僕', '2sg': 'あなた／君', '3sgm': '彼', '3sgf': '彼女',
            '1pl': '私たち', '3pl': '彼ら'}.get(key, key)


_EN_NOUNISH_STOP = {'is', 'are', 'was', 'were', 'am', 'has', 'have', 'had', 'do',
                    'does', 'did', 'will', 'would', 'can', 'could', 'should',
                    'must', 'may', 'might', 'to', 'in', 'on', 'at', 'for',
                    'with', 'and', 'or', 'but', 'that', 'than', 'too', 'very',
                    'not', 'never', 'again', 'here', 'there', 'now', 'then'}


def _en_person_slot_for(tr, jf, key, present):
    """英文人称轴：先确定这个代词处在主格/宾格/属格的哪一格，只做同格替换。

    `you`（主宾同形）与 `her`（宾格/属格同形）必须靠位置判别，判不了就放弃；
    主格换人称会牵动 be 动词与第三人称单数，这里只在能同时改对缩合形和
    变位形时才产出候选。
    """
    words = _en_words(tr)
    if not words:
        return None
    forms = _EN_PERSON.get(key)
    if not forms:
        return None
    subj_form, obj_form, poss_form = forms
    plural_key = key in ('1pl', '3pl')
    low_forms = {f.lower() for f in forms}
    _AUX_ANY = (set(_BE_FORMS) | _HAVE_FORMS | _MODALS | set(_DO_FORMS)
                | set(_NEG_AUX))

    # 同一人称在句中出现几次就要一起换，只换一处会造出人称前后不一致的怪句
    hits = []
    for idx, (w, s, e) in enumerate(words):
        low = w.lower()
        if low not in low_forms:
            continue
        prev = words[idx - 1][0].lower() if idx else ''
        nxt = words[idx + 1][0].lower() if idx + 1 < len(words) else ''
        before = tr[:s].rstrip()
        clause_start = (idx == 0 or before.endswith((',', ';', ':', '"', '“', '.'))
                        or prev in ('that', 'because', 'and', 'but', 'when',
                                    'if', 'so', 'while', 'though', 'as'))
        role = None
        if low == subj_form.lower() and clause_start:
            role = 0
        elif low == obj_form.lower() or low == poss_form.lower():
            if prev in _AUX_ANY:
                return None        # 疑问倒装里的主语，改了要动前面的助动词
            if obj_form.lower() == poss_form.lower():
                role = 2 if (nxt and nxt not in _EN_NOUNISH_STOP
                             and nxt not in _CONTRACTION
                             and (en_base_of(nxt) or ('', ''))[1] not in ('3sg', 'past')) else 1
            else:
                role = 1 if low == obj_form.lower() else 2
        if role is None:
            return None            # 认不出这个代词的格，整条规则放弃
        if role == 1 and nxt in _CONTRACTION:
            return None
        hits.append((idx, s, e, w, role))
    if not hits:
        return None

    # 句首主语的人称：换宾语时不能换成与主语同指的人称（"We have to stop me" ✗）
    subj_key = _pron_key(words[0][0].lower(), True) if words else None
    obj_only = all(h[4] == 1 for h in hits)

    cands = []
    for other, other_forms in _EN_PERSON.items():
        if other == key or other in present:
            continue
        if (other in ('1pl', '3pl')) != plural_key:
            continue
        if obj_only and subj_key and _same_person_group(subj_key, other):
            continue
        if any(re.search(rf'\b{re.escape(f)}\b', tr, flags=re.IGNORECASE)
               for f in set(other_forms)):
            continue
        edits, ok = [], True
        for idx, s, e, w, role in hits:
            edits.append((s, e, other_forms[role]))
            if role == 0:
                fix = _en_subject_agreement(words, idx, key, other)
                if fix is None:
                    ok = False
                    break
                edits += fix
        if not ok:
            continue
        note = f"{hits[0][3]} → {other_forms[hits[0][4]]}"
        cands.append({'edits': edits, 'note': note})
        if len(cands) >= 3:
            break
    if not cands:
        return None
    span = (hits[0][1], max(x[1] for c in cands for x in c['edits']))
    return _slot('person', '人称（是谁）',
                 f'日文里显式出现了代词（{_pron_jp_label(key)}），人称不是靠上下文猜的',
                 cands, 0.78, span)


def _en_subject_agreement(words, idx, key, other):
    """主格换人称时，把紧跟其后的缩合形/be 动词/第三人称单数改对；
    改不动就返回 None（宁可不出题也不造病句）。"""
    if idx + 1 >= len(words):
        return []
    w, s, e = words[idx + 1]
    low = w.lower()
    third = {'3sgm', '3sgf'}
    sing = {'1sg', '2sg', '3sgm', '3sgf'}
    if low in _CONTRACTION:
        if low in ("'m", "'re", "'s"):
            return [(s, e, _BE_CONTRACTION[other])]
        if low == "'ve":
            return [(s, e, _HAVE_CONTRACTION[other])]
        return []           # 'll / 'd 与人称无关
    be_map = {'am': {'1sg': 'am', '2sg': 'are', '3sgm': 'is', '3sgf': 'is',
                     '1pl': 'are', '3pl': 'are'},
              'is': {'1sg': 'am', '2sg': 'are', '3sgm': 'is', '3sgf': 'is',
                     '1pl': 'are', '3pl': 'are'},
              'are': {'1sg': 'am', '2sg': 'are', '3sgm': 'is', '3sgf': 'is',
                      '1pl': 'are', '3pl': 'are'},
              'was': {'1sg': 'was', '2sg': 'were', '3sgm': 'was', '3sgf': 'was',
                      '1pl': 'were', '3pl': 'were'},
              'were': {'1sg': 'was', '2sg': 'were', '3sgm': 'was', '3sgf': 'was',
                       '1pl': 'were', '3pl': 'were'}}
    if low in be_map:
        new = be_map[low][other]
        return [] if new == low else [(s, e, new)]
    if low in ('has', 'have'):
        new = 'has' if other in third else 'have'
        return [] if new == low else [(s, e, new)]
    if low in ('does', 'do'):
        new = 'does' if other in third else 'do'
        return [] if new == low else [(s, e, new)]
    if low in ("doesn't", "don't"):
        new = "doesn't" if other in third else "don't"
        return [] if new == low else [(s, e, new)]
    if low in ("isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't"):
        table = {"isn't": {'p': "aren't", 's': "isn't"},
                 "aren't": {'p': "aren't", 's': "isn't"},
                 "wasn't": {'p': "weren't", 's': "wasn't"},
                 "weren't": {'p': "weren't", 's': "wasn't"},
                 "hasn't": {'p': "haven't", 's': "hasn't"},
                 "haven't": {'p': "haven't", 's': "hasn't"}}
        if low in ("isn't", "aren't"):
            new = "isn't" if other in third else ("am not" if other == '1sg' else "aren't")
        elif low in ("wasn't", "weren't"):
            new = table[low]['s'] if other in sing and other != '2sg' else table[low]['p']
        else:
            new = table[low]['s'] if other in third else table[low]['p']
        return [] if new == low else [(s, e, new)]
    base = en_base_of(low)
    if base and base[1] in ('3sg', 'base') and low not in _MODALS:
        b = base[0]
        new = en_3sg(b) if other in third else b
        return [] if new == low else [(s, e, new)]
    if base and base[1] == 'past':
        return []
    if low in _MODALS or base:
        return []
    return None


# ================================================================
# 七、中文改写规则
# ================================================================
_ZH_VERBS = '''去 来 來 回 到 走 跑 飞 飛 坐 站 躺 睡 起 醒 吃 喝 尝 嘗 买 買 卖 賣
付 借 还 還 给 給 送 拿 带 帶 收 放 扔 丢 丟 找 等 叫 喊 说 說 讲 講 谈 談 问 問 答
回答 告诉 告訴 听 聽 看 见 見 读 讀 写 寫 画 畫 唱 跳 玩 学 學 学习 學習 教 记 記
记得 記得 忘 忘记 忘記 想 要 会 會 能 应该 應該 必须 必須 喜欢 喜歡 爱 愛 恨 怕
知道 认识 認識 觉得 覺得 认为 認為 希望 打算 决定 決定 同意 反对 反對 参加 參加
准备 準備 开始 開始 结束 結束 完成 继续 繼續 停 停止 用 花 修 洗 穿 脱 脫 戴 开
開 关 關 打开 打開 关上 關上 做 作 干 幹 工作 上班 下班 上学 上學 毕业 畢業
住 搬 租 建 造 死 活 生 长 長 变 變 成为 成為 帮 幫 帮助 幫助 救 请 請 邀请 邀請
打 踢 推 拉 抱 亲 親 笑 哭 生气 生氣 担心 擔心 相信 怀疑 懷疑 发现 發現 找到
得到 收到 接到 看到 听到 聽到 遇到 碰到 通过 通過 经过 經過 需要 缺 少 多
拍 照 寄 发 發 打电话 打電話 上网 上網 出发 出發 到达 到達 离开 離開 回家 回来 回來'''.split()
_ZH_VERBS = sorted(set(_ZH_VERBS), key=len, reverse=True)
_ZH_MODAL_NEGATABLE = ['应该', '應該', '必须', '必須', '可以', '能够', '能夠',
                       '会', '會', '能', '要', '想', '喜欢', '喜歡', '知道',
                       '觉得', '覺得', '认为', '認為', '记得', '記得', '同意']
_ZH_PRON = ('我们', '我們', '你们', '你們', '他们', '他們', '她们', '她們',
            '我', '你', '他', '她', '它')
_ZH_SYMMETRIC = ('见面', '見面', '结婚', '結婚', '一样', '一樣', '相似', '认识',
                 '認識', '聊天', '吵架', '是')


_ZH_IMPERATIVE = ('请', '請', '别', '別', '不要', '吧！', '吧。', '吧', '快点', '快點')


def _zh_single_clause(tr):
    """中文没有形态变化，插入否定/时体标记只有在单小句里才敢动手：
    一旦有逗号，被改的很可能是从句（「为了不吵醒宝宝，…」改成肯定就完全走样）。"""
    return not re.search(r'[，,、；;：:]', tr)


def _zh_imperative(tr):
    return any(w in tr for w in _ZH_IMPERATIVE)


def _zh_slots(tr, jf):
    slots = []
    if len(tr) < 4 or len(tr) > 60:
        return slots
    slots += _zh_polarity_slot(tr, jf)
    slots += _zh_tense_slot(tr, jf)
    slots += _zh_role_slot(tr, jf)
    slots += _zh_comparative_slot(tr, jf)
    slots += _lex_table_slots(tr, jf, 'zh')
    return slots


def _zh_find_verb(tr):
    """找出可以挂否定的谓语位置，返回 (start, end, verb, kind)。认不出就 None。

    中文没有形态标记，这里只认四种高置信度结构：V了 / 助动词 / 代词+动词 /
    很+形容词。插入点前一个字是「地」「得」「把」「被」时一律放弃——
    那些位置插否定会造出病句（"把我不叫起来"）。
    """
    # 前一个字属于这些情况时，插入否定会把复合词/固定搭配劈开（入睡 → 入没睡）
    _COMPOUND_HEAD = set('入出上下起过過来來去回开開关關打拿放走跑坐站看听聽说說'
                         '做作吃喝买買卖賣学學工完成发發收送带帶找等叫问問答教睡'
                         '醒洗穿脱脫用花修想要会會能可以得')
    _NOT_BEFORE_SHI = set('总總就只真也还還於于可但倒要如而若凡')

    def _safe(pos):
        if pos == 0:
            return True
        prev = tr[pos - 1]
        return prev not in '地得把被不没沒别別很太将將' and prev not in _COMPOUND_HEAD

    # (a) 「V了」：了 前面紧挨着的动词
    for m in re.finditer(r'了', tr):
        for v in _ZH_VERBS:
            s = m.start() - len(v)
            if s >= 0 and tr[s:m.start()] == v and _safe(s):
                return (s, m.end(), v, 'le')
    # (b) 是 / 有：特事特办（不有 ✗ → 没有）；「总是／就是／要是」里的是不算谓语
    for v in ('是', '有'):
        i = tr.find(v)
        if i < 0 or not _safe(i):
            continue
        if i and tr[i - 1] in _NOT_BEFORE_SHI:
            continue
        if tr[i + 1:i + 2] in ('不', '没', '沒', '了'):
            continue
        return (i, i + len(v), v, 'be' if v == '是' else 'you')
    # (c) 助动词/心理动词：直接前缀「不」
    for v in _ZH_MODAL_NEGATABLE:
        i = tr.find(v)
        if i < 0 or not _safe(i):
            continue
        if i and tr[i - 1] in '一这這那每':
            continue          # 「一会儿」「这会儿」里的会不是助动词
        if v in ('会', '會') and tr[i + 1:i + 2] in ('儿', '兒'):
            continue
        return (i, i + len(v), v, 'modal')
    # (d) 代词/名词 + 动词
    for p in _ZH_PRON:
        i = tr.find(p)
        if i < 0:
            continue
        rest_at = i + len(p)
        for v in _ZH_VERBS:
            if tr.startswith(v, rest_at) and _safe(rest_at):
                return (rest_at, rest_at + len(v), v, 'verb')
    # (e) 「很/非常/太 + 形容词」；前面已经出现体标记「了」时，这多半是补语
    # （"留下了很深的印象"），改成「不深」会很生硬，放弃
    m = re.search(r'(很|非常|太)([\u4e00-\u9fff]{1,2})', tr)
    if m and '了' not in tr[:m.start()]:
        return (m.start(), m.end(), m.group(2), 'adj')
    return None


def _zh_polarity_slot(tr, jf):
    trad = _is_trad(tr)
    mei = '沒' if trad else '没'
    if not _zh_single_clause(tr) or _zh_imperative(tr):
        return []
    if re.search(r'[把被让讓使]', tr):
        # 把字句/被字句的否定要放到介词前面（"不把我叫起来"），规则引擎不冒这个险
        return []
    # (a) 译文是肯定的 → 造否定
    if not re.search(r'[不没沒未別别無无]', tr) and jf['neg_count'] == 0:
        got = _zh_find_verb(tr)
        if not got:
            return []
        s, e, v, kind = got
        ev = '日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事'
        # 句尾有语气/完成的「了」时，否定必须用「没」并把「了」一起去掉：
        # 「他来东京找工作了」→「他没来东京找工作」，而不是病句「他不来…了」。
        tail_le = re.search(r'了([。．.！!？?]*)$', tr)
        if tail_le and kind != 'le' and tail_le.start() > e:
            if kind in ('be', 'modal', 'adj'):
                return []      # 「是…了」「会…了」「很…了」情况太杂，不冒险
            new = mei + v
            return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                          [{'edits': [(s, e, new),
                                      (tail_le.start(), tail_le.start() + 1, '')],
                            'note': f'{tr[s:e]} → {new}（句尾「了」一并去掉）'}],
                          0.92, (s, tail_le.start() + 1))]
        if kind in ('le', 'you'):
            new = mei + v
        else:
            new = '不' + v
        return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                      [{'edits': [(s, e, new)], 'note': f'{tr[s:e]} → {new}'}],
                      0.95, (s, e))]
    # (b) 译文是否定的 → 去掉否定
    if jf['neg_count'] >= 1 and len(re.findall(r'[不没沒]', tr)) == 1:
        ev = '日文句尾谓语带否定形态素（ない／ません／ぬ），录音说的是「没有／不」'
        m = re.search(r'(没有|沒有)([\u4e00-\u9fff]{1,3})', tr)
        if m:
            new = m.group(2) + '了'
            return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                          [{'edits': [(m.start(), m.end(), new)],
                            'note': f'{m.group()} → {new}'}], 0.95, (m.start(), m.end()))]
        m = re.search(r'(不|没|沒)([\u4e00-\u9fff]{1,3})', tr)
        if m:
            new = m.group(2) + ('了' if m.group(1) in ('没', '沒') else '')
            return [_slot('polarity', '肯否（句子到底有没有否定）', ev,
                          [{'edits': [(m.start(), m.end(), new)],
                            'note': f'{m.group()} → {new}'}], 0.95, (m.start(), m.end()))]
    return []


def _zh_tense_slot(tr, jf):
    """中文时体：了/过（已然） ↔ 会/要（未然）。证据同英文，看日文「た」。"""
    trad = _is_trad(tr)
    hui = '會' if trad else '会'
    if not _zh_single_clause(tr) or _zh_imperative(tr):
        return []
    if jf['tail_past'] and jf['past_count'] >= 1 and '了' in tr:
        ev = '日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事'
        got = _zh_find_verb(tr)
        if got and got[3] == 'le':
            s, e, v, _ = got
            return [_slot('tense', '时制（已经发生 vs 还没发生）', ev,
                          [{'edits': [(s, e, hui + v)], 'note': f'{tr[s:e]} → {hui}{v}'}],
                          0.8, (s, e))]
    if not jf['tail_past'] and jf['past_count'] == 0:
        m = re.search(r'(会|會|要|将|將)([\u4e00-\u9fff]{1,3})', tr)
        if m and '了' not in tr:
            ev = '日文句里没有过去助動詞「た」，说的不是已经完成的事'
            new = m.group(2) + '了'
            return [_slot('tense', '时制（已经发生 vs 还没发生）', ev,
                          [{'edits': [(m.start(), m.end(), new)],
                            'note': f'{m.group()} → {new}'}], 0.8, (m.start(), m.end()))]
    return []


def _zh_role_slot(tr, jf):
    """中文施受互换：主语代词与宾语代词直接换位（中文代词无格变化，换位即改变施受）。"""
    if any(w in tr for w in _ZH_SYMMETRIC):
        return []
    if jf['passive'] or jf['causative'] or '被' in tr:
        return []
    pron_hits = []
    for p in _ZH_PRON:
        for m in re.finditer(re.escape(p), tr):
            if any(abs(m.start() - h[0]) < max(len(p), len(h[1])) for h in pron_hits):
                continue
            pron_hits.append((m.start(), p))
    pron_hits.sort()
    # 去掉「我们/我」这类包含关系的重复命中
    dedup = []
    for pos, p in pron_hits:
        if dedup and pos < dedup[-1][0] + len(dedup[-1][1]):
            continue
        dedup.append((pos, p))
    if len(dedup) != 2:
        return []
    (p1, w1), (p2, w2) = dedup
    if w1 == w2 or p1 != 0:
        return []
    if re.search(r'的$', tr[:p2]) or tr[p2 - 1:p2] == '的':
        return []
    k1 = _zh_pron_key(w1)
    k2 = _zh_pron_key(w2)
    if not k1 or not k2 or k1 == k2:
        return []
    jp1, jp2 = jf['pronouns'].get(k1), jf['pronouns'].get(k2)
    if not jp2 or not any(_role_of(p) == 'object' for p in jp2):
        return []
    if jp1 and not any(_role_of(p) == 'subject' for p in jp1):
        return []
    ev = '日文里表示对象的代词带「を／に」格助词，谁对谁做是显式的'
    edits = [(p1, p1 + len(w1), w2), (p2, p2 + len(w2), w1)]
    return [_slot('role', '施受关系（谁对谁做）', ev,
                  [{'edits': edits, 'note': f'{w1} ↔ {w2} 互换'}],
                  1.0, (p1, p2 + len(w2)))]


def _zh_pron_key(w):
    return {'我': '1sg', '你': '2sg', '他': '3sgm', '她': '3sgf',
            '我们': '1pl', '我們': '1pl', '他们': '3pl', '他們': '3pl',
            '她们': '3pl', '她們': '3pl'}.get(w)


def _zh_comparative_slot(tr, jf):
    """中文比较句：A 比 B … → B 比 A …。证据：日文「より」。"""
    if not jf['comparative'] or jf['superlative']:
        return []
    m = re.match(r'^([\u4e00-\u9fff]{1,6})比([\u4e00-\u9fff]{2,12}[了呢吧]?[。．.！!]?)$', tr)
    if not m:
        return []
    a, rest = m.group(1), m.group(2)
    # 中文没有词边界，「鯊魚的皮比鮪魚的皮粗糙」里 NP2 到哪结束只能靠对称性推断：
    # 只接受与 NP1 等长的切分（人称代词、平行名词短语），否则宁可不出题。
    b = rest[:len(a)]
    pred = rest[len(a):]
    if len(pred) < 1 or len(pred) > 6 or a == b:
        return []
    if re.search(r'[的了是在和跟与與]$', b) or b[0] in '很太更还還最':
        return []
    ev = '日文用「〜より」显式标出了比较的基准，互换两侧后意思相反'
    s2 = m.start(2)
    edits = [(m.start(1), m.end(1), b), (s2, s2 + len(b), a)]
    return [_slot('comparative', '比较方向（谁更…）', ev,
                  [{'edits': edits, 'note': f'{a} ↔ {b} 互换'}], 0.95,
                  (m.start(1), s2 + len(b)))]


# ================================================================
# 八、组装四个选项
# ================================================================
_AXIS_LABEL = {
    'polarity': '肯否', 'tense': '时制', 'role': '施受', 'direction': '起讫点',
    'comparative': '比较方向', 'conj': '分句逻辑', 'modal': '情态',
    'quant': '频度量化', 'place': '方位', 'number': '数量', 'time': '时间',
    'person': '人称',
}


def detect_lang(text):
    if re.search(r'[\u4e00-\u9fff]', text or ''):
        return 'zh'
    if re.search(r'[A-Za-z]', text or ''):
        return 'en'
    return 'other'


def _sane(option, answer, lang):
    """产出句的形式质检：不能和答案重复、不能出现明显病句痕迹、长度不能突变。"""
    if not option or option == answer:
        return False
    if lang == 'en':
        low = ' ' + option.lower() + ' '
        for bad in (' not not ', ' the the ', " didn't  ", ' to to ', ' a a ',
                    " don't not ", ' will will ', ' is is ', ' was was ',
                    ' not never ', ' never not '):
            if bad in low:
                return False
        if re.search(r"\b(didn't|doesn't|don't|will|can|must|may|should)\s+"
                     r"(is|are|was|were|has|had)\b", low):
            return False
        # 缩合形与人称必须一致：he'm / I're / they's 都是病句
        if re.search(r"\b(he|she|it)'(m|re|ve)\b|\bi'(s|re)\b"
                     r"|\b(we|they|you)'(m|s)\b", low):
            return False
        if re.search(r"\b(he|she|it)\s+(am|are|were|have|do)\b"
                     r"|\bi\s+(is|are|has)\b"
                     r"|\b(we|they|you)\s+(is|am|was|has)\b", low):
            return False
        if '  ' in option:
            return False
    else:
        if re.search(r'[不没沒][了着著过過]|把[不没沒]|地[不没沒]|得[不没沒]', option):
            return False
    ratio = len(option) / max(1, len(answer))
    return 0.55 <= ratio <= 1.8


def build_contrast(jp_text, translation, rng=None, min_quality=0.0):
    """核心入口：把一条真实译文改写成「四选一」的最小对立选项组。

    返回 None 表示这句话凑不出合格的对立组（缺日文侧证据、结构认不出、
    或者改写结果通不过形式质检）——调用方应当换一句，而不是降低门槛。
    """
    rng = rng or random
    jp_text = (jp_text or '').strip()
    tr = (translation or '').strip()
    if not jp_text or not tr:
        return None
    lang = detect_lang(tr)
    if lang == 'other':
        return None
    jf = jp_features(jp_text)
    if not jf['ok']:
        return None
    slots = _en_slots(tr, jf) if lang == 'en' else _zh_slots(tr, jf)
    slots = [s for s in slots if s['quality'] >= min_quality and s['alts']]
    if not slots:
        return None
    slots.sort(key=lambda s: (-s['quality'], s['span'][0]))
    tidy = _tidy_en if lang == 'en' else _tidy_zh

    # ---- 版式 1：2×2 矩阵（优先，两个轴都要听懂） ----
    for a in range(len(slots)):
        for b in range(a + 1, len(slots)):
            sa, sb_ = slots[a], slots[b]
            if sa['axis'] == sb_['axis']:
                continue
            # 否定 × 频度会叠出「always doesn't / 从不…不…」这种绕口的双重否定
            if {sa['axis'], sb_['axis']} == {'polarity', 'quant'}:
                continue
            alt_a, alt_b = sa['alts'][0], sb_['alts'][0]
            if not _edits_disjoint(alt_a['edits'], alt_b['edits']):
                continue
            o_a = tidy(_apply_edits(tr, alt_a['edits']))
            o_b = tidy(_apply_edits(tr, alt_b['edits']))
            o_ab = tidy(_apply_edits(tr, alt_a['edits'] + alt_b['edits']))
            opts = [tr, o_a, o_b, o_ab]
            if len(set(opts)) != 4:
                continue
            if not all(_sane(o, tr, lang) for o in opts[1:]):
                continue
            audit = [
                {'option': tr, 'is_answer': True, 'changes': []},
                {'option': o_a, 'is_answer': False,
                 'changes': [_chg(sa, alt_a)]},
                {'option': o_b, 'is_answer': False,
                 'changes': [_chg(sb_, alt_b)]},
                {'option': o_ab, 'is_answer': False,
                 'changes': [_chg(sa, alt_a), _chg(sb_, alt_b)]},
            ]
            order = list(range(4))
            rng.shuffle(order)
            return {
                'lang': lang, 'answer': tr, 'structure': 'matrix_2x2',
                'axes': [sa['axis'], sb_['axis']],
                'axis_labels': [sa['label'], sb_['label']],
                'options': [opts[i] for i in order],
                'audit': [audit[i] for i in order],
                'evidence': [sa['evidence'], sb_['evidence']],
            }

    # ---- 版式 2：同一槽位四个互斥取值 ----
    for s in slots:
        if len(s['alts']) < 3:
            continue
        opts, audit, used_groups = [tr], [{'option': tr, 'is_answer': True, 'changes': []}], set()
        for alt in s['alts']:
            # 四个选项里出现两个近义值（although / even though）等于白送一次排除
            group = _synonym_group(alt['edits'][0][2])
            if group in used_groups:
                continue
            o = tidy(_apply_edits(tr, alt['edits']))
            if not _sane(o, tr, lang) or o in opts:
                continue
            used_groups.add(group)
            opts.append(o)
            audit.append({'option': o, 'is_answer': False, 'changes': [_chg(s, alt)]})
            if len(opts) == 4:
                break
        if len(opts) != 4:
            continue
        order = list(range(4))
        rng.shuffle(order)
        return {
            'lang': lang, 'answer': tr, 'structure': 'four_way_slot',
            'axes': [s['axis']], 'axis_labels': [s['label']],
            'options': [opts[i] for i in order],
            'audit': [audit[i] for i in order],
            'evidence': [s['evidence']],
        }
    return None


_SYNONYM_GROUPS = [
    {'although', 'even though', 'though'}, {'must', 'have to', 'has to'},
    {'may', 'can'}, {'want to', 'wants to'}, {'never', 'rarely', 'seldom'},
    {'often', 'frequently', 'usually'}, {'sometimes', 'occasionally'},
    {'a little', 'only a few', 'few'}, {'虽然', '雖然'}, {'因为', '因為'},
    {'必须', '必須'}, {'可以', '能'}, {'想', '想要'}, {'从不', '從不'},
    {'总是', '總是', '一直'}, {'有时', '有時', '偶尔', '偶爾'},
    {'之后', '之後', '以后', '以後'}, {'之前', '以前'},
    {'即使', '就算', '哪怕'}, {'如果', '要是'},
]


def _synonym_group(word):
    low = (word or '').strip().lower()
    for i, g in enumerate(_SYNONYM_GROUPS):
        if low in g:
            return i
    return low


def _chg(slot, alt):
    return {'axis': slot['axis'], 'axis_label': _AXIS_LABEL.get(slot['axis'], slot['axis']),
            'label': slot['label'], 'note': alt['note'], 'evidence': slot['evidence']}


def diff_marks(answer, option):
    """给前端做差异高亮：返回 option 里与答案不同的片段 [(start, end)]。"""
    from difflib import SequenceMatcher
    sm = SequenceMatcher(None, answer, option, autojunk=False)
    return [(j1, j2) for tag, i1, i2, j1, j2 in sm.get_opcodes()
            if tag in ('replace', 'insert')]

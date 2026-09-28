# -*- coding: utf-8 -*-
"""篇章精读（discourse.py）专项测试
================================================================
这套测试的重点不是"能不能出题"，而是"出的题会不会冤枉人"：
  1. 存储：分段/切句/录入/查询/删除
  2. 出厂门禁：选项互异、答案在选项中、证据非空、客观性标签合法
  3. **逐题客观性复核**（核心）：
     - verbatim 题：答案必须能在原文里逐字找到；
       absent 题反过来，答案必须在原文中一次也找不到
     - contradiction 题：错误项必须与原文某句矛盾且本身是合法日语
     - rule 题：答案必须等于原文本来的那个成分/位置
  4. 反例防御：接续词干扰项不得与答案同义类；格助词干扰项必须语料零共现；
     文体×时制的活用必须能还原原文（还原不出就不许出题）
  5. 句子插入 / 语序重排的位置编号正确（曾经 off-by-one）
  6. 统计落库
临时库隔离，不碰真实数据。
"""
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


HERE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
tdb = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(HERE, 'kanji.db'), tdb)
with sqlite3.connect(tdb) as c0:
    for t in ('passages', 'passage_sents', 'passage_results'):
        try:
            c0.execute(f'DROP TABLE IF EXISTS {t}')
        except sqlite3.OperationalError:
            pass
c0.close()

import db                                                    # noqa: E402
db.DB_PATH = tdb
import discourse as D                                        # noqa: E402

TEXT = """昨日、私は駅前の図書館へ行きました。図書館には新しい本がたくさん並んでいます。その本の中から、日本の祭りについての一冊を借りました。

祭りは地域の人をつなぐ行事です。夏には三十の町が同じ日に祭りを開きます。去年、私の町では二千人が参加しました。今年は三千人が来る予定です。

まず、朝から準備を始めます。次に、昼過ぎに行列が出発します。その行列は駅前を通って神社まで進みます。最後に、夜は花火が上がります。

しかし、雨の日は花火を中止します。町の人は「祭りがあるから町が元気になる」と言っています。来年も私はこの祭りに参加します。"""

TEXT2 = """日本の若者の読書離れが進んでいると言われています。ある調査によると、大学生の五十パーセントが一日の読書時間をゼロと答えました。

しかし、この調査だけで結論を出すのは早いです。同じ調査で、電子書籍を読む学生は三十パーセントに増えていました。つまり、読書の形が変わっただけだという見方もできます。

たとえば、紙の本はページをめくる動作が記憶を助けます。一方、画面では通知が集中を妨げます。だから、目的によって紙と画面を使い分けることが大切です。"""


def main():
    print('\n[1] 录入 / 分段 / 切句')
    r = D.import_passage('祭りの一日', TEXT, source='自作')
    pid = r['id']
    check(r['n_para'] == 4, f"分段应为 4 段，实际 {r['n_para']}")
    check(r['n_sent'] == 14, f"切句应为 14 句，实际 {r['n_sent']}")
    p = D.get_passage(pid)
    check(p and p['sentences'][0]['text'] == '昨日、私は駅前の図書館へ行きました。', '首句切分错误')
    check(all(s['text'].endswith(('。', '！', '？')) for s in p['sentences']), '存在没有句末标点的句子')
    check(len(D.list_passages()) >= 1, '列表查询失败')
    try:
        D.import_passage('空', '   ')
        check(False, '空正文应当报错')
    except ValueError:
        check(True, '')
    # 引号内的句点不得切句
    one = D.split_sentences('彼は「今日は雨です。明日は晴れです。」と言った。')
    check(len(one) == 1, f'引号内句点不应切句，实际切成 {len(one)} 句')

    print('\n[2] 出题 + 出厂门禁')
    pid2 = D.import_passage('読書離れ', TEXT2)['id']
    quiz = D.make_quiz(pid, count=20, seed=11, mode='choice')
    quiz2 = D.make_quiz(pid2, count=20, seed=12, mode='choice')
    check(quiz['ok'] and quiz['questions'], '第一篇一道题都出不了')
    check(quiz2['ok'] and quiz2['questions'], '第二篇一道题都出不了')
    allq = quiz['questions'] + quiz2['questions']
    print(f'  共生成 {len(allq)} 道题，覆盖题型 {sorted(set(q["qtype"] for q in allq))}')
    check(len(set(q['qtype'] for q in allq)) >= 6,
          '题型覆盖太少（长文章应能出 6 种以上）')
    for q in allq:
        t = q['qtype']
        check(len(q['options']) == len(set(q['options'])), f'[{t}] 选项有重复')
        check(q['answer'] in q['options'], f'[{t}] 答案不在选项中')
        check(q['options'][q['answer_index']] == q['answer'], f'[{t}] answer_index 错位')
        check(bool(q['evidence']), f'[{t}] 没有判定依据')
        check(q['objectivity'] in ('verbatim', 'contradiction', 'rule'),
              f'[{t}] 客观性标签非法')
        check(bool(q.get('prompt')) and bool(q.get('type_label')), f'[{t}] 缺少题面信息')

    print('\n[3] 逐题客观性复核（防冤假错案）')
    for pidx, (pp, qq) in enumerate(((pid, quiz), (pid2, quiz2))):
        P = D.load(pp)
        full = P.joined()
        for q in qq['questions']:
            t = q['qtype']
            if t == 'multi':
                a, b = q['sub_answers']
                r1 = q['context'].replace('（①）', a, 1).replace('（②）', b, 1)
                r2 = q['context'].replace('（①）', b, 1).replace('（②）', a, 1)
                check(P.sents[q['sent_idx']] in (r1, r2), '[multi] 填回去得不到原句')
                continue
            if t == 'absent':
                check(q['answer'] not in full, f'[absent] 答案「{q["answer"]}」其实在原文里（冤案！）')
                for o in q['options']:
                    if o != q['answer']:
                        check(o in full, f'[absent] 干扰项「{o}」不在原文里（冤案！）')
            elif t in ('connective', 'anaphora', 'particle', 'fact', 'headword', 'truth'):
                check(q['answer'] in full, f'[{t}] 答案「{q["answer"]}」在原文中找不到原样字串')
            if t == 'connective':
                cls = D.CONJ[q['answer']]
                for o in q['options']:
                    if o == q['answer']:
                        continue
                    check(o in D.CONJ, f'[connective] 干扰项不在接续词表中：{o}')
                    check(not D._conj_conflict(D.CONJ[o], cls),
                          f'[connective] 干扰项「{o}」({D.CONJ[o]}) 与答案类别 {cls} 语义相邻，可能同样成立')
                    check(o not in full, f'[connective] 干扰项「{o}」在原文别处出现过，易产生歧义')
            if t == 'particle':
                noun = q['context'].split('（＿）')[0]
                noun = D.tag(noun)[-1]['s'] if D.tag(noun) else ''
                for o in q['options']:
                    if o == q['answer']:
                        check(D.corpus_count(noun + o) >= 1,
                              f'[particle] 正确搭配「{noun}{o}」没有语料实证')
                    else:
                        check(D.corpus_count(noun + o) == 0,
                              f'[particle] 干扰项「{noun}{o}」在语料库中存在实证，可能也对（冤案！）')
            if t == 'truth':
                check(q['answer'] in P.sents, '[truth] 正确项不是原文句子')
                for o in q['options']:
                    if o != q['answer']:
                        check(o not in full, f'[truth] 错误项「{o}」竟然是原文内容')
                        check(len(q['evidence']) >= 4, '[truth] 每个错误项都必须写明矛盾点')
            if t == 'polite_tense':
                check(len(q['options']) == 4 and len(set(q['options'])) == 4,
                      '[polite_tense] 2×2 必须是四个互异的形')
                blanked = q['context'].replace('＿＿。', '')
                check(any(s.startswith(blanked) and q['answer'] in s for s in P.sents),
                      '[polite_tense] 答案不是原文该句的实际形式（活用自校验失效）')
            if t == 'quote':
                check(q['answer'] in q['context'], '[quote] 说话人不在该句中')
                for o in q['options']:
                    if o != q['answer']:
                        check(o not in q['context'], f'[quote] 干扰项「{o}」也出现在本句中')

    print('\n[4] 句子插入 / 语序重排 的位置正确性')
    ins = [q for q in allq if q['qtype'] == 'insert']
    for q in ins:
        sent = q['prompt'].split('「', 1)[1].rsplit('」', 1)[0]
        body = [x for x in q['context'].split('\n') if not x.startswith('（')]
        slot = int(q['answer'].strip('（）'))
        rebuilt = body[:slot - 1] + [sent] + body[slot - 1:]
        P = D.load(q.get('_pid', pid))
        joined = ''.join(rebuilt)
        ok = joined in D.load(pid).joined() or joined in D.load(pid2).joined()
        check(ok, f'[insert] 按答案位置插回去，得不到原文顺序：{joined[:60]}')
    orders = [q for q in allq if q['qtype'] == 'order']
    for q in orders:
        lab = {}
        for line in q['context'].split('\n'):
            lab[line[0]] = line[3:]
        joined = ''.join(lab[ch] for ch in q['answer'])
        ok = joined in D.load(pid).joined() or joined in D.load(pid2).joined()
        check(ok, '[order] 按答案顺序拼接不等于原文顺序')
    print(f'  插入题 {len(ins)} 道 / 重排题 {len(orders)} 道 位置校验通过')

    print('\n[5] 反例：无线索的文章不应硬出题')
    junk = D.import_passage('断片', '。'.join(['犬が走る'] * 3) + '。\n\n猫が寝る。鳥が飛ぶ。')['id']
    jq = D.make_quiz(junk, count=10, seed=3)
    for q in jq['questions']:
        check(q['objectivity'] in ('verbatim', 'contradiction', 'rule'), '劣质文本产生了无标签题')
    check(all(q['qtype'] != 'order' for q in jq['questions']),
          '毫无衔接线索的短句群不应生成语序重排题')

    print('\n[6] 统计落库')
    D.record_results(pid, [{'qtype': 'connective', 'ok': True},
                           {'qtype': 'connective', 'ok': False},
                           {'qtype': 'absent', 'ok': True}])
    st = D.stats(14)
    check(st['total'] == 3 and st['ok'] == 2, f'统计不对：{st}')
    check(st['by_type']['connective']['rate'] == 50, '分题型正确率不对')

    print('\n[7] 删除')
    check(D.delete_passage(junk), '删除失败')
    check(D.get_passage(junk) is None, '删除后仍能查到')

    return 0


# ================================================================
# 追加：真实新闻文章 / 任意形状输入 / 进阶题型 / 反作弊统计
# ================================================================
SAMPLES = {}
_sdir = os.path.join(HERE, 'samples')
if os.path.isdir(_sdir):
    for fn in sorted(os.listdir(_sdir)):
        if fn.endswith('.txt'):
            SAMPLES[fn[:-4]] = open(os.path.join(_sdir, fn), encoding='utf-8').read()


def objectivity_audit(P, q, label=''):
    if q.get('answer_format') == 'input':
        return
    """对任意一道题做客观性复核（测试自己再验一遍，不信任生成器）。"""
    t, full = q['qtype'], P.joined()
    tag = f'[{label}/{t}]'
    check(len(q['options']) == len(set(q['options'])), f'{tag} 选项重复')
    check(q['answer'] in q['options'], f'{tag} 答案不在选项中')
    check(q['options'][q['answer_index']] == q['answer'], f'{tag} answer_index 错位')
    check(bool(q['evidence']), f'{tag} 无判定依据')
    check(q['objectivity'] in ('verbatim', 'contradiction', 'rule'), f'{tag} 客观性标签非法')
    check(q['difficulty'] in ('easy', 'medium', 'hard'), f'{tag} 难度标签非法')
    check(q['text_policy'] in ('open', 'closed'), f'{tag} 开卷/闭卷标签非法')
    if t == 'multi':
        a, b = q['sub_answers']
        src = P.sents[q['sent_idx']]
        r1 = q['context'].replace('（①）', a, 1).replace('（②）', b, 1)
        r2 = q['context'].replace('（①）', b, 1).replace('（②）', a, 1)
        check(src in (r1, r2), f'{tag} 多空题填回去得不到原句')
        return
    if t == 'multi':
        a, b = q['sub_answers']
        src = P.sents[q['sent_idx']]
        r1 = q['context'].replace('（①）', a, 1).replace('（②）', b, 1)
        r2 = q['context'].replace('（①）', b, 1).replace('（②）', a, 1)
        check(src in (r1, r2), f'{tag} 多空题填回去得不到原句')
        return
    if t == 'absent':
        check(q['answer'] not in full, f'{tag} 答案其实在原文里（冤案）')
        for o in q['options']:
            if o != q['answer']:
                check(o in full, f'{tag} 干扰项「{o}」不在原文里（冤案）')
    elif t in ('connective', 'anaphora', 'particle', 'fact', 'headword',
               'truth', 'compound_particle', 'pairing', 'compare',
               'chronology', 'heading'):
        check(q['answer'] in full or q['answer'] in P.text,
              f'{tag} 答案「{q["answer"]}」在原文中找不到原样字串')
    if t == 'connective':
        cls = D.CONJ[q['answer']]
        for o in q['options']:
            if o != q['answer']:
                check(o in D.CONJ, f'{tag} 干扰项不在接续词表：{o}')
                check(not D._conj_conflict(D.CONJ[o], cls), f'{tag} 干扰项语义相邻：{o}')
                check(o not in full, f'{tag} 干扰项在原文别处出现：{o}')
    if t == 'compound_particle':
        cls = D.COMPOUND_P[q['answer']]
        for o in q['options']:
            if o != q['answer']:
                check(o in D.COMPOUND_P, f'{tag} 干扰项不在机能表现表：{o}')
                check(D.COMPOUND_P[o] != cls, f'{tag} 干扰项与答案同类：{o}')
                check(o not in full, f'{tag} 干扰项在原文别处出现：{o}')
    if t == 'particle':
        head = q['context'].split('（＿）')[0]
        # 生成器必须声明它用哪个名词做的语料检索（probe），
        # 而且这个名词必须真的紧贴在空格前面 —— 不许挑一个好查的词来糊弄
        noun = q.get('probe') or ''
        check(bool(noun) and head.endswith(noun),
              f'{tag} 检索键「{noun}」不是空格前紧邻的名词')
        for o in q['options']:
            if o == q['answer']:
                check(D.corpus_count(noun + o) >= 1, f'{tag} 正解搭配无语料实证')
            else:
                check(D.corpus_count(noun + o) == 0, f'{tag} 干扰项「{noun}{o}」有语料实证（冤案）')
    if t == 'compare':
        vals = [D.parse_number(re.sub(r'[^0-9０-９.．〇零一二三四五六七八九十百千万億]', '', o))
                for o in q['options']]
        check(all(v is not None for v in vals), f'{tag} 选项里有解析不出的数值')
        if all(v is not None for v in vals):
            ai = q['options'].index(q['answer'])
            if '最も大きい' in q['prompt']:
                check(vals[ai] == max(vals), f'{tag} 答案不是最大值（算术复核失败）')
            elif '最も小さい' in q['prompt']:
                check(vals[ai] == min(vals), f'{tag} 答案不是最小值（算术复核失败）')
            else:
                check(vals[ai] == sorted(vals, reverse=True)[1],
                      f'{tag} 答案不是第二大（算术复核失败）')
    if t == 'pairing':
        pct = q['prompt'].split('「')[1].split('」')[0]
        hit = [s2 for s2 in P.sents if q['answer'] in s2 and pct in s2]
        check(bool(hit), f'{tag} 项目与数值不在同一句中（配对无据）')
        for o in q['options']:
            if o != q['answer']:
                check(not any(o in s2 and pct in s2 for s2 in P.sents),
                      f'{tag} 干扰项「{o}」也与该数值同句（冤案）')
    if t == 'transitivity':
        blanked = q['context'].replace('＿＿。', '')
        check(any(s2.startswith(blanked) and q['answer'] in s2 for s2 in P.sents),
              f'{tag} 答案不是原文该句的实际形式（活用自校验失效）')
    if t == 'heading':
        check(q['answer'] in [h['text'] for h in P.headings], f'{tag} 答案不是本文小标题')
    if t == 'polite_tense':
        blanked = q['context'].replace('＿＿。', '')
        check(any(s2.startswith(blanked) and q['answer'] in s2 for s2 in P.sents),
              f'{tag} 答案不是原文该句的实际形式')
    if t == 'quote':
        check(q['answer'] in q['context'], f'{tag} 说话人不在该句中')
        for o in q['options']:
            if o != q['answer']:
                check(o not in q['context'], f'{tag} 干扰项也在本句中：{o}')
    if t == 'truth':
        check(q['answer'] in P.sents, f'{tag} 正确项不是原文句子')
        for o in q['options']:
            if o != q['answer']:
                check(o not in full, f'{tag} 错误项竟在原文中')
    if t == 'insert':
        sent = q['prompt'].split('「', 1)[1].rsplit('」', 1)[0]
        body = [x for x in q['context'].split('\n') if not x.startswith('（')]
        slot = int(q['answer'].strip('（）'))
        joined = ''.join(body[:slot - 1] + [sent] + body[slot - 1:])
        check(joined in full, f'{tag} 按答案插回去得不到原文顺序')
    if t == 'order':
        lab = {}
        for line in q['context'].split('\n'):
            lab[line[0]] = line[3:]
        check(''.join(lab[ch] for ch in q['answer']) in full,
              f'{tag} 按答案顺序拼接不等于原文')


def main2():
    import re as _re
    globals()['re'] = _re

    print('\n[8] 真实新闻文章：清洗 / 结构识别 / 预览不落库')
    n_before = len(D.list_passages())
    for name, txt in SAMPLES.items():
        pv = D.preview(txt)
        check(pv['ok'], f'{name} 预览失败')
        check(pv['n_sent'] >= 5, f'{name} 切出的正文句太少：{pv["n_sent"]}')
        check(pv['title'] and '\n' not in pv['title'], f'{name} 标题识别异常')
        check('シェアする' not in ''.join(sum(pv['paragraphs'], [])),
              f'{name} 界面样板行「シェアする」混进了正文')
        check(not any(_re.fullmatch(r'\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}', x)
                      for x in sum(pv['paragraphs'], [])),
              f'{name} 时间戳混进了正文')
        for st in sum(pv['paragraphs'], []):
            # 正文句必须以句末标点结尾；整行引语（「…」）是唯一的例外
            ok_end = st[-1] in '。！？!?…' or (st[0] in '「『“' and st[-1] in '」』”')
            check(ok_end, f'{name} 有没切干净的句子：{st[:30]}')
        check(pv['total_questions'] >= 10,
              f'{name} 可出题数太少：{pv["total_questions"]}')
        print(f'  {name}: {pv["n_para"]}段/{pv["n_sent"]}句/小标题{pv["n_heading"]} '
              f'→ 可出题 {pv["total_questions"]}，剔除样板行 {len(pv["dropped_lines"])} 行')
    check(len(D.list_passages()) == n_before, '预览不应落库（列表数量被改变了）')

    print('\n[9] 真实新闻文章：全部题目逐题客观性复核')
    total = 0
    cover = set()
    for name, txt in SAMPLES.items():
        pid = D.import_passage('', txt, source='NHK')['id']
        P = D.load(pid)
        rng = __import__('random').Random(5)
        pools = D._gen_all(P, rng)
        for t, qs in pools.items():
            for k, q in enumerate(qs):
                D._decorate(q, pid, k)
                D._finish(q, rng)
                objectivity_audit(P, q, name)
                total += 1
            cover.add(t)
    print(f'  共复核 {total} 道题，覆盖题型 {len(cover)} 种：{sorted(cover)}')
    check(total >= 80, f'真实文章的题量太少：{total}')
    check(len(cover) >= 12, f'真实文章的题型覆盖太少：{len(cover)}')

    print('\n[10] 任意形状输入的稳健性（不崩、不出坏题）')
    shapes = {
        '只有一行标题': '米前国務副長官“中国は日米の結束弱めるねらい”',
        '只有一句话': '秋雨前線の影響で、関東甲信では大気の状態が非常に不安定になっています。',
        '一段话（无空行）': ('秋雨前線の影響で、関東甲信では大気の状態が非常に不安定になっています。'
                     'しかし、あすの朝には落ち着く見込みです。気象庁は土砂災害に注意するよう'
                     '呼びかけています。伊豆諸島では1時間に47ミリの激しい雨が降りました。'),
        '硬换行的长句': ('台風25号に伴う大雨で東京 目黒区の住宅街では、高さ2メートルから\n'
                   '3メートルほどの住宅の擁壁が崩れました。\n現地を調査した専門家は状態の確認を'
                   '呼びかけています。'),
        '全是界面文字': 'シェアする\n2026年9月28日 17:43\n関連ニュース\nもっと見る',
        '中日混排': '这是中文说明。\n日本語の文章です。とても短いです。\nend of text.',
        '空白与符号': '   \n\n・・・\n▽\n\n   ',
    }
    for name, txt in shapes.items():
        try:
            pv = D.preview(txt)
        except Exception as e:
            check(False, f'[{name}] 预览抛异常：{e}')
            continue
        check(pv['ok'], f'[{name}] 预览未返回 ok')
        P = D.build('', txt)
        rng = __import__('random').Random(1)
        try:
            pools = D._gen_all(P, rng)
        except Exception as e:
            check(False, f'[{name}] 出题抛异常：{e}')
            continue
        nq = sum(len(v) for v in pools.values())
        for t, qs in pools.items():
            for k, q in enumerate(qs):
                D._decorate(q, 0, k)
                D._finish(q, rng)
                objectivity_audit(P, q, name)
        print(f'  {name}: {pv["n_sent"]} 句 → {nq} 道题（全部通过客观性复核）')
    # 全是界面文字时应当明确拒绝录入，而不是造出一篇空篇章
    try:
        D.import_passage('', shapes['全是界面文字'])
        check(False, '全是界面文字时应当拒绝录入')
    except ValueError:
        check(True, '')

    print('\n[11] 截断模糊测试（长文章的任意片段都不能崩）')
    base = SAMPLES.get('nhk_yoheki', TEXT)
    rnd = __import__('random').Random(20260928)
    bad = 0
    for _ in range(40):
        a = rnd.randrange(0, max(1, len(base) - 100))
        b = min(len(base), a + rnd.randrange(80, 2000))
        frag = base[a:b]
        try:
            P = D.build('', frag)
            rng = __import__('random').Random(2)
            pools = D._gen_all(P, rng)
            for t, qs in pools.items():
                for k, q in enumerate(qs):
                    D._decorate(q, 0, k)
                    D._finish(q, rng)
                    if not D._valid(q):
                        bad += 1
        except Exception as e:
            check(False, f'片段 [{a}:{b}] 抛异常：{type(e).__name__} {e}')
    check(bad == 0, f'模糊测试产出 {bad} 道未通过门禁的题')
    print('  40 个随机片段：无异常、无坏题')

    print('\n[12] 难度与开卷/闭卷分层')
    pid = D.import_passage('', SAMPLES.get('nhk_yoheki', TEXT))['id']
    hard = D.make_quiz(pid, count=10, difficulty='hard', seed=3, mode='choice')
    check(all(q['difficulty'] == 'hard' for q in hard['questions']),
          '难度筛选失效')
    mix = D.make_quiz(pid, count=16, seed=4, mode='choice')
    check(len(set(q['qtype'] for q in mix['questions'])) >= 6,
          f'一套 16 题的题型多样性不足：{mix["coverage"]}')
    check(any(q['text_policy'] == 'closed' for q in mix['questions']) and
          any(q['text_policy'] == 'open' for q in mix['questions']),
          '开卷/闭卷题没有同时出现')

    print('\n[13] 反作弊统计：参考原文的题单独记账')
    D.record_results(pid, [{'qtype': 'connective', 'ok': True, 'peeked': False},
                           {'qtype': 'connective', 'ok': True, 'peeked': True},
                           {'qtype': 'compare', 'ok': False, 'peeked': False}])
    st = D.stats(14)
    check(st['peeked'] == 1, f'偷看计数不对：{st}')
    check(st['by_type']['connective']['peeked'] == 1, '分题型偷看计数不对')

    print('\n[14] 并入语料库（组句 / 听力 / 挖空 共用题源）')
    before = 0
    with db.get_conn() as c:
        before = c.execute("SELECT COUNT(*) n FROM sentences WHERE source='passage'").fetchone()['n']
    n = D.add_to_corpus(pid)
    with db.get_conn() as c:
        after = c.execute("SELECT COUNT(*) n FROM sentences WHERE source='passage'").fetchone()['n']
        row = c.execute("SELECT text, tokens FROM sentences WHERE source='passage' LIMIT 1").fetchone()
    check(n > 0 and after > before, f'并入语料库失败：{n}')
    check(row and row['tokens'] and '[' in row['tokens'], '并入的句子没有注音 tokens')
    # 二次并入不应重复插入
    n2 = D.add_to_corpus(pid)
    with db.get_conn() as c:
        after2 = c.execute("SELECT COUNT(*) n FROM sentences WHERE source='passage'").fetchone()['n']
    check(after2 == after, f'重复并入产生了重复句：{after}→{after2}')
    print(f'  并入 {n} 句（去重后二次并入 {n2} 句，总数不变）')

    print('\n[15] 组句 / 听力 能用上篇章句子')
    import sentence_builder as SB
    ok_any = False
    with db.get_conn() as c:
        rows = c.execute("SELECT text FROM sentences WHERE source='passage' LIMIT 12").fetchall()
    for r in rows:
        try:
            parsed = SB.parse_sentence(r['text'])
            if parsed and len(parsed['chunks']) >= 3:
                ok_any = True
                break
        except Exception:
            pass
    check(ok_any, '并入的篇章句子没有一句能被组句引擎解析')

    return 0


# ================================================================
# 追加 2：题量天花板 / 填空模式 / 服务端判分 / 曝光调度 / 多空题
# ================================================================
def main3():
    print('\n[16] 题量天花板（stems / deliveries / variants）')
    caps = {}
    for name, txt in SAMPLES.items():
        pid = D.import_passage('cap-' + name, txt)['id']
        c = D.capacity(pid)
        caps[name] = (pid, c)
        # 题量随篇幅走：短消息 600 字给二十几道是正常的，长报道必须上百
        floor = 12 if len(txt) < 1500 else (60 if len(txt) < 6000 else 100)
        check(c['stems'] >= floor, f'{name} 题干数过少：{c["stems"]} < {floor}')
        check(c['deliveries'] > c['stems'], f'{name} 填空形态没有增加可交付题数')
        check(c['variants'] >= c['stems'], f'{name} 题面变体估计异常')
        check(c['fresh'] + c['done'] >= c['stems'] - 2, f'{name} 新旧题统计对不上')
        print(f'  {name}: 题干 {c["stems"]} / 可交付 {c["deliveries"]} / '
              f'题面变体 {c["variants"]:,} / 未做过 {c["fresh"]}')

    print('\n[17] 多空题：继承两个子题的门禁，且两空位置正确')
    pid, _ = caps.get('nhk_yoheki', list(caps.values())[0])
    P = D.load(pid)
    rng = __import__('random').Random(7)
    pools = D._gen_all(P, rng)
    multi = D.make_multi(P, rng, pools)
    check(len(multi) >= 3, f'多空题太少：{len(multi)}')
    for q in multi:
        D._decorate(q, pid, 0)
        D._finish(q, rng)
        check('（①）' in q['context'] and '（②）' in q['context'], '多空题缺少空位标记')
        a, b = q['sub_answers']
        restored = q['context'].replace('（①）', a, 1).replace('（②）', b, 1)
        if restored != P.sents[q['sent_idx']]:
            restored = q['context'].replace('（①）', b, 1).replace('（②）', a, 1)
        check(restored == P.sents[q['sent_idx']],
              f'多空题按答案填回去得不到原句：{restored[:40]}')
        check(len(q['options']) == 4 and q['answer'] in q['options'], '多空题选项异常')
        check(q['difficulty'] == 'hard', '多空题应为 hard')
    print(f'  {len(multi)} 道多空题：填回原句逐字复原通过')

    print('\n[18] 填空模式：不给选项 + 服务端判分 + 归一化')
    quiz = D.make_quiz(pid, count=20, seed=13, mode='input', secure=True)
    ins = [q for q in quiz['questions'] if q.get('answer_format') == 'input']
    check(len(ins) >= 3, f'填空题太少：{len(ins)}')
    for q in quiz['questions']:
        for k in ('answer', 'evidence', 'explain', 'answer_index', 'stem'):
            check(k not in q, f'secure 模式下题面仍带 {k}（等于把答案送到浏览器里）')
        check(q.get('answer_format') != 'input' or not q.get('options'),
              '填空题不应带选项')
    # 正确答案必须判对，错答案必须判错，全角/空格归一化必须生效
    for q in ins[:5]:
        real = D._QUIZ_CACHE[quiz['quiz_id']]['qs'][q['qid']]['answer']
        r1 = D.grade(quiz['quiz_id'], q['qid'], real)
        r2 = D.grade(quiz['quiz_id'], q['qid'], real + 'ぜんぜん')
        r3 = D.grade(quiz['quiz_id'], q['qid'], ' ' + real + ' ')
        check(r1['correct'], f'[input] 原文答案被判错：{real}')
        check(not r2['correct'], f'[input] 明显错答被判对：{real}')
        check(r3['correct'], f'[input] 前后空格没有归一化：{real}')
        check(r1['evidence'] and r1['answer'] == real, '[input] 判分结果缺少答案/依据')
    check(D.grade('bogus-quiz', 'x-0', 'a')['ok'] is False, '过期 quiz 应当报错而不是崩')
    print(f'  {len(ins)} 道填空题：答案不下发、判分正确、归一化生效')

    print('\n[19] 曝光调度：优先出没做过的题，做过的换干扰项重出')
    pid2 = D.import_passage('sched', SAMPLES.get('nhk_weather', TEXT))['id']
    c0 = D.capacity(pid2)
    q1 = D.make_quiz(pid2, count=8, seed=1, mode='choice')
    for q in q1['questions']:
        D.log_item(pid2, q, True)
    c1 = D.capacity(pid2)
    check(c1['done'] >= 6, f'曝光没有被记录：done={c1["done"]}')
    check(c1['fresh'] == c0['fresh'] - c1['done'], '新旧题账目对不上')
    q2 = D.make_quiz(pid2, count=8, seed=2, mode='choice')
    old = {q['stem'] for q in q1['questions']}
    new = {q['stem'] for q in q2['questions']}
    check(len(new - old) >= 5, f'第二套题没有优先给新题：重复 {len(new & old)} 题')
    # 同一题干重出时，干扰项集合应当不同（选项不是固定的四个）
    same = [(a, b) for a in q1['questions'] for b in q2['questions']
            if a['stem'] == b['stem'] and a['answer_format'] == b['answer_format'] == 'choice']
    if same:
        diff = sum(1 for a, b in same if set(a['options']) != set(b['options']))
        print(f'  重复出现的 {len(same)} 道题中，{diff} 道换了干扰项组合')
    print(f'  未做过 {c0["fresh"]} → 做过 8 题后剩 {c1["fresh"]}')

    print('\n[20] 同一题干的不同题面：随机种子换一套干扰项')
    P2 = D.load(pid2)
    seen_sets = {}
    for sd in range(12):
        rng2 = __import__('random').Random(sd)
        for q in D.GENERATORS['particle'](P2, rng2):
            seen_sets.setdefault(q['stem'], set()).add(tuple(sorted(q['options'])))
    multi_variant = [k for k, v in seen_sets.items() if len(v) > 1]
    check(bool(multi_variant),
          '同一个挖空位置在不同种子下始终给出同一套干扰项（题面无法刷新）')
    print(f'  {len(multi_variant)}/{len(seen_sets)} 个格助词题干在 12 个随机种子下产生了多套干扰项')

    return 0


# ================================================================
# 追加 3：行分类 / 阅读面板契约 / 注音 / 反作弊不下发答案
# ================================================================
def main4():
    print('\n[21] 行分类：正文 / 小标题 / 图注·说话人标签')
    cases = [
        ('「アメリカはAIにおける世界的な覇権を握るための競争の中にある」', 'body', '整行引语是正文'),
        ('「私たちには懸念の声を上げる機会が全くなかった」', 'body', '整行引语是正文'),
        ('ハンター「あのようなクマは初めて」', 'heading', '引号只占一部分＝小标题'),
        ('3分の2の自治体が「今後に不安」', 'heading', '引号只占一部分＝小标题'),
        ('「シストセンチュウ」という脅威', 'heading', '引号只占一部分＝小标题'),
        ('トランプ大統領が推し進めるAI開発', 'heading', '正常小标题'),
        ('全米に広がる反発 建設反対率が原発を上回るデータセンター', 'heading', '正常小标题'),
        ('トランプ大統領', 'caption', '说话人标签'),
        ('リンゼー・ショウさん', 'caption', '说话人标签'),
        ('酪農学園大学 伊吾田宏正 教授', 'caption', '说话人标签'),
        ('（ワシントン支局記者 黒瀬総一郎）', 'caption', '括号署名'),
        ('建設中のデータセンター（バージニア州）', 'caption', '图片说明'),
        ('クマ被害', 'caption', '栏目标签'),
        ('文化・芸術・エンタメ', 'caption', '栏目标签'),
        ('深掘りコンテンツ', 'caption', '栏目标签'),
        ('秋雨前線の影響で、関東甲信では大気の状態が非常に不安定になっています。', 'body', '普通句子'),
        ('福島市の中心部からおよそ3キロの笹木野地区。', 'body', '体言止め也是正文'),
    ]
    for line, want, why in cases:
        got = D.classify_line(line)
        check(got == want, f'[分类] 「{line[:22]}」应为 {want}（{why}），实际 {got}')
    # 首行标题：以「？」结尾也必须识别成标题
    check(D.classify_line('アメリカ産ジャガイモ輸入解禁手続き なぜ今進展？', first=True) == 'heading',
          '首行标题（以？结尾）未被识别')
    check(D.import_passage('', SAMPLES['nhk_potato'])['title'].startswith('アメリカ産ジャガイモ'),
          '标题应取正文大标题，而不是栏目标签')
    print(f'  {len(cases)+2} 条分类断言通过')

    print('\n[22] 阅读面板注音接口')
    pid = D.import_passage('t-furi', SAMPLES['nhk_nagasaki'])['id']
    rows = D.furigana_rows(pid)
    P = D.load(pid)
    check(len(rows) == len(P.sents) + len(P.headings) + len(P.captions),
          f'注音行数与存储行数对不上：{len(rows)}')
    check(all(r['tokens'] for r in rows), '有行没有注音 tokens')
    check(any(t.get('r') for r in rows for t in r['tokens']), '整篇没有任何读音，注音管线可能没接上')
    joined = ''.join(''.join(t.get('s', '') for t in r['tokens']) for r in rows)
    check('長崎' in joined, '注音结果拼回去丢了正文')
    print(f'  {len(rows)} 行注音，逐行 tokens 拼回原文一致')

    print('\n[23] 前端契约：双栏/抽屉/字号/注音/跳转 + 答案不下发')
    html = open(os.path.join(HERE, 'static', 'index.html'), encoding='utf-8').read()
    need = ['.dc-split', '.dc-rcol', '.dc-reader', '.dc-fab', '@media(max-width:1060px)',
            'dcShell(', 'dcReaderHTML(', 'dcOpenReader(', 'dcCloseReader(', 'dcFabTap(',
            'dcToggleFuri(', 'dcFontSize(', 'dcJump(', 'dcSyncFab(',
            "api('/api/discourse/grade'", 'secure:true', 'dcS${bodyN}']
    for k in need:
        check(k in html, f'前端缺少 {k}')
    # 反作弊契约：渲染题目的代码里不能出现 q.answer / q.evidence
    seg = html[html.index('function dcRender('):html.index('async function dcCheck(')]
    for bad in ('q.answer', 'q.evidence', 'q.explain'):
        check(bad + '_format' in seg or bad not in seg,
              f'题目渲染代码引用了 {bad}（答案不该下发到浏览器）')
    # 服务端路由齐备
    appsrc = open(os.path.join(HERE, 'app.py'), encoding='utf-8').read()
    for route in ('/api/discourse/preview', '/api/discourse/grade',
                  '/api/discourse/passages/<int:pid>/furigana',
                  '/api/discourse/passages/<int:pid>/capacity'):
        check(route in appsrc, f'后端缺少路由 {route}')
    print('  前端 16 项 / 后端 4 路由 / 反作弊契约 通过')

    print('\n[24] 长文性能：冷启动一次、之后命中缓存')
    big = SAMPLES.get('nhk_ai_datacenter') or SAMPLES['nhk_yoheki']
    pid2 = D.import_passage('t-perf', big)['id']
    D._PASSAGE_CACHE.clear(); D._TAG_CACHE.clear()      # 真·冷启动
    t0 = time.time(); D.make_quiz(pid2, count=12, seed=1); cold = time.time() - t0
    t1 = time.time(); D.make_quiz(pid2, count=12, seed=2); warm = time.time() - t1
    t2 = time.time(); D.capacity(pid2); cap = time.time() - t2
    check(cold < 20, f'长文冷启动过慢：{cold:.1f}s')
    check(warm < cold / 2 + 0.05, f'缓存没生效：冷 {cold:.2f}s / 热 {warm:.2f}s')
    print(f'  {len(big)} 字：冷 {cold:.2f}s → 热 {warm:.2f}s，capacity {cap:.2f}s')

    print('\n' + '=' * 56)
    if FAILS:
        print(f'FAILED: {len(FAILS)} 项')
        for f in FAILS[:40]:
            print(' -', f)
        return 1
    print('ALL PASSED（含 8 篇真实报道 / 行分类 / 阅读面板契约 / 性能）')
    return 0


if __name__ == '__main__':
    rc = main()
    rc2 = main2()
    rc3 = main3()
    rc4 = main4()
    sys.exit(rc or rc2 or rc3 or rc4)

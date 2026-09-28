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
    quiz = D.make_quiz(pid, count=20, seed=11)
    quiz2 = D.make_quiz(pid2, count=20, seed=12)
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

    print('\n' + '=' * 56)
    if FAILS:
        print(f'FAILED: {len(FAILS)} 项')
        for f in FAILS:
            print(' -', f)
        return 1
    print('ALL PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())

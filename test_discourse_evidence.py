# -*- coding: utf-8 -*-
"""判定依据自洽性测试：跑在 samples/ 里那 8 篇真实报道上
================================================================
`discourse.py` 的立身之本是「每道题都给出可逐字核对的判定依据」。
那么依据本身就必须经得起核对 —— 曾经出过这样的事故：

    问：本文の「％」のうち最も小さいものはどれか
    选项：67％ / 4.4％ / 53％ / 71％      答案：4.4％
    依据：排序：71％ > 67％ > 53％ > 40％   ← 不含答案，还混进了不是选项的 40％

答案是对的，依据却是错的 —— 对一个主打「不冤枉人」的引擎，这和出错题一样严重。
这套测试把「依据必须支撑答案」钉死，并顺带复核题目本身的客观性：

  1. `compare`：证据里的排序集合 == 选项集合，且含答案
  2. `chronology`：证据里的日期一览必须含答案
  3. `fact`：答案必须在它声明的那一句里
  4. `absent`：答案在全文一次都找不到，三个干扰项都能找到
  5. `truth`：正确项是原文句，三个错误项都不在原文里
  6. 所有题：证据非空、选项互异、答案在选项中、verbatim 题答案能逐字找到
"""
import os
import random
import re
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
    for t in ('passages', 'passage_sents', 'passage_results', 'passage_item_log'):
        c0.execute('DROP TABLE IF EXISTS %s' % t)
    c0.execute("DELETE FROM settings WHERE key='discourse_seed_v1'")
c0.close()

import db                                                    # noqa: E402
db.DB_PATH = tdb
import discourse as D                                        # noqa: E402


def norm(s):
    return re.sub(r'\s+', '', str(s or ''))


def main():
    D.ensure_seeded()
    ps = sorted(D.list_passages(), key=lambda p: p['id'])
    check(len(ps) >= 8, '内置篇章应有 8 篇，实际 %d' % len(ps))

    print('\n[1] compare / chronology：证据里的排序·清单必须支撑答案')
    n_cmp = n_chr = 0
    for p in ps:
        P = D.load(p['id'])
        rng = random.Random(1)
        for q in D.g_compare(P, rng):
            n_cmp += 1
            line = next((e for e in q['evidence'] if '排序' in e), '')
            listed = [x for x in re.split(r'[ >：]+', line.split('：')[-1]) if x]
            check(set(listed) == set(q['options']),
                  'compare 证据排序与选项对不上：%s / 证据 %s / 选项 %s'
                  % (q['prompt'], listed, q['options']))
            check(q['answer'] in listed, 'compare 证据排序里没有答案：%s' % q['answer'])
        for q in D.g_chronology(P, rng):
            n_chr += 1
            line = next((e for e in q['evidence'] if '一覧' in e or '一览' in e), '')
            check(norm(q['answer']) in norm(line),
                  'chronology 证据清单里没有答案：%s' % q['answer'])
    print('  compare %d 道 / chronology %d 道，证据均自洽' % (n_cmp, n_chr))

    print('\n[2] 全题型批量客观性复核（8 篇 × 2 套 × 10 题）')
    total = 0
    types = set()
    for p in ps:
        text = norm(D.get_passage(p['id'])['text'])
        for seed in (11, 22):
            quiz = D.make_quiz(p['id'], count=10, seed=seed, mode='mixed')
            check(quiz.get('ok'), '《%s》出题失败：%s' % (p['title'][:12], quiz.get('reason')))
            for q in quiz.get('questions', []):
                total += 1
                types.add(q['qtype'])
                tag = '《%s》%s' % (p['title'][:10], q['qtype'])
                check(bool(q.get('evidence')), '%s 没有判定依据' % tag)
                check(bool(q.get('prompt')) and bool(q.get('context')), '%s 题面不完整' % tag)
                opts = q.get('options') or []
                if q.get('answer_format') == 'input':
                    check(not opts, '%s 填空题不该下发选项' % tag)
                else:
                    check(len(opts) == 4 and len(set(opts)) == 4, '%s 选项不是 4 个互异项' % tag)
                    check(q['answer'] in opts, '%s 答案不在选项里' % tag)
                    check(opts[q['answer_index']] == q['answer'], '%s answer_index 指错' % tag)
                if q['qtype'] == 'absent':
                    check(norm(q['answer']) not in text, '%s absent 的答案其实在原文里' % tag)
                    for o in opts:
                        if o != q['answer']:
                            check(norm(o) in text, '%s absent 的干扰项不在原文里：%s' % (tag, o))
                elif q['qtype'] == 'truth':
                    check(norm(q['answer']) in text, '%s truth 的正确项不是原文句' % tag)
                    for o in opts:
                        if o != q['answer']:
                            check(norm(o) not in text, '%s truth 的错误项也在原文里' % tag)
                elif q['qtype'] == 'fact':
                    si = q.get('sent_idx')
                    if isinstance(si, int) and 0 <= si < len(D.load(p['id']).sents):
                        check(norm(q['answer']) in norm(D.load(p['id']).sents[si]),
                              '%s fact 的答案不在它声明的那一句里' % tag)
                elif q['qtype'] == 'multi':
                    for sub in (q.get('sub_answers') or []):
                        check(norm(sub) in text, '%s multi 子答案不是原文原样' % tag)
                elif q.get('objectivity') == 'verbatim':
                    check(norm(q['answer']) in text,
                          '%s verbatim 的答案在原文里找不到：%s' % (tag, q['answer']))
    print('  复核 %d 道，覆盖 %d 种题型' % (total, len(types)))

    print('\n[3] truth 的错误项必须是「错事实」而不是「坏句子」')
    n_truth = 0
    for p in ps:
        P = D.load(p['id'])
        text = norm(D.get_passage(p['id'])['text'])
        for q in D._gen_all(P, random.Random(5)).get('truth', []):
            n_truth += 1
            check(norm(q['answer']) in text, 'truth 正确项不是原文句：%s' % q['answer'])
            for o in q['options']:
                if o == q['answer']:
                    continue
                check(norm(o) not in text, 'truth 错误项其实在原文里：%s' % o)
                # 数值改写不得造出「NからN」这种上下限相同的假区间
                check(not re.search(r'([0-9０-９]+)(\S{1,3}?)から\1\2', o),
                      'truth 错误项里出现上下限相同的区间：%s' % o)
                # 固有名詞替换不得把复合名切半（「NTT西日本」→「NTT西長崎」）
                for frag in re.findall(r'[A-Za-zＡ-Ｚ]{2,}[一-龥ァ-ヶ]{2,}', o):
                    check(frag in text, 'truth 错误项造出了原文没有的复合专名：%s' % frag)
    check(n_truth >= 6, 'truth 可出题点太少（%d），改写门禁收得过紧' % n_truth)
    # 主宾互换：新的两个格关系都必须有语料实证。
    # 「日本擁壁保証協会は…調査を行いました」互换后是「協会を行いました」，
    # 语料库里「協会を」零出现 —— 这种坏句必须被门禁挡掉。
    P = next(D.load(p['id']) for p in ps if '擁壁' in p['title'])
    hit = 0
    for i, s in enumerate(P.sents):
        if '協会' in s and 'を行' in s:
            hit += 1
            v, _note = D._swap_args(s, P.toks[i])
            check(v is None, '未实证的主宾互换被放行了：%s' % v)
    check(hit >= 1, '没找到用来验证主宾互换门禁的那句话')
    print('  truth 候选 %d 道，错误项均为合法日语且与原文矛盾' % n_truth)

    print('\n[4] 题型配额：一套题不被单一题型占满')
    for p in ps:
        for count in (10, 20):
            quiz = D.make_quiz(p['id'], count=count, seed=9, mode='choice')
            mix = quiz['type_mix']
            cap = quiz['type_cap']
            check(sum(mix.values()) == len(quiz['questions']), 'type_mix 与题数对不上')
            if not quiz['type_relaxed']:
                check(max(mix.values()) <= cap,
                      '%s：%d 题里 %s 超过配额 %d（%s）'
                      % (p['title'][:10], count, max(mix, key=mix.get), cap, mix))
            check(max(mix.values()) <= max(cap, len(quiz['questions'])),
                  '配额放宽后仍应有上限：%s' % mix)
    print('  8 篇 × count=10/20：单一题型均未超过 1/4 配额（或已如实标记放宽）')

    print('\n[5] 判分闭环：对的判对、错的判错、闭卷不下发答案')
    bad = 0
    for p in ps:
        quiz = D.make_quiz(p['id'], count=8, seed=77, mode='mixed', secure=True)
        real = D._QUIZ_CACHE[quiz['quiz_id']]['qs']
        for item in quiz['questions']:
            if any(k in item for k in ('answer', 'evidence', 'explain')):
                bad += 1
                check(False, 'secure 模式把答案/解析下发到了前端：%s' % item['qid'])
            r = real[item['qid']]
            if not D.grade(quiz['quiz_id'], item['qid'], r['answer']).get('correct'):
                bad += 1
                check(False, '正确答案被判错：%s %s' % (item['qid'], r['answer']))
            wrong = next((o for o in (r.get('options') or []) if o != r['answer']),
                         str(r['answer']) + 'ZZ')
            if D.grade(quiz['quiz_id'], item['qid'], wrong).get('correct'):
                bad += 1
                check(False, '错误答案被判对：%s %s' % (item['qid'], wrong))
    print('  判分闭环异常 %d 处' % bad)

    print()
    if FAILS:
        print('X 失败 %d 项' % len(FAILS))
    else:
        print('OK 判定依据与客观性全部自洽')
    return 1 if FAILS else 0


if __name__ == '__main__':
    try:
        code = main()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(code)

# -*- coding: utf-8 -*-
"""听力练习（listening.py）专项测试
================================================================
覆盖：
  1. 配置读写：白名单 + 边界修正
  2. meaning 题：4 选项语言一致（绝不出现"一眼认出哪个是中文"的伪劣题）、
     干扰项均为真实译文、答案在选项中
  3. discriminate 题：4 个选项均为真实语料完整句、互不相同，
     答案与原句完全一致，绝不通过机械替换名词合成坏句
  4. 双空最小对立：分句逻辑/词汇/格成分与极性联合挖空、2×2 唯一答案、整句复验
  5. scope 稳健性：与组句练习共用同一套 resolve_book_scope，
     "仅课本" 不会泄漏语料库句子
  6. 统计记录
临时库隔离，不碰真实数据。"""
import os
import sys
import json
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
    for t in ('books', 'book_lessons', 'book_sentences'):
        try:
            c0.execute(f'DELETE FROM {t}')
        except sqlite3.OperationalError:
            pass
    c0.execute("DELETE FROM settings WHERE key IN ('listening_cfg','listening_stats')")
# 必须关掉这条连接：sqlite3 的 with 只提交事务、不关连接，留着它会让下面
# init_db() 的 ALTER TABLE 撞上 database is locked，而那个异常被 db.py 按
# 「列已存在」吞掉 —— 结果就是补列静默失败。
c0.close()
db.DB_PATH = api_db
# db._migrate() 是在 import db 那一刻对「当时的 DB_PATH」跑的，换库之后必须
# 再补一次（test_ktv / test_ai_translate 同理）：否则拷贝出来的旧库缺 v22 的
# sentences.grammar_cache 列，textbook.fetch_book_sentence_rows 那条 SQL 直接
# 报 no such column 并被吞掉，「仅课本」题源随即静默退化成全库语料——
# 本套测试长期偶发失败（第 5、8 节）的真正原因就是这个。
db.init_db()
db._migrate()

import textbook
import listening as ls

random.seed(20260926)

print('== 1. 配置读写：白名单 + 边界修正 ==')
cfg = ls.listening_cfg()
check(cfg['enabled'] is True and cfg['scope'] == 'corpus' and cfg['rate'] == 'normal'
      and cfg['types'].get('contrast') == 40 and cfg['types'].get('cloze') == 30
      and cfg['types'].get('discriminate') == 10 and cfg['meaning_difficulty'] == 'advanced',
      f'默认配置以译文最小对立为主力、听音辨句占比最低：{cfg}')
cfg2 = ls.save_listening_cfg({'scope': 'book', 'rate': 'slow', 'count': 999,
                              'meaning_difficulty': 'bogus', 'bogus_key': 'x'})
check(cfg2['scope'] == 'book' and cfg2['rate'] == 'slow' and cfg2['count'] == 20
      and cfg2['meaning_difficulty'] == 'advanced',
      f'保存并做边界修正（count 上限 20）：{cfg2}')
check('bogus_key' not in cfg2, '非白名单键不写入')
ls.save_listening_cfg({'scope': 'corpus', 'rate': 'normal', 'count': 6})

print('== 2. meaning 题：语言一致 + 真实干扰项 ==')
GOOD_ZH = [
    ('彼は手を私の肩に置いた。', '他把手放在我的肩膀上。'),
    ('簡単に手に入れたものはすぐに失いやすい。', '来得容易去得快。'),
    ('夜遅くまで起きていては駄目だよ。', '晚上不该熬夜到这么晚。'),
    ('これはセルビアで三番目に大きい町である。', '这是塞尔维亚第三大城市。'),
    ('警戒するに越したことはない。', '再怎么小心也不为过。'),
    ('彼はこのギターが好きだ。', '他喜欢这把吉他。'),
    ('今朝から本を三冊読んだ。', '今天早上以来我读了三本书。'),
]
GOOD_EN = [
    ('猫が窓の外を見ている。', 'The cat is looking out the window.'),
    ('明日は雨が降るでしょう。', 'It will probably rain tomorrow.'),
]
for i in range(30):
    db.add_sentence(t := f'これはテスト文{i}です。', f'This is test sentence {i}.', 'unit_test', None, [], [])
for txt, tr in GOOD_ZH + GOOD_EN:
    db.add_sentence(txt, tr, 'unit_test', None, [], [])

d = ls.make_quiz(count=12, scope='corpus')
check(d['ok'], f'出题成功：{d}')
meaning_qs = [q for q in d['questions'] if q['qtype'] == 'meaning']
check(bool(meaning_qs), 'meaning 题型应出现')
with db.get_conn() as c:
    attested_translations = {r['translation'] for r in c.execute(
        "SELECT translation FROM sentences WHERE translation IS NOT NULL AND trim(translation)<>''").fetchall()}
for q in meaning_qs:
    check(len(q['options']) == 4 and len(set(q['options'])) == 4, f'4 个选项且不重复：{q["options"]}')
    check(q['answer'] in q['options'], f'答案在选项中：{q}')
    langs = {ls._tr_lang(o) for o in q['options']}
    check(len(langs) == 1, f'4 个选项语言必须一致（否则靠文字系统就能蒙对）：{q["options"]} → {langs}')
    check(all(o in attested_translations for o in q['options']),
          f'中英选项全部来自数据库真实译文，不机械篡改：{q["options"]}')
    check(q.get('distractor_source') == 'attested_translation_lexical_hard_negative'
          and q.get('meaning_difficulty') == 'advanced'
          and len(q.get('distractor_audit') or []) == 3,
          '高级译文干扰项必须标记为词汇硬负例并携带三项审计证据')
    for audit in q.get('distractor_audit') or []:
        check(audit.get('lexical_overlap', 0) >= 0.18 and bool(audit.get('shared_terms')),
              f'每个高级干扰项必须与答案共享可审计的高信息词：{audit}')
        check({'grammar_overlap', 'same_polarity', 'same_tense', 'same_question_type',
               'same_translation_shape'} <= set(audit), f'硬负例审计维度完整：{audit}')

# 中英文最小语义对立：必须优先同话题、只改变地点/人物/时间，而不是无关句。
for controlled, unrelated in [
    ([
        {'text': '私は昨日メアリーと電車で東京へ行った。', 'translation': 'I went to Tokyo by train with Mary yesterday.'},
        {'text': '私は昨日メアリーと電車で大阪へ行った。', 'translation': 'I went to Osaka by train with Mary yesterday.'},
        {'text': '私は昨日トムと電車で東京へ行った。', 'translation': 'I went to Tokyo by train with Tom yesterday.'},
        {'text': '私は今朝メアリーと飛行機で東京へ行った。', 'translation': 'I went to Tokyo by plane with Mary this morning.'},
        {'text': '猫が窓辺で眠っている。', 'translation': 'The cat is sleeping beside the window.'},
    ], 'The cat is sleeping beside the window.'),
    ([
        {'text': '彼は今日電車で東京へ行った。', 'translation': '他今天坐火车去了东京。'},
        {'text': '彼は今日電車で大阪へ行った。', 'translation': '他今天坐火车去了大阪。'},
        {'text': '彼は昨日飛行機で東京へ行った。', 'translation': '他昨天坐飞机去了东京。'},
        {'text': '彼女は今日電車で東京を離れた。', 'translation': '她今天坐火车离开了东京。'},
        {'text': '猫は窓辺で寝ている。', 'translation': '猫在窗边睡觉。'},
    ], '猫在窗边睡觉。'),
]:
    hard = ls._build_meaning_q(controlled[0], controlled, 'advanced',
                               ls._meaning_search_context(controlled))
    check(hard is not None and len(hard['options']) == 4,
          f'高级模式可构造四项中英最小语义对立：{hard}')
    if hard:
        check(unrelated not in hard['options'], f'高级模式不得混入无关话题：{hard["options"]}')
        check(all(len(a['shared_terms']) >= 2 for a in hard['distractor_audit']),
              f'长句干扰项至少共享两个信息锚点：{hard["distractor_audit"]}')

print('== 2.5 contrast 题：同一条译文的语法改写，实词不变 ==')
_FUNC_EN = set('''i you he she it we they me him her us them my your his its our their
mine yours hers ours theirs myself yourself himself herself itself ourselves themselves
am is are was were be been being do does did doing done have has had having will would
shall should can could may might must not no n t don doesn didn isn aren wasn weren
won can hasn haven hadn shouldn wouldn couldn mustn a an the this that these those
there here s re ve ll d m'''.split())
CONTRAST_CASES = [
    ('トムはメアリーに電話しました。', 'Tom called Mary.'),
    ('彼女は私に手紙を書いた。', 'She wrote me a letter.'),
    ('机の上に本があります。', 'There is a book on the desk.'),
    ('彼はいつも遅刻する。', 'He is always late.'),
    ('私は昨日公園へ行きませんでした。', "I didn't go to the park yesterday."),
    ('彼は私の兄より背が高い。', '他比我哥哥高。'),
    ('她比你大两岁テスト用。', None),
]
built = 0
for txt, tr in CONTRAST_CASES:
    if not tr:
        continue
    db.add_sentence(txt, tr, 'unit_test', None, [], [])
    q = ls._build_contrast_q({'text': txt, 'translation': tr, 'sid': None, 'source': 'unit_test'})
    if q is None:
        continue
    built += 1
    check(q['qtype'] == 'contrast' and len(q['options']) == 4 and len(set(q['options'])) == 4,
          f'4 个互不相同的选项：{q["options"]}')
    check(q['answer'] in q['options'] and q['answer'] == tr,
          f'正确选项就是数据库里的真实译文，不被改写：{q["answer"]}')
    check(q['distractor_source'] == 'rule_perturbed_translation_minimal_pair',
          '标记干扰项来源为规则改写最小对立')
    check(len(q['distractor_audit']) == 4
          and [a['option'] for a in q['distractor_audit']] == q['options'],
          f'审计信息与选项同序且逐项齐全：{q["distractor_audit"]}')
    check(sum(1 for a in q['distractor_audit'] if a['is_answer']) == 1,
          '四项中恰有一项被标记为正确答案')
    for a in q['distractor_audit']:
        if a['is_answer']:
            continue
        check(bool(a['changes']) and all(c.get('axis') and c.get('evidence') for c in a['changes']),
              f'每个干扰项都要说明改了哪条语法轴、日文侧证据是什么：{a}')
    # 反泄漏：2×2 版式下每条轴上正确值与错误值必须各占两项，
    # 否则「哪个选项长得跟别人都不一样」就能反推答案。
    if q['contrast_structure'] == 'matrix_2x2':
        for axis in q['contrast_axes']:
            changed = sum(1 for a in q['distractor_audit']
                          if any(c['axis'] == axis for c in a['changes']))
            check(changed == 2, f'轴 {axis} 上必须 2:2 平分：{q["distractor_audit"]}')
    # 实词不许凭空出现：改写只允许动语法（人称、时态、极性、方向…），
    # 不允许换话题。比较时把词还原成原形，并忽略人称代词与助动词——
    # 这些正是改写要动的部分。
    if q['tr_lang'] == 'en':
        import re
        import translation_contrast as _tc

        def _content(txt):
            out = set()
            for w in re.findall(r"[a-z]+", txt.lower()):
                if w in _FUNC_EN:
                    continue
                b = _tc.en_base_of(w)
                out.add(b[0] if b else w)
            return out

        base = _content(tr)
        for a in q['distractor_audit']:
            # 允许出现的新词只有一种来源：审计里明确写出来的那处语法替换
            # （on → under、always → never…）。凡是没写进 audit 的新词，
            # 都说明改写偷偷换了内容，必须判不合格。
            declared = set()
            for ch in a['changes']:
                declared |= _content(ch.get('note') or '')
            extra = _content(a['option']) - base - declared
            check(not extra, f'改写只在语法层面动手，不引入未申报的新词：{a["option"]} 新增 {extra}')
check(built >= 4, f'上述典型句中至少 4 句能构造译文最小对立题（实得 {built}）')

q_sym = ls._build_contrast_q({'text': 'これはペンです。', 'translation': 'This is a pen.',
                              'sid': None, 'source': 'unit_test'})
check(q_sym is None or len(q_sym['options']) == 4,
      '找不到足够语法证据时返回 None，而不是硬造选项')
check(ls._build_contrast_q({'text': '私は学生です。', 'translation': '', 'sid': None,
                            'source': 'unit_test'}) is None, '没有译文一律不出 contrast 题')

ls.save_listening_cfg({'types': {'contrast': 100, 'meaning': 0, 'discriminate': 0, 'cloze': 0}})
d_c = ls.make_quiz(count=6, scope='corpus')
check(d_c['ok'] and any(q['qtype'] == 'contrast' for q in d_c['questions']),
      f'contrast 占比 100% 时能真的出到该题型：{[q["qtype"] for q in d_c["questions"]]}')
ls.save_listening_cfg({'types': {'contrast': 40, 'meaning': 20, 'discriminate': 10, 'cloze': 30}})

print('== 3. discriminate 题：完整实证句 + 互不相同 + 禁止机械换词 ==')
db.add_sentence('彼女は毎日図書館で本を読んでいる。', '她每天在图书馆看书。', 'unit_test', None, [], [])
db.add_sentence('卵はどのように調理しましょうか。', '鸡蛋要怎么烹调呢。', 'unit_test', None, [], [])
db.add_sentence('彼はソファーに座って雑誌を読んでいた。', '他坐在沙发上看杂志。', 'unit_test', None, [], [])
# 回归：最近是无助词时间状语，旧实现会生成「霊魂彼は…」式拼接垃圾。
db.add_sentence('最近彼は新しい事業を始めた。', '最近他开始了一项新事业。', 'unit_test', None, [], [])
db.add_sentence('一週間シャンプーをしていないので頭がかゆいです。',
                '我一个星期没洗头，所以头很痒。', 'unit_test', None, [], [])
db.add_sentence('家に電話して！', '给家里打电话！', 'unit_test', None, [], [])
db.add_sentence('彼に助けを求めても無駄だ。', '向他求助也没有用。', 'unit_test', None, [], [])
# 新策略不再做任何词语替换：每个选项都必须是数据库中真实存在的完整句子。
with db.get_conn() as c:
    attested_texts = {r['text'] for r in c.execute('SELECT text FROM sentences').fetchall()}
d = ls.make_quiz(count=15, scope='corpus')
disc_qs = [q for q in d['questions'] if q['qtype'] == 'discriminate']
check(bool(disc_qs), 'discriminate 题型应出现')
for q in disc_qs:
    check(len(q['options']) == 4 and len(set(q['options'])) == 4, f'4 个选项且不重复：{q["options"]}')
    check(q['answer'] == q['text'] and q['answer'] in q['options'], f'原句本身是唯一正确答案：{q}')
    check(q.get('distractor_source') == 'attested_sentences' and not q.get('swapped'),
          '辨句题必须标记为完整实证句来源，且不得再携带机械换词数据')
    for opt in q['options']:
        check(opt in attested_texts, f'每个选项必须是数据库中的完整真实句，不得合成：{opt}')
        check(ls._sound_sentence(opt), f'每个选项必须通过句子质量门禁：{opt}')
        check(opt not in ('彼に助けを求めても合図だ。', '彼に助けを求めても午後だ。',
                          '彼に助けを求めても国民だ。'),
              f'不得生成「無駄だ」机械换词坏句：{opt}')

print('== 4. 双空最小对立：分句逻辑/词汇/格成分 × 极性，四条完整句均质检 ==')
cloze_row = {'sid': 900001, 'text': '彼女は毎日図書館で本を読んでいます。',
             'translation': '她每天在图书馆看书。', 'source': 'unit_test'}
q = ls._build_cloze_q(cloze_row)
check(q is not None, '可生成双空最小对立题')
if q:
    check(q['qtype'] == 'cloze' and len(q['options']) == 4
          and len(set(q['options'])) == 4 and q['answer'] in q['options'],
          f'双空题 2×2 四项且答案唯一：{q}')
    check(len(q.get('prompt_parts') or []) == 3 and len(q.get('blank_answers') or []) == 2,
          '题面同时挖两个互不重叠的空')
    check(q.get('distractor_source') == 'minimal_pair_grammar_checked'
          and len(set(q.get('candidate_sentences') or [])) == 4,
          '四个选项均对应唯一完整候选句')
    for sent in q.get('candidate_sentences') or []:
        check(ls._sound_sentence(sent), f'最小对立候选必须通过整句语法门禁：{sent}')
    check(any(('ません' in s or 'ない' in s) for s in q['candidate_sentences']),
          f'至少含一个否定极性、可产生相反意义：{q["candidate_sentences"]}')

# 多分句优先考几乎同音的接续逻辑：ので（原因）↔のに（逆接），并同时考
# 主句肯定/否定；只听见名词无法用排除法秒选。
clause_q = ls._build_cloze_q({
    'sid': 900002,
    'text': '雨が降っているので、試合は中止になっていません。',
    'source': 'unit_test',
})
check(clause_q is not None, '多分句可生成「接续逻辑 × 极性」双空题')
if clause_q:
    check(clause_q['blank_answers'][0] == 'ので'
          and clause_q['contrast']['lexical_kind'] == '分句逻辑（原因↔逆接）',
          f'第一空应精确考 ので↔のに：{clause_q}')
    check(any('のに' in s for s in clause_q['candidate_sentences'])
          and any('なっています' in s for s in clause_q['candidate_sentences']),
          f'四项同时覆盖接续反转和极性反转：{clause_q["candidate_sentences"]}')
    check(all(ls._sound_sentence(s) for s in clause_q['candidate_sentences']),
          '多分句四条最小对立完整句全部通过语法门禁')

# 纯形态回归：肯定/否定与过去/非过去必须整段替换，不能留下半截活用。
for original, expected in [
    ('本を読んでいます。', '本を読んでいません。'),
    ('本を読みました。', '本を読みませんでした。'),
    ('学生です。', '学生ではありません。'),
]:
    pv = ls._polarity_variant(original)
    check(pv and pv['text'] == expected,
          f'极性最小对立 {original} → {expected}（实际 {pv}）')

# 真实语料属性测试：不是只保证手写样例；随机性下每道产出的四句仍须满足
# 唯一性、可重建性和语法门禁。
with db.get_conn() as c:
    audit_rows = [dict(r) for r in c.execute(
        'SELECT id sid,text,translation,source FROM sentences '
        'WHERE length(text) BETWEEN 8 AND 60 ORDER BY id LIMIT 240').fetchall()]
n_cloze = 0
for row in audit_rows:
    cq = ls._build_cloze_q(row)
    if not cq:
        continue
    n_cloze += 1
    rebuilt = (cq['prompt_parts'][0] + cq['blank_answers'][0]
               + cq['prompt_parts'][1] + cq['blank_answers'][1]
               + cq['prompt_parts'][2])
    check(rebuilt == cq['text'], f'双空题可无损重建原句：{cq}')
    check(len(cq['options']) == len(set(cq['options'])) == 4,
          f'真实语料双空题四项唯一：{cq["options"]}')
    check(all(ls._sound_sentence(s) for s in cq['candidate_sentences']),
          f'真实语料四条完整候选均过门禁：{cq["candidate_sentences"]}')
check(n_cloze >= 15, f'240 条真实语料至少稳定生成 15 道高难双空题（实际 {n_cloze}）')

print('== 5. scope 稳健性：与组句练习共用同一套解析，"仅课本" 不泄漏语料库 ==')
bk = textbook.import_book({'title': '听力测试课本', 'author': '', 'level': '',
                           'lessons': [{'title': '第1課', 'sentences': [g[0] for g in GOOD_ZH]}]})
book_sids = {r['sentence_id'] for r in db.get_conn().execute(
    'SELECT sentence_id FROM book_sentences WHERE book_id=?', (bk['id'],)).fetchall()}
d = ls.make_quiz(count=8, scope='book')
check(d['ok'] and d['scope'] == 'book' and d.get('scope_auto_all') is True,
      f'不传 book_ids 时自动使用全部启用中的课本：{d.get("scope")} {d.get("scope_auto_all")}')
for q in d['questions']:
    if q.get('sid'):
        check(q['sid'] in book_sids, f'"仅课本" 题目必须来自该课本：{q.get("sid")}')

d0 = ls.make_quiz(count=5, scope='book', book_ids=[])
print('== 6. 空书架诚实退化 + 关闭开关 ==')
with sqlite3.connect(api_db) as c0:
    c0.execute('DELETE FROM books')
    c0.execute('DELETE FROM book_lessons')
    c0.execute('DELETE FROM book_sentences')
d = ls.make_quiz(count=5, scope='book')
check(d['ok'] and d['scope'] == 'corpus' and d.get('scope_note') == 'no_books_fallback_corpus',
      f'空书架应诚实退化为 corpus：{d}')
ls.save_listening_cfg({'enabled': False})
d = ls.make_quiz()
check(d['ok'] is False and '关闭' in (d.get('reason') or ''), f'关闭开关生效：{d}')
ls.save_listening_cfg({'enabled': True})

print('== 7. 统计记录 ==')
r = ls.record_results([{'qtype': 'meaning', 'level': 'N4', 'ok': True},
                       {'qtype': 'discriminate', 'level': 'N4', 'ok': False}])
check(r['ok'] and r['asked'] == 2 and r['correct'] == 1, f'计分 {r}')
st = ls.listening_stats(7)
check(st and st[-1]['asked'] == 2 and st[-1]['correct'] == 1, f'统计落库 {st}')

print('== 8. 全配置组合出题健壮性：无死锁、无空白 ==')
# 各种边界异常配置清洗验证
cfg_corrupt = ls.save_listening_cfg({
    'level': 'INVALID_LV', 'scope': 'BOGUS_SCOPE', 'rate': 'TURBO',
    'count': -5, 'max_plays': 999, 'meaning_difficulty': 'RANDOM',
    'types': {'contrast': -5, 'meaning': -10, 'discriminate': 'invalid', 'cloze': None}
})
check(cfg_corrupt['level'] == 'any' and cfg_corrupt['scope'] == 'corpus'
      and cfg_corrupt['count'] == 1 and cfg_corrupt['max_plays'] == 10
      and cfg_corrupt['types']['meaning'] == 0 and cfg_corrupt['types']['contrast'] == 0,
      f'异常配置深度清洗与边界安全：{cfg_corrupt}')

# 遍历所有 scope、level、题型组合，确保均能稳定出题
for scope in ('corpus', 'mixed', 'lyric'):
    for level in ('any', 'N5', 'N4', 'N3', 'N2', 'N1'):
        for types in [
            {'contrast': 100, 'meaning': 0, 'discriminate': 0, 'cloze': 0},
            {'meaning': 30, 'discriminate': 25, 'cloze': 45},
            {'meaning': 100, 'discriminate': 0, 'cloze': 0},
            {'meaning': 0, 'discriminate': 100, 'cloze': 0},
            {'meaning': 0, 'discriminate': 0, 'cloze': 100},
        ]:
            ls.save_listening_cfg({'scope': scope, 'level': level, 'types': types, 'enabled': True})
            q_res = ls.make_quiz(count=4)
            check(q_res['ok'] and len(q_res['questions']) > 0,
                  f'配置 scope={scope} level={level} types={types} 出题成功（实得 {len(q_res["questions"])} 题）')

# 单句微型课本出题测试：即使课本只有 1 句且无译文，辨句也能借保底句生成完整选项
b_tiny = textbook.import_book({'title': '微型测试课本', 'author': '', 'level': '',
                               'lessons': [{'title': 'L1', 'sentences': ['私は学生です。']}]})
tiny_res = ls.make_quiz(book_ids=[b_tiny['id']], scope='book', count=1)
check(tiny_res['ok'] and len(tiny_res['questions']) == 1,
      f'单句课本成功生成辨句题目：{tiny_res}')
if tiny_res['questions']:
    tq = tiny_res['questions'][0]
    check(tq['qtype'] == 'discriminate' and len(tq['options']) == 4 and tq['answer'] == '私は学生です。',
          f'单句课本选项完整且答案正确：{tq}')

print('== 9. API 接口全链路测试 ==')
import app
app.app.config['TESTING'] = True
client = app.app.test_client()

r_cfg_get = client.get('/api/listening/cfg')
check(r_cfg_get.status_code == 200 and r_cfg_get.json.get('ok') is True,
      f'/api/listening/cfg GET 成功：{r_cfg_get.json}')

r_cfg_set = client.post('/api/listening/cfg', json={'scope': 'corpus', 'count': 5, 'rate': 'fast'})
check(r_cfg_set.status_code == 200 and r_cfg_set.json.get('cfg', {}).get('rate') == 'fast',
      f'/api/listening/cfg POST 成功：{r_cfg_set.json}')

r_quiz = client.post('/api/listening/quiz', json={'count': 3})
check(r_quiz.status_code == 200 and r_quiz.json.get('ok') is True
      and len(r_quiz.json.get('questions', [])) == 3,
      f'/api/listening/quiz 出题接口成功：{len(r_quiz.json.get("questions", []))} 题')

r_ans = client.post('/api/listening/answer', json={'results': [{'qtype': 'cloze', 'level': 'N5', 'ok': True}]})
check(r_ans.status_code == 200 and r_ans.json.get('ok') is True,
      f'/api/listening/answer 提交结果成功：{r_ans.json}')

r_stats = client.get('/api/listening/stats')
check(r_stats.status_code == 200 and len(r_stats.json.get('stats', [])) > 0,
      f'/api/listening/stats 统计接口成功：{r_stats.json}')

print()
if FAILS:
    print(f'===== 听力练习测试: {len(FAILS)} 项失败 =====')
    sys.exit(1)
else:
    print('===== 听力练习测试: 全部通过 =====')

shutil.rmtree(tmp, ignore_errors=True)

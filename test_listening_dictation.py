# -*- coding: utf-8 -*-
"""听力新增三题型的快速回归测试：不触碰仓库数据库。"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, '.')
import db


def check(ok, msg):
    if not ok:
        raise AssertionError(msg)


tmp = tempfile.mkdtemp(prefix='kanji-listening-dictation-')
try:
    path = os.path.join(tmp, 'kanji.db')
    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), path)
    db.DB_PATH = path
    db.init_db()
    db._migrate()
    with db.get_conn() as c:
        c.execute('DELETE FROM sentences')
        c.execute('DELETE FROM kanji_index')
        c.execute("DELETE FROM settings WHERE key IN ('listening_cfg','listening_stats')")

    import listening as ls

    rows = [
        ('私は学生です。', 'I am a student.'),
        ('先生は学生に宿題を説明しました。', 'The teacher explained homework.'),
        ('東京の大学で日本語を勉強しています。', 'I study Japanese at a university in Tokyo.'),
        ('新しい電車が駅に到着しました。', 'A new train arrived at the station.'),
        ('友達と映画館で映画を見ました。', 'I watched a movie with a friend.'),
        ('毎朝新聞を読みます。', 'I read the newspaper every morning.'),
        ('学校で日本語を話します。', 'I speak Japanese at school.'),
    ]
    for text, tr in rows:
        db.add_sentence(text, tr, 'dictation_test', None, [], [])

    cfg = ls.listening_cfg()
    check(cfg['types']['discriminate'] == 0, '听音辨句默认必须为 0')
    check(cfg['types']['sentence_dictation'] > cfg['types']['contrast'],
          '整句听写默认权重应高于旧主力选择题')
    check(cfg['types']['sentence_arrange'] == 20 and cfg['arrange_max_plays'] == 2,
          '听后组句应有默认权重并且默认最多听两次')

    row = {'sid': 1, 'text': rows[0][0], 'source': 'dictation_test'}
    word = ls._build_word_dictation_q(row)
    check(word and ls._is_pure_kanji(word['answer']), '纯汉字听写必须选纯汉字词')
    check(word['audio_text'] == word['answer'] and word['input_rule'] == 'pure_kanji_only',
          '纯汉字题音频只读目标词并标记严格输入规则')
    check(ls.grade_response(word, word['answer'])['ok'], '纯汉字正确表记应判对')
    check(not ls.grade_response(word, word['reading'])['ok'], '纯汉字题写假名不能代替表记')

    bank = ls._word_bank_from_rows([{'text': x[0], 'source': 'dictation_test'} for x in rows])
    kanji = ls._build_kanji_choice_q(row, bank)
    check(kanji and len(kanji['options']) == 4, '听音选汉字应有四个选项')
    check(all(ls._is_pure_kanji(x) for x in kanji['options']), '汉字选项不能带假名')
    check(kanji['answer'] in kanji['options'] and len(kanji['kanji_option_audit']) == 4,
          '汉字题答案和混淆审计必须齐全')

    sentence = ls._build_sentence_dictation_q(row, 'advanced')
    check(sentence and sentence['dictation_mode'] == 'advanced', '最高难度句子题应无提示模式')
    check(ls.grade_sentence_dictation(row['text'], '私は学生です')['ok'], '句子判定应忽略标点')
    check(ls.grade_sentence_dictation(row['text'], 'わたしはがくせいです')['ok'],
          '句子判定应接受推荐假名读音')
    alt = ls.grade_sentence_dictation('東京の大学で日本語を勉強しています。',
                                      'とうきょうのだいがくでにっぽんごをべんきょうしています')
    check(alt['ok'] and alt['needs_correction'], '有证据的非推荐读音应判对并提示修正')

    check(ls.sentence_suggestions('私は', 'beginner'), '初级应能从部分词给全语料库联想')
    check(ls.sentence_suggestions('私は学生', 'intermediate'), '中级完整词后应给后续短搭配')
    check(not ls.sentence_suggestions('私は', 'advanced'), '最高难度不应调用联想')

    arrange = ls._build_sentence_arrange_q(row)
    check(arrange and arrange['qtype'] == 'sentence_arrange' and arrange['must_use_all_tiles'],
          '听后组句必须生成完整词块题而不是半句题')
    if arrange:
        by_slot = {int(v): k for k, v in arrange['spec']['tile_map'].items() if int(v) >= 0}
        canonical_order = [by_slot[i] for i in range(arrange['n_required'])]
        good = ls.grade_arrangement(arrange, canonical_order)
        bad = ls.grade_arrangement(arrange, canonical_order[:-1])
        wrong_order = canonical_order[1:] + canonical_order[:1]
        wrong = ls.grade_arrangement(arrange, wrong_order)
        check(good['ok'], '完整正确词块顺序应判对')
        check(not bad['ok'], '漏掉词块的半句不能判对')
        check(not wrong['ok'], '完整但顺序与录音不同也不能判对')

    ls.save_listening_cfg({'types': {'contrast': 0, 'meaning': 0, 'discriminate': 0, 'cloze': 0,
                                      'word_dictation': 0, 'kanji_choice': 0,
                                      'sentence_dictation': 0, 'sentence_arrange': 100},
                           'sentence_mode': 'advanced', 'arrange_max_plays': 2})
    quiz = ls.make_quiz(count=5, scope='corpus')
    check(quiz['ok'] and quiz['questions'], '新增题型权重应能生成题目')
    check(not any(q['qtype'] == 'discriminate' for q in quiz['questions']),
          '0% 题型不能作为凑数兜底偷偷出现')
    arrange_quiz = ls.make_quiz(count=1, scope='corpus')
    check(any(q['qtype'] == 'sentence_arrange' and q['max_plays'] == 2
              for q in arrange_quiz['questions']), '听后组句默认最多播放两次')
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print('听力新增题型测试：全部通过')

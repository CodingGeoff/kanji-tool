# -*- coding: utf-8 -*-
"""
艾宾浩斯遗忘曲线复习调度（汉字 + 词汇双轨）。
经典复习点: 5分钟 → 30分钟 → 12小时 → 1天 → 2天 → 4天 → 7天 → 15天 → 1个月 → 2个月
答对进入下一阶段，模糊维持当前阶段，答错回退（记忆重置）。

说明：srs 表的 kanji 列是主键，实际存放「单个汉字或整个单词」；
kind 列区分字/词（老数据默认为 kanji），reading 列存放单词读音。
"""
import time
import random
import json
import db

INTERVALS_MIN = [5, 30, 720, 1440, 2880, 5760, 10080, 21600, 43200, 86400]
STAGE_NAMES = ['5分', '30分', '12时', '1天', '2天', '4天', '7天', '15天', '1月', '2月', '✓长期']
MATURE_STAGE = 7   # stage ≥ 7 即「长期记忆」


def _kind_of(item, kind=None):
    if kind in ('kanji', 'words'):
        return kind
    return 'words' if len(item or '') > 1 else 'kanji'


def add_kanji(kanji, kind=None, reading=''):
    """开始学习一个汉字或单词（kind 未指定时按长度推断；reading 为单词读音）。"""
    now = time.time()
    kind = _kind_of(kanji, kind)
    with db._lock, db.get_conn() as c:
        c.execute('INSERT OR IGNORE INTO srs(kanji,stage,next_due,added_at,kind,reading) '
                  'VALUES(?,0,?,?,?,?)',
                  (kanji, now + INTERVALS_MIN[0] * 60, now, kind, reading or ''))
    db.log('learn', f'开始学习{"词汇" if kind == "words" else "汉字"}「{kanji}」')


# 别名：语义更准的入口（老接口 add_kanji 保留兼容）
add_item = add_kanji


def remove_kanji(kanji):
    with db._lock, db.get_conn() as c:
        c.execute('DELETE FROM srs WHERE kanji=?', (kanji,))
    db.log('remove', f'移除「{kanji}」的学习记录')


def answer(kanji, result):
    """result: 'ok' 认识 | 'hard' 模糊 | 'ng' 忘记"""
    now = time.time()
    with db._lock, db.get_conn() as c:
        row = c.execute('SELECT * FROM srs WHERE kanji=?', (kanji,)).fetchone()
        if not row:
            return
        stage = row['stage']
        if result == 'ok':
            stage = min(stage + 1, len(INTERVALS_MIN))
            c.execute('UPDATE srs SET stage=?, next_due=?, last_at=?, ok=ok+1 WHERE kanji=?',
                      (stage, now + INTERVALS_MIN[min(stage, len(INTERVALS_MIN) - 1)] * 60, now, kanji))
        elif result == 'hard':
            c.execute('UPDATE srs SET next_due=?, last_at=? WHERE kanji=?',
                      (now + INTERVALS_MIN[max(stage - 1, 0)] * 60, now, kanji))
        else:  # ng 遗忘 -> 曲线重置
            c.execute('UPDATE srs SET stage=0, next_due=?, last_at=?, ng=ng+1 WHERE kanji=?',
                      (now + INTERVALS_MIN[0] * 60, now, kanji))
    label = {'ok': '认识', 'hard': '模糊', 'ng': '忘记'}[result]
    db.log('review', f'复习「{kanji}」：{label}')


def _pick_sentence(item, kind, known: set):
    """
    从本地语料库智能抽取例句：
    优先带翻译、长度适中、句中其他汉字大多已学过的句子；每次随机，不固定。
    单词用子串检索，汉字走汉字索引。
    """
    import furigana
    if kind == 'words':
        cands = db.sentences_for_word(item, limit=30)
    else:
        cands = db.sentences_for_kanji(item, limit=30)
    if not cands:
        return None

    def score(s):
        if kind == 'words':
            others = [c for c in s['text'] if furigana.is_kanji(c) and c not in item]
        else:
            others = [c for c in s['text'] if furigana.is_kanji(c) and c != item]
        known_ratio = (sum(1 for c in others if c in known) / len(others)) if others else 1.0
        sc = known_ratio * 3.0
        if s['translation']:
            sc += 2.0
        L = len(s['text'])
        if 8 <= L <= 40:
            sc += 1.0
        sc += random.random() * 1.5   # 随机扰动，保证每次例句不同
        return sc

    return max(cands, key=score)


def due_reviews(limit=30):
    now = time.time()
    with db.get_conn() as c:
        rows = c.execute('SELECT * FROM srs WHERE next_due<=? ORDER BY next_due LIMIT ?',
                         (now, limit)).fetchall()
        known = {r['kanji'] for r in c.execute('SELECT kanji FROM srs WHERE stage>=3')}
    out = []
    for r in rows:
        item = dict(r)
        kind = item.get('kind') or _kind_of(item['kanji'])
        item['kind'] = kind
        sent = _pick_sentence(item['kanji'], kind, known)
        if kind == 'words':
            item['words'] = []
        else:
            item['words'] = db.kanji_words(item['kanji'], 6)
        if sent:
            sent['tokens'] = json.loads(sent['tokens'])
            item['sentence'] = sent
        out.append(item)
    return out


def overview():
    now = time.time()
    with db.get_conn() as c:
        total = c.execute('SELECT COUNT(*) n FROM srs').fetchone()['n']
        due = c.execute('SELECT COUNT(*) n FROM srs WHERE next_due<=?', (now,)).fetchone()['n']
        mature = c.execute('SELECT COUNT(*) n FROM srs WHERE stage>=7').fetchone()['n']
        try:
            words_total = c.execute("SELECT COUNT(*) n FROM srs WHERE kind='words'").fetchone()['n']
            words_due = c.execute("SELECT COUNT(*) n FROM srs WHERE kind='words' AND next_due<=?",
                                  (now,)).fetchone()['n']
        except Exception:
            words_total, words_due = 0, 0
        today0 = now - (now % 86400)
        reviewed_today = c.execute(
            "SELECT COUNT(*) n FROM history WHERE type='review' AND ts>=?", (today0,)).fetchone()['n']
    return {'total': total, 'due': due, 'mature': mature, 'reviewed_today': reviewed_today,
            'words_total': words_total, 'words_due': words_due,
            'kanji_total': total - words_total}

# -*- coding: utf-8 -*-
"""日语汉字学习工具 —— Flask 后端"""
import json
import os
import time
import threading
from flask import Flask, request, jsonify, send_from_directory

import db
import srs
import corpus
import furigana
import grammar
import rag

app = Flask(__name__, static_folder='static')
db.init_db()

# ---------- 后台持续抓取线程：语料库源源不断扩充 ----------
_fetch_state = {'running': False, 'last': None, 'last_added': 0}


def _bg_fetch(source='all'):
    if _fetch_state['running']:
        return
    _fetch_state['running'] = True
    try:
        added = corpus.fetch(source)
        _fetch_state['last'] = time.time()
        _fetch_state['last_added'] = len(added)
    finally:
        _fetch_state['running'] = False


def _auto_loop():
    while True:
        try:
            total, _ = db.query_sentences(per=1)
            # 语料不足500句时快速补充，之后每10分钟慢速持续扩充
            _bg_fetch('tatoeba' if total < 500 else 'all')
        except Exception:
            pass
        total, _ = db.query_sentences(per=1)
        time.sleep(60 if total < 500 else 600)


threading.Thread(target=_auto_loop, daemon=True).start()


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ---------- 统计 ----------
@app.route('/api/stats')
def stats():
    with db.get_conn() as c:
        n_sent = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
        n_kanji = c.execute('SELECT COUNT(DISTINCT kanji) n FROM kanji_index').fetchone()['n']
        by_src = {r['source']: r['n'] for r in
                  c.execute('SELECT source, COUNT(*) n FROM sentences GROUP BY source')}
    return jsonify({'sentences': n_sent, 'kanji': n_kanji, 'by_source': by_src,
                    'srs': srs.overview(), 'fetching': _fetch_state['running'],
                    'last_fetch': _fetch_state['last'], 'last_added': _fetch_state['last_added']})


# ---------- 语料抓取 ----------
@app.route('/api/fetch', methods=['POST'])
def api_fetch():
    source = (request.json or {}).get('source', 'all')
    added = corpus.fetch(source)
    return jsonify({'added': len(added), 'samples': added[:5]})


# ---------- 语料 CRUD ----------
@app.route('/api/sentences')
def api_sentences():
    total, rows = db.query_sentences(
        q=request.args.get('q') or None,
        kanji=request.args.get('kanji') or None,
        page=int(request.args.get('page', 1)),
        per=int(request.args.get('per', 20)))
    with db.get_conn() as c:
        fav_ids = {x['sentence_id'] for x in c.execute('SELECT sentence_id FROM fav_sentences')}
    for r in rows:
        r['tokens'] = json.loads(r['tokens'])
        r['fav'] = r['id'] in fav_ids
    return jsonify({'total': total, 'rows': rows})


@app.route('/api/sentences', methods=['POST'])
def api_add_sentence():
    d = request.json or {}
    text = (d.get('text') or '').strip()
    if not text:
        return jsonify({'error': '句子不能为空'}), 400
    if corpus.is_junk(text):
        return jsonify({'error': '文本包含垃圾字符（下划线/时间戳/测试标记），已拒绝入库'}), 400
    text, n_fix = corpus.repair_inline_furigana(text)
    text, orig = corpus.modernize_old_kana(text)
    tokens = furigana.annotate(text)
    kw = furigana.extract_kanji_words(tokens)
    sid = db.add_sentence(text, d.get('translation') or None, 'manual', None, tokens, kw, orig_text=orig)
    if sid is None:
        return jsonify({'error': '该句子已存在'}), 409
    db.log('add', f'手动添加语料：{text[:30]}')
    return jsonify({'id': sid, 'repaired': n_fix >= 2, 'text': text})


@app.route('/api/sentences/<int:sid>', methods=['PUT'])
def api_update_sentence(sid):
    d = request.json or {}
    text = (d.get('text') or '').strip() or None
    tokens = kw = None
    if text:
        tokens = furigana.annotate(text)
        kw = furigana.extract_kanji_words(tokens)
    db.update_sentence(sid, text=text, translation=d.get('translation'), tokens=tokens, kanji_words=kw)
    db.log('edit', f'编辑语料 #{sid}')
    return jsonify({'ok': True})


@app.route('/api/sentences/<int:sid>', methods=['DELETE'])
def api_delete_sentence(sid):
    db.delete_sentence(sid)
    db.log('delete', f'删除语料 #{sid}')
    return jsonify({'ok': True})


# ---------- 汉字 ----------
@app.route('/api/kanji')
def api_kanji():
    learned = request.args.get('learned')
    learned = True if learned == '1' else (False if learned == '0' else None)
    total, rows = db.kanji_stats(learned=learned, q=request.args.get('q') or None,
                                 page=int(request.args.get('page', 1)),
                                 per=int(request.args.get('per', 60)))
    return jsonify({'total': total, 'rows': rows})


@app.route('/api/kanji/<kanji>')
def api_kanji_detail(kanji):
    words = db.kanji_words(kanji, 12)
    sents = db.sentences_for_kanji(kanji, 200)
    for s in sents:
        s['tokens'] = json.loads(s['tokens'])
    return jsonify({'kanji': kanji, 'words': words,
                    'sentences': sents, 'total': len(sents)})


# ---------- 学习 / 复习 (艾宾浩斯) ----------
@app.route('/api/learn/new')
def api_new_kanji():
    """按语料频次推荐未学习的高频汉字"""
    limit = int(request.args.get('limit', 10))
    _, rows = db.kanji_stats(learned=False, per=limit)
    for r in rows:
        r['words'] = db.kanji_words(r['kanji'], 4)
    return jsonify({'rows': rows})


@app.route('/api/learn', methods=['POST'])
def api_learn():
    ks = (request.json or {}).get('kanji', [])
    if isinstance(ks, str):
        ks = [ks]
    for k in ks:
        srs.add_kanji(k)
    return jsonify({'ok': True, 'added': len(ks)})


@app.route('/api/learn/<kanji>', methods=['DELETE'])
def api_unlearn(kanji):
    srs.remove_kanji(kanji)
    return jsonify({'ok': True})


@app.route('/api/review/due')
def api_due():
    return jsonify({'rows': srs.due_reviews(), 'stage_names': srs.STAGE_NAMES})


@app.route('/api/review/answer', methods=['POST'])
def api_answer():
    d = request.json or {}
    srs.answer(d.get('kanji'), d.get('result', 'ok'))
    return jsonify({'ok': True})


# ---------- 任意文本注音（字幕直贴） ----------
@app.route('/api/annotate', methods=['POST'])
def api_annotate():
    text = (request.json or {}).get('text', '')
    lines = []
    for line in text.splitlines():
        lines.append(furigana.annotate(line) if line.strip() else [])
    db.log('annotate', f'注音文本 {len(text)} 字')
    return jsonify({'lines': lines})


# ---------- 全库重新注音（引擎升级后刷新旧数据） ----------
@app.route('/api/reannotate', methods=['POST'])
def api_reannotate():
    n = 0
    with db.get_conn() as c:
        rows = c.execute('SELECT id, text FROM sentences').fetchall()
    for r in rows:
        if corpus.is_junk(r['text']) or not corpus._good_sentence(r['text']):
            db.delete_sentence(r['id'])
            continue
        text, n_fix = corpus.repair_inline_furigana(r['text'])
        text, orig = corpus.modernize_old_kana(text)
        tokens = furigana.annotate(text)
        kw = furigana.extract_kanji_words(tokens)
        db.update_sentence(r['id'], text=text, tokens=tokens, kanji_words=kw, orig_text=orig)
        n += 1
    db.log('edit', f'引擎升级：全库 {n} 句重新注音')
    return jsonify({'ok': True, 'count': n})


# ---------- 语法解析（高级模式） ----------
@app.route('/api/grammar', methods=['POST'])
def api_grammar():
    d = request.json or {}
    text = (d.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'empty'}), 400
    points = grammar.analyze(text)
    tokens = furigana.annotate(text)
    db.log('grammar', f'语法解析：{text[:24]}（{len(points)}个语法点）')
    return jsonify({'text': text, 'tokens': tokens, 'points': points})


# ---------- 语料清理（脏数据修复/剔除） ----------
@app.route('/api/cleanup', methods=['POST'])
def api_cleanup():
    removed, repaired = 0, 0
    with db.get_conn() as c:
        rows = c.execute('SELECT id, text FROM sentences').fetchall()
    for r in rows:
        if corpus.is_junk(r['text']) or not corpus._good_sentence(r['text']):
            db.delete_sentence(r['id'])
            removed += 1
            continue
        moderned, orig = corpus.modernize_old_kana(r['text'])
        if orig is not None:
            tokens = furigana.annotate(moderned)
            kw = furigana.extract_kanji_words(tokens)
            db.update_sentence(r['id'], text=moderned, tokens=tokens, kanji_words=kw, orig_text=orig)
            repaired += 1
            continue
        fixed, n = corpus.repair_inline_furigana(r['text'])
        if n >= 2 and fixed != r['text']:
            if db.sentence_exists(fixed):
                db.delete_sentence(r['id'])
                removed += 1
            else:
                tokens = furigana.annotate(fixed)
                kw = furigana.extract_kanji_words(tokens)
                db.update_sentence(r['id'], text=fixed, tokens=tokens, kanji_words=kw)
                repaired += 1
    db.log('cleanup', f'语料清理：修复{repaired}句、删除{removed}句垃圾数据')
    return jsonify({'repaired': repaired, 'removed': removed})


# ---------- 收藏夹：句子 ----------
@app.route('/api/favs')
def api_favs():
    with db.get_conn() as c:
        sents = c.execute('''
            SELECT s.*, f.note fav_note, f.created_at fav_at FROM fav_sentences f
            JOIN sentences s ON s.id=f.sentence_id ORDER BY f.created_at DESC''').fetchall()
        words = c.execute('SELECT * FROM fav_words ORDER BY created_at DESC').fetchall()
    out_s = []
    for r in sents:
        d = dict(r)
        d['tokens'] = json.loads(d['tokens'])
        out_s.append(d)
    return jsonify({'sentences': out_s, 'words': [dict(w) for w in words]})


@app.route('/api/favs/sentence/toggle', methods=['POST'])
def api_fav_toggle():
    sid = (request.json or {}).get('sentence_id')
    with db._lock, db.get_conn() as c:
        if c.execute('SELECT 1 FROM fav_sentences WHERE sentence_id=?', (sid,)).fetchone():
            c.execute('DELETE FROM fav_sentences WHERE sentence_id=?', (sid,))
            fav = False
        else:
            c.execute('INSERT INTO fav_sentences(sentence_id,note,created_at) VALUES(?,?,?)',
                      (sid, '', time.time()))
            fav = True
    db.log('fav', f'{"收藏" if fav else "取消收藏"}句子 #{sid}')
    return jsonify({'fav': fav})


@app.route('/api/favs/sentence/<int:sid>', methods=['PUT'])
def api_fav_note(sid):
    note = (request.json or {}).get('note', '')
    with db._lock, db.get_conn() as c:
        c.execute('UPDATE fav_sentences SET note=? WHERE sentence_id=?', (note, sid))
    db.log('fav', f'更新句子收藏笔记 #{sid}')
    return jsonify({'ok': True})


# ---------- 收藏夹：词汇 ----------
@app.route('/api/favs/word', methods=['POST'])
def api_fav_word_add():
    d = request.json or {}
    word = (d.get('word') or '').strip()
    if not word:
        return jsonify({'error': '词汇不能为空'}), 400
    tokens = furigana.annotate(word)
    reading = ''.join((t.get('r') if t.get('r') is not None else t['s']) for t in tokens)
    with db._lock, db.get_conn() as c:
        try:
            c.execute('INSERT INTO fav_words(word,reading,note,created_at) VALUES(?,?,?,?)',
                      (word, reading, d.get('note') or '', time.time()))
        except Exception:
            return jsonify({'error': '该词已在收藏夹'}), 409
    db.log('fav', f'收藏词汇「{word}」({reading})')
    return jsonify({'word': word, 'reading': reading})


@app.route('/api/favs/word/<word>', methods=['PUT'])
def api_fav_word_edit(word):
    note = (request.json or {}).get('note', '')
    with db._lock, db.get_conn() as c:
        c.execute('UPDATE fav_words SET note=? WHERE word=?', (note, word))
    return jsonify({'ok': True})


@app.route('/api/favs/word/<word>', methods=['DELETE'])
def api_fav_word_del(word):
    with db._lock, db.get_conn() as c:
        c.execute('DELETE FROM fav_words WHERE word=?', (word,))
    db.log('fav', f'移除收藏词汇「{word}」')
    return jsonify({'ok': True})


# ---------- RAG 语义检索 ----------
@app.route('/api/rag/search', methods=['POST'])
def api_rag_search():
    d = request.json or {}
    q = (d.get('q') or '').strip()
    if not q:
        return jsonify({'error': 'empty'}), 400
    hits = rag.INDEX.query(q, limit=int(d.get('limit', 10)))
    out = []
    with db.get_conn() as c:
        for sid, score in hits:
            r = c.execute('SELECT * FROM sentences WHERE id=?', (sid,)).fetchone()
            if r:
                item = dict(r)
                item['tokens'] = json.loads(item['tokens'])
                item['score'] = score
                out.append(item)
    db.log('rag', f'语义检索：{q[:24]}（{len(out)}条结果）')
    return jsonify({'rows': out})


@app.route('/api/rag/similar/<int:sid>')
def api_rag_similar(sid):
    with db.get_conn() as c:
        r = c.execute('SELECT text FROM sentences WHERE id=?', (sid,)).fetchone()
    if not r:
        return jsonify({'rows': []})
    hits = rag.INDEX.query(r['text'], limit=6, exclude_sid=sid)
    out = []
    with db.get_conn() as c:
        for hid, score in hits:
            row = c.execute('SELECT * FROM sentences WHERE id=?', (hid,)).fetchone()
            if row:
                item = dict(row)
                item['tokens'] = json.loads(item['tokens'])
                item['score'] = score
                out.append(item)
    return jsonify({'rows': out})


# ---------- 数据备份 ----------
@app.route('/api/backup')
def api_backup():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'kanji.db',
                               as_attachment=True, download_name='kanji_backup.db')


# ---------- 历史记录 ----------
@app.route('/api/history')
def api_history():
    with db.get_conn() as c:
        rows = c.execute('SELECT * FROM history ORDER BY id DESC LIMIT ?',
                         (int(request.args.get('limit', 100)),)).fetchall()
    return jsonify({'rows': [dict(r) for r in rows]})


@app.route('/api/history', methods=['DELETE'])
def api_clear_history():
    with db._lock, db.get_conn() as c:
        c.execute('DELETE FROM history')
    return jsonify({'ok': True})


# ---------- 语音朗读 (TTS) ----------
import hashlib
import asyncio

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audio_cache')
os.makedirs(AUDIO_DIR, exist_ok=True)

# 精选音色：2个日语原生神经音色 + 4个多语言神经音色（都能自然朗读日语）
VOICES = [
    {'id': 'ja-JP-NanamiNeural',            'name': '七海 Nanami（女·日语原生）'},
    {'id': 'ja-JP-KeitaNeural',             'name': '圭太 Keita（男·日语原生）'},
    {'id': 'en-US-AvaMultilingualNeural',   'name': 'Ava（女·柔和多语）'},
    {'id': 'en-US-EmmaMultilingualNeural',  'name': 'Emma（女·明快多语）'},
    {'id': 'en-US-AndrewMultilingualNeural','name': 'Andrew（男·沉稳多语）'},
    {'id': 'en-US-BrianMultilingualNeural', 'name': 'Brian（男·清晰多语）'},
]
RATES = {'slow': '-25%', 'slower': '-10%', 'normal': '+0%', 'fast': '+15%'}


@app.route('/api/voices')
def api_voices():
    return jsonify({'voices': VOICES, 'rates': list(RATES.keys())})


@app.route('/api/tts', methods=['POST'])
def api_tts():
    import edge_tts
    d = request.json or {}
    text = (d.get('text') or '').strip()
    voice = d.get('voice') or VOICES[0]['id']
    rate = RATES.get(d.get('rate') or 'normal', '+0%')
    if not text:
        return jsonify({'error': 'empty'}), 400
    if voice not in {v['id'] for v in VOICES}:
        return jsonify({'error': 'bad voice'}), 400
    key = hashlib.md5(f'{voice}|{rate}|{text}'.encode()).hexdigest()
    path = os.path.join(AUDIO_DIR, key + '.mp3')
    if not os.path.exists(path):     # 本地缓存优先，同句同音色只合成一次
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate)
            asyncio.run(comm.save(path))
            db.log('tts', f'合成朗读[{voice.split("-")[-1].replace("Neural","")}]：{text[:24]}')
        except Exception as e:
            if os.path.exists(path):
                os.remove(path)
            return jsonify({'error': f'TTS失败: {e}'}), 502
    return send_from_directory(AUDIO_DIR, key + '.mp3', mimetype='audio/mpeg')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)

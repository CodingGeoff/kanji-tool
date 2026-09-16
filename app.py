# -*- coding: utf-8 -*-
"""日语汉字学习工具 —— Flask 后端"""
import json
import os
import time
import threading
from flask import Flask, request, jsonify, send_from_directory, Response

import db
import srs
import corpus
import furigana
import grammar
import rag
import ktv
import structsim
import textbook

app = Flask(__name__, static_folder='static')
db.init_db()

# ---------- 版本信息（用于前端"关于"界面核对缓存是否为新版） ----------
APP_VERSION = 'v11'
try:
    import subprocess as _sp
    _g = _sp.run(['git', 'log', '-1', '--format=%h|%ci'],
                 capture_output=True, text=True, timeout=5,
                 cwd=os.path.dirname(os.path.abspath(__file__)))
    _parts = _g.stdout.strip().split('|')
    BUILD_HASH = _parts[0] if _parts and _parts[0] else ''
    BUILD_TIME = (_parts[1][:16].replace('T', ' ') if len(_parts) > 1 and _parts[1]
                  else time.strftime('%Y-%m-%d %H:%M'))
except Exception:
    BUILD_HASH = ''
    BUILD_TIME = time.strftime('%Y-%m-%d %H:%M')

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
            # 省流模式：不再自动抓取任何新语料
            if db.get_setting('data_saver', '1') != '1':
                total, _ = db.query_sentences(per=1)
                # 语料不足500句时快速补充，之后每10分钟慢速持续扩充
                _bg_fetch('tatoeba' if total < 500 else 'all')
        except Exception:
            pass
        time.sleep(90)


threading.Thread(target=_auto_loop, daemon=True).start()
# 句子结构索引后台预热（首次约10秒，之后增量）
structsim.INDEX.warmup_async()


@app.route('/')
def index():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'index.html'),
              encoding='utf-8') as f:
        html = f.read()
    # 注入版本号与构建时间：缓存的旧页面不含这些新内容，前端"关于"界面可据此核对
    html = html.replace('__APP_VERSION__', APP_VERSION).replace('__BUILD_TIME__', BUILD_TIME)
    resp = Response(html, mimetype='text/html')
    resp.headers['Cache-Control'] = 'no-cache'   # 前端更新后不被旧缓存挡住
    return resp


@app.route('/api/version')
def api_version():
    return jsonify({'version': APP_VERSION, 'build_time': BUILD_TIME, 'hash': BUILD_HASH})


# ---------- 统计 ----------
@app.route('/api/stats')
def stats():
    with db.get_conn() as c:
        n_sent = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
        n_kanji = c.execute('SELECT COUNT(DISTINCT kanji) n FROM kanji_index').fetchone()['n']
        n_song = c.execute('SELECT COUNT(*) n FROM songs').fetchone()['n']
        by_src = {r['source']: r['n'] for r in
                  c.execute('SELECT source, COUNT(*) n FROM sentences GROUP BY source')}
    return jsonify({'sentences': n_sent, 'kanji': n_kanji, 'songs': n_song,
                    'by_source': by_src, 'data_saver': db.get_setting('data_saver', '0') == '1',
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
    # 句子结构相似检索：输入是整句时，分析成分并匹配结构相似的句子（歌词优先）
    struct = None
    if structsim.is_sentence(q):
        sig = structsim.signature(q)
        hits = structsim.INDEX.query(q, limit=8,
                                     per_song=int(d.get('per_song', 2)))
        srows = []
        for sc, kind, title, sid, txt, shared in hits:
            if sc < 0.25:
                continue
            item = {'type': kind, 'id': sid, 'title': title, 'text': txt,
                    'score': round(min(sc, 1.0), 3),
                    'shared_particles': sorted(shared),
                    'tokens': furigana.annotate(txt)}
            srows.append(item)
        comp = structsim.describe(sig, q)
        comp['template'] = structsim.structure_template(sig)
        struct = {'is_sentence': True, 'components': comp, 'rows': srows}
    db.log('rag', f'语义检索：{q[:24]}（{len(out)}条结果'
                 + (f'，结构匹配{len(struct["rows"])}条' if struct else '') + '）')
    min_score = float(d.get('min_score', 0))
    if min_score:
        out = [r for r in out if r.get('score', 0) >= min_score]
    resp = {'rows': out}
    # 任意查询（词/句）自动匹配相关歌词行（亲和检索：子串+字符bigram）
    lyric_hits = structsim.INDEX.lyric_affinity(
        q, limit=8, per_song=int(d.get('per_song', 3)),
        min_aff=float(d.get('min_affinity', 0.18)))
    for h in lyric_hits:
        if h.get('text'):
            h['tokens'] = furigana.annotate(h['text'])
    if lyric_hits:
        resp['lyrics'] = lyric_hits
    if struct:
        resp['struct'] = struct
    return jsonify(resp)


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


# ---------- 设置（省流模式等） ----------
@app.route('/api/settings')
def api_settings_get():
    return jsonify({'data_saver': db.get_setting('data_saver', '1') == '1'})


@app.route('/api/settings', methods=['POST'])
def api_settings_set():
    d = request.json or {}
    out = {}
    if 'data_saver' in d:
        db.set_setting('data_saver', '1' if d['data_saver'] else '0')
        db.log('setting', f"省流模式：{'开启（停止自动抓取）' if d['data_saver'] else '关闭'}")
    out['data_saver'] = db.get_setting('data_saver', '0') == '1'
    return jsonify(out)


# ---------- KTV 歌词 ----------
@app.route('/api/songs')
def api_songs():
    q = (request.args.get('q') or '').strip()
    songs = db.list_songs(q, limit=min(int(request.args.get('limit', 200)), 500))
    return jsonify({'songs': songs, 'total': len(songs)})


@app.route('/api/songs/<int:sid>')
def api_song_get(sid):
    row = db.get_song(sid)
    if not row:
        return jsonify({'error': 'not found'}), 404
    row['tokens'] = ktv.ensure_seg(row) if row['tokens'] else []
    return jsonify(row)


@app.route('/api/songs/search')
def api_songs_search():
    """在歌词行中搜索（语料库·高级学习模式用）。返回逐行命中+注音。"""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'rows': [], 'total': 0})
    with db.get_conn() as c:
        songs = c.execute('SELECT id, title, lyrics FROM songs').fetchall()
    rows, seen = [], set()
    for s in songs:
        for ln in (s['lyrics'] or '').split('\n'):
            t = ln.strip()
            if t and q in t and (s['id'], t) not in seen:
                seen.add((s['id'], t))
                rows.append({'sid': s['id'], 'title': s['title'], 'line': t,
                             'tokens': furigana.annotate(t)})
            if len(rows) >= 30:
                break
        if len(rows) >= 30:
            break
    return jsonify({'rows': rows, 'total': len(rows)})


@app.route('/api/songs/reannotate', methods=['POST'])
def api_songs_reannotate():
    """引擎升级后：全部歌曲用最新引擎重新注音（含简体字转换/空格恢复/一致性回填）。"""
    with db.get_conn() as c:
        rows = c.execute('SELECT id,lyrics FROM songs').fetchall()
    n = 0
    for r in rows:
        tokens, kc = ktv.annotate_lyrics(r['lyrics'])
        db.update_song(r['id'], lyrics=r['lyrics'], tokens=tokens, kanji_count=kc)
        n += 1
    db.log('song', f'全部歌词重新注音（{n}首）')
    return jsonify({'reannotated': n})


@app.route('/api/songs/import', methods=['POST'])
def api_songs_import():
    d = request.json or {}
    text = d.get('text') or ''
    if not text.strip():
        return jsonify({'error': 'empty'}), 400
    parsed = ktv.parse_import(text)
    if d.get('dry_run'):
        return jsonify({'songs': [
            {'title': p['title'], 'artist': p['artist'],
             'lines': len([l for l in p['lyrics'].split('\n') if l.strip()])}
            for p in parsed]})
    created, skipped = [], []
    for p in parsed:
        if db.song_exists(p['title'], p['lyrics']):
            skipped.append(p['title'])
            continue
        tokens, kcount = ktv.annotate_lyrics(p['lyrics'])
        sid = db.add_song(p['title'], p['artist'], p['lyrics'], tokens, kcount)
        db.log('song', f'导入歌词《{p["title"]}》（{kcount}个汉字）')
        created.append({'id': sid, 'title': p['title']})
    return jsonify({'created': created, 'skipped': skipped})


@app.route('/api/songs/<int:sid>', methods=['POST'])
def api_song_update(sid):
    row = db.get_song(sid)
    if not row:
        return jsonify({'error': 'not found'}), 404
    d = request.json or {}
    title = (d.get('title') if d.get('title') is not None else row['title'])
    artist = (d.get('artist') if d.get('artist') is not None else row['artist'])
    title, artist = (title or '未命名歌曲').strip()[:120], (artist or '').strip()[:120]
    lyrics = d.get('lyrics')
    if lyrics is not None:
        lyrics = ktv.normalize_lyrics(lyrics)
        if not lyrics:
            return jsonify({'error': '歌词不能为空'}), 400
        tokens, kcount = ktv.annotate_lyrics(lyrics)
        db.update_song(sid, title=title, artist=artist, lyrics=lyrics,
                       tokens=tokens, kanji_count=kcount)
        db.log('song', f'编辑歌词《{title}》')
    else:
        db.update_song(sid, title=title, artist=artist)
    row = db.get_song(sid)
    row['tokens'] = json.loads(row['tokens']) if row['tokens'] else []
    return jsonify(row)


@app.route('/api/songs/<int:sid>', methods=['DELETE'])
def api_song_delete(sid):
    row = db.get_song(sid)
    if not row:
        return jsonify({'error': 'not found'}), 404
    db.delete_song(sid)
    db.log('song', f'删除歌词《{row["title"]}》')
    return jsonify({'ok': True})


# ---------- 自建课本（v11）：自制教材 / 自动拆分字词句 / 截止日学习计划 ----------
@app.route('/api/books')
def api_books():
    return jsonify({'rows': db.list_books(q=request.args.get('q') or '')})


@app.route('/api/books/analyze', methods=['POST'])
def api_books_analyze():
    """导入前预览：拆出几本书 / 多少课 / 多少句 / 字词规模 / 与既有语料的重复度"""
    d = request.json or {}
    text = (d.get('text') or '').strip()
    if len(text) < 6:
        return jsonify({'error': '文本太短，请粘贴句子或文章'}), 400
    lesson_size = int(d.get('lesson_size') or textbook.AUTO_LESSON_SIZE)
    res = textbook.analyze(text, lesson_size=lesson_size)
    res['curve_days'] = textbook.curve_days(int(d.get('target_stage') or 7))
    return jsonify(res)


@app.route('/api/books/import', methods=['POST'])
def api_books_import():
    """正式导入：自动拆分 → 建书/课 → 句子入库（注音/索引全走主引擎）→ 建字/词索引"""
    d = request.json or {}
    text = (d.get('text') or '').strip()
    if len(text) < 6:
        return jsonify({'error': '文本太短，请粘贴句子或文章'}), 400
    lesson_size = int(d.get('lesson_size') or textbook.AUTO_LESSON_SIZE)
    deadline = (d.get('deadline') or '').strip() or None
    minutes = int(d.get('minutes_per_day') or textbook.DEFAULT_MINUTES)
    target = int(d.get('target_stage') or 7)
    note = (d.get('note') or '').strip()
    books = textbook.parse_books(text, lesson_size)
    out = [textbook.import_book(b, deadline=deadline, minutes_per_day=minutes,
                                target_stage=target, note=note) for b in books]
    return jsonify({'ok': True, 'books': out})


@app.route('/api/books/<int:bid>', methods=['GET'])
def api_book_get(bid):
    info = textbook.book_detail(bid)
    if not info:
        return jsonify({'error': 'not found'}), 404
    return jsonify(info)


@app.route('/api/books/<int:bid>', methods=['PUT'])
def api_book_update(bid):
    d = request.json or {}
    kw = {}
    if 'title' in d:
        kw['title'] = (d.get('title') or '').strip() or None
    for f in ('author', 'level', 'note', 'deadline'):
        if f in d:
            kw[f] = (d.get(f) or '').strip() or None
    for f in ('minutes_per_day', 'target_stage', 'sort_order'):
        if f in d and d.get(f) is not None:
            kw[f] = int(d[f])
    if 'active' in d:
        kw['active'] = 1 if d.get('active') else 0
    if not kw:
        return jsonify({'error': '没有可更新字段'}), 400
    db.update_book(bid, **kw)
    db.log('book', f'更新课本 #{bid}: {", ".join(kw)}')
    return jsonify({'ok': True, 'book': db.get_book(bid)})


@app.route('/api/books/<int:bid>', methods=['DELETE'])
def api_book_delete(bid):
    book = db.get_book(bid)
    if not book:
        return jsonify({'error': 'not found'}), 404
    db.delete_book(bid)
    db.log('book', f'删除课本《{book["title"]}》（语料本体保留）')
    return jsonify({'ok': True})


@app.route('/api/books/<int:bid>/sentences')
def api_book_sentences(bid):
    total, rows = db.list_book_sentences(
        bid, lesson_id=int(request.args.get('lesson_id')) if request.args.get('lesson_id') else None,
        q=request.args.get('q') or None,
        page=int(request.args.get('page', 1)), per=int(request.args.get('per', 30)))
    with db.get_conn() as c:
        fav_ids = {x['sentence_id'] for x in c.execute('SELECT sentence_id FROM fav_sentences')}
    for r in rows:
        r['tokens'] = json.loads(r['tokens']) if r['tokens'] else []
        r['fav'] = r['id'] in fav_ids
    return jsonify({'total': total, 'rows': rows})


@app.route('/api/books/<int:bid>/sentences/<int:sid>', methods=['DELETE'])
def api_book_sentence_del(bid, sid):
    db.delete_book_sentence(bid, sid)
    textbook.rebuild_book_index(bid)
    db.log('book', f'课本 #{bid} 移除句子 #{sid}')
    return jsonify({'ok': True})


@app.route('/api/books/<int:bid>/lessons/<int:lid>', methods=['PUT'])
def api_book_lesson_put(bid, lid):
    d = request.json or {}
    db.update_lesson(lid, title=(d.get('title') or '').strip() or None,
                     idx=d.get('idx') if d.get('idx') is not None else None)
    return jsonify({'ok': True})


@app.route('/api/books/<int:bid>/lessons/<int:lid>', methods=['DELETE'])
def api_book_lesson_del(bid, lid):
    keep = request.args.get('keep_sentences', '1') != '0'
    db.delete_lesson(lid, keep_sentences=keep)
    if not keep:
        textbook.rebuild_book_index(bid)
    return jsonify({'ok': True})


@app.route('/api/books/<int:bid>/reindex', methods=['POST'])
def api_book_reindex(bid):
    """编辑句子后重建本书的字/词索引（教学顺序 = 首次出现顺序）"""
    stat = textbook.rebuild_book_index(bid)
    return jsonify({'ok': True, **stat})


@app.route('/api/books/units')
def api_book_units():
    """选中的一本/多本书的「字」或「词」总表（学习界面数据源；含 SRS 进度）"""
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    if not ids:
        ids = [b['id'] for b in db.list_books() if b.get('active')]
    type_ = request.args.get('type', 'kanji')
    page = int(request.args.get('page', 1))
    per = min(int(request.args.get('per', 100)), 500)
    q = request.args.get('q') or None
    if type_ == 'words':
        if len(ids) == 1:
            total, rows = db.list_book_words(ids[0], q=q, page=page, per=per)
        else:
            agg, order = {}, []
            for bid in ids:
                _t, ws = db.list_book_words(bid, q=q, page=1, per=500)
                for w in ws:
                    a = agg.get(w['word'])
                    if a is None:
                        agg[w['word']] = dict(w)
                        order.append(w['word'])
                    else:
                        a['freq'] += w['freq']
            total = len(order)
            rows = [agg[w] for w in order[(page - 1) * per: page * per]]
        return jsonify({'total': total, 'rows': rows, 'ids': ids})
    filter_ = request.args.get('filter', 'all')
    total, rows = db.list_book_kanji(None, filter_=filter_, q=q, book_ids=ids, page=page, per=per)
    return jsonify({'total': total, 'rows': rows, 'ids': ids})


@app.route('/api/books/plan', methods=['GET'])
def api_book_plan_get():
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    if not ids:
        ids = [b['id'] for b in db.list_books() if b.get('active')]
    return jsonify(textbook.load_plan(ids))


@app.route('/api/books/plan', methods=['POST'])
def api_book_plan_build():
    """生成（并保存）截止日学习计划：保证记忆曲线在截止日前走完 + 每日负载不超时"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    res = textbook.build_plan(
        ids or None, start=d.get('start') or None, deadline=d.get('deadline') or None,
        minutes_per_day=d.get('minutes_per_day'), target_stage=d.get('target_stage'),
        max_new_per_day=d.get('max_new_per_day'))
    return jsonify(res)


@app.route('/api/books/plan/done', methods=['POST'])
def api_book_plan_done():
    """勾选/取消某天（或某个字）的计划完成状态"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    n = db.set_plan_done(ids or None, day=d.get('day') or None,
                         kanji=d.get('kanji') or None, done=1 if d.get('done', True) else 0)
    return jsonify({'ok': True, 'updated': n})


@app.route('/api/books/plan', methods=['DELETE'])
def api_book_plan_clear():
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    n = db.clear_book_plan(ids or None)
    db.log('book', f'清除学习计划（{len(ids or [])} 本书，{n} 行）')
    return jsonify({'ok': True, 'cleared': n})


@app.route('/api/books/progress', methods=['POST'])
def api_book_progress_set():
    """本书内单字标记（增/改）：learning 在学 | done 已掌握 | skip 跳过"""
    d = request.json or {}
    kanji = (d.get('kanji') or '').strip()
    book_id = int(d.get('book_id') or 0)
    if not kanji or not book_id:
        return jsonify({'error': '需要 book_id 与 kanji'}), 400
    state = d.get('state') or ''
    if state not in ('learning', 'done', 'skip'):
        db.delete_book_progress(book_id, kanji)     # 空 state = 清除标记
    else:
        db.set_book_progress(book_id, kanji, state, d.get('note') or '')
    return jsonify({'ok': True})


@app.route('/api/books/progress', methods=['DELETE'])
def api_book_progress_del():
    """本书内单字标记（删）：kanji 为空则清空本书全部标记"""
    try:
        bid = int(request.args.get('book_id') or 0)
    except ValueError:
        bid = 0
    if not bid:
        return jsonify({'error': '需要 book_id'}), 400
    n = db.delete_book_progress(bid, kanji=request.args.get('kanji') or None)
    return jsonify({'ok': True, 'deleted': n})


@app.route('/api/books/<int:bid>/reset', methods=['POST'])
def api_book_reset(bid):
    """一键重置本书计划与标记（不动全局 SRS 记忆数据）"""
    db.reset_book_plan_and_progress(bid)
    db.log('book', f'重置课本 #{bid} 的计划与标记')
    return jsonify({'ok': True})


@app.route('/api/books/active', methods=['POST'])
def api_books_active():
    """选择纳入学习的书（一本或多本）：计划与「今天学什么」只统计 active 的书"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    if not ids:
        return jsonify({'error': '至少选择一本'}), 400
    db.set_books_active(ids, 1 if d.get('active', True) else 0)
    return jsonify({'ok': True, 'ids': ids})


@app.route('/api/books/study-cfg', methods=['GET'])
def api_study_cfg_get():
    """学习配置 + 最近挖空统计（配置界面 / 学习曲线页数据源）"""
    cfg = textbook.study_cfg()
    cfg['cloze_stats'] = textbook.cloze_stats()
    return jsonify(cfg)


@app.route('/api/books/study-cfg', methods=['POST'])
def api_study_cfg_set():
    """保存学习配置：例句来源/数量、语法难度下限、挖空开关/范围/题数/难度等"""
    cfg = textbook.save_study_cfg(request.json or {})
    return jsonify({'ok': True, 'cfg': cfg})


@app.route('/api/books/examples')
def api_book_examples():
    """例句检索：选中的书 + 完整语料库（来源与数量由配置或参数指定）"""
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    return jsonify({'rows': textbook.unit_examples(
        kanji=request.args.get('kanji') or None,
        word=request.args.get('word') or None,
        book_ids=ids,
        source=request.args.get('source') or None,
        limit=int(request.args.get('limit', 0) or 0) or None)})


@app.route('/api/books/grammar')
def api_book_grammar():
    """本书语法点抽取（默认排除 N5/N4 等太简单的级别，可配）"""
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    return jsonify({'rows': textbook.book_grammar(
        ids, min_level=request.args.get('min_level') or None,
        per=int(request.args.get('per', 40)))})


@app.route('/api/books/cloze', methods=['POST'])
def api_book_cloze():
    """生成挖空测验（范围/难度/题数取配置，可用参数覆盖）"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    return jsonify(textbook.make_cloze(ids or None, scope=d.get('scope'),
                                       min_level=d.get('min_level'), count=d.get('count')))


@app.route('/api/books/cloze/answer', methods=['POST'])
def api_book_cloze_answer():
    """提交挖空练习结果（计入当日统计与历史）"""
    d = request.json or {}
    return jsonify(textbook.record_cloze(d.get('results') or []))


# ---------- 数据备份：完整导出 / 导入（JSON，跨库合并） ----------
@app.route('/api/backup')
def api_backup():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'kanji.db',
                               as_attachment=True, download_name='kanji_backup.db')


@app.route('/api/export')
def api_export():
    """全量 JSON 备份：语料+歌词+SRS进度+收藏+历史（可在任何实例导入合并）。"""
    with db.get_conn() as c:
        sentences = [dict(r) for r in c.execute(
            'SELECT text,translation,source,url,orig_text FROM sentences')]
        songs = [dict(r) for r in c.execute('SELECT title,artist,lyrics FROM songs')]
        srs_rows = [dict(r) for r in c.execute(
            'SELECT kanji,stage,next_due,added_at,last_at,ok,ng FROM srs')]
        fav_s = [dict(r) for r in c.execute(
            'SELECT fs.note, fs.created_at, s.text sentence '
            'FROM fav_sentences fs JOIN sentences s ON s.id=fs.sentence_id')]
        fav_w = [dict(r) for r in c.execute(
            'SELECT word,reading,note,created_at FROM fav_words')]
        hist = [dict(r) for r in c.execute(
            'SELECT ts,type,detail FROM history ORDER BY id DESC LIMIT 1000')]
    data = {'app': 'kanji-tool', 'version': 2, 'exported_at': time.time(),
            'sentences': sentences, 'songs': songs, 'srs': srs_rows,
            'fav_sentences': fav_s, 'fav_words': fav_w, 'history': hist}
    from flask import Response
    fn = time.strftime('kanji_backup_%Y%m%d_%H%M.json')
    resp = Response(json.dumps(data, ensure_ascii=False), mimetype='application/json')
    resp.headers['Content-Disposition'] = f'attachment; filename={fn}'
    db.log('export', f'导出 JSON 备份（语料{len(sentences)} 歌词{len(songs)}）')
    return resp


@app.route('/api/import', methods=['POST'])
def api_import():
    d = request.json if request.is_json else None
    if d is None:
        f = request.files.get('file')
        if f is None:
            return jsonify({'error': '未收到文件'}), 400
        try:
            d = json.load(f)
        except Exception:
            return jsonify({'error': 'JSON 解析失败'}), 400
    if not isinstance(d, dict) or ('sentences' not in d and 'songs' not in d):
        return jsonify({'error': '不是本工具的备份文件（缺少 sentences/songs）'}), 400

    sent_add = sent_skip = song_add = song_skip = 0
    # 1) 语料（按文本去重，重新注音建索引）
    for r in d.get('sentences', []):
        text = (r.get('text') or '').strip()
        if not text:
            continue
        if db.sentence_exists(text):
            sent_skip += 1
            continue
        tokens = furigana.annotate(text)
        db.add_sentence(text, r.get('translation'), r.get('source') or 'import',
                        r.get('url'), tokens, furigana.extract_kanji_words(tokens),
                        r.get('orig_text'))
        sent_add += 1
    # 2) 歌词（按 标题+正文 去重，重新注音+分词）
    for r in d.get('songs', []):
        title = (r.get('title') or '').strip()
        lyrics = r.get('lyrics') or ''
        if not lyrics or db.song_exists(title, lyrics):
            song_skip += 1
            continue
        tokens, kc = ktv.annotate_lyrics(lyrics)
        db.add_song(title or '未命名歌曲', r.get('artist') or '', lyrics, tokens, kc)
        song_add += 1
    # 3) SRS 进度合并
    srs_add = srs_merge = 0
    rows = [r for r in d.get('srs', []) if r.get('kanji')]
    if rows:
        srs_add, srs_merge = db.upsert_srs(rows)
    # 4) 收藏合并
    fav_s = sum(db.import_fav_sentence(r.get('sentence') or '', r.get('note') or '',
                                       r.get('created_at'))
                for r in d.get('fav_sentences', []) if r.get('sentence'))
    fav_w = sum(db.import_fav_word(r['word'], r.get('reading'), r.get('note') or '',
                                   r.get('created_at'))
                for r in d.get('fav_words', []) if r.get('word'))
    # 5) 历史（保留原始时间戳）
    hist = d.get('history', [])[:1000]
    hist_n = db.add_history_rows(hist) if hist else 0
    db.log('import', f"导入备份：语料+{sent_add} 歌词+{song_add} SRS+{srs_add}/合并{srs_merge}")
    return jsonify({'sentences_added': sent_add, 'sentences_skipped': sent_skip,
                    'songs_added': song_add, 'songs_skipped': song_skip,
                    'srs_added': srs_add, 'srs_merged': srs_merge,
                    'fav_sentences_added': fav_s, 'fav_words_added': fav_w,
                    'history_added': hist_n})


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

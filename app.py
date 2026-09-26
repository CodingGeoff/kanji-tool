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
import edu_psychology
import ai_translate
import sentence_builder

app = Flask(__name__, static_folder='static')

# ---------------------------------------------------------------
# v20 性能：JSON/文本响应 gzip 压缩（零依赖，纯标准库）。
# 单曲 tokens ≈60KB → 压缩后 ≈8-10KB，移动网络下加载明显提速。
# ---------------------------------------------------------------
import gzip as _gzip

_GZIP_TYPES = ('application/json', 'text/html', 'text/plain',
               'text/css', 'application/javascript', 'text/javascript')


@app.after_request
def _gzip_response(resp):
    try:
        if (resp.direct_passthrough
                or resp.status_code < 200 or resp.status_code >= 300
                or 'Content-Encoding' in resp.headers
                or 'gzip' not in (request.headers.get('Accept-Encoding') or '').lower()
                or not resp.content_type
                or not resp.content_type.startswith(_GZIP_TYPES)):
            return resp
        data = resp.get_data()
        if len(data) < 1024:          # 小响应压缩得不偿失
            return resp
        gz = _gzip.compress(data, compresslevel=5)
        if len(gz) >= len(data):
            return resp
        resp.set_data(gz)
        resp.headers['Content-Encoding'] = 'gzip'
        resp.headers['Content-Length'] = str(len(gz))
        resp.headers.setdefault('Vary', 'Accept-Encoding')
    except Exception:
        pass                          # 压缩失败绝不影响正常响应
    return resp
db.init_db()
try:
    # 一次性数据迁移：词条索引升级为完整词典展示形（旧库的截断词条平滑改键，幂等）
    textbook.ensure_word_index_migration()
except Exception as _mig_e:
    print('[app] 词条索引迁移未完成（不影响启动）：', _mig_e)

# ---------- 版本信息（用于前端"关于"界面核对缓存是否为新版） ----------
APP_VERSION = 'v18'
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
# 多源 RAG 联邦索引（rag.MULTI）采用「按需构建」：首次检索时 ensure() 建好索引，
# 数据签名（句子/歌词/课本）变化时自动重建 —— 不另开后台线程，避免与数据写入/测试
# 临时库抢建索引，保证检索结果始终对应最新数据。




def _num(value, default, lo, hi, cast=int):
    """宽容的数字参数解析：缺失/空串/非法 → default，否则钳制到 [lo, hi]。
    default 为 None 时表示「未指定」（调用方再用业务默认值）。"""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return cast(v)


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
        page=_num(request.args.get('page'), 1, 1, 100000),
        per=_num(request.args.get('per'), 20, 1, 100),
        missing_trans=request.args.get('missing_trans') == '1')
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
    chk = grammar.check_sentence_grammar(text, strict_mode=False)
    if not chk['ok']:
        return jsonify({'error': f'句子未通过基本语法检查：{"; ".join(chk["errors"])}', 'grammar_check': chk}), 400
    text, n_fix = corpus.repair_inline_furigana(text)
    text, orig = corpus.modernize_old_kana(text)
    tokens = furigana.annotate(text)
    kw = furigana.extract_kanji_words(tokens)
    sid = db.add_sentence(text, d.get('translation') or None, 'manual', None, tokens, kw, orig_text=orig)
    if sid is None:
        return jsonify({'error': '该句子已存在'}), 409
    db.log('add', f'手动添加语料：{text[:30]}')
    return jsonify({'id': sid, 'repaired': n_fix >= 2, 'text': text, 'grammar_check': chk})


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
                                 page=_num(request.args.get('page'), 1, 1, 100000),
                                 per=_num(request.args.get('per'), 60, 1, 200))
    return jsonify({'total': total, 'rows': rows})


@app.route('/api/kanji/<kanji>')
def api_kanji_detail(kanji):
    words = db.kanji_words(kanji, 12)
    sents = db.sentences_for_kanji(kanji, 60)
    for s in sents:
        s['tokens'] = json.loads(s['tokens'])
    return jsonify({'kanji': kanji, 'words': words,
                    'sentences': sents, 'total': len(sents)})


# ---------- 学习 / 复习 (艾宾浩斯) ----------
@app.route('/api/learn/new')
def api_new_kanji():
    """按语料频次推荐未学习的高频汉字"""
    limit = _num(request.args.get('limit'), 10, 1, 50)
    _, rows = db.kanji_stats(learned=False, per=limit)
    for r in rows:
        r['words'] = db.kanji_words(r['kanji'], 4)
    return jsonify({'rows': rows})


@app.route('/api/learn/new-words')
def api_new_words():
    """按语料频次推荐未学过的高频多字词（背单词用户用）"""
    limit = _num(request.args.get('limit'), 10, 1, 50)
    return jsonify({'rows': db.top_words(limit)})


@app.route('/api/learn', methods=['POST'])
def api_learn():
    d = request.json or {}
    ks = d.get('kanji', [])
    if isinstance(ks, str):
        ks = [ks]
    ks = [k.strip() for k in ks if isinstance(k, str) and k.strip()][:200]
    ks = [k for k in ks if len(k) <= 24]
    kind = d.get('kind')                    # kanji | words（不传则按长度推断）
    if kind not in ('kanji', 'words'):
        kind = None
    readings = d.get('readings') or {}      # {单词: 读音}
    single_reading = d.get('reading') or ''
    for k in ks:
        srs.add_kanji(k, kind=kind, reading=readings.get(k) or single_reading)
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
    result = d.get('result', 'ok')
    if result not in ('ok', 'hard', 'ng'):
        return jsonify({'error': 'bad result'}), 400
    if not d.get('kanji'):
        return jsonify({'error': 'empty'}), 400
    srs.answer(d.get('kanji'), result)
    return jsonify({'ok': True})


# ---------- 任意文本注音（字幕直贴） ----------
@app.route('/api/annotate', methods=['POST'])
def api_annotate():
    text = (request.json or {}).get('text', '')
    lines = []
    if len(text) > 30000:
        return jsonify({'error': '文本过长（最多30000字）'}), 400
    if not text:
        return jsonify({'lines': []})
    for line in text.split('\n'):
        line = line.rstrip('\r')   # 与前端 data-raw 逐行对齐
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
    if len(text) > 2000:
        return jsonify({'error': '文本过长（语法解析最多2000字）'}), 400
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
    sid = _num((request.json or {}).get('sentence_id'), 0, 1, 100000000)
    if not sid:
        return jsonify({'error': 'bad sentence_id'}), 400
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
    def _ids(value):
        out = []
        for x in value or []:
            try:
                n = int(x)
            except Exception:
                continue
            if n not in out:
                out.append(n)
        return out

    sources = d.get('sources') or []
    if isinstance(sources, str):
        sources = [x.strip() for x in sources.split(',') if x.strip()]
    book_ids = _ids(d.get('book_ids') or d.get('books') or [])
    multi = rag.MULTI.search(
        q,
        limit=_num(d.get('limit'), 10, 1, 50),
        sources=sources,
        per_song=_num(d.get('per_song'), 3, 0, 20),
        per_book=_num(d.get('per_book'), 4, 0, 20),
        min_score=_num(d.get('min_score'), 0, 0, 1, cast=float),
        min_affinity=_num(d.get('min_affinity'), 0.18, 0, 1, cast=float),
        book_ids=book_ids,
        sort=d.get('sort') or 'priority',
    )
    def _annotate(seq):
        """补注音（前端 ruby 渲染用）；标题命中行无正文，保持空 token。"""
        out = []
        for row in seq:
            item = dict(row)
            txt = item.get('text') or (item.get('title') if item.get('kind') in ('song', 'book') else '') or ''
            item['tokens'] = furigana.annotate(txt) if txt else []
            out.append(item)
        return out

    out = _annotate(multi['rows'])
    lyric_hits = _annotate(multi['lyrics'])
    results = _annotate(multi.get('results') or [])
    groups = {c: _annotate(v) for c, v in (multi.get('groups') or {}).items()}
    # 句子结构相似检索：输入是整句时，分析成分并匹配结构相似的句子（歌词优先）
    struct = None
    if structsim.is_sentence(q):
        sig = structsim.signature(q)
        hits = structsim.INDEX.query(q, limit=8,
                                     per_song=_num(d.get('per_song'), 2, 0, 20),
                                     book_ids=book_ids,
                                     sources=sources)
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
    db.log('rag', f'语义检索：{q[:24]}（{len(out) + len(lyric_hits)}条结果'
                 + (f'，结构匹配{len(struct["rows"])}条' if struct else '') + '）')
    resp = {'rows': out, 'lyrics': lyric_hits, 'results': results,
            'titles': multi.get('titles', {}),
            'groups': groups, 'meta': multi.get('meta', {})}
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
    songs = db.list_songs(q, limit=_num(request.args.get('limit'), 200, 1, 500))
    return jsonify({'songs': songs, 'total': len(songs)})


@app.route('/api/songs/<int:sid>')
def api_song_get(sid):
    row = db.get_song(sid)
    if not row:
        return jsonify({'error': 'not found'}), 404
    # 引擎版本对齐：老引擎注音自动惰性重注回写（首次打开 ~20ms，之后走缓存）
    row['tokens'], row['anno_ver'] = ktv.ensure_fresh(row) if row['tokens'] else ([], row.get('anno_ver') or 0)
    return jsonify(row)


@app.route('/api/songs/<int:sid>/study')
def api_song_study(sid):
    """v20 歌曲学习档案：歌内汉字/词汇 vs SRS 学习进度（覆盖率 + 生字生词优先级）。"""
    row = db.get_song(sid)
    if not row:
        return jsonify({'error': 'not found'}), 404
    return jsonify(ktv.song_study(row))


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
        db.update_song(r['id'], lyrics=r['lyrics'], tokens=tokens, kanji_count=kc,
                       anno_ver=ktv.ANNO_VER)
        n += 1
    db.log('song', f'全部歌词重新注音（{n}首）')
    return jsonify({'reannotated': n})


@app.route('/api/songs/import', methods=['POST'])
def api_songs_import():
    d = request.json or {}
    text = d.get('text') or ''
    if not text.strip():
        return jsonify({'error': 'empty'}), 400
    if len(text) > 300000:
        return jsonify({'error': '文本过长（最多30万字，请分批导入）'}), 400
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
        sid = db.add_song(p['title'], p['artist'], p['lyrics'], tokens, kcount, anno_ver=ktv.ANNO_VER)
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
                       tokens=tokens, kanji_count=kcount, anno_ver=ktv.ANNO_VER)
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
    if len(text) > 1000000:
        return jsonify({'error': '文本过长（最多100万字，请分批导入）'}), 400
    lesson_size = _num(d.get('lesson_size'), textbook.AUTO_LESSON_SIZE, 1, 500)
    res = textbook.analyze(text, lesson_size=lesson_size)
    res['curve_days'] = textbook.curve_days(_num(d.get('target_stage'), 7, 1, 10))
    return jsonify(res)


@app.route('/api/books/import', methods=['POST'])
def api_books_import():
    """正式导入：自动拆分 → 建书/课 → 句子入库（注音/索引全走主引擎）→ 建字/词索引"""
    d = request.json or {}
    text = (d.get('text') or '').strip()
    if len(text) < 6:
        return jsonify({'error': '文本太短，请粘贴句子或文章'}), 400
    if len(text) > 1000000:
        return jsonify({'error': '文本过长（最多100万字，请分批导入）'}), 400
    lesson_size = _num(d.get('lesson_size'), textbook.AUTO_LESSON_SIZE, 1, 500)
    deadline = (d.get('deadline') or '').strip() or None
    minutes = _num(d.get('minutes_per_day'), textbook.DEFAULT_MINUTES, 1, 600)
    target = _num(d.get('target_stage'), 7, 1, 10)
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
        bid, lesson_id=_num(request.args.get('lesson_id'), None, 1, 1000000),
        q=request.args.get('q') or None,
        page=_num(request.args.get('page'), 1, 1, 100000),
        per=_num(request.args.get('per'), 30, 1, 200))
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
    """选中的一本/多本书的「字」或「词」总表（学习界面数据源；含 SRS 进度）。

    词汇模式额外返回 tokens（furigana.annotate 结果），前端用 rubyHTML() 渲染
    规范的汉字上方假名注音（而非 <small> 并排）。"""
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    if not ids:
        ids = [b['id'] for b in db.list_books() if b.get('active')]
    type_ = request.args.get('type', 'kanji')
    page = _num(request.args.get('page'), 1, 1, 100000)
    per = _num(request.args.get('per'), 100, 1, 500)
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
        # 为每个词生成 furigana tokens，前端用 rubyHTML 渲染规范注音
        for r in rows:
            word = r.get('word', '')
            if word:
                r['tokens'] = furigana.annotate(word)
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
    content = d.get('content') or 'both'
    if content not in ('both', 'kanji', 'words'):
        content = 'both'
    res = textbook.build_plan(
        ids or None, start=d.get('start') or None, deadline=d.get('deadline') or None,
        minutes_per_day=_num(d.get('minutes_per_day'), None, 1, 600),
        target_stage=_num(d.get('target_stage'), None, 1, 10),
        max_new_per_day=_num(d.get('max_new_per_day'), None, 1, 500), content=content)
    return jsonify(res)


@app.route('/api/books/curve')
def api_book_curve():
    """艾宾浩斯 1-10 阶段说明：每阶段的复习间隔 + 从零走完该阶段需要的天数。
    前端「学到第几阶段」选择器的数据源（每个数字都配中文解释，不再是裸数字）。"""
    target = _num(request.args.get('target'), 7, 1, 10)
    stages = []
    for i in range(1, 11):
        stages.append({'stage': i, 'interval': srs.STAGE_NAMES[i - 1],
                       'days': textbook.curve_days(i),
                       'mature': i >= srs.MATURE_STAGE})
    return jsonify({'stages': stages, 'target': target,
                    'curve': textbook.full_curve_preview(target),
                    'curve_days': textbook.curve_days(target),
                    'mature_stage': srs.MATURE_STAGE})


@app.route('/api/books/plan/done', methods=['POST'])
def api_book_plan_done():
    """勾选/取消某天（或某个字/词）的计划完成状态。

    勾选「完成」时自动把该字/词加入全局艾宾浩斯复习（SRS），
    字/词双轨都生效 —— 之后会按遗忘曲线在「今日复习」里推送。
    取消勾选不删除 SRS 进度（已复习过的记录不受影响）。
    """
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    kanji = d.get('kanji') or None
    done = 1 if d.get('done', True) else 0
    n = db.set_plan_done(ids or None, day=d.get('day') or None,
                         kanji=kanji, done=done)
    if done and kanji:
        kind = d.get('kind') or ('words' if len(kanji) > 1 else 'kanji')
        if kind not in ('kanji', 'words'):
            kind = 'words' if len(kanji) > 1 else 'kanji'
        srs.add_kanji(kanji, kind=kind, reading=d.get('reading') or '')
    return jsonify({'ok': True, 'updated': n})


@app.route('/api/books/plan', methods=['DELETE'])
def api_book_plan_clear():
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    n = db.clear_book_plan(ids or None)
    db.log('book', f'清除学习计划（{len(ids or [])} 本书，{n} 行）')
    return jsonify({'ok': True, 'cleared': n})


@app.route('/api/books/progress', methods=['POST'])
def api_book_progress_set():
    """本书内单字/词标记（增/改）：learning 在学 | done 已掌握 | skip 跳过；state 为空则删除标记"""
    d = request.json or {}
    try:
        book_id = int(d.get('book_id') or 0)
    except ValueError:
        book_id = 0
    kanji = (d.get('kanji') or '').strip()
    kind = (d.get('kind') or 'kanji').strip() or 'kanji'
    if not kanji or not book_id:
        return jsonify({'error': '需要 book_id 与 kanji'}), 400
    state = d.get('state') or ''
    if state not in ('learning', 'done', 'skip'):
        db.delete_book_progress(book_id, kanji, kind=kind)     # 空 state = 清除标记
    else:
        db.set_book_progress(book_id, kanji, state, d.get('note') or '', kind=kind)
    return jsonify({'ok': True})


@app.route('/api/books/progress', methods=['DELETE'])
def api_book_progress_del():
    """本书内单字/单词标记（删）：kanji 为空则清空本书全部标记，kind 为空则删本书全部"""
    try:
        bid = int(request.args.get('book_id') or 0)
    except ValueError:
        bid = 0
    if not bid:
        return jsonify({'error': '需要 book_id'}), 400
    n = db.delete_book_progress(bid, kanji=request.args.get('kanji') or None,
                                kind=request.args.get('kind') or None)
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
    """例句检索：选中的书 + 完整语料库（来源与数量由参数指定，未指定则取学习配置）"""
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    return jsonify({'rows': textbook.unit_examples(
        kanji=request.args.get('kanji') or None,
        word=request.args.get('word') or None,
        book_ids=ids,
        source=request.args.get('source') or None,
        limit=_num(request.args.get('limit'), None, 1, 30))})


@app.route('/api/books/grammar')
def api_book_grammar():
    """本书语法点抽取（默认排除 N5/N4 等太简单的级别，可配）"""
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    return jsonify({'rows': textbook.book_grammar(
        ids, min_level=request.args.get('min_level') or None,
        per=_num(request.args.get('per'), 40, 1, 200))})


@app.route('/api/grammar/check', methods=['POST'])
def api_grammar_check():
    """单句/批量基础语法质检"""
    d = request.json or {}
    text = (d.get('text') or '').strip()
    strict = bool(d.get('strict', False))
    if 'sentences' in d and isinstance(d['sentences'], list):
        results = [grammar.check_sentence_grammar(s, strict_mode=strict) for s in d['sentences'][:100]]
        return jsonify({'total': len(results), 'rows': results})
    if not text:
        return jsonify({'error': '文本不能为空'}), 400
    res = grammar.check_sentence_grammar(text, strict_mode=strict)
    return jsonify(res)


@app.route('/api/books/<int:bid>/grammar-check', methods=['GET', 'POST'])
def api_book_grammar_check(bid):
    """课本书内句子语法审计"""
    res = textbook.check_book_grammar(bid)
    return jsonify(res)


@app.route('/api/books/cloze', methods=['POST'])
def api_book_cloze():
    """生成挖空测验（范围/难度/题数取配置，可用参数覆盖）"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    return jsonify(textbook.make_cloze(ids or None, scope=d.get('scope'),
                                       min_level=d.get('min_level'),
                                       count=_num(d.get('count'), None, 1, 20)))


@app.route('/api/books/quiz-recommend', methods=['GET', 'POST'])
def api_book_quiz_recommend():
    """高级算法自动推荐题量与占比（课文总量 + 正确率 + 难度）"""
    d = {}
    if request.method == 'POST':
        d = request.json or {}
    # book_ids 可从 query 或 body 来
    ids = []
    if d.get('book_ids'):
        ids = [int(x) for x in d.get('book_ids') if str(x).strip().isdigit()]
    elif request.args.get('ids'):
        ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    total = None
    if d.get('total'):
        try:
            total = int(d.get('total'))
        except Exception:
            total = None
    return jsonify(textbook.recommend_quiz_config(ids or None, total_override=total))


@app.route('/api/books/cloze-multi', methods=['POST'])
def api_book_cloze_multi():
    """多源按比例出题：课文/语料库/歌词（占比和100%）"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    ratios = d.get('ratios') or d.get('ratio')
    # 兼容 {book,corpus,lyric} 或数组
    difficulty = d.get('difficulty')
    # 兼容旧：min_level 全局
    return jsonify(textbook.make_cloze_multi(
        book_ids=ids or None,
        total=d.get('total') or d.get('count'),
        ratios=ratios,
        difficulty=difficulty,
        min_level=d.get('min_level'),
        count=d.get('count')))


@app.route('/api/books/cloze/answer', methods=['POST'])
def api_book_cloze_answer():
    """提交挖空练习结果（计入当日统计与历史）"""
    d = request.json or {}
    return jsonify(textbook.record_cloze(d.get('results') or []))


# ================================================================
# 组句练习（多邻国式拼句，sentence_builder v1）
# ================================================================

@app.route('/api/builder/cfg')
def api_builder_cfg_get():
    """组句练习配置（mode 初级/高级 与 level N级难度 两条独立轴）"""
    cfg = sentence_builder.builder_cfg()
    return jsonify({'ok': True, 'cfg': cfg,
                    'stats': sentence_builder.builder_stats()})


@app.route('/api/builder/cfg', methods=['POST'])
def api_builder_cfg_set():
    """保存组句练习配置（白名单键 + 边界修正）"""
    cfg = sentence_builder.save_builder_cfg(request.json or {})
    return jsonify({'ok': True, 'cfg': cfg})


@app.route('/api/builder/quiz', methods=['POST'])
def api_builder_quiz():
    """生成一组组句/配对题；mode、level、scope、count 可临时覆盖配置"""
    d = request.json or {}
    return jsonify(sentence_builder.make_quiz(
        book_ids=d.get('book_ids'), count=d.get('count'),
        mode=d.get('mode'), level=d.get('level'), scope=d.get('scope')))


@app.route('/api/builder/check', methods=['POST'])
def api_builder_check():
    """稳健判卷：多种语法正确语序均判对，并返回结构化反馈"""
    d = request.json or {}
    return jsonify(sentence_builder.check_arrangement(
        d.get('spec') or {}, d.get('order') or []))


@app.route('/api/builder/answer', methods=['POST'])
def api_builder_answer():
    """记录一组答题结果（按日 + 题型/模式/级别 细分统计）"""
    d = request.json or {}
    return jsonify(sentence_builder.record_results(d.get('results') or []))


@app.route('/api/builder/stats')
def api_builder_stats():
    """最近 N 天组句练习统计"""
    days = _num(request.args.get('days'), 14, 1, 90)
    return jsonify({'ok': True, 'stats': sentence_builder.builder_stats(days)})


# ================================================================
# 教育心理学深度模块 (v16) - 完整教育心理学整合
# ================================================================

@app.route('/api/edu/profile')
def api_edu_profile():
    """学习者画像：能力、动机、元认知等"""
    return jsonify(edu_psychology.get_learner_profile())

@app.route('/api/edu/analytics')
def api_edu_analytics():
    """学习分析仪表盘：全方位数据"""
    days = request.args.get('days', 14, type=int)
    return jsonify(edu_psychology.get_learning_analytics(days=days))

@app.route('/api/edu/zpd')
def api_edu_zpd():
    """最近发展区"""
    return jsonify(edu_psychology.calculate_zpd())

@app.route('/api/edu/cognitive-load', methods=['POST'])
def api_edu_cognitive_load():
    d = request.json or {}
    text = d.get('text', '')
    level = d.get('level', 'N4')
    ui = d.get('ui_settings')
    expl_len = d.get('explanation_length', 0)
    return jsonify(edu_psychology.calculate_total_load(text, level, ui, expl_len))

@app.route('/api/edu/bkt', methods=['GET'])
def api_edu_bkt_get():
    """获取BKT状态"""
    kc = request.args.get('kc')
    if kc:
        return jsonify({'kc': kc, 'mastery': edu_psychology.get_mastery(kc)})
    model = edu_psychology._load_learner_model()
    return jsonify({'bkt': model.get('bkt', {})})

@app.route('/api/edu/bkt/update', methods=['POST'])
def api_edu_bkt_update():
    d = request.json or {}
    kc_id = d.get('kc_id') or d.get('name')
    correct = d.get('correct', False)
    skill = d.get('skill', 'grammar')
    if not kc_id:
        return jsonify({'error': 'kc_id required'}), 400
    entry = edu_psychology.update_knowledge_component(kc_id, bool(correct), skill)
    return jsonify({'ok': True, 'entry': entry})

@app.route('/api/edu/irt/update', methods=['POST'])
def api_edu_irt_update():
    d = request.json or {}
    theta = d.get('theta', 0.0)
    a = d.get('a', 1.0)
    b = d.get('b', 0.0)
    correct = d.get('correct', False)
    new_theta = edu_psychology.irt_update_theta(theta, a, b, bool(correct))
    return jsonify({'old_theta': theta, 'new_theta': new_theta, 'p': edu_psychology.irt_probability(theta, a, b)})

@app.route('/api/edu/recommend', methods=['POST'])
def api_edu_recommend():
    """整合教育心理学的推荐（ZPD+认知负荷+心流）"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    return jsonify(edu_psychology.recommend_quiz_config_psy(ids or None))

@app.route('/api/edu/cloze-multi', methods=['POST'])
def api_edu_cloze_multi():
    """自适应多源出题（教育心理学增强）"""
    d = request.json or {}
    ids = [int(x) for x in (d.get('book_ids') or []) if str(x).strip().isdigit()]
    return jsonify(edu_psychology.adaptive_cloze_multi(
        book_ids=ids or None,
        total=d.get('total') or d.get('count'),
        ratios=d.get('ratios'),
        difficulty=d.get('difficulty'),
        include_bloom=d.get('include_bloom', True),
        include_scaffold=d.get('include_scaffold', True)
    ))

@app.route('/api/edu/scaffold', methods=['GET'])
def api_edu_scaffold():
    kc = request.args.get('kc')
    mastery = request.args.get('mastery', type=float)
    if kc and mastery is None:
        mastery = edu_psychology.get_mastery(kc)
    level = edu_psychology.recommend_scaffold_level(kc_id=kc, p_mastery=mastery)
    return jsonify({'scaffold': level, 'config': edu_psychology.SCAFFOLD_LEVELS[level], 'mastery': mastery})

@app.route('/api/edu/error', methods=['POST'])
def api_edu_error():
    d = request.json or {}
    q = d.get('question', {})
    chosen = d.get('chosen', '')
    correct = d.get('correct', '')
    err_type = edu_psychology.analyze_error(q, chosen, correct)
    if err_type:
        edu_psychology.record_error(err_type, q.get('name'))
    remediation = edu_psychology.get_error_remediation(err_type) if err_type else None
    return jsonify({'error_type': err_type, 'label': edu_psychology.ERROR_TAXONOMY.get(err_type) if err_type else None, 'remediation': remediation})

@app.route('/api/edu/confidence', methods=['POST'])
def api_edu_confidence():
    d = request.json or {}
    kc_id = d.get('kc_id') or d.get('name', 'unknown')
    conf = d.get('confidence', 0.5)
    correct = d.get('correct', False)
    result = edu_psychology.record_confidence(kc_id, float(conf), bool(correct))
    result['ok'] = True
    return jsonify(result)

@app.route('/api/edu/motivation')
def api_edu_motivation():
    model = edu_psychology._load_learner_model()
    flow = edu_psychology.estimate_flow_state(model)
    return jsonify({
        'motivation': model.get('motivation', 0.7),
        'self_efficacy': model.get('self_efficacy', 0.65),
        'flow': flow,
        'feedback': edu_psychology.recommend_motivational_feedback(True, streak=3)
    })

@app.route('/api/edu/sessions', methods=['GET', 'POST'])
def api_edu_sessions():
    if request.method == 'POST':
        d = request.json or {}
        return jsonify(edu_psychology.record_study_session(d))
    else:
        return jsonify(edu_psychology.get_session_analytics())

@app.route('/api/edu/srl/plan')
def api_edu_srl_plan():
    ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip().isdigit()]
    return jsonify(edu_psychology.get_study_plan_srl(ids or None))

@app.route('/api/edu/bloom')
def api_edu_bloom():
    profile = edu_psychology.get_learner_profile()
    return jsonify({
        'levels': edu_psychology.BLOOM_LEVELS,
        'descriptions': {k: k for k in edu_psychology.BLOOM_LEVELS},
        'mastery': profile.get('bloom_mastery', {}),
        'coverage': profile.get('bloom_mastery', {}),
        'current_coverage': profile.get('bloom_mastery', {})
    })

@app.route('/api/edu/test')
def api_edu_test():
    return jsonify({'results': edu_psychology.run_self_test()})

@app.route('/api/edu/reset', methods=['POST'])
def api_edu_reset():
    """重置学习者模型（调试用）"""
    db.set_setting('edu_learner_model', '')
    db.set_setting('edu_sessions', '[]')
    return jsonify({'ok': True})




# ---------- 数据备份：完整导出 / 导入（JSON，跨库合并） ----------
@app.route('/api/backup')
def api_backup():
    # 先把 WAL 里的最新写入折回 kanji.db，否则下载到的备份会缺最后一笔数据
    try:
        db.checkpoint()
    except Exception:
        pass
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'kanji.db',
                               as_attachment=True, download_name='kanji_backup.db')


@app.route('/api/export')
def api_export():
    """全量 JSON 备份：语料+歌词+SRS进度+收藏+历史（可在任何实例导入合并）。"""
    with db.get_conn() as c:
        sentences = [dict(r) for r in c.execute(
            'SELECT text,translation,source,url,orig_text FROM sentences')]
        songs = [dict(r) for r in c.execute('SELECT title,artist,lyrics FROM songs')]
        try:
            srs_rows = [dict(r) for r in c.execute(
                'SELECT kanji,stage,next_due,added_at,last_at,ok,ng,kind,reading FROM srs')]
        except Exception:
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
        db.add_song(title or '未命名歌曲', r.get('artist') or '', lyrics, tokens, kc, anno_ver=ktv.ANNO_VER)
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
                         (_num(request.args.get('limit'), 100, 1, 500),)).fetchall()
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
    if len(text) > 600:
        return jsonify({'error': '朗读文本过长（最多600字，请分句朗读）'}), 400
    if voice not in {v['id'] for v in VOICES}:
        return jsonify({'error': 'bad voice'}), 400
    key = hashlib.md5(f'{voice}|{rate}|{text}'.encode()).hexdigest()
    path = os.path.join(AUDIO_DIR, key + '.mp3')
    if not os.path.exists(path):     # 本地缓存优先，同句同音色只合成一次
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate)
            asyncio.run(comm.save(path))
        except Exception as e:
            if os.path.exists(path):
                os.remove(path)
            return jsonify({'error': f'TTS失败: {e}'}), 502
    return send_from_directory(AUDIO_DIR, key + '.mp3', mimetype='audio/mpeg')


# ---------- AI 翻译（v18）：缺译补译 + 来源标记 ----------
@app.route('/api/translate/config')
def api_translate_config():
    cfg = ai_translate.load_config()
    return jsonify({'config': cfg.to_dict(hide_key=True),
                    'has_key': bool(cfg.api_key),
                    'providers': list(ai_translate.PROVIDERS),
                    'missing': ai_translate.count_missing(),
                    'version': ai_translate.AI_TRANSLATE_VERSION})


@app.route('/api/translate/config', methods=['POST'])
def api_translate_config_save():
    d = request.json or {}
    cur = ai_translate.load_config()
    # 前端打码回传的 '***' 表示"保持原 key 不变"
    if d.get('api_key') in (None, '', '***'):
        d['api_key'] = cur.api_key
    cfg = ai_translate.save_config(ai_translate.AIConfig.from_dict(d))
    db.log('ai_translate', f'更新AI翻译配置：{cfg.provider}/{cfg.model}/{cfg.lang}')
    out = cfg.to_dict(hide_key=True)
    out['has_key'] = bool(cfg.api_key)
    return jsonify({'ok': True, 'config': out})


@app.route('/api/translate/missing')
def api_translate_missing():
    limit = _num(request.args.get('limit'), 50, 1, 200)
    return jsonify({'count': ai_translate.count_missing(),
                    'rows': ai_translate.list_missing(limit)})


@app.route('/api/translate/one', methods=['POST'])
def api_translate_one():
    """单条翻译：{text} 或 {sid}；save=1 且 sid 有效时落库。"""
    d = request.json or {}
    sid = d.get('sid')
    text = (d.get('text') or '').strip()
    if sid and not text:
        with db.get_conn() as c:
            r = c.execute('SELECT text FROM sentences WHERE id=?', (sid,)).fetchone()
        if not r:
            return jsonify({'ok': False, 'error': '句子不存在'}), 404
        text = r['text']
    if not text:
        return jsonify({'ok': False, 'error': '翻译内容为空'}), 400
    res = ai_translate.translate_text(text, ai_translate.load_config())
    if not res.ok:
        return jsonify(res.to_dict()), 502
    out = res.to_dict()
    if d.get('save') and sid:
        out['saved'] = ai_translate.save_translation(sid, res.text, res.source)
        db.log('ai_translate', f'AI补译 #{sid}（{res.source}）')
    return jsonify(out)


@app.route('/api/translate/batch-missing', methods=['POST'])
def api_translate_batch_missing():
    """批量补译缺翻译例句（失败逐条跳过，不断流）。"""
    d = request.json or {}
    limit = _num(d.get('limit'), 20, 1, 200)
    cfg = ai_translate.load_config()
    if cfg.provider != 'mock' and not cfg.api_key:
        return jsonify({'ok': False,
                        'error': f'{cfg.provider} 未配置 API Key（请先在 AI 翻译面板填写，或切换 mock 演示）'}), 400
    stat = ai_translate.batch_translate_missing(limit=limit, config=cfg)
    db.log('ai_translate', f'批量补译：{stat["done"]}/{stat["total"]} 成功（{cfg.source_tag}）')
    stat['ok'] = True
    stat['source'] = cfg.source_tag
    stat['missing_left'] = ai_translate.count_missing()
    return jsonify(stat)


@app.route('/api/translate/batch-stream', methods=['POST'])
def api_translate_batch_stream():
    """SSE 流式批量补译：前端用 EventSource 接收逐条进度事件。

    每翻译完一条就推送 {done, total, text, translation, ok} 事件，
    最后推送 {type: 'complete'} 汇总。
    """
    d = request.json or {}
    limit = _num(d.get('limit'), 20, 1, 200)
    cfg = ai_translate.load_config()
    if cfg.provider != 'mock' and not cfg.api_key:
        return jsonify({'ok': False,
                        'error': f'{cfg.provider} 未配置 API Key'}), 400

    def generate():
        for evt in ai_translate.batch_translate_stream(limit=limit, config=cfg):
            yield f'data: {json.dumps(evt, ensure_ascii=False)}\n\n'
        db.log('ai_translate', f'SSE批量补译完成（{cfg.source_tag}）')

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/books/<int:bid>/translate-lesson', methods=['POST'])
def api_book_translate_lesson(bid, ):
    """翻译指定课程的全部缺译句子（或指定句子列表）。"""
    d = request.json or {}
    lesson_id = d.get('lesson_id')
    sids = d.get('sentence_ids') or []
    cfg = ai_translate.load_config()
    if cfg.provider != 'mock' and not cfg.api_key:
        return jsonify({'ok': False,
                        'error': f'{cfg.provider} 未配置 API Key（请先在 AI 翻译面板填写）'}), 400
    if not sids and lesson_id:
        _, rows = db.list_book_sentences(bid, lesson_id=lesson_id, per=200)
        sids = [r['id'] for r in rows if not (r.get('translation') or '').strip()]
    if not sids:
        return jsonify({'ok': True, 'translated': 0, 'message': '无需翻译'})
    results = ai_translate.translate_sentence_ids(sids, config=cfg)
    translated = sum(1 for r in results if r.get('ok') and not r.get('skipped'))
    db.log('ai_translate', f'课本 #{bid} 翻译 {translated}/{len(sids)} 句（{cfg.source_tag}）')
    return jsonify({'ok': True, 'translated': translated, 'total': len(sids),
                    'results': results, 'source': cfg.source_tag})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)

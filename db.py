# -*- coding: utf-8 -*-
"""数据库层：语料 / 汉字索引 / SRS复习记录 / 历史记录，完整增删改查"""
import sqlite3
import json
import time
import os
import threading

DB_PATH = os.path.join(os.path.dirname(__file__), 'kanji.db')
_lock = threading.Lock()

# ---------- 自建课本（v11）需要的表：老库升级时自动补建，不破坏既有数据 ----------
BOOK_DDL = '''
CREATE TABLE IF NOT EXISTS books(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    level TEXT DEFAULT '',
    note TEXT DEFAULT '',
    deadline TEXT,
    minutes_per_day INTEGER DEFAULT 30,
    target_stage INTEGER DEFAULT 7,
    active INTEGER DEFAULT 1,
    sort_order INTEGER DEFAULT 0,
    created_at REAL,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);
CREATE TABLE IF NOT EXISTS book_lessons(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    idx INTEGER DEFAULT 0,
    title TEXT DEFAULT '',
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_bl_book ON book_lessons(book_id, idx);
CREATE TABLE IF NOT EXISTS book_sentences(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    lesson_id INTEGER,
    idx INTEGER DEFAULT 0,
    sentence_id INTEGER NOT NULL,
    created_at REAL,
    UNIQUE(book_id, sentence_id)
);
CREATE INDEX IF NOT EXISTS idx_bs_book ON book_sentences(book_id, idx);
CREATE TABLE IF NOT EXISTS book_kanji(
    book_id INTEGER NOT NULL,
    kanji TEXT NOT NULL,
    word TEXT DEFAULT '',
    reading TEXT DEFAULT '',
    freq INTEGER DEFAULT 0,
    first_idx INTEGER DEFAULT 0,
    UNIQUE(book_id, kanji)
);
CREATE INDEX IF NOT EXISTS idx_bk_book ON book_kanji(book_id, first_idx);
CREATE TABLE IF NOT EXISTS book_words(
    book_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    reading TEXT DEFAULT '',
    kanji TEXT DEFAULT '',
    pos TEXT DEFAULT '',
    freq INTEGER DEFAULT 0,
    first_idx INTEGER DEFAULT 0,
    UNIQUE(book_id, word)
);
CREATE TABLE IF NOT EXISTS book_plan(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    is_new INTEGER DEFAULT 1,
    kanji TEXT NOT NULL,
    kind TEXT DEFAULT 'kanji',
    done INTEGER DEFAULT 0,
    created_at REAL,
    UNIQUE(book_id, day, kanji, is_new)
);
CREATE INDEX IF NOT EXISTS idx_bp_day ON book_plan(book_id, day);
CREATE TABLE IF NOT EXISTS book_progress(
    book_id INTEGER NOT NULL,
    kanji TEXT NOT NULL,
    kind TEXT DEFAULT 'kanji',
    state TEXT DEFAULT 'learning',
    note TEXT DEFAULT '',
    added_at REAL,
    done_at REAL,
    UNIQUE(book_id, kanji)
);
'''


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def checkpoint():
    """把 WAL 里的最新写入折回 kanji.db 本体（提交/备份数据库前必做）。

    WAL 模式下刚写入的数据可能还压在 kanji.db-wal 里：只复制/提交 kanji.db
    会得到「少了最后一次写入」的旧数据。dbtool.py 与「备份数据库」都会先调它。
    """
    with get_conn() as c:
        c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
    return True


def init_db():
    with get_conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS sentences(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT UNIQUE NOT NULL,
            translation TEXT,
            source TEXT,
            url TEXT,
            tokens TEXT,
            created_at REAL,
            translation_source TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS kanji_index(
            kanji TEXT NOT NULL,
            sentence_id INTEGER NOT NULL,
            word TEXT,
            word_reading TEXT,
            UNIQUE(kanji, sentence_id, word)
        );
        CREATE INDEX IF NOT EXISTS idx_ki_kanji ON kanji_index(kanji);
        CREATE INDEX IF NOT EXISTS idx_ki_sent ON kanji_index(sentence_id);
        CREATE TABLE IF NOT EXISTS srs(
            kanji TEXT PRIMARY KEY,
            stage INTEGER DEFAULT 0,
            next_due REAL,
            added_at REAL,
            last_at REAL,
            ok INTEGER DEFAULT 0,
            ng INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS fav_sentences(
            sentence_id INTEGER PRIMARY KEY,
            note TEXT DEFAULT '',
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS fav_words(
            word TEXT PRIMARY KEY,
            reading TEXT,
            note TEXT DEFAULT '',
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            type TEXT,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS songs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT DEFAULT '',
            lyrics TEXT NOT NULL,
            tokens TEXT,
            kanji_count INTEGER DEFAULT 0,
            created_at REAL,
            updated_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_songs_title ON songs(title);
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        ''')
        c.executescript(BOOK_DDL)


def _migrate():
    """兼容性迁移：为既有库补列/补表（不破坏任何数据）"""
    with get_conn() as c:
        try:
            c.execute('ALTER TABLE sentences ADD COLUMN orig_text TEXT')
        except sqlite3.OperationalError:
            pass
        # v18 AI 翻译：译文来源标记（''=人工/导入，'ai:<provider>:<model>'=AI 补译）
        try:
            c.execute("ALTER TABLE sentences ADD COLUMN translation_source TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # 字 / 词双轨（v12：计划与进度同时支持汉字与词汇）
        for tab in ('book_plan', 'book_progress'):
            try:
                c.execute(f"ALTER TABLE {tab} ADD COLUMN kind TEXT DEFAULT 'kanji'")
            except sqlite3.OperationalError:
                pass
        # 词汇艾宾浩斯（v13：SRS 主键列沿用 kanji 之名、实际存放「汉字或单词」；
        # kind 区分字/词，reading 存放单词读音供复习卡展示）
        for ddl in ("ALTER TABLE srs ADD COLUMN kind TEXT DEFAULT 'kanji'",
                    "ALTER TABLE srs ADD COLUMN reading TEXT DEFAULT ''"):
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        # KTV 歌词表（旧库升级时补建）
        c.execute('''CREATE TABLE IF NOT EXISTS songs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT DEFAULT '',
            lyrics TEXT NOT NULL,
            tokens TEXT,
            kanji_count INTEGER DEFAULT 0,
            created_at REAL,
            updated_at REAL
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_songs_title ON songs(title)')
        # v20 注音引擎版本号：存量 tokens 落后于当前引擎时 get_song 惰性重注（见 ktv.ANNO_VER）
        try:
            c.execute('ALTER TABLE songs ADD COLUMN anno_ver INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass
        # 自建课本表（v11 老库升级补建）
        c.executescript(BOOK_DDL)


_migrate()


def get_setting(key, default=None):
    with get_conn() as c:
        r = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return r['value'] if r else default


def set_setting(key, value):
    with _lock, get_conn() as c:
        c.execute('INSERT INTO settings(key,value) VALUES(?,?) '
                  'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))


def log(type_, detail):
    with _lock, get_conn() as c:
        c.execute('INSERT INTO history(ts,type,detail) VALUES(?,?,?)',
                  (time.time(), type_, detail))


# ---------- 语料 CRUD ----------

def add_sentence(text, translation, source, url, tokens, kanji_words, orig_text=None):
    """插入句子并建立汉字索引；重复返回 None"""
    with _lock, get_conn() as c:
        try:
            cur = c.execute(
                'INSERT INTO sentences(text,translation,source,url,tokens,created_at,orig_text) VALUES(?,?,?,?,?,?,?)',
                (text, translation, source, url, json.dumps(tokens, ensure_ascii=False), time.time(), orig_text))
        except sqlite3.IntegrityError:
            return None
        sid = cur.lastrowid
        for kanji, word, wr in kanji_words:
            c.execute('INSERT OR IGNORE INTO kanji_index(kanji,sentence_id,word,word_reading) VALUES(?,?,?,?)',
                      (kanji, sid, word, wr))
        return sid


def update_sentence(sid, text=None, translation=None, tokens=None, kanji_words=None, orig_text=None,
                  translation_source=None):
    with _lock, get_conn() as c:
        if orig_text is not None:
            c.execute('UPDATE sentences SET orig_text=? WHERE id=?', (orig_text, sid))
        if translation_source is not None:
            c.execute('UPDATE sentences SET translation_source=? WHERE id=?', (translation_source, sid))
        if text is not None:
            c.execute('UPDATE sentences SET text=?, tokens=? WHERE id=?',
                      (text, json.dumps(tokens, ensure_ascii=False), sid))
            c.execute('DELETE FROM kanji_index WHERE sentence_id=?', (sid,))
            for kanji, word, wr in (kanji_words or []):
                c.execute('INSERT OR IGNORE INTO kanji_index(kanji,sentence_id,word,word_reading) VALUES(?,?,?,?)',
                          (kanji, sid, word, wr))
        if translation is not None:
            c.execute('UPDATE sentences SET translation=? WHERE id=?', (translation, sid))


def delete_sentence(sid):
    with _lock, get_conn() as c:
        c.execute('DELETE FROM sentences WHERE id=?', (sid,))
        c.execute('DELETE FROM kanji_index WHERE sentence_id=?', (sid,))


def query_sentences(q=None, kanji=None, page=1, per=20, missing_trans=False):
    with get_conn() as c:
        where, args = [], []
        if q:
            where.append('(text LIKE ? OR translation LIKE ?)')
            args += [f'%{q}%', f'%{q}%']
        if kanji:
            where.append('id IN (SELECT sentence_id FROM kanji_index WHERE kanji=?)')
            args.append(kanji)
        if missing_trans:
            where.append("(translation IS NULL OR TRIM(COALESCE(translation,''))='')")
        w = ('WHERE ' + ' AND '.join(where)) if where else ''
        total = c.execute(f'SELECT COUNT(*) n FROM sentences {w}', args).fetchone()['n']
        rows = c.execute(
            f'SELECT * FROM sentences {w} ORDER BY id DESC LIMIT ? OFFSET ?',
            args + [per, (page - 1) * per]).fetchall()
        return total, [dict(r) for r in rows]


def sentence_exists(text):
    with get_conn() as c:
        return c.execute('SELECT 1 FROM sentences WHERE text=?', (text,)).fetchone() is not None


# ---------- KTV 歌曲 CRUD ----------

def add_song(title, artist, lyrics, tokens, kanji_count, anno_ver=0):
    now = time.time()
    with _lock, get_conn() as c:
        cur = c.execute(
            'INSERT INTO songs(title,artist,lyrics,tokens,kanji_count,anno_ver,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (title, artist or '', lyrics,
             json.dumps(tokens, ensure_ascii=False), kanji_count, int(anno_ver), now, now))
        return cur.lastrowid


def update_song(sid, title=None, artist=None, lyrics=None, tokens=None, kanji_count=None, anno_ver=None):
    with _lock, get_conn() as c:
        if title is not None:
            c.execute('UPDATE songs SET title=? WHERE id=?', (title, sid))
        if artist is not None:
            c.execute('UPDATE songs SET artist=? WHERE id=?', (artist, sid))
        if anno_ver is not None:
            c.execute('UPDATE songs SET anno_ver=? WHERE id=?', (int(anno_ver), sid))
        if lyrics is not None:
            c.execute('UPDATE songs SET lyrics=?, tokens=?, kanji_count=?, updated_at=? WHERE id=?',
                      (lyrics,
                       json.dumps(tokens, ensure_ascii=False) if tokens is not None else None,
                       kanji_count or 0, time.time(), sid))
        else:
            c.execute('UPDATE songs SET updated_at=? WHERE id=?', (time.time(), sid))


def delete_song(sid):
    with _lock, get_conn() as c:
        c.execute('DELETE FROM songs WHERE id=?', (sid,))


def update_song_tokens(sid, tokens, anno_ver=None, kanji_count=None):
    """只更新 token（分词标记补算 / 引擎版本升级重注回写用）。"""
    with _lock, get_conn() as c:
        c.execute('UPDATE songs SET tokens=? WHERE id=?',
                  (json.dumps(tokens, ensure_ascii=False), sid))
        if anno_ver is not None:
            c.execute('UPDATE songs SET anno_ver=? WHERE id=?', (int(anno_ver), sid))
        if kanji_count is not None:
            c.execute('UPDATE songs SET kanji_count=? WHERE id=?', (int(kanji_count), sid))


def get_song(sid):
    with get_conn() as c:
        r = c.execute('SELECT * FROM songs WHERE id=?', (sid,)).fetchone()
        return dict(r) if r else None


def list_songs(q='', limit=200):
    """按更新时间倒序；可按歌名/歌手/歌词模糊搜索。"""
    with get_conn() as c:
        if q:
            rows = c.execute(
                'SELECT id,title,artist,kanji_count,length(lyrics)-length(replace(lyrics,char(10),\'\'))+1 lines,'
                'updated_at FROM songs WHERE title LIKE ? OR artist LIKE ? OR lyrics LIKE ? '
                'ORDER BY updated_at DESC LIMIT ?',
                (f'%{q}%', f'%{q}%', f'%{q}%', limit)).fetchall()
        else:
            rows = c.execute(
                'SELECT id,title,artist,kanji_count,length(lyrics)-length(replace(lyrics,char(10),\'\'))+1 lines,'
                'updated_at FROM songs ORDER BY updated_at DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]


def _mn(a, b):
    return a if b is None else (b if a is None else min(a, b))


def _mx(a, b):
    return a if b is None else (b if a is None else max(a, b))


def upsert_srs(rows):
    """导入备份时合并 SRS：保留更高阶段、更早的 next_due/added_at、更晚的 last_at，累计 ok/ng（NULL 安全）。"""
    added = merged = 0
    with _lock, get_conn() as c:
        for r in rows:
            ex = c.execute('SELECT * FROM srs WHERE kanji=?', (r['kanji'],)).fetchone()
            kind = r.get('kind') or ('words' if len(r['kanji'] or '') > 1 else 'kanji')
            reading = r.get('reading') or ''
            if ex:
                c.execute('UPDATE srs SET stage=?,next_due=?,added_at=?,last_at=?,ok=?,ng=?,'
                          'kind=?,reading=? WHERE kanji=?',
                          (_mx(ex['stage'], r['stage'] or 0), _mn(ex['next_due'], r['next_due']),
                           _mn(ex['added_at'], r['added_at']), _mx(ex['last_at'], r['last_at']),
                           (ex['ok'] or 0) + (r['ok'] or 0), (ex['ng'] or 0) + (r['ng'] or 0),
                           ex['kind'] if ex['kind'] not in (None, '') else kind,
                           ex['reading'] or reading, r['kanji']))
                merged += 1
            else:
                c.execute('INSERT INTO srs(kanji,stage,next_due,added_at,last_at,ok,ng,kind,reading) '
                          'VALUES(?,?,?,?,?,?,?,?,?)',
                          (r['kanji'], r['stage'] or 0, r['next_due'], r['added_at'],
                           r['last_at'], r['ok'] or 0, r['ng'] or 0, kind, reading))
                added += 1
    return added, merged


def add_history_rows(rows):
    """导入历史（按 ts+type+detail 去重，导回自己的备份不会翻倍）。返回实际新增数。"""
    n = 0
    with _lock, get_conn() as c:
        for r in rows:
            cur = c.execute('''INSERT INTO history(ts,type,detail)
                         SELECT ?,?,? WHERE NOT EXISTS
                         (SELECT 1 FROM history WHERE ts=? AND type=? AND detail=?)''',
                            (r['ts'], r['type'], r['detail'], r['ts'], r['type'], r['detail']))
            n += cur.rowcount if cur.rowcount > 0 else 0
    return n


def import_fav_word(word, reading, note, created_at):
    with _lock, get_conn() as c:
        cur = c.execute('INSERT OR IGNORE INTO fav_words(word,reading,note,created_at) VALUES(?,?,?,?)',
                        (word, reading, note or '', created_at or time.time()))
        return cur.rowcount > 0


def import_fav_sentence(text, note, created_at):
    """按句子文本找回 id 再收藏（备份里的 sentence_id 在新库会变）。"""
    with _lock, get_conn() as c:
        row = c.execute('SELECT id FROM sentences WHERE text=?', (text,)).fetchone()
        if not row:
            return False
        cur = c.execute('INSERT OR IGNORE INTO fav_sentences(sentence_id,note,created_at) VALUES(?,?,?)',
                        (row['id'], note or '', created_at or time.time()))
        return cur.rowcount > 0


def song_exists(title, lyrics):
    with get_conn() as c:
        return c.execute('SELECT 1 FROM songs WHERE title=? AND lyrics=?',
                         (title, lyrics)).fetchone() is not None


# ---------- 汉字 ----------

def kanji_stats(learned=None, q=None, page=1, per=50):
    """按语料频次排序的汉字表，附带 SRS 状态"""
    with get_conn() as c:
        rows = c.execute('''
            SELECT ki.kanji, COUNT(DISTINCT ki.sentence_id) freq,
                   s.stage, s.next_due, s.ok, s.ng, s.added_at
            FROM kanji_index ki LEFT JOIN srs s ON s.kanji = ki.kanji
            GROUP BY ki.kanji ORDER BY freq DESC
        ''').fetchall()
        out = [dict(r) for r in rows]
        if q:
            out = [r for r in out if r['kanji'] == q]
        if learned is True:
            out = [r for r in out if r['stage'] is not None]
        elif learned is False:
            out = [r for r in out if r['stage'] is None]
        total = len(out)
        return total, out[(page - 1) * per: page * per]


def kanji_words(kanji, limit=10):
    with get_conn() as c:
        rows = c.execute('''
            SELECT word, word_reading, COUNT(*) n FROM kanji_index
            WHERE kanji=? GROUP BY word, word_reading ORDER BY n DESC LIMIT ?
        ''', (kanji, limit)).fetchall()
        return [dict(r) for r in rows]


def top_words(limit=10):
    """全库高频多字词（排除已在 SRS 中的），供「学新词」推荐。"""
    with get_conn() as c:
        rows = c.execute("""
            SELECT ki.word word, ki.word_reading reading,
                   COUNT(DISTINCT ki.sentence_id) freq
            FROM kanji_index ki LEFT JOIN srs s ON s.kanji = ki.word
            WHERE LENGTH(ki.word) > 1 AND s.kanji IS NULL
            GROUP BY ki.word, ki.word_reading
            ORDER BY freq DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def sentences_for_kanji(kanji, limit=200):
    """该汉字的全部例句：短句在前（更易读），同长度新句在前"""
    with get_conn() as c:
        rows = c.execute('''
            SELECT s.* FROM sentences s
            JOIN kanji_index ki ON ki.sentence_id = s.id
            WHERE ki.kanji=? GROUP BY s.id
            ORDER BY LENGTH(s.text) ASC, s.id DESC LIMIT ?
        ''', (kanji, limit)).fetchall()
        return [dict(r) for r in rows]


def sentences_for_word(word, limit=200):
    """含某词汇的全部例句（词汇 SRS 取例 / 单词查例）：短句在前，同长度新句在前"""
    with get_conn() as c:
        rows = c.execute('''
            SELECT * FROM sentences WHERE text LIKE ?
            ORDER BY LENGTH(text) ASC, id DESC LIMIT ?
        ''', (f'%{word}%', limit)).fetchall()
        return [dict(r) for r in rows]
# ================================================================
# 自建课本（v11）：课本 / 课 / 句 / 字 / 词 / 计划 / 进度 完整增删改查
# ================================================================

def add_book(title, author='', level='', note='', deadline=None,
             minutes_per_day=30, target_stage=7, active=1):
    now = time.time()
    with _lock, get_conn() as c:
        cur = c.execute(
            'INSERT INTO books(title,author,level,note,deadline,minutes_per_day,'
            'target_stage,active,sort_order,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?,?,0,?,?)',
            (title, author or '', level or '', note or '', deadline or None,
             int(minutes_per_day or 30), int(target_stage or 7), 1 if active else 0, now, now))
        return cur.lastrowid


def get_book(book_id):
    with get_conn() as c:
        r = c.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()
        return dict(r) if r else None


def find_book_by_title(title):
    with get_conn() as c:
        r = c.execute('SELECT * FROM books WHERE title=?', (title,)).fetchone()
        return dict(r) if r else None


def update_book(book_id, **kw):
    """只允许白名单字段更新（标题/作者/难度/备注/截止日/每日时长/目标阶段/纳入学习）"""
    fields = {'title', 'author', 'level', 'note', 'deadline',
              'minutes_per_day', 'target_stage', 'active', 'sort_order'}
    sets, args = [], []
    for k, v in kw.items():
        if k in fields and v is not None:
            sets.append(f'{k}=?')
            args.append(int(v) if k in ('minutes_per_day', 'target_stage', 'active', 'sort_order') else v)
    if not sets:
        return False
    sets.append('updated_at=?')
    args += [time.time(), book_id]
    with _lock, get_conn() as c:
        c.execute(f'UPDATE books SET {", ".join(sets)} WHERE id=?', args)
    return True


def delete_book(book_id):
    """删书同时清掉它的课/句/字/词/计划/进度（语料本体不删，其他书/复习不受影响）"""
    with _lock, get_conn() as c:
        for t in ('book_lessons', 'book_sentences', 'book_kanji',
                  'book_words', 'book_plan', 'book_progress'):
            c.execute(f'DELETE FROM {t} WHERE book_id=?', (book_id,))
        c.execute('DELETE FROM books WHERE id=?', (book_id,))

def list_books(q=''):
    """课本列表 + 规模统计 + 进度（已学/长期记忆自动识别）"""
    with get_conn() as c:
        if q:
            rows = c.execute('SELECT * FROM books WHERE title LIKE ? OR author LIKE ? '
                             'OR note LIKE ? ORDER BY sort_order, id',
                             (f'%{q}%', f'%{q}%', f'%{q}%')).fetchall()
        else:
            rows = c.execute('SELECT * FROM books ORDER BY sort_order, id').fetchall()
        out = []
        for r in rows:
            b = dict(r)
            bid = b['id']
            b['lessons'] = c.execute('SELECT COUNT(*) n FROM book_lessons WHERE book_id=?',
                                     (bid,)).fetchone()['n']
            b['sentences'] = c.execute('SELECT COUNT(*) n FROM book_sentences WHERE book_id=?',
                                       (bid,)).fetchone()['n']
            b['kanji_total'] = c.execute('SELECT COUNT(*) n FROM book_kanji WHERE book_id=?',
                                         (bid,)).fetchone()['n']
            b['words_total'] = c.execute('SELECT COUNT(*) n FROM book_words WHERE book_id=?',
                                         (bid,)).fetchone()['n']
            st = c.execute(
                'SELECT SUM(CASE WHEN s.stage IS NOT NULL THEN 1 ELSE 0 END) learned, '
                'SUM(CASE WHEN s.stage>=7 THEN 1 ELSE 0 END) mature, '
                'SUM(CASE WHEN s.next_due IS NOT NULL AND s.next_due<=? THEN 1 ELSE 0 END) due '
                'FROM book_kanji bk LEFT JOIN srs s ON s.kanji=bk.kanji WHERE bk.book_id=?',
                (time.time(), bid)).fetchone()
            b['learned'] = st['learned'] or 0
            b['mature'] = st['mature'] or 0
            b['due'] = st['due'] or 0
            b['skipped'] = c.execute(
                "SELECT COUNT(*) n FROM book_progress WHERE book_id=? AND state='skip'",
                (bid,)).fetchone()['n']
            b['done_marks'] = c.execute(
                "SELECT COUNT(*) n FROM book_progress WHERE book_id=? AND state='done'",
                (bid,)).fetchone()['n']
            b['progress'] = round(100.0 * b['learned'] / b['kanji_total'], 1) if b['kanji_total'] else 0.0
            b['plan_days'] = c.execute('SELECT COUNT(DISTINCT day) n FROM book_plan WHERE book_id=?',
                                       (bid,)).fetchone()['n']
            out.append(b)
        return out


def set_books_active(book_ids, active):
    with _lock, get_conn() as c:
        for bid in book_ids:
            c.execute('UPDATE books SET active=?, updated_at=? WHERE id=?',
                      (1 if active else 0, time.time(), bid))


# ---------- 课（章节） ----------

def add_lesson(book_id, idx, title):
    with _lock, get_conn() as c:
        cur = c.execute('INSERT INTO book_lessons(book_id,idx,title,created_at) VALUES(?,?,?,?)',
                        (book_id, idx, title or '', time.time()))
        return cur.lastrowid


def list_lessons(book_id):
    with get_conn() as c:
        rows = c.execute(
            'SELECT l.*, (SELECT COUNT(*) FROM book_sentences bs WHERE bs.lesson_id=l.id) n_sentences, '
            '(SELECT COUNT(*) FROM book_sentences bs WHERE bs.lesson_id=l.id) n '
            'FROM book_lessons l WHERE l.book_id=? ORDER BY l.idx, l.id', (book_id,)).fetchall()
        return [dict(r) for r in rows]


def update_lesson(lesson_id, title=None, idx=None):
    with _lock, get_conn() as c:
        if title is not None:
            c.execute('UPDATE book_lessons SET title=? WHERE id=?', (title, lesson_id))
        if idx is not None:
            c.execute('UPDATE book_lessons SET idx=? WHERE id=?', (int(idx), lesson_id))


def delete_lesson(lesson_id, keep_sentences=True):
    """删课；keep_sentences=True 时句子退回「未分课」而不丢内容"""
    with _lock, get_conn() as c:
        if keep_sentences:
            c.execute('UPDATE book_sentences SET lesson_id=NULL WHERE lesson_id=?', (lesson_id,))
        else:
            c.execute('DELETE FROM book_sentences WHERE lesson_id=?', (lesson_id,))
        c.execute('DELETE FROM book_lessons WHERE id=?', (lesson_id,))


# ---------- 课本句子 ----------

def add_book_sentence(book_id, lesson_id, idx, sentence_id):
    with _lock, get_conn() as c:
        cur = c.execute('INSERT OR IGNORE INTO book_sentences(book_id,lesson_id,idx,sentence_id,created_at) '
                        'VALUES(?,?,?,?,?)', (book_id, lesson_id, idx, sentence_id, time.time()))
        return cur.rowcount > 0


def list_book_sentences(book_id, lesson_id=None, q=None, page=1, per=30):
    where, args = ['bs.book_id=?'], [book_id]
    if lesson_id:
        where.append('bs.lesson_id=?')
        args.append(lesson_id)
    if q:
        where.append('(s.text LIKE ? OR s.translation LIKE ?)')
        args += [f'%{q}%', f'%{q}%']
    w = 'WHERE ' + ' AND '.join(where)
    with get_conn() as c:
        total = c.execute(f'SELECT COUNT(*) n FROM book_sentences bs '
                          f'JOIN sentences s ON s.id=bs.sentence_id {w}', args).fetchone()['n']
        rows = c.execute(
            f'SELECT s.*, bs.id bs_id, bs.idx bs_idx, bs.lesson_id lesson_id, l.title lesson_title, '
            f'b.title book_title '
            f'FROM book_sentences bs JOIN sentences s ON s.id=bs.sentence_id '
            f'LEFT JOIN book_lessons l ON l.id=bs.lesson_id JOIN books b ON b.id=bs.book_id {w} '
            f'ORDER BY bs.idx, bs.id LIMIT ? OFFSET ?', args + [per, (page - 1) * per]).fetchall()
        return total, [dict(r) for r in rows]


def clear_book_links(book_id):
    """清空本书的课与句子「链接」（句子本体保留在语料库）——幂等重建课本时使用"""
    with _lock, get_conn() as c:
        c.execute('DELETE FROM book_sentences WHERE book_id=?', (book_id,))
        c.execute('DELETE FROM book_lessons WHERE book_id=?', (book_id,))


def delete_book_sentence(book_id, sentence_id):
    with _lock, get_conn() as c:
        c.execute('DELETE FROM book_sentences WHERE book_id=? AND sentence_id=?', (book_id, sentence_id))


# ---------- 课本字/词索引 ----------

def replace_book_index(book_id, kanji_rows, word_rows):
    """重建本书的字/词索引（先删后插）"""
    with _lock, get_conn() as c:
        c.execute('DELETE FROM book_kanji WHERE book_id=?', (book_id,))
        c.execute('DELETE FROM book_words WHERE book_id=?', (book_id,))
        c.executemany('INSERT OR REPLACE INTO book_kanji(book_id,kanji,word,reading,freq,first_idx) '
                      'VALUES(?,?,?,?,?,?)', [(book_id,) + tuple(r) for r in kanji_rows])
        c.executemany('INSERT OR REPLACE INTO book_words(book_id,word,reading,kanji,pos,freq,first_idx) '
                      'VALUES(?,?,?,?,?,?,?)', [(book_id,) + tuple(r) for r in word_rows])


def list_book_kanji(book_id, filter_='all', q=None, book_ids=None, page=1, per=100):
    """本书（或多本书合集）的汉字表 + 全局 SRS 状态 + 本书进度标记。
    filter_: all | new(未学) | learning(已学未长期) | mature(stage>=7) | due(到期)
             | skip(已跳过) | done(已标记掌握)"""
    ids = book_ids or [book_id]
    ph = ','.join('?' * len(ids))
    where, args = [f'bk.book_id IN ({ph})'], list(ids)
    if q:
        where.append('bk.kanji=?')
        args.append(q)
    if filter_ == 'new':
        where.append('s.stage IS NULL')
    elif filter_ == 'learning':
        where.append('s.stage IS NOT NULL AND (s.stage<7 OR s.stage IS NULL)')
    elif filter_ == 'mature':
        where.append('s.stage>=7')
    elif filter_ == 'due':
        where.append('s.next_due IS NOT NULL AND s.next_due<=?')
        args.append(time.time())
    elif filter_ == 'skip':
        where.append("p.state='skip'")
    elif filter_ == 'done':
        where.append("p.state='done'")
    w = 'WHERE ' + ' AND '.join(where)
    sql_base = (f'FROM book_kanji bk LEFT JOIN srs s ON s.kanji=bk.kanji '
                f'LEFT JOIN book_progress p ON p.kanji=bk.kanji AND p.book_id=bk.book_id {w}')
    with get_conn() as c:
        total = c.execute(f'SELECT COUNT(DISTINCT bk.kanji) n {sql_base}', args).fetchone()['n']
        rows = c.execute(
            f'SELECT bk.kanji kanji, MIN(bk.first_idx) first_idx, SUM(bk.freq) freq, '
            f'MAX(bk.word) word, MAX(bk.reading) reading, '
            f'MAX(s.stage) srs_stage, MAX(s.next_due) next_due, MAX(s.ok) ok, MAX(s.ng) ng, '
            f'MAX(p.state) progress {sql_base} '
            f'GROUP BY bk.kanji ORDER BY first_idx, kanji LIMIT ? OFFSET ?',
            args + [per, (page - 1) * per]).fetchall()
        return total, [dict(r) for r in rows]


def list_book_words(book_id, q=None, has_kanji=None, page=1, per=100):
    where, args = ['book_id=?'], [book_id]
    if q:
        where.append('(word LIKE ? OR reading LIKE ?)')
        args += [f'%{q}%', f'%{q}%']
    if has_kanji is True:
        where.append("kanji<>''")
    elif has_kanji is False:
        where.append("kanji=''")
    w = 'WHERE ' + ' AND '.join(where)
    with get_conn() as c:
        total = c.execute(f'SELECT COUNT(*) n FROM book_words {w}', args).fetchone()['n']
        rows = c.execute(f'SELECT * FROM book_words {w} ORDER BY first_idx, word LIMIT ? OFFSET ?',
                         args + [per, (page - 1) * per]).fetchall()
        return total, [dict(r) for r in rows]


def book_kanji_set(book_ids, exclude_states=('skip', 'done')):
    """多本书的汉字集合（用于计划/学习；默认剔除已跳过与已标记掌握的）"""
    ids = list(book_ids)
    if not ids:
        return []
    ph = ','.join('?' * len(ids))
    with get_conn() as c:
        rows = c.execute(
            f'SELECT bk.kanji kanji, MIN(bk.first_idx) first_idx, SUM(bk.freq) freq '
            f'FROM book_kanji bk LEFT JOIN book_progress p '
            f'ON p.kanji=bk.kanji AND p.book_id=bk.book_id '
            f'WHERE bk.book_id IN ({ph}) GROUP BY bk.kanji ORDER BY first_idx, kanji', ids).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['state'] = c.execute(
                f"SELECT state FROM book_progress WHERE kanji=? AND book_id IN ({ph}) LIMIT 1",
                [d['kanji']] + ids).fetchone()
            st = d['state']
            if exclude_states and st and st['state'] in exclude_states:
                continue
            d.pop('state')
            out.append(d)
        return out
def book_words_set(book_ids, exclude_states=('skip', 'done')):
    """多本书的词汇集合（用于计划/学习；默认剔除已跳过与已标记掌握的）"""
    ids = list(book_ids)
    if not ids:
        return []
    ph = ','.join('?' * len(ids))
    with get_conn() as c:
        rows = c.execute(
            f'SELECT bw.word word, bw.reading reading, bw.kanji kanji, bw.pos pos, '
            f'MIN(bw.first_idx) first_idx, SUM(bw.freq) freq '
            f'FROM book_words bw '
            f'WHERE bw.book_id IN ({ph}) GROUP BY bw.word ORDER BY first_idx, word', ids).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            st = c.execute(
                f"SELECT state FROM book_progress WHERE kanji=? AND book_id IN ({ph}) LIMIT 1",
                [d['word']] + ids).fetchone()
            if exclude_states and st and st['state'] in exclude_states:
                continue
            out.append(d)
        return out


# ---------- 学习计划（截止日 + 艾宾浩斯曲线排程） ----------

def save_book_plan(book_id, rows):
    """整体替换某本书的计划（rows: [(day, is_new, kanji)] 或 [(day, is_new, kanji, kind)]）"""
    with _lock, get_conn() as c:
        c.execute('DELETE FROM book_plan WHERE book_id=?', (book_id,))
        norm = []
        for r in rows:
            d, is_new, k = r[0], r[1], r[2]
            kind = r[3] if len(r) > 3 and r[3] in ('kanji', 'words') else \
                ('words' if len(k or '') > 1 else 'kanji')
            norm.append((book_id, d, 1 if is_new else 0, k, kind, time.time()))
        c.executemany('INSERT OR IGNORE INTO book_plan(book_id,day,is_new,kanji,kind,done,created_at) '
                      'VALUES(?,?,?,?,?,0,?)', norm)


def load_book_plan(book_ids):
    """读取多本书的计划行（按天聚合由上层完成）"""
    ids = list(book_ids)
    if not ids:
        return []
    ph = ','.join('?' * len(ids))
    with get_conn() as c:
        rows = c.execute(f'SELECT * FROM book_plan WHERE book_id IN ({ph}) '
                         f'ORDER BY day, is_new DESC, id', ids).fetchall()
        return [dict(r) for r in rows]


def clear_book_plan(book_ids):
    ids = list(book_ids)
    if not ids:
        return 0
    ph = ','.join('?' * len(ids))
    with _lock, get_conn() as c:
        cur = c.execute(f'DELETE FROM book_plan WHERE book_id IN ({ph})', ids)
        return cur.rowcount


def remap_word_keys(book_id, mapping):
    """词条键迁移（旧 lemma 形 → 新词典展示形）：同步 book_plan / book_progress / srs。

    重建索引把词条从「此れ/箇月/ヨサノ」这类旧键升级为「これ/一ヶ月/与謝野晶子」时，
    既有计划行、进度标记与全局 SRS 记录跟着改键，勾选/复习状态原样保留；
    目标键已存在（多个旧键合并成同一个新词）时合并去重，done/进度取两者较优。"""
    if not mapping:
        return 0
    n = 0
    with _lock, get_conn() as c:
        for old, new in mapping.items():
            if not old or not new or old == new:
                continue
            # --- book_plan：UNIQUE(book_id, day, kanji, is_new)，冲突则合并 ---
            for r in c.execute('SELECT id, day, is_new, done FROM book_plan '
                               'WHERE book_id=? AND kanji=?', (book_id, old)).fetchall():
                dup = c.execute('SELECT id, done FROM book_plan '
                                'WHERE book_id=? AND day=? AND kanji=? AND is_new=?',
                                (book_id, r['day'], new, r['is_new'])).fetchone()
                if dup:
                    if r['done'] and not dup['done']:
                        c.execute('UPDATE book_plan SET done=1 WHERE id=?', (dup['id'],))
                    c.execute('DELETE FROM book_plan WHERE id=?', (r['id'],))
                else:
                    c.execute("UPDATE book_plan SET kanji=?, kind='words' WHERE id=?",
                              (new, r['id']))
                n += 1
            # --- book_progress：UNIQUE(book_id, kanji)，冲突保留已有目标行 ---
            r = c.execute('SELECT rowid FROM book_progress WHERE book_id=? AND kanji=?',
                          (book_id, old)).fetchone()
            if r:
                dup = c.execute('SELECT rowid FROM book_progress WHERE book_id=? AND kanji=?',
                                (book_id, new)).fetchone()
                if dup:
                    c.execute('DELETE FROM book_progress WHERE rowid=?', (r['rowid'],))
                else:
                    c.execute("UPDATE book_progress SET kanji=?, kind='words' WHERE rowid=?",
                              (new, r['rowid']))
                n += 1
            # --- srs：kanji 为主键（全局表，只迁移词条），冲突保留已有目标行 ---
            r = c.execute("SELECT kanji FROM srs WHERE kanji=? AND kind='words'",
                          (old,)).fetchone()
            if r:
                dup = c.execute('SELECT kanji FROM srs WHERE kanji=?', (new,)).fetchone()
                if dup:
                    c.execute('DELETE FROM srs WHERE kanji=?', (old,))
                else:
                    c.execute('UPDATE srs SET kanji=? WHERE kanji=?', (new, old))
                n += 1
    return n


def set_plan_done(book_ids, day=None, kanji=None, done=1):
    """标记计划的某天（或某个字/词）为已完成/未完成；book_ids 为空 = 作用于全部书"""
    ids = list(book_ids or [])
    where, args = [], []
    if ids:
        ph = ','.join('?' * len(ids))
        where.append(f'book_id IN ({ph})')
        args += ids
    if day:
        where.append('day=?')
        args.append(day)
    if kanji:
        where.append('kanji=?')
        args.append(kanji)
    if not where:      # 无任何限定 = 会全表误改，直接拒绝
        return 0
    with _lock, get_conn() as c:
        cur = c.execute(f'UPDATE book_plan SET done=? WHERE {" AND ".join(where)}',
                        [1 if done else 0] + args)
        return cur.rowcount


# ---------- 本书进度（增删改查保存） ----------

def set_book_progress(book_id, kanji, state, note='', kind=None):
    """state: learning(在学) | done(已掌握·不计入计划) | skip(跳过·不计入计划)；
    kanji 列存放「汉字或单词」，kind 未指定时按长度自动推断"""
    now = time.time()
    kind = kind if kind in ('kanji', 'words') else ('words' if len(kanji or '') > 1 else 'kanji')
    with _lock, get_conn() as c:
        c.execute('INSERT INTO book_progress(book_id,kanji,kind,state,note,added_at,done_at) '
                  'VALUES(?,?,?,?,?,?,?) ON CONFLICT(book_id,kanji) DO UPDATE SET '
                  'kind=excluded.kind, state=excluded.state, note=excluded.note, '
                  'done_at=excluded.done_at',
                  (book_id, kanji, kind, state or 'learning', note or '', now,
                   now if state in ('done', 'skip') else None))


def list_book_progress(book_id, state=None):
    where, args = ['book_id=?'], [book_id]
    if state:
        where.append('state=?')
        args.append(state)
    with get_conn() as c:
        rows = c.execute(f'SELECT * FROM book_progress WHERE {" AND ".join(where)} '
                         f'ORDER BY added_at DESC', args).fetchall()
        return [dict(r) for r in rows]


def delete_book_progress(book_id, kanji=None, kind=None):
    with _lock, get_conn() as c:
        if kanji and kind:
            cur = c.execute('DELETE FROM book_progress WHERE book_id=? AND kanji=? AND kind=?',
                            (book_id, kanji, kind))
        elif kanji:
            cur = c.execute('DELETE FROM book_progress WHERE book_id=? AND kanji=?', (book_id, kanji))
        elif kind:
            cur = c.execute('DELETE FROM book_progress WHERE book_id=? AND kind=?', (book_id, kind))
        else:
            cur = c.execute('DELETE FROM book_progress WHERE book_id=?', (book_id,))
        return cur.rowcount


def reset_book_plan_and_progress(book_id):
    """一键重置本书的计划与进度标记（不动全局 SRS 记忆数据）"""
    with _lock, get_conn() as c:
        c.execute('DELETE FROM book_plan WHERE book_id=?', (book_id,))
        c.execute('DELETE FROM book_progress WHERE book_id=?', (book_id,))
        c.execute('UPDATE books SET updated_at=? WHERE id=?', (time.time(), book_id))
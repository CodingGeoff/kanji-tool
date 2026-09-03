# -*- coding: utf-8 -*-
"""数据库层：语料 / 汉字索引 / SRS复习记录 / 历史记录，完整增删改查"""
import sqlite3
import json
import time
import os
import threading

DB_PATH = os.path.join(os.path.dirname(__file__), 'kanji.db')
_lock = threading.Lock()


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


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
            created_at REAL
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
        ''')


def _migrate():
    """兼容性迁移：为既有库补列/补表（不破坏任何数据）"""
    with get_conn() as c:
        try:
            c.execute('ALTER TABLE sentences ADD COLUMN orig_text TEXT')
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


_migrate()


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


def update_sentence(sid, text=None, translation=None, tokens=None, kanji_words=None, orig_text=None):
    with _lock, get_conn() as c:
        if orig_text is not None:
            c.execute('UPDATE sentences SET orig_text=? WHERE id=?', (orig_text, sid))
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


def query_sentences(q=None, kanji=None, page=1, per=20):
    with get_conn() as c:
        where, args = [], []
        if q:
            where.append('(text LIKE ? OR translation LIKE ?)')
            args += [f'%{q}%', f'%{q}%']
        if kanji:
            where.append('id IN (SELECT sentence_id FROM kanji_index WHERE kanji=?)')
            args.append(kanji)
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

def add_song(title, artist, lyrics, tokens, kanji_count):
    now = time.time()
    with _lock, get_conn() as c:
        cur = c.execute(
            'INSERT INTO songs(title,artist,lyrics,tokens,kanji_count,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?)',
            (title, artist or '', lyrics,
             json.dumps(tokens, ensure_ascii=False), kanji_count, now, now))
        return cur.lastrowid


def update_song(sid, title=None, artist=None, lyrics=None, tokens=None, kanji_count=None):
    with _lock, get_conn() as c:
        if title is not None:
            c.execute('UPDATE songs SET title=? WHERE id=?', (title, sid))
        if artist is not None:
            c.execute('UPDATE songs SET artist=? WHERE id=?', (artist, sid))
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

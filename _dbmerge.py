# -*- coding: utf-8 -*-
"""DB merge: local DB is the superset; remote only contributes new settings keys
and 4 history rows (today's v17 test data). Produce the merged "latest and fullest"
DB at _dbbackup/merged/kanji.db, leaving backups untouched."""
import os
import shutil
import sqlite3

BASE = r'd:\10_Workspace\kanji-tool\_dbbackup'
LOCAL = os.path.join(BASE, 'local', 'kanji.db')
REMOTE = os.path.join(BASE, 'remote', 'kanji.db')
OUTDIR = os.path.join(BASE, 'merged')
OUT = os.path.join(OUTDIR, 'kanji.db')


def counts(conn):
    stats = {}
    for t in ('sentences', 'history', 'songs', 'kanji_index', 'srs',
              'settings', 'fav_words', 'fav_sentences', 'book_plan'):
        stats[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    return stats


# 1) Checkpoint the local backup's WAL into its main file, then copy it out.
src = sqlite3.connect(LOCAL)
src.execute('PRAGMA wal_checkpoint(TRUNCATE)')
src.close()
os.makedirs(OUTDIR, exist_ok=True)
shutil.copy2(LOCAL, OUT)

# 2) Merge remote-only rows into the copied DB.
out = sqlite3.connect(OUT)
out.execute('PRAGMA journal_mode=WAL')
out.execute('ATTACH DATABASE ? AS r', (REMOTE,))
out.execute('BEGIN')

cur = out.execute(
    "INSERT INTO main.settings(key, value) "
    "SELECT r.key, r.value FROM r.settings r "
    "WHERE NOT EXISTS (SELECT 1 FROM main.settings s WHERE s.key = r.key)")
n_settings = cur.rowcount

cur = out.execute(
    "INSERT INTO main.history(ts, type, detail) "
    "SELECT r.ts, r.type, r.detail FROM r.history r "
    "WHERE NOT EXISTS (SELECT 1 FROM main.history h "
    "                  WHERE h.ts = r.ts AND h.type = r.type AND h.detail = r.detail)")
n_history = cur.rowcount

out.execute('COMMIT')
out.execute('DETACH DATABASE r')

# 3) Verify integrity and show the final stats.
ok = out.execute('PRAGMA integrity_check').fetchone()[0]
stats = counts(out)
print(f'integrity: {ok}')
print(f'merged settings keys added: {n_settings}, history rows added: {n_history}')
for t, n in stats.items():
    print(f'  {t}: {n}')
print('settings keys:', sorted(r[0] for r in out.execute('SELECT key FROM settings')))

out.execute('PRAGMA wal_checkpoint(TRUNCATE)')
out.close()
print(f'\nmerged DB written to {OUT}')

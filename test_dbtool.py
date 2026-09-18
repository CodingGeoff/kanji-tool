# -*- coding: utf-8 -*-
"""dbtool 测试：并集合并引擎（句子 id 重映射 / 进度取优 / 历史去重 / 黑名单 / 清理）、
WAL 折叠、git 历史黑名单，以及命令级全流程（save → merge → verify → publish → pull）。

全部在临时目录的迷你库上跑，不动仓库里的真库。
"""
import os
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, '.')

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


import dbtool as dt

SCHEMA = '''
CREATE TABLE sentences(
    id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT UNIQUE NOT NULL,
    translation TEXT, source TEXT, url TEXT, tokens TEXT, created_at REAL);
CREATE TABLE kanji_index(
    kanji TEXT NOT NULL, sentence_id INTEGER NOT NULL, word TEXT, word_reading TEXT,
    UNIQUE(kanji, sentence_id, word));
CREATE TABLE srs(
    kanji TEXT PRIMARY KEY, stage INTEGER DEFAULT 0, next_due REAL, added_at REAL,
    last_at REAL, ok INTEGER DEFAULT 0, ng INTEGER DEFAULT 0);
CREATE TABLE history(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, type TEXT, detail TEXT);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE songs(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, artist TEXT, lyrics TEXT);
CREATE TABLE books(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, author TEXT);
CREATE TABLE book_plan(
    id INTEGER PRIMARY KEY AUTOINCREMENT, book_id INTEGER, day TEXT, is_new INTEGER DEFAULT 1,
    kanji TEXT NOT NULL, done INTEGER DEFAULT 0, created_at REAL,
    kind TEXT DEFAULT 'kanji', UNIQUE(book_id, day, kanji, is_new));
CREATE TABLE fav_sentences(sentence_id INTEGER PRIMARY KEY, note TEXT, created_at REAL);
'''


def new_db(path):
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.commit()
    c.close()


def sent(c, text, sid=None, source='tatoeba'):
    if sid is None:
        c.execute('INSERT INTO sentences(text, source, created_at) VALUES(?,?,1)',
                  (text, source))
    else:
        c.execute('INSERT INTO sentences(id, text, source, created_at) VALUES(?,?,?,1)',
                  (sid, text, source))


def val(path, sql, *args):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(sql, args).fetchone()
    finally:
        c.close()


def num(path, sql, *args):
    r = val(path, sql, *args)
    return r[0] if r else None


def idmap(path):
    c = sqlite3.connect(path)
    d = {t: i for i, t in c.execute('SELECT id, text FROM sentences')}
    c.close()
    return d


def git(repo, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t'] + list(args),
                          cwd=repo, capture_output=True)


# ============ 1. 合并引擎（迷你库） ============
print('== 1. 合并引擎 ==')
TMP = tempfile.mkdtemp(prefix='dbtool_test_')
dt.set_root(TMP)
A = os.path.join(TMP, 'a.db')
B = os.path.join(TMP, 'b.db')
new_db(A)
new_db(B)

ca = sqlite3.connect(A)
sent(ca, 'S1', 1)
sent(ca, 'S2', 2)
sent(ca, 'S3', 3)
ca.execute('INSERT INTO kanji_index(kanji,sentence_id,word) VALUES(?,?,?)', ('日', 2, '日本'))
ca.execute("INSERT INTO srs(kanji,stage,last_at,ok) VALUES('日',1,100,1)")
ca.execute("INSERT INTO srs(kanji,stage,last_at,ok) VALUES('本',5,100,9)")
ca.execute("INSERT INTO history(ts,type,detail) VALUES(1,'fetch','x')")
ca.execute("INSERT INTO settings(key,value) VALUES('data_saver','1')")
ca.execute("INSERT INTO settings(key,value) VALUES('blank','')")
ca.execute("INSERT INTO book_plan(book_id,day,kanji,is_new,done) VALUES(1,'d1','日',1,0)")
ca.execute("INSERT INTO fav_sentences(sentence_id,note) VALUES(1,'收藏')")
ca.commit()
ca.close()

cb = sqlite3.connect(B)
sent(cb, 'S1', 1)
sent(cb, 'X2', 2)          # 源库 id=2 在本库里是另一句话 → 必须重映射，不能串位
sent(cb, 'S4', 4)
sent(cb, 'S5', 5)          # 只在源库有，但会被黑名单挡掉
cb.execute('INSERT INTO kanji_index(kanji,sentence_id,word) VALUES(?,?,?)', ('X', 2, 'X語'))
cb.execute('INSERT INTO kanji_index(kanji,sentence_id,word) VALUES(?,?,?)', ('S', 1, 'S1語'))
cb.execute('INSERT INTO kanji_index(kanji,sentence_id,word) VALUES(?,?,?)', ('五', 5, '五語'))
cb.execute("INSERT INTO srs(kanji,stage,last_at,ok) VALUES('日',3,50,2)")   # 阶段更高
cb.execute("INSERT INTO srs(kanji,stage,last_at,ok) VALUES('本',1,999,1)")  # 阶段更低
cb.execute("INSERT INTO history(ts,type,detail) VALUES(1,'fetch','x')")     # 同一条事件
cb.execute("INSERT INTO history(ts,type,detail) VALUES(2,'learn','y')")     # 新事件
cb.execute("INSERT INTO settings(key,value) VALUES('blank','filled')")
cb.execute("INSERT INTO settings(key,value) VALUES('edu_sessions','[]')")
cb.execute("INSERT INTO book_plan(book_id,day,kanji,is_new,done) VALUES(1,'d1','日',1,1)")
cb.commit()
cb.close()

report = dt.merge_db(A, [B], A, blocklist={'S5'})
check(report.added.get('sentences') == 2,
      f"补进 2 句（X2/S4）实际 {report.added.get('sentences')}")
m = idmap(A)
check(set(m) == {'S1', 'S2', 'S3', 'X2', 'S4'}, f'句子并集正确 {sorted(m)}')
check('S5' not in m, '黑名单里的句子没有被复活')
check(m['X2'] != 2, f"源库 id 撞车后重映射（X2 新 id={m['X2']}）")
row = val(A, 'SELECT sentence_id FROM kanji_index WHERE kanji=? AND word=?', 'X', 'X語')
check(row is not None and row[0] == m['X2'], '索引跟着重映射到正确句子（不串位）')
check(num(A, 'SELECT COUNT(*) FROM kanji_index WHERE sentence_id NOT IN '
             '(SELECT id FROM sentences)') == 0, '没有孤儿索引')
check(num(A, 'SELECT COUNT(*) FROM kanji_index WHERE kanji=? AND word=?', '五', '五語') == 0,
      '黑名单句子的索引也没有进来')
check(num(A, "SELECT stage FROM srs WHERE kanji='日'") == 3, 'SRS 取更高阶段 1→3')
check(num(A, "SELECT stage FROM srs WHERE kanji='本'") == 5, 'SRS 不被更低进度覆盖')
check(num(A, 'SELECT COUNT(*) FROM history') == 2, '历史按 (ts,type,detail) 去重')
check(num(A, "SELECT value FROM settings WHERE key='data_saver'") == '1', '同名设置以本库为准')
check(num(A, "SELECT value FROM settings WHERE key='blank'") == 'filled', '空值设置用源库补上')
check(num(A, "SELECT value FROM settings WHERE key='edu_sessions'") == '[]',
      '缺失的设置键补齐（云端 v17 配置）')
check(num(A, "SELECT done FROM book_plan WHERE day='d1'") == 1, 'book_plan 勾选取并（0+1→1）')
check(num(A, 'SELECT COUNT(*) FROM fav_sentences') == 1, '收藏表保持原样')
check(dt.integrity(A) == 'ok', '合并结果完整性 ok')

report2 = dt.merge_db(A, [B], A, blocklist={'S5'})
check(not report2.touched(), f'重复合并幂等（{report2.touched()}）')

cp = sqlite3.connect(A)
sent(cp, 'JUNK', 99)
cp.execute('INSERT INTO kanji_index(kanji,sentence_id,word) VALUES(?,?,?)', ('脏', 99, '脏语'))
cp.commit()
cp.close()
dt.merge_db(A, [], A, blocklist={'JUNK'}, purge=True)
check(num(A, "SELECT COUNT(*) FROM sentences WHERE text='JUNK'") == 0, '--purge-deleted 删除脏句子')
check(num(A, 'SELECT COUNT(*) FROM kanji_index WHERE sentence_id=99') == 0,
      '--purge-deleted 同时清掉它的索引')


# ============ 2. WAL 折叠（提交前必须做的那一步） ============
print('== 2. WAL 折叠 ==')
W = os.path.join(TMP, 'wal.db')
new_db(W)
c1 = sqlite3.connect(W)
check(c1.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal', '切到 WAL 模式')
sent(c1, 'W1', 1)
c1.commit()
check(os.path.exists(W + '-wal') and os.path.getsize(W + '-wal') > 0,
      '提交后数据仍压在 -wal 里（这正是「提交了却是旧数据」的根源）')
check(dt.checkpoint(W) == 'ok', 'checkpoint 成功')
check(os.path.getsize(W + '-wal') == 0, 'WAL 已折叠清空')
c1.close()
c2 = sqlite3.connect(W)
check(c2.execute("SELECT COUNT(*) FROM sentences WHERE text='W1'").fetchone()[0] == 1,
      '折叠后数据在主文件里')
c2.close()
D = os.path.join(TMP, 'copy.db')
dt.copy_db(W, D)
check(num(D, "SELECT COUNT(*) FROM sentences WHERE text='W1'") == 1,
      'copy_db 连边车一起拷，数据不丢')


# ============ 3. git 历史黑名单（不复活上游删掉的脏数据） ============
print('== 3. git 历史黑名单 ==')
G = tempfile.mkdtemp(prefix='dbtool_git_')
dt.set_root(G)
GDB = os.path.join(G, 'kanji.db')
new_db(GDB)
c = sqlite3.connect(GDB)
sent(c, 'A', 1)
sent(c, 'B', 2)
sent(c, 'C', 3)
c.commit()
c.close()
check(git(G, 'init', '-q').returncode == 0, 'git init')
git(G, 'add', 'kanji.db')
check(git(G, 'commit', '-qm', 'v1').returncode == 0, '提交 v1')
c = sqlite3.connect(GDB)
c.execute("DELETE FROM sentences WHERE text='C'")
c.commit()
c.close()
git(G, 'add', 'kanji.db')
check(git(G, 'commit', '-qm', 'v2').returncode == 0, '提交 v2（删掉 C）')
check(dt.deleted_texts(G, 2) == {'C'}, f"历史黑名单 = {dt.deleted_texts(G, 2)}")


# ============ 4. 命令级全流程：save → merge → verify → publish → pull ============
print('== 4. 命令级全流程 ==')
import io
import contextlib

P = tempfile.mkdtemp(prefix='dbtool_proj_')
dt.set_root(P)
PDB = os.path.join(P, 'kanji.db')
new_db(PDB)
c = sqlite3.connect(PDB)
sent(c, 'S1', 1)
sent(c, 'S2', 2)
c.commit()
c.close()
os.makedirs(os.path.join(P, '_dbbackup', 'local'), exist_ok=True)
LB = os.path.join(P, '_dbbackup', 'local', 'kanji.db')
new_db(LB)
c = sqlite3.connect(LB)
sent(c, 'S1', 1)
sent(c, 'S2', 2)
sent(c, 'S3', 3)
c.execute("INSERT INTO srs(kanji,stage,last_at) VALUES('日',4,1000)")
c.commit()
c.close()
REMOTE = os.path.join(P, 'remote.git')
check(git(P, 'init', '-q', '--bare', REMOTE).returncode == 0, '建裸仓库当远端')
git(P, 'init', '-q')
git(P, 'remote', 'add', 'origin', REMOTE)
git(P, 'add', 'kanji.db')
git(P, 'commit', '-qm', 'init')
git(P, 'branch', '-M', 'main')
check(git(P, 'push', '-q', '-u', 'origin', 'main').returncode == 0, '推送初始库')

check(dt.cmd_save() == 0, 'save 正常返回')
check(num(LB, 'SELECT COUNT(*) FROM sentences') == 3, 'save 把当前库与旧备份并起来（3 句）')
check(dt.cmd_merge() == 0, 'merge 正常返回')
check(num(PDB, 'SELECT COUNT(*) FROM sentences') == 3, 'merge 后主库=并集（3 句）')
check(num(PDB, "SELECT stage FROM srs WHERE kanji='日'") == 4, 'merge 带回本地 SRS 进度')
check(dt.cmd_verify() == 0, 'verify 通过')
check(dt.cmd_publish(push=False, message='t1') == 0, 'publish（--no-push）正常返回')
check(dt.cmd_publish(push=False) == 0, '已提交后 publish 幂等（无需重复提交）')

c = sqlite3.connect(PDB)
sent(c, 'S4', None)
c.commit()
c.close()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = dt.cmd_pull()
log = buf.getvalue()
check(rc == 0, 'pull 正常返回')
check('已回退工作区改动' in log, 'pull 识别出本地库改动并先备份／回退')
check(num(PDB, "SELECT COUNT(*) FROM sentences WHERE text='S4'") == 1,
      'pull 之后本地新增的数据被并回来了（没有丢）')
check(num(PDB, 'SELECT COUNT(*) FROM sentences') == 4, 'pull 后主库=4 句（并集）')
check(dt.db_dirty_vs_head(P) is True,
      'pull 后本地库带着本地数据（相对 HEAD 有差异，等待 publish 提交）')
check(dt.cmd_verify() == 0, 'pull 之后 verify 通过')

for d in (TMP, G, P):
    try:
        __import__('shutil').rmtree(d, ignore_errors=True)
    except OSError:
        pass

print()
if FAILS:
    print(f'===== dbtool 测试: 失败 {len(FAILS)} 项 =====')
    sys.exit(1)
print('===== dbtool 测试: 全部通过 =====')
sys.exit(0)
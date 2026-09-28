# -*- coding: utf-8 -*-
"""篇章上云链路测试：合并不串篇 + 导出成文本 + 云端还原
================================================================
用户的诉求是「本地录入的语料和篇章进数据库，云端永久可见」。这条链路上有两个
真实存在过的坑，这套测试把它们钉死：

  1. **合并串篇**：两份库里 `passages.id=1` 各是一篇完全不同的文章。
     旧实现按 id 认行，`INSERT OR IGNORE` 会把其中一篇静默吃掉，
     而它的 `passage_sents` 还会挂到另一篇名下 —— 出题时引用的原文就是错的。
     现在必须：两边的篇章都在、句子挂在自己文章下、反复合并不产生重复。
  2. **只在本机**：库里有篇章、仓库版没有时，`status` 必须明确告诉你
     「云端还看不到」，并给出 publish / export-passages 两条路。

再加一条正向链路：export-passages → samples/*.txt → 干净库启动补种，
标题与出处要原样还原（这才是「云端永久可见」的那条不怕重启的路）。
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


import dbtool as dt                                          # noqa: E402

PASSAGE_DDL = '''
CREATE TABLE passages(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
    source TEXT DEFAULT '', level TEXT DEFAULT '', note TEXT DEFAULT '', text TEXT NOT NULL,
    n_para INTEGER, n_sent INTEGER, n_char INTEGER, created_at REAL, updated_at REAL);
CREATE TABLE passage_sents(id INTEGER PRIMARY KEY AUTOINCREMENT, passage_id INTEGER NOT NULL,
    para_idx INTEGER, idx INTEGER, text TEXT NOT NULL, kind TEXT DEFAULT 'body');
CREATE TABLE passage_results(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
    passage_id INTEGER, qtype TEXT, ok INTEGER, peeked INTEGER DEFAULT 0);
CREATE TABLE sentences(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT UNIQUE NOT NULL,
    translation TEXT, source TEXT, url TEXT, tokens TEXT, created_at REAL);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
'''


def mk(path, arts, sent_id0=1):
    """建一个迷你库：每篇文章 2 句 + 1 条答题记录，id 故意从 1 开始（制造撞车）。"""
    c = sqlite3.connect(path)
    c.executescript(PASSAGE_DDL)
    sid = sent_id0
    for i, (title, body) in enumerate(arts, 1):
        c.execute('INSERT INTO passages(id,title,source,text,n_para,n_sent,n_char)'
                  ' VALUES(?,?,?,?,1,2,9)', (i, title, '出处' + str(i), body))
        for k in range(2):
            c.execute('INSERT INTO passage_sents(id,passage_id,para_idx,idx,text)'
                      ' VALUES(?,?,0,?,?)', (sid, i, k, body + str(k)))
            sid += 1
        c.execute('INSERT INTO passage_results(ts,passage_id,qtype,ok) VALUES(?,?,?,1)',
                  (1000.0 + i, i, 'truth'))
    c.commit()
    c.close()


def rows(path, sql):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def num(path, sql):
    return rows(path, sql)[0][0]


def misattached(path):
    """句子文本必须以它所属文章的正文开头（建库时就是这么造的）。"""
    return [r['st'] for r in rows(
        path, 'SELECT s.text st, p.text pt FROM passage_sents s '
              'JOIN passages p ON p.id = s.passage_id')
        if not r['st'].startswith(r['pt'])]


TMP = tempfile.mkdtemp(prefix='dbtool_pass_')
CLOUD = os.path.join(TMP, 'cloud.db')
LOCAL = os.path.join(TMP, 'local.db')
mk(CLOUD, [('云端内置A', 'クラウドA。'), ('云端内置B', 'クラウドB。')], sent_id0=1)
mk(LOCAL, [('我的文章1', 'わたしの記事1。'), ('我的文章2', 'わたしの記事2。'),
           ('我的文章3', 'わたしの記事3。')], sent_id0=50)

print('== 1. 合并：id 撞车也不能吃掉篇章、更不能串篇 ==')
for tag, primary, source, out in (
        ('本地为主（pull 回填方向）', LOCAL, CLOUD, os.path.join(TMP, 'o1.db')),
        ('仓库为主（publish 前合并方向）', CLOUD, LOCAL, os.path.join(TMP, 'o2.db'))):
    dt.merge_db(primary, [source], out)
    check(num(out, 'SELECT COUNT(*) FROM passages') == 5,
          '%s：应为 5 篇（2+3），实际 %d' % (tag, num(out, 'SELECT COUNT(*) FROM passages')))
    check(num(out, 'SELECT COUNT(*) FROM passage_sents') == 10,
          '%s：应为 10 句，实际 %d' % (tag, num(out, 'SELECT COUNT(*) FROM passage_sents')))
    check(not misattached(out), '%s：有句子挂到了别人的文章下面 %s' % (tag, misattached(out)))
    check(num(out, 'SELECT COUNT(*) FROM passage_results') == 5,
          '%s：答题记录应为 5 条' % tag)
    titles = {r[0] for r in rows(out, 'SELECT title FROM passages')}
    check(titles == {'云端内置A', '云端内置B', '我的文章1', '我的文章2', '我的文章3'},
          '%s：篇章被吃掉了，只剩 %s' % (tag, sorted(titles)))

print('== 2. 反复合并幂等（每次 pull 都会跑一遍，不能越滚越多） ==')
o3 = os.path.join(TMP, 'o3.db')
dt.merge_db(os.path.join(TMP, 'o1.db'), [CLOUD, LOCAL, os.path.join(TMP, 'o2.db')], o3)
check(num(o3, 'SELECT COUNT(*) FROM passages') == 5, '重复合并后篇章数变了')
check(num(o3, 'SELECT COUNT(*) FROM passage_sents') == 10, '重复合并后句子重复了')
check(num(o3, 'SELECT COUNT(*) FROM passage_results') == 5, '重复合并后答题记录重复了')
check(not misattached(o3), '重复合并后出现串篇')

print('== 3. 孤儿子行：父篇章缺失时整行放弃，绝不乱挂 ==')
ORPH = os.path.join(TMP, 'orphan.db')
mk(ORPH, [('孤儿源', 'みなしご。')])
c = sqlite3.connect(ORPH)
c.execute('INSERT INTO passage_sents(passage_id,para_idx,idx,text) VALUES(99,0,0,?)',
          ('親のいない行。',))
c.execute('DELETE FROM passages WHERE id=1')      # 只留下子行，父篇章没了
c.commit()
c.close()
o4 = os.path.join(TMP, 'o4.db')
dt.merge_db(CLOUD, [ORPH], o4)
check(num(o4, "SELECT COUNT(*) FROM passage_sents WHERE text='親のいない行。'") == 0,
      '孤儿行被塞进了别人的文章里')
check(not misattached(o4), '孤儿合并造成串篇')

print('== 4. status：库里有、仓库版没有 → 必须明说「云端还看不到」 ==')
P = tempfile.mkdtemp(prefix='dbtool_pass_repo_')
dt.set_root(P)
PDB = os.path.join(P, 'kanji.db')
mk(PDB, [('已上云的一篇', 'アップ済み。')])


def git(*args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t'] + list(args),
                          cwd=P, capture_output=True)


git('init', '-q')
git('add', 'kanji.db')
git('commit', '-qm', 'init')
check(dt.head_gap(P) == [], '刚提交完不应有差额，实际 %s' % (dt.head_gap(P),))
c = sqlite3.connect(PDB)
c.execute("INSERT INTO passages(title,text,n_para,n_sent,n_char) VALUES('新录入的','ローカル。',1,1,5)")
c.execute("INSERT INTO sentences(text,source) VALUES('ローカル。','passage')")
c.commit()
c.close()
gap = dict((t, d) for t, d, _, _ in (dt.head_gap(P) or []))
check(gap.get('passages') == 1, 'status 没能报出「篇章比仓库版多 1 篇」，实际 %s' % gap)
check(gap.get('sentences') == 1, 'status 没能报出语料差额，实际 %s' % gap)
import io
import contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    dt.cmd_status(P)
log = buf.getvalue()
check('云端还看不到' in log, 'status 输出里没有「云端还看不到」的提示')
check('publish' in log and 'export-passages' in log, 'status 没给出上云的两条路')

print('== 5. export-passages → samples/*.txt → 干净库启动补种（不怕云端重启） ==')
dt.cmd_export_passages(P)
files = sorted(f for f in os.listdir(os.path.join(P, 'samples')) if f.endswith('.txt'))
check(len(files) == 2, '应导出 2 篇文本，实际 %s' % files)
meta_path = os.path.join(P, 'samples', files[0][:-4] + '.meta.json')
check(os.path.exists(meta_path), '缺少 .meta.json（标题/出处会丢）')
before = sorted(os.listdir(os.path.join(P, 'samples')))
dt.cmd_export_passages(P)
check(sorted(os.listdir(os.path.join(P, 'samples'))) == before,
      '重复导出产生了多余文件（文件名不稳定）')

# 干净库（云端全新容器）：只有 samples/ 的文本，启动补种应还原标题与出处
import db                                                    # noqa: E402
CDB = os.path.join(TMP, 'fresh.db')
c = sqlite3.connect(CDB)
c.executescript('CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);'
                'CREATE TABLE history(id INTEGER PRIMARY KEY AUTOINCREMENT,'
                ' ts REAL, type TEXT, detail TEXT);')
c.commit()
c.close()
db.DB_PATH = CDB
import discourse as D                                        # noqa: E402
D.SEED_DIR = os.path.join(P, 'samples')
D._seed_done = False
D.ensure_seeded()
got = {(p['title'], p['source']) for p in D.list_passages()}
check(('新录入的', '') in got or any(t == '新录入的' for t, _ in got),
      '云端没还原出本地录入的篇章，实际 %s' % sorted(got))
check(any(t == '已上云的一篇' and s == '出处1' for t, s in got),
      '.meta.json 里的标题/出处没有被还原，实际 %s' % sorted(got))
D._seed_done = False
D.ensure_seeded()
check(len(D.list_passages()) == 2, '重启补种把篇章变多了（应仍为 2 篇）')

for d in (TMP, P):
    shutil.rmtree(d, ignore_errors=True)

print()
if FAILS:
    print('===== 篇章上云链路测试: 失败 %d 项 =====' % len(FAILS))
    sys.exit(1)
print('===== 篇章上云链路测试: 全部通过 =====')
sys.exit(0)

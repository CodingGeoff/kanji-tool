# -*- coding: utf-8 -*-
"""dbtool —— 数据库与 Git 协作工具（本地库 / 仓库库 / Render 三者的唯一操作入口）

为什么需要它：
  1. 本项目的真正数据源是**仓库根目录的 kanji.db**（Render 部署时直接从 GitHub 仓库读它，
     所以它必须被 Git 跟踪、必须能随 push 一起更新——绝不能被 .gitignore 忽略）。
  2. SQLite 在 WAL 模式下运行时会额外产生 kanji.db-wal / kanji.db-shm 两个**边车文件**，
     它们是运行时产物。一旦被 Git 跟踪，pull 就会报
     “The following files would be overwritten by merge: kanji.db kanji.db-shm kanji.db-wal”；
     而如果提交前不做 checkpoint，kanji.db 本体又不含最新写入 —— 云端看到的是旧数据。
  3. 多个副本（本地库 / 仓库库 / 备份 / stash）各自都攒了语料，直接二选一必然丢数据，
     需要「按内容求并集 + 按进度取更优」的专用合并。

本工具把所有危险动作固化成安全命令（都在项目根目录执行）：

    python dbtool.py status                  体检：数据量 / WAL 状态 / 与 HEAD 的差异
    python dbtool.py save                    快照 + 把当前库并入 _dbbackup/local（只增不减）
    python dbtool.py merge                   合并成「最新最全」→ 写回 kanji.db
    python dbtool.py pull                    安全拉取：备份 → 清掉本地库改动 → pull → 合并回填
    python dbtool.py publish -m "说明"        checkpoint + 提交 kanji.db + 推送（Render 自动重部署）
    python dbtool.py setup                   一次性配置：WAL 边车移出版本控制 + 注册合并驱动
    python dbtool.py merge-driver %O %A %B   git 合并驱动（由 git 自动调用）

详细原理与标准流程见 DATABASE.md。
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

# 让中文输出在 Windows(GBK 控制台) 与 Linux 都不炸（控制台编码不变，只是遇到生僻字不报错）
try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_NAME = 'kanji.db'
DB = os.path.join(ROOT, DB_NAME)
BACKUP_DIR = os.path.join(ROOT, '_dbbackup')
LOCAL_BAK = os.path.join(BACKUP_DIR, 'local', DB_NAME)
STASH_BAK = os.path.join(BACKUP_DIR, 'stash', DB_NAME)
REMOTE_BAK = os.path.join(BACKUP_DIR, 'remote', DB_NAME)
SNAPSHOTS = os.path.join(BACKUP_DIR, 'snapshots')
TMP_DIR = os.path.join(BACKUP_DIR, 'tmp')

# 表格分类（合并策略不同，见 _merge_table）
LINKED_TABLES = ('kanji_index', 'fav_sentences', 'book_sentences')
# 没有自然唯一键、只能按行 id 认的表：按 id 认，避免同一首歌/同一本书被复制成两份
IDENTITY_OVERRIDE = {
    'songs': ['id'],
    'books': ['id'],
    'book_lessons': ['id'],
    'history': ['ts', 'type', 'detail'],
}
# 进度类表：同一个对象取「进度更靠前」的那一行（本地优先同分）
PROGRESS_KEYS = {'srs': ['kanji'], 'book_progress': ['book_id', 'kanji']}


# ---------------------------------------------------------------- 输出小工具
def say(msg=''):
    print(msg)


def hr(char='-', n=64):
    say(char * n)


def fmt_mb(n):
    return '%.1f MB' % (n / 1048576.0)


# ---------------------------------------------------------------- git 层
def git(root, *args, check=False):
    """执行 git 命令，返回 CompletedProcess（stdout 为 bytes，避免二进制库被改写）。"""
    p = subprocess.run(['git'] + list(args), cwd=root, capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError('git %s 失败: %s' % (' '.join(args),
                                                p.stderr.decode('utf-8', 'replace').strip()))
    return p


def git_text(root, *args):
    p = git(root, *args)
    return (p.stdout or b'').decode('utf-8', 'replace').strip()


def git_ok(root, *args):
    return git(root, *args).returncode == 0


def rev_exists(root, rev):
    return git(root, 'rev-parse', '--verify', '--quiet', rev + '^{commit}').returncode == 0


def git_blob_to_file(root, ref, dst):
    """把 git 里的 blob（如 HEAD:kanji.db）按二进制安全地写到 dst。"""
    p = git(root, 'cat-file', 'blob', ref)
    if p.returncode != 0 or not p.stdout:
        return None
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(p.stdout)
    return dst


def head_db_refs(root, depth):
    """返回最近 depth 个提交的库引用，用于推算「上游刻意删除过哪些句子」。"""
    refs = []
    for i in range(1, depth + 1):
        rev = 'HEAD~%d' % i
        if rev_exists(root, rev):
            refs.append(rev + ':' + DB_NAME)
    return refs


def is_clean_except_db(root):
    """除 kanji.db 外，工作区是否干净（有其它改动时 pull 前要提醒）。"""
    out = git_text(root, 'status', '--porcelain')
    others = []
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if path.replace('\\', '/').endswith('/' + DB_NAME) or path == DB_NAME:
            continue
        others.append(line)
    return others


def db_dirty_vs_head(root):
    """工作区的 kanji.db 与 HEAD 里的版本是否有差异。"""
    return not git_ok(root, 'diff', '--quiet', '--', DB_NAME)


# ---------------------------------------------------------------- sqlite 层
def connect(path, readonly=False):
    if readonly:
        uri = 'file:%s?mode=ro' % path.replace('\\', '/')
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def table_names(conn, schema='main'):
    return [r[0] for r in conn.execute(
        "SELECT name FROM %s.sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%%' ORDER BY name" % schema)]


def columns(conn, schema, table):
    return [r[1] for r in conn.execute('PRAGMA %s.table_info("%s")' % (schema, table))]


def unique_keys(conn, schema, table):
    """返回该表所有唯一索引的列组合（含 PK 自动索引），用于判断「同一行」。"""
    keys = []
    for r in conn.execute('PRAGMA %s.index_list("%s")' % (schema, table)):
        if not r[2]:            # r[2] = unique
            continue
        cols = [x[2] for x in conn.execute('PRAGMA %s.index_info("%s")' % (schema, r[1]))]
        if cols:
            keys.append(cols)
    return keys


def identity_cols(conn, schema, table):
    """判断「同一行」的列：优先唯一索引，否则用全部公共列。"""
    if table in IDENTITY_OVERRIDE:
        return list(IDENTITY_OVERRIDE[table])
    keys = unique_keys(conn, schema, table)
    if keys:
        keys.sort(key=len)                      # 列最少的唯一键最像自然键
        return list(keys[0])
    return columns(conn, schema, table)


def table_counts(path):
    """{表名: 行数}；打不开或不是库则返回 {}。"""
    try:
        conn = connect(path)
    except sqlite3.Error:
        return {}
    try:
        out = {}
        for t in table_names(conn):
            out[t] = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
        return out
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def integrity(path):
    conn = connect(path)
    try:
        return conn.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        conn.close()


def busy_hint(exc):
    return ('数据库被占用（%s）。请先关闭正在运行的服务：关掉 start.bat 的窗口，'
            '或结束占用 kanji.db 的 python/gunicorn 进程，然后重试。' % exc)


def checkpoint(path, quiet=False):
    """把 WAL 里的改动写回 kanji.db 本体（提交前必做，否则提交的是旧数据）。"""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path)
    try:
        busy, log, done = conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
    except sqlite3.OperationalError as e:
        raise RuntimeError(busy_hint(e))
    finally:
        conn.close()
    if not quiet and busy:
        say('  ! WAL 尚有读者，未完全折叠；请关闭正在运行的服务后重试')
    return ok


def drop_sidecars(path):
    """删除 -wal/-shm 边车文件（仅在确认没有连接持有该库时调用）。"""
    for suf in ('-wal', '-shm'):
        try:
            os.remove(path + suf)
        except OSError:
            pass


def copy_db(src, dst, fold_wal=True):
    """把库连同边车文件一起复制到 dst；fold_wal=True 时把 WAL 折进主文件。

    WAL 模式下「只拷 kanji.db」会丢掉还在 -wal 里的最新写入，所以必须连边车一起拷。
    """
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    for suf in ('', '-wal', '-shm'):
        if os.path.exists(src + suf):
            shutil.copy2(src + suf, dst + suf)
    if fold_wal:
        checkpoint(dst, quiet=True)
        drop_sidecars(dst)
    return dst


def normalize_source(path, tmpdir, tag):
    """把任意源库（可能带 -wal）整理成一份干净的只读输入，供 ATTACH 使用。"""
    if not os.path.exists(path):
        return None
    if not os.path.exists(path + '-wal'):
        return path
    dst = os.path.join(tmpdir, '%s.db' % tag)
    copy_db(path, dst, fold_wal=True)
    return dst


# ---------------------------------------------------------------- 黑名单：上游删过的脏数据
def deleted_texts(root, depth=2, cache=None):
    """从 git 历史里算出「上游刻意删除过的句子文本」黑名单。

    规则：某个历史提交的 kanji.db 里有、最新提交(HEAD)的 kanji.db 里没有 → 视为已清理，
    合并时不再从旧副本里复活。depth 越大越保守（默认回看 2 个提交）。
    """
    if cache is not None and 'deleted_texts' in cache:
        return cache['deleted_texts']
    newest = os.path.join(TMP_DIR, 'head.db')
    if git_blob_to_file(root, 'HEAD:' + DB_NAME, newest) is None:
        return set()
    conn = connect(newest)
    try:
        current = {r[0] for r in conn.execute('SELECT text FROM sentences')}
    finally:
        conn.close()
    removed = set()
    for i, ref in enumerate(head_db_refs(root, depth)):
        old = os.path.join(TMP_DIR, 'prev%d.db' % i)
        if git_blob_to_file(root, ref, old) is None:
            continue
        conn = connect(old)
        try:
            removed |= {r[0] for r in conn.execute('SELECT text FROM sentences')} - current
        finally:
            conn.close()
        os.remove(old)
    if cache is not None:
        cache['deleted_texts'] = removed
    return removed


# ---------------------------------------------------------------- 合并引擎
class MergeReport(object):
    """记录每个表补进了多少行 / 升级了多少进度，供命令行打印。"""

    def __init__(self):
        self.added = {}
        self.upgraded = {}
        self.purged = 0
        self.skipped = []

    def bump(self, table, n):
        if n:
            self.added[table] = self.added.get(table, 0) + n

    def bump_up(self, table, n):
        if n:
            self.upgraded[table] = self.upgraded.get(table, 0) + n

    def touched(self):
        return sorted(set(self.added) | set(self.upgraded))


def _score_srs(d):
    """复习进度比较：阶段高者胜，同阶段看最近一次复习时间，再看总作答数。"""
    return (float(d.get('stage') or 0), float(d.get('last_at') or 0),
            float((d.get('ok') or 0) + (d.get('ng') or 0)))


def _score_book_progress(d):
    return (1.0 if d.get('done_at') else 0.0, float(d.get('done_at') or 0))


PROGRESS_SCORE = {'srs': _score_srs, 'book_progress': _score_book_progress}


def _ensure_table(conn, alias, table):
    """目标库缺少该表时，按源库 DDL 补建（连同索引/触发器），避免新版本新增表丢数据。"""
    row = conn.execute("SELECT sql FROM %s.sqlite_master WHERE type='table' AND name=?"
                       % alias, (table,)).fetchone()
    if not row or not row[0]:
        return False
    try:
        conn.execute(row[0])
    except sqlite3.Error:
        return False
    for r in list(conn.execute("SELECT sql FROM %s.sqlite_master WHERE tbl_name=? "
                               "AND type IN ('index','trigger') AND sql IS NOT NULL"
                               % alias, (table,))):
        try:
            conn.execute(r[0])
        except sqlite3.Error:
            pass
    return True


def _insert_missing(conn, alias, table, report):
    """通用合并：按「同一行」的判据，把源库里缺失的行补进主库。

    - 判据 = 唯一索引列（自然键）；没有唯一索引的表用 IDENTITY_OVERRIDE。
    - 若判据里没有 id，则插入时丢弃源库 id 让 SQLite 自行分配，
      避免源库 id 恰好撞上本库另一行、导致 OR IGNORE 把整行丢掉。
    """
    tcols = columns(conn, 'main', table)
    scols = columns(conn, alias, table)
    cols = [c for c in scols if c in tcols]
    if not cols:
        report.skipped.append((table, '两库列名无交集'))
        return 0
    idcols = [c for c in identity_cols(conn, 'main', table) if c in cols] or list(cols)
    insert_cols = [c for c in cols if not (c == 'id' and 'id' not in idcols)]
    cl = ','.join('"%s"' % c for c in insert_cols)
    sel = ','.join('s."%s"' % c for c in insert_cols)
    cond = ' AND '.join('m."%s" IS s."%s"' % (c, c) for c in idcols) or '1'
    cur = conn.execute('INSERT OR IGNORE INTO main."%s" (%s) SELECT %s '
                       'FROM %s."%s" s WHERE NOT EXISTS '
                       '(SELECT 1 FROM main."%s" m WHERE %s)'
                       % (table, cl, sel, alias, table, table, cond))
    n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    report.bump(table, n)
    return n


def _merge_sentences(conn, alias, report):
    """句子表：先保 id 直搬，再把「文本缺失但 id 撞车」的句子用新 id 补进来。

    同时把 源id → 本库id 的映射写进 temp._idmap，供 kanji_index 等关联表按文本对齐。
    temp._blk 里是「上游已清理」的黑名单文本，合并时不再复活。
    """
    tcols = columns(conn, 'main', 'sentences')
    scols = columns(conn, alias, 'sentences')
    cols = [c for c in scols if c in tcols]
    cl = ','.join('"%s"' % c for c in cols)
    sel = ','.join('s."%s"' % c for c in cols)
    not_blocked = 's.text NOT IN (SELECT text FROM temp._blk)'
    cur = conn.execute('INSERT OR IGNORE INTO main.sentences (%s) SELECT %s '
                       'FROM %s.sentences s WHERE %s' % (cl, sel, alias, not_blocked))
    kept = cur.rowcount or 0
    added = 0
    non_id = [c for c in cols if c != 'id']
    if non_id:
        cn = ','.join('"%s"' % c for c in non_id)
        seln = ','.join('s."%s"' % c for c in non_id)
        cur = conn.execute('INSERT INTO main.sentences (%s) SELECT %s FROM %s.sentences s '
                           'WHERE %s AND NOT EXISTS (SELECT 1 FROM main.sentences m '
                           'WHERE m.text = s.text)' % (cn, seln, alias, not_blocked))
        added = cur.rowcount or 0
    conn.execute('INSERT OR REPLACE INTO temp._idmap(old_id, new_id) '
                 'SELECT s.id, m.id FROM %s.sentences s JOIN main.sentences m '
                 'ON m.text = s.text' % alias)
    report.bump('sentences', kept + added)
    return kept + added


def _merge_linked(conn, alias, table, report):
    """带 sentence_id 的表（kanji_index / fav_sentences / book_sentences）：

    源库 sentence_id 先经 temp._idmap 映射到本库真实 id，再要求「映射后两条句子文本一致」，
    文本对不上（id 被复用）的整行放弃 —— 宁可不合并，绝不让索引指向错误的句子。
    """
    tcols = columns(conn, 'main', table)
    scols = columns(conn, alias, table)
    cols = [c for c in scols if c in tcols]
    if not cols:
        report.skipped.append((table, '两库列名无交集'))
        return 0
    idcols = [c for c in identity_cols(conn, 'main', table) if c in cols] or list(cols)

    def expr(c):
        return ('COALESCE(mp.new_id, k."sentence_id")' if c == 'sentence_id'
                else 'k."%s"' % c)

    cl = ','.join('"%s"' % c for c in cols)
    sel = ','.join(expr(c) for c in cols)
    cond = ' AND '.join('m."%s" IS %s' % (c, expr(c)) for c in idcols) or '1'
    cur = conn.execute(
        'INSERT OR IGNORE INTO main."%s" (%s) SELECT %s FROM %s."%s" k '
        'JOIN %s.sentences ss ON ss.id = k."sentence_id" '
        'LEFT JOIN temp._idmap mp ON mp.old_id = k."sentence_id" '
        'JOIN main.sentences ms ON ms.id = COALESCE(mp.new_id, k."sentence_id") '
        'WHERE ms.text = ss.text AND NOT EXISTS '
        '(SELECT 1 FROM main."%s" m WHERE %s)'
        % (table, cl, sel, alias, table, alias, table, cond))
    n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    report.bump(table, n)
    return n


def _merge_progress(conn, alias, table, score):
    """进度表（srs / book_progress）：同一对象取「进度更靠前」的一行，绝不倒退。"""
    key = [c for c in PROGRESS_KEYS.get(table, [])
           if c in columns(conn, 'main', table) and c in columns(conn, alias, table)]
    if not key:
        return 0, 0
    tcols = columns(conn, 'main', table)
    scols = columns(conn, alias, table)
    cols = [c for c in scols if c in tcols]
    upd_cols = [c for c in cols if c not in key]
    where = ' AND '.join('"%s" IS ?' % c for c in key)
    added = upgraded = 0
    for srow in conn.execute('SELECT * FROM %s."%s"' % (alias, table)).fetchall():
        sd = {c: srow[c] for c in cols}
        kvals = tuple(sd[c] for c in key)
        mrow = conn.execute('SELECT * FROM main."%s" WHERE %s' % (table, where),
                            kvals).fetchone()
        if mrow is None:
            cl = ','.join('"%s"' % c for c in cols)
            conn.execute('INSERT INTO main."%s" (%s) VALUES (%s)'
                         % (table, cl, ','.join('?' * len(cols))),
                         tuple(sd[c] for c in cols))
            added += 1
            continue
        md = {c: mrow[c] for c in cols}
        if upd_cols and score(sd) > score(md):
            sets = ','.join('"%s"=?' % c for c in upd_cols)
            conn.execute('UPDATE main."%s" SET %s WHERE %s' % (table, sets, where),
                         tuple(sd[c] for c in upd_cols) + kvals)
            upgraded += 1
    return added, upgraded


def _or_done(conn, alias, table, report):
    """清单表（book_plan）：已打勾的项在合并后不能变回未打勾。"""
    if 'done' not in columns(conn, 'main', table):
        return 0
    idcols = [c for c in identity_cols(conn, 'main', table)
              if c in columns(conn, alias, table)]
    if not idcols:
        return 0
    cond = ' AND '.join('s."%s" = main."%s"."%s"' % (c, table, c) for c in idcols)
    cur = conn.execute('UPDATE main."%s" SET done=1 WHERE done=0 AND EXISTS '
                       '(SELECT 1 FROM %s."%s" s WHERE %s AND s.done=1)'
                       % (table, alias, table, cond))
    n = cur.rowcount or 0
    report.bump_up(table, n)
    return n


def _fill_blanks(conn, alias, table, report):
    """设置项：同名以本库为准，但本库为空值时用源库补上（例如云端写入的 v17 配置）。"""
    if 'key' not in columns(conn, 'main', table) or 'value' not in columns(conn, alias, table):
        return 0
    cur = conn.execute(
        'UPDATE main."%s" SET value=(SELECT s.value FROM %s."%s" s '
        'WHERE s.key = main."%s".key) WHERE (value IS NULL OR value=\'\') '
        'AND EXISTS (SELECT 1 FROM %s."%s" s WHERE s.key = main."%s".key '
        'AND s.value IS NOT NULL AND s.value<>\'\')'
        % (table, alias, table, table, alias, table, table))
    n = cur.rowcount or 0
    report.bump_up(table, n)
    return n


def _merge_table(conn, alias, table, report):
    """按表分派合并策略（顺序即优先级）。"""
    if table == 'sentences':
        _merge_sentences(conn, alias, report)
    elif table in PROGRESS_SCORE:
        added, up = _merge_progress(conn, alias, table, PROGRESS_SCORE[table])
        report.bump(table, added)
        report.bump_up(table, up)
    elif 'sentence_id' in columns(conn, alias, table):
        _merge_linked(conn, alias, table, report)
    else:
        _insert_missing(conn, alias, table, report)
    if table == 'settings':
        _fill_blanks(conn, alias, table, report)
    if 'done' in columns(conn, 'main', table):
        _or_done(conn, alias, table, report)


def _merge_source(conn, alias, report, exclude):
    """把 ATTACH 进来的一个源库整体并入主库；句子先合，关联表后合（依赖 id 映射）。"""
    tables = [t for t in table_names(conn, alias) if t not in exclude]
    order = []
    if 'sentences' in tables:
        order.append('sentences')
    order += [t for t in tables
              if t not in order and 'sentence_id' in columns(conn, alias, t)]
    order += [t for t in tables if t not in order]
    main_tables = set(table_names(conn, 'main'))
    for t in order:
        if t not in main_tables and not _ensure_table(conn, alias, t):
            report.skipped.append((t, '主库缺少该表且无法按源库 DDL 补建'))
            continue
        _merge_table(conn, alias, t, report)


def _purge(conn, report):
    """删除「上游已清理过」的脏句子及其索引/收藏/课本引用（--purge-deleted 时才做）。"""
    ids = [r[0] for r in conn.execute(
        'SELECT m.id FROM main.sentences m JOIN temp._blk b ON b.text = m.text')]
    if not ids:
        return 0
    marks = ','.join('?' * len(ids))
    for t in table_names(conn, 'main'):
        if t == 'sentences' or 'sentence_id' not in columns(conn, 'main', t):
            continue
        conn.execute('DELETE FROM main."%s" WHERE sentence_id IN (%s)' % (t, marks), ids)
    conn.execute('DELETE FROM main.sentences WHERE id IN (%s)' % marks, ids)
    report.purged = len(ids)
    return report.purged


KEY_TABLES = ('sentences', 'kanji_index', 'songs', 'srs', 'history', 'settings',
              'books', 'book_lessons', 'book_plan')


def merge_db(primary, sources, out, blocklist=(), exclude=(), purge=False):
    """以 primary 为基准，把 sources 依次并进来，结果原子替换到 out。

    - primary：主库（进度/内容的权威版本，一般为 _dbbackup/local 或当前 kanji.db）
    - sources：其它副本（仓库里的 HEAD 版、stash 归档、快照……），只补缺、不覆盖
    - blocklist：不再复活的句子文本（上游清理过的脏数据）
    """
    report = MergeReport()
    # 临时工作目录必须和目标库同盘（Windows 下 os.replace 不能跨盘移动）
    out_dir = os.path.dirname(os.path.abspath(out)) or '.'
    os.makedirs(out_dir, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix='.dbtool_merge_', dir=out_dir)
    conn = None
    try:
        work = os.path.join(tmpdir, 'merged.db')
        copy_db(primary, work, fold_wal=True)
        conn = sqlite3.connect(work)
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None            # 自己管事务，避免与 sqlite3 隐式事务打架
        # WAL 要在「干正事之前」设好：ATTACH 之后再切日志模式，
        # 同一连接上会残留一个活跃语句，随后的 checkpoint 会报
        # “database table is locked”。
        conn.execute('PRAGMA journal_mode=WAL').fetchone()
        conn.execute('CREATE TEMP TABLE _blk(text TEXT PRIMARY KEY)')
        conn.execute('CREATE TEMP TABLE _idmap(old_id INTEGER PRIMARY KEY, new_id INTEGER)')
        blk = sorted(set(blocklist))
        if blk:
            conn.executemany('INSERT OR IGNORE INTO _blk(text) VALUES (?)',
                             [(t,) for t in blk])
        for i, src in enumerate(sources):
            path = normalize_source(src, tmpdir, 'src%d' % i)
            if not path:
                report.skipped.append((src, '文件不存在，已跳过'))
                continue
            alias = 'src%d' % i
            conn.execute('ATTACH DATABASE ? AS %s' % alias, (path,))
            try:
                conn.execute('BEGIN')
                try:
                    _merge_source(conn, alias, report, set(exclude))
                finally:
                    conn.execute('COMMIT')
            finally:
                conn.execute('DETACH DATABASE %s' % alias)
        if purge:
            conn.execute('BEGIN')
            try:
                _purge(conn, report)
            finally:
                conn.execute('COMMIT')
        # 注意：PRAGMA 也会返回结果集，必须取走（fetch），
        # 否则该语句一直处于 active 状态，紧接着的操作会报 database table is locked。
        conn.execute('PRAGMA optimize').fetchall()
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
        ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
        if ok != 'ok':
            raise RuntimeError('合并结果 integrity_check 失败：%s' % ok)
        conn.close()
        conn = None
        drop_sidecars(work)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        try:
            os.replace(work, out)
        except OSError as e:
            raise RuntimeError('写入 %s 失败（%s）。请先关闭正在运行的服务再试。'
                               % (out, e))
        drop_sidecars(out)                     # 清掉与新库不匹配的旧 WAL，防止串档
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        shutil.rmtree(tmpdir, ignore_errors=True)
    return report


def print_report(report, before=None, after=None, title='合并报告'):
    hr('=')
    say(title)
    if report.touched():
        for t in report.touched():
            parts = []
            if report.added.get(t):
                parts.append('补进 %d 行' % report.added[t])
            if report.upgraded.get(t):
                parts.append('升级 %d 行' % report.upgraded[t])
            say('  %-16s %s' % (t, '，'.join(parts)))
    else:
        say('  （没有需要补的数据，两份库内容一致）')
    if report.purged:
        say('  已清除上游清理过的脏句子：%d 条' % report.purged)
    for t, why in report.skipped:
        say('  ! 跳过 %s：%s' % (t, why))
    if before or after:
        before, after = before or {}, after or {}
        keys = [t for t in KEY_TABLES if t in before or t in after]
        say('  行数变化：' + '  '.join(
            '%s %s→%s' % (t, before.get(t, '-'), after.get(t, '-')) for t in keys))


# ---------------------------------------------------------------- 命令：status
def _line(label, value):
    say('  %-22s %s' % (label, value))


def cmd_status(root=None):
    root = root or ROOT
    hr('=')
    say('kanji.db 体检报告')
    hr('=')
    say('[1] 文件')
    if not os.path.exists(DB):
        _line('kanji.db', '不存在！先运行 python app.py 生成')
    else:
        st = os.stat(DB)
        _line('kanji.db', '%s  %s' % (fmt_mb(st.st_size),
                                      time.strftime('%Y-%m-%d %H:%M',
                                                    time.localtime(st.st_mtime))))
        conn = connect(DB)
        try:
            _line('journal_mode', conn.execute('PRAGMA journal_mode').fetchone()[0])
        finally:
            conn.close()
        for suf in ('-wal', '-shm'):
            p = DB + suf
            _line('kanji.db' + suf,
                  fmt_mb(os.path.getsize(p)) + '（运行时边车，已 .gitignore）'
                  if os.path.exists(p) else '无（干净）')
    say()
    say('[2] 数据量')
    counts = table_counts(DB)
    for t in KEY_TABLES:
        if t in counts:
            _line(t, counts[t])
    extra = [t for t in counts if t not in KEY_TABLES]
    if extra:
        _line('其它表', ', '.join('%s=%d' % (t, counts[t]) for t in extra))
    if os.path.exists(LOCAL_BAK):
        lb = table_counts(LOCAL_BAK)
        diffs = []
        for t in (KEY_TABLES + tuple(extra)):
            if t in lb and lb[t] != counts.get(t):
                diffs.append('%s %d→%d' % (t, counts.get(t, 0), lb[t]))
        _line('_dbbackup/local', ('差异 ' + ', '.join(diffs)) if diffs
              else '与本地库一致')
    else:
        _line('_dbbackup/local', '还没有备份（可运行 save 生成）')
    say()
    say('[3] Git')
    if git(root, 'rev-parse', '--git-dir').returncode != 0:
        _line('仓库', '当前目录不是 git 仓库')
    else:
        _line('分支', git_text(root, 'rev-parse', '--abbrev-ref', 'HEAD'))
        _line('HEAD', git_text(root, 'log', '-1', '--format=%h %s'))
        cnt = git_text(root, 'rev-list', '--left-right', '--count',
                       '@{upstream}...HEAD') if git_ok(
            root, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}') else ''
        if cnt:
            behind, ahead = cnt.split()
            _line('与远端', '落后 %s 个提交 / 领先 %s 个提交' % (behind, ahead))
        _line('kanji.db', '与 HEAD 有差异（有未提交的进度）' if db_dirty_vs_head(root)
              else '与 HEAD 一致')
        sidecars = git_text(root, 'ls-files', '*.db-wal', '*.db-shm').splitlines()
        _line('被跟踪的边车文件', ', '.join(sidecars) if sidecars
              else '无（正确，pull 不会再报 would be overwritten）')
        if _gitignore_ignores_db(os.path.join(root, '.gitignore')):
            say('  ! .gitignore 里有会屏蔽 kanji.db 的规则（如 *.db）——'
                '这会让 Render 拿不到你的数据库，请删掉该行（见 DATABASE.md）')
        others = is_clean_except_db(root)
        _line('其它未提交改动', '%d 个文件' % len(others) if others else '无')
        for line in others[:8]:
            say('      ' + line)
    hr('=')
    return 0


def _read_text(path):
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except OSError:
        return ''


def _gitignore_ignores_db(path):
    """检查 .gitignore 里是否有会屏蔽 kanji.db 的生效规则（注释行不算）。"""
    for line in _read_text(path).splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        if s in ('*.db', 'kanji.db', '/kanji.db', '**/kanji.db') or s == '*':
            return True
    return False


# ---------------------------------------------------------------- 命令：save
def snapshot(prefix='kanji_'):
    """给当前库做一份带时间戳的快照，返回路径。"""
    os.makedirs(SNAPSHOTS, exist_ok=True)
    dst = os.path.join(SNAPSHOTS, prefix + time.strftime('%Y%m%d_%H%M%S') + '.db')
    copy_db(DB, dst, fold_wal=True)
    return dst


def prune_snapshots(keep):
    if keep <= 0:
        return []
    files = sorted((os.path.join(SNAPSHOTS, f) for f in os.listdir(SNAPSHOTS)
                    if f.endswith('.db')), key=os.path.getmtime, reverse=True)
    removed = []
    for old in files[keep:]:
        try:
            os.remove(old)
            removed.append(os.path.basename(old))
        except OSError:
            pass
    return removed


def cmd_save(root=None, keep=10):
    """把当前 kanji.db 存进 _dbbackup/local（与旧备份求并集，只增不减）。"""
    root = root or ROOT
    hr('=')
    say('备份本地数据库 → %s' % os.path.relpath(LOCAL_BAK, root))
    ok = checkpoint(DB)
    _line('checkpoint + integrity', ok)
    snap = snapshot()
    _line('本次快照', os.path.relpath(snap, root))
    before = table_counts(LOCAL_BAK) if os.path.exists(LOCAL_BAK) else {}
    sources = [LOCAL_BAK] if os.path.exists(LOCAL_BAK) else []
    report = merge_db(DB, sources, LOCAL_BAK, blocklist=deleted_texts(root, 2))
    print_report(report, before, table_counts(LOCAL_BAK),
                 '备份写入报告（当前库为主，旧备份只补缺）')
    dropped = prune_snapshots(keep)
    if dropped:
        _line('淘汰旧快照', ', '.join(dropped))
    hr('=')
    return 0


# ---------------------------------------------------------------- 命令：merge / pull
def head_db(root=None):
    """把 HEAD 版本里的 kanji.db 导出成普通文件，供合并使用。"""
    root = root or ROOT
    dst = git_blob_to_file(root, 'HEAD:' + DB_NAME, REMOTE_BAK)
    if dst:
        drop_sidecars(dst)      # 只导出主文件，避免旧边车串档
    return dst


def db_tracked(root=None):
    return git_ok(root or ROOT, 'ls-files', '--error-unmatch', DB_NAME)


def _abs(root, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(root, p))


def cmd_merge(root=None, sources=(), out=None, exclude='', purge=False, depth=2):
    """把「仓库版 + 本地备份 + 指定副本」合并成最新最全，写回 kanji.db。"""
    root = root or ROOT
    hr('=')
    say('合并数据：仓库版 + 本地备份' + (' + 指定副本' if sources else '') + ' → '
        + (out or DB_NAME))
    primary = LOCAL_BAK if os.path.exists(LOCAL_BAK) else DB
    _line('主库（内容/进度权威）', os.path.relpath(primary, root))
    srcs = []
    head = head_db(root)
    if head:
        srcs.append(head)
        _line('仓库版 HEAD:kanji.db', os.path.relpath(head, root))
    else:
        _line('仓库版 HEAD:kanji.db', '取不到（非 git 仓库，或 HEAD 里没有该文件）')
    for s in sources:
        srcs.append(_abs(root, s))
        _line('额外副本', s)
    blk = deleted_texts(root, depth)
    _line('不复活的脏句子', '%d 条（git 历史里被删过的文本）' % len(blk))
    excl = [x.strip() for x in (exclude or '').split(',') if x.strip()]
    if excl:
        _line('跳过这些表', ', '.join(excl))
    target = _abs(root, out) if out else DB
    before = table_counts(target)
    report = merge_db(primary, srcs, target, blocklist=blk, exclude=excl, purge=purge)
    print_report(report, before, table_counts(target), '合并报告')
    if os.path.abspath(target) == os.path.abspath(DB):
        keep = os.path.join(BACKUP_DIR, 'merged', DB_NAME)
        copy_db(DB, keep, fold_wal=True)
        _line('另存一份', os.path.relpath(keep, root))
    say('下一步：python dbtool.py publish -m "更新数据库"  （提交并推送，Render 自动重部署）')
    hr('=')
    return 0


def cmd_pull(root=None, depth=2, purge=False, keep=10):
    """安全拉取：备份本地库 → 清掉本地库改动 → git pull → 把本地数据并回新仓库版。"""
    root = root or ROOT
    hr('=')
    say('安全拉取：先护住本地数据库，再拉远端，最后把数据并回来')
    others = is_clean_except_db(root)
    if others:
        _line('注意', '除 kanji.db 外还有 %d 处未提交改动（与远端冲突时 pull 仍会失败）：'
              % len(others))
        for line in others[:8]:
            say('      ' + line)
        say('  建议先 commit 或 stash 它们，再跑本命令。')
    say()
    say('[1/3] 备份当前库')
    cmd_save(root, keep=keep)
    say('[2/3] 让工作区的 kanji.db 回到 HEAD 版本，释放 pull 阻塞')
    if not db_tracked(root):
        say('  ! kanji.db 当前没有被 Git 跟踪：Render 会拿不到你的数据库！')
        say('    请检查 .gitignore 是否写了 *.db（正确写法见 DATABASE.md），'
            '并运行 git add -f kanji.db')
    elif db_dirty_vs_head(root):
        p = git(root, 'checkout', '--', DB_NAME)
        if p.returncode != 0:
            say('  ! git checkout 失败：'
                + p.stderr.decode('utf-8', 'replace').strip())
            return 1
        say('  已回退工作区改动（数据在 _dbbackup/local 与 _dbbackup/snapshots 里）')
    else:
        say('  工作区 kanji.db 与 HEAD 一致，无需回退')
    say('[3/3] git pull')
    p = git(root, 'pull')
    out = (p.stdout or b'').decode('utf-8', 'replace').strip()
    err = (p.stderr or b'').decode('utf-8', 'replace').strip()
    if out:
        say(out)
    if err:
        say(err)
    if p.returncode != 0:
        say('  ! pull 失败。若仍提示 would be overwritten，说明还有别的被跟踪文件有本地改动：')
        say('    把它们 commit / stash，或用 python dbtool.py setup 检查被跟踪的 WAL 边车。')
        return 1
    say()
    say('[回填] 把本地数据并回新的仓库版')
    head = head_db(root)
    primary = LOCAL_BAK if os.path.exists(LOCAL_BAK) else DB
    before = table_counts(DB)
    report = merge_db(primary, [head] if head else [], DB,
                      blocklist=deleted_texts(root, depth), purge=purge)
    print_report(report, before, table_counts(DB), '回填报告')
    say('完成。要同步到 Render：python dbtool.py publish -m "更新数据库"')
    hr('=')
    return 0


# ---------------------------------------------------------------- 命令：publish / setup / merge-driver
def db_summary():
    c = table_counts(DB)
    return ('语料 %d 句 / 复习 %d 字 / 歌曲 %d 首 / 课本 %d 本'
            % (c.get('sentences', 0), c.get('srs', 0), c.get('songs', 0),
               c.get('books', 0)))


def cmd_publish(root=None, message=None, push=True, dry_run=False):
    """把最新 kanji.db 提交并推送 —— 这是让 Render 看到本地数据的唯一通道。"""
    root = root or ROOT
    hr('=')
    say('发布数据库：checkpoint → git commit kanji.db → git push')
    if not db_tracked(root):
        say('  ! kanji.db 没有被 Git 跟踪，Render 拿不到你的数据。')
        say('    先把 .gitignore 里的 *.db 删掉（正确写法见 DATABASE.md），再执行：')
        say('      git add -f kanji.db')
        return 1
    ok = checkpoint(DB)
    _line('checkpoint + integrity', ok)
    summary = db_summary()
    _line('当前数据量', summary)
    p = git(root, 'add', '--', DB_NAME)
    if p.returncode != 0:
        say('  ! git add 失败：' + p.stderr.decode('utf-8', 'replace').strip())
        return 1
    if git_ok(root, 'diff', '--cached', '--quiet', '--', DB_NAME):
        say('  kanji.db 与 HEAD 一致，没有需要提交的内容')
        return 0
    msg = message or ('chore(db): 更新数据库（%s）' % summary)
    if dry_run:
        say('  [dry-run] git commit -m "%s" -- %s' % (msg, DB_NAME))
        return 0
    p = git(root, 'commit', '-m', msg, '--', DB_NAME)
    out = (p.stdout or b'').decode('utf-8', 'replace').strip()
    if out:
        say(out)
    if p.returncode != 0:
        say('  ! commit 失败：' + p.stderr.decode('utf-8', 'replace').strip())
        return 1
    if not push:
        say('  已提交（未推送）。要上线请再执行 git push')
        return 0
    say('  git push ...')
    p = git(root, 'push')
    out = (p.stdout or b'').decode('utf-8', 'replace').strip()
    err = (p.stderr or b'').decode('utf-8', 'replace').strip()
    for text in (out, err):
        if text:
            say(text)
    if p.returncode != 0:
        say('  ! push 失败。若提示落后于远端，先跑 python dbtool.py pull（会保护本地数据），'
            '然后再 publish。')
        return 1
    say('  已推送成功。Render 检测到 push 会自动重新部署，1~3 分钟后新数据生效：')
    say('  部署日志出现 “Booting worker” 即可刷新网页查看。')
    hr('=')
    return 0


GITATTR_LINES = [
    '# SQLite 二进制数据库：行式 diff / 文本合并没有意义，改用 dbtool.py 的并集合并驱动',
    'kanji.db -diff -text merge=kanjidb',
    'v1/kanji.db -diff -text',
]


def _ensure_gitattributes(root):
    path = os.path.join(root, '.gitattributes')
    text = _read_text(path)
    add = [l for l in GITATTR_LINES if l not in text]
    if not add:
        return []
    with open(path, 'a', encoding='utf-8', newline='\n') as f:
        if text and not text.endswith('\n'):
            f.write('\n')
        f.write('\n'.join(add) + '\n')
    return add


def cmd_setup(root=None):
    """一次性配置：WAL 边车移出版本控制 + 注册 kanji.db 专用合并驱动。"""
    root = root or ROOT
    hr('=')
    say('一次性配置：让 kanji.db 安全地跟着 Git 走')
    tracked = [t.strip() for t in
               git_text(root, 'ls-files', '*.db-wal', '*.db-shm').splitlines() if t.strip()]
    if tracked:
        p = git(root, 'rm', '--cached', '-r', '--ignore-unmatch', '--', *tracked)
        if p.returncode != 0:
            p = git(root, 'rm', '--cached', '-r', '-f', '--', *tracked)
        _line('边车移出版本控制', ', '.join(tracked) if p.returncode == 0
              else ('失败：' + p.stderr.decode('utf-8', 'replace').strip()))
        say('  （文件仍在磁盘上，只是不再被 Git 跟踪 / 提交）')
    else:
        _line('WAL/SHM 边车', '没有被 Git 跟踪（正确）')
    add = _ensure_gitattributes(root)
    _line('.gitattributes', ('已追加 %d 行' % len(add)) if add else '已是最新')
    if add:
        for l in add:
            say('      ' + l)
    exe = sys.executable.replace('\\', '/')
    tool = os.path.join(root, 'dbtool.py').replace('\\', '/')
    driver = '"%s" "%s" merge-driver %%O %%A %%B' % (exe, tool)
    git(root, 'config', 'merge.kanjidb.name', 'kanji.db 数据库并集合并（dbtool）')
    git(root, 'config', 'merge.kanjidb.driver', driver)
    _line('合并驱动', driver)
    say()
    say('配置完成。别忘了把这些改动提交上去：')
    say('  git add .gitignore .gitattributes dbtool.py DATABASE.md')
    say('  git commit -m "chore(db): 数据库与 Git 协作工具"')
    hr('=')
    return 0


def cmd_merge_driver(root, base, ours, theirs):
    """git 合并驱动：把 theirs 并进 ours（%A 就是 git 要保留的那份）。"""
    root = root or ROOT
    try:
        if not os.path.exists(ours):
            if os.path.exists(theirs):
                shutil.copy2(theirs, ours)
            return 0
        if not os.path.exists(theirs) or not table_counts(theirs):
            return 0
        if not table_counts(ours):
            shutil.copy2(theirs, ours)
            return 0
        before = table_counts(ours)
        report = merge_db(ours, [theirs], ours)
        print_report(report, before, table_counts(ours), 'kanji.db 自动并集合并')
        return 0
    except Exception as e:                       # 交给 git 标冲突，绝不让库坏掉
        sys.stderr.write('dbtool merge-driver 失败：%s\n' % e)
        return 1


def set_root(root):
    """把模块级路径切到另一个项目根（测试用：可指向临时目录）。"""
    global ROOT, DB, BACKUP_DIR, LOCAL_BAK, STASH_BAK, REMOTE_BAK, SNAPSHOTS, TMP_DIR
    ROOT = os.path.abspath(root)
    DB = os.path.join(ROOT, DB_NAME)
    BACKUP_DIR = os.path.join(ROOT, '_dbbackup')
    LOCAL_BAK = os.path.join(BACKUP_DIR, 'local', DB_NAME)
    STASH_BAK = os.path.join(BACKUP_DIR, 'stash', DB_NAME)
    REMOTE_BAK = os.path.join(BACKUP_DIR, 'remote', DB_NAME)
    SNAPSHOTS = os.path.join(BACKUP_DIR, 'snapshots')
    TMP_DIR = os.path.join(BACKUP_DIR, 'tmp')
    return ROOT


# ---------------------------------------------------------------- 命令行入口
# ---------------------------------------------------------------- 命令：verify
def cmd_verify(root=None):
    """体检合并结果：完整性 + 孤儿索引 + 与备份对比。合并后建议跑一次。"""
    root = root or ROOT
    hr('=')
    say('kanji.db 校验：完整性 / 孤儿索引 / 与备份对比')
    problems = []
    ok = integrity(DB)
    _line('integrity_check', ok)
    if ok != 'ok':
        problems.append('integrity_check=%s' % ok)
    conn = connect(DB)
    try:
        counts = {t: conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
                  for t in table_names(conn)}
        if 'sentences' in counts:
            dup = conn.execute('SELECT COUNT(*) FROM (SELECT text FROM sentences '
                               'GROUP BY text HAVING COUNT(*) > 1)').fetchone()[0]
            _line('重复句子文本', dup)
            if dup:
                problems.append('重复句子 %d 条' % dup)
            empty = conn.execute("SELECT COUNT(*) FROM sentences "
                                 "WHERE text IS NULL OR TRIM(text)=''").fetchone()[0]
            _line('空句子', empty)
            if empty:
                problems.append('空句子 %d 条' % empty)
        for t in sorted(counts):
            cols = columns(conn, 'main', t)
            if 'sentence_id' not in cols or t == 'sentences':
                continue
            orphan = conn.execute(
                'SELECT COUNT(*) FROM "%s" x WHERE NOT EXISTS '
                '(SELECT 1 FROM sentences s WHERE s.id = x.sentence_id)' % t).fetchone()[0]
            _line('孤儿索引 %s' % t, orphan)
            if orphan:
                problems.append('%s 有 %d 行指向不存在的句子' % (t, orphan))
        _line('journal_mode', conn.execute('PRAGMA journal_mode').fetchone()[0])
        _line('foreign_key_check', len(conn.execute('PRAGMA foreign_key_check').fetchall()))
    finally:
        conn.close()
    if os.path.exists(LOCAL_BAK):
        lb, cur = table_counts(LOCAL_BAK), table_counts(DB)
        lost = ['%s %d→%d' % (t, lb[t], cur.get(t, 0)) for t in lb
                if cur.get(t, 0) < lb[t]]
        _line('相对 _dbbackup/local', ('少于备份：' + ', '.join(lost)) if lost
              else '不少于备份（内容没有丢）')
        if lost:
            problems.append('比备份少：' + ', '.join(lost))
    _line('文件大小', fmt_mb(os.path.getsize(DB)))
    hr('=')
    if problems:
        say('发现问题 %d 项：%s' % (len(problems), '；'.join(problems)))
        say('可用 python dbtool.py merge 重新合并（主库取 _dbbackup/local）。')
        return 1
    say('校验通过：数据库完整，没有孤儿索引，也没有比备份少数据。')
    return 0


# ---------------------------------------------------------------- 命令行入口
def build_parser():
    import argparse
    ap = argparse.ArgumentParser(
        prog='python dbtool.py',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='kanji.db 与 Git 协作工具：备份 / 合并 / 安全拉取 / 发布到 Render',
        epilog='完整原理与标准流程见 DATABASE.md')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('status', help='体检：数据量、WAL 状态、与 HEAD 的差异')
    sp = sub.add_parser('save', help='备份当前库到 _dbbackup/local（与旧备份求并集，只增不减）')
    sp.add_argument('--keep', type=int, default=10, help='保留最近几份快照（默认 10，0 表示全留）')

    def _common(p):
        p.add_argument('--depth', type=int, default=2,
                       help='回看几个历史提交来推算「上游删过的脏句子」黑名单（默认 2）')
        p.add_argument('--purge-deleted', action='store_true',
                       help='顺带删除主库里仍残留的上游已清理句子')

    sm = sub.add_parser('merge', help='合并成最新最全并写回 kanji.db')
    sm.add_argument('--from', dest='sources', action='append', default=[],
                    help='额外副本路径（可重复；例如归档的 stash 库）')
    sm.add_argument('--out', default=None, help='输出到其它文件（默认写回 kanji.db）')
    sm.add_argument('--exclude', default='', help='逗号分隔的表名，不参与合并')
    _common(sm)
    spull = sub.add_parser('pull', help='安全拉取：备份→清理本地库改动→pull→回填')
    _common(spull)
    spub = sub.add_parser('publish', help='checkpoint + 提交 kanji.db + 推送（Render 自动重部署）')
    spub.add_argument('-m', '--message', default=None, help='提交说明')
    spub.add_argument('--no-push', action='store_true', help='只提交不推送')
    spub.add_argument('--dry-run', action='store_true', help='只打印将要执行的 git 命令')
    sub.add_parser('setup', help='一次性配置：边车移出版本控制 + 注册合并驱动')
    sub.add_parser('verify', help='校验：完整性 / 孤儿索引 / 与备份对比')
    sd = sub.add_parser('merge-driver', help='git 合并驱动（由 git 自动调用，人不用手敲）')
    sd.add_argument('files', nargs=3, help='base ours theirs（对应 %O %A %B）')
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.cmd == 'status':
            return cmd_status()
        if args.cmd == 'save':
            return cmd_save(keep=args.keep)
        if args.cmd == 'merge':
            return cmd_merge(sources=args.sources, out=args.out, exclude=args.exclude,
                             purge=args.purge_deleted, depth=args.depth)
        if args.cmd == 'pull':
            return cmd_pull(depth=args.depth, purge=args.purge_deleted)
        if args.cmd == 'publish':
            return cmd_publish(message=args.message, push=not args.no_push,
                               dry_run=args.dry_run)
        if args.cmd == 'setup':
            return cmd_setup()
        if args.cmd == 'verify':
            return cmd_verify()
        if args.cmd == 'merge-driver':
            base, ours, theirs = args.files
            return cmd_merge_driver(ROOT, base, ours, theirs)
    except (RuntimeError, FileNotFoundError, sqlite3.Error) as e:
        say('!! ' + str(e))
        return 1
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
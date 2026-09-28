# -*- coding: utf-8 -*-
"""不可变、内容寻址的分片语料库。

设计目标：单片目标 48 MiB、硬上限 80 MiB；密封后以 SHA-256 命名且只读。
多设备合并等于文件集合求并，杜绝对同一个 SQLite 二进制文件并发修改导致的 Git
冲突。catalog/manifest 均可由扫描分片重建，不是数据真源。
"""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(os.environ.get('KANJI_CORPUS_DIR') or Path(__file__).with_name('corpus_data'))
SHARD_DIR = ROOT / 'shards'
STAGING_DIR = ROOT / 'staging'
TARGET_BYTES = 48 * 1024 * 1024
MAX_BYTES = 80 * 1024 * 1024
SCHEMA_VERSION = 1

DDL = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sentences(
 uid TEXT PRIMARY KEY,
 text TEXT NOT NULL,
 translation TEXT,
 language TEXT NOT NULL DEFAULT 'jpn',
 source_id TEXT NOT NULL,
 source_item_id TEXT,
 source_url TEXT,
 title TEXT,
 author TEXT,
 license TEXT NOT NULL,
 attribution TEXT,
 retrieved_at REAL,
 content_hash TEXT NOT NULL,
 created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_shard_text_hash ON sentences(content_hash);
CREATE INDEX IF NOT EXISTS idx_shard_source ON sentences(source_id,source_item_id);
CREATE INDEX IF NOT EXISTS idx_shard_lang ON sentences(language);
'''

SOURCES = {
 'tatoeba': {'mode':'bulk_text','redistributable':True,'license':'CC BY 2.0 FR',
   'official':'https://tatoeba.org/en/downloads','update':'weekly-or-manual'},
 'wikipedia_ja': {'mode':'official_dump','redistributable':True,'license':'CC BY-SA 4.0 / GFDL',
   'official':'https://dumps.wikimedia.org/jawiki/','update':'monthly'},
 'wikinews_ja': {'mode':'official_dump','redistributable':True,'license':'CC BY 2.5 (check current project notice)',
   'official':'https://dumps.wikimedia.org/jawikinews/','update':'monthly'},
 'aozora': {'mode':'public_domain_per_work','redistributable':True,'license':'work-specific public domain',
   'official':'https://www.aozora.gr.jp/','update':'manual'},
 'egov_laws': {'mode':'official_api','redistributable':True,'license':'Public Data License 1.0 / law text excluded from copyright',
   'official':'https://laws.e-gov.go.jp/','update':'monthly'},
 'kaken': {'mode':'official_open_dataset','redistributable':True,'license':'CC BY 4.0',
   'official':'https://kaken.nii.ac.jp/','update':'yearly'},
 'kokkai': {'mode':'official_api','redistributable':True,'license':'CC BY 4.0; preserve government attribution',
   'official':'https://kokkai.ndl.go.jp/api.html','update':'monthly'},
 'snow_t15': {'mode':'official_dataset','redistributable':True,'license':'CC BY 4.0',
   'official':'https://www.jnlp.org/SNOW/T15','update':'manual'},
 'jsut_text': {'mode':'official_dataset','redistributable':True,'license':'record-specific; commonly CC BY-SA 4.0, verify LICENCE',
   'official':'https://sites.google.com/site/shinnosuketakamichi/publication/jsut','update':'manual'},
 'oncoj': {'mode':'official_dataset','redistributable':True,'license':'CC BY 4.0',
   'official':'https://oncoj.ninjal.ac.jp/','update':'release'},
 'nhk_easy': {'mode':'link_only','redistributable':False,'license':'NHK copyrighted; permission required',
   'official':'https://www3.nhk.or.jp/news/easy/','update':'never-copy-body'},
}


def _connect(path, readonly=False):
    if readonly:
        c=sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro',uri=True)
    else:c=sqlite3.connect(path)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=DELETE')
    c.execute('PRAGMA synchronous=FULL')
    return c


# ---------------------------------------------------------------------------
# v25：分片只读连接缓存 + 可丢弃的 bigram 倒排索引。
#
# 背景：federated_search._shard_candidates 此前对每个分片、每次查询都重新
# open() 一个连接，并对 `text LIKE '%term%'` 做全表扫描（无法用 B-tree，前导
# 通配符）。分片数一多（真实语料按 48 MiB 一片轮转，可能几十上百片），单次检索
# 就是 N_片 × N_候选词 次全表扫描，正是「精排/召回阶段耗时 20+ 秒，个别情况下
# 超过反向代理或应用超时导致连接被切断（浏览器侧表现为 JSON.parse 报
# "Unexpected end of JSON input"）」的根因。
#
# 修复思路（不违反分片不可变、不常驻内存两条既有约束）：
# - 只读连接按文件路径 + mtime 缓存复用，省掉重复 open/close 的系统调用开销；
# - 为每个分片惰性构建一份「派生、可随时丢弃、不放进 Git」的字符 bigram 倒排
#   索引 sidecar（`<shard 目录>/idx/<分片文件名>.idx.db`），把候选检索从全表
#   扫描降为索引查找；索引本身不常驻内存，仍是磁盘上的 SQLite 文件，由操作系统
#   页缓存按需换入换出；
# - sidecar 内容随源分片的 (size, mtime_ns) 变化自动判定过期重建；分片本身只读
#   不会被修改，因此正常情况下只需构建一次；
# - 任何环境下索引缺失/损坏/构建失败都静默回退到原始全表扫描，绝不因为加速层
#   出问题而让检索整体失败。
# ---------------------------------------------------------------------------
_RO_CACHE = {}          # str(path) -> (mtime_ns, size, sqlite3.Connection)
_IDX_SUBDIR = 'idx'


def ro_conn(path):
    """打开（或复用缓存的）分片只读连接；分片内容一旦改变（文件被替换）自动重开。"""
    path = Path(path)
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        return None
    hit = _RO_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    if hit:
        try:
            hit[2].close()
        except sqlite3.Error:
            pass
    try:
        conn = _connect(path, True)
    except sqlite3.Error:
        _RO_CACHE.pop(key, None)
        return None
    _RO_CACHE[key] = (st.st_mtime_ns, st.st_size, conn)
    return conn


def _idx_path(shard_path):
    shard_path = Path(shard_path)
    d = shard_path.parent / _IDX_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d / (shard_path.name + '.idx.db')


def _text_grams(text):
    s = str(text or '')
    if len(s) < 2:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def ensure_shard_index(shard_path, force=False):
    """确保分片的 bigram 倒排索引最新；返回索引 sqlite 文件路径，构建/校验失败返回 None
    （调用方应回退为对原分片的全表扫描，不应把索引缺失当成错误）。"""
    shard_path = Path(shard_path)
    try:
        src_stat = shard_path.stat()
    except OSError:
        return None
    idx_path = _idx_path(shard_path)
    if not force and idx_path.exists():
        try:
            with sqlite3.connect(f'file:{idx_path}?mode=ro', uri=True) as ic:
                meta = dict(ic.execute('SELECT k,v FROM meta').fetchall())
            if (meta.get('src_size') == str(src_stat.st_size)
                    and meta.get('src_mtime') == str(src_stat.st_mtime_ns)):
                return idx_path
        except sqlite3.Error:
            pass    # 索引缺失/损坏 → 下面重建
    tmp = idx_path.with_suffix('.tmp')
    try:
        if tmp.exists():
            tmp.unlink()
        with _connect(shard_path, True) as sc:
            src_rows = sc.execute('SELECT rowid AS rid, uid, text FROM sentences').fetchall()
        ic = sqlite3.connect(tmp)
        try:
            ic.execute('PRAGMA journal_mode=DELETE')
            ic.execute('CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)')
            ic.execute('CREATE TABLE grams(gram TEXT NOT NULL, rid INTEGER NOT NULL)')
            ic.execute('CREATE TABLE docs(rid INTEGER PRIMARY KEY, uid TEXT NOT NULL)')

            def _gen():
                for r in src_rows:
                    for g in _text_grams(r['text']):
                        yield (g, r['rid'])
            ic.executemany('INSERT INTO grams(gram,rid) VALUES(?,?)', _gen())
            ic.executemany('INSERT INTO docs(rid,uid) VALUES(?,?)',
                            ((r['rid'], r['uid']) for r in src_rows))
            ic.execute('CREATE INDEX idx_grams_gram ON grams(gram)')
            ic.execute('INSERT INTO meta VALUES(?,?)', ('src_size', str(src_stat.st_size)))
            ic.execute('INSERT INTO meta VALUES(?,?)', ('src_mtime', str(src_stat.st_mtime_ns)))
            ic.execute('INSERT INTO meta VALUES(?,?)', ('rows', str(len(src_rows))))
            ic.commit()
        finally:
            ic.close()
        os.replace(tmp, idx_path)
        return idx_path
    except (sqlite3.Error, OSError):
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return None


def index_candidate_uids(shard_path, terms, cap):
    """用 bigram 倒排索引查候选 uid 集合；索引不存在/查询失败返回 None（调用方回退扫描）。
    只查已存在的索引，不在这里同步构建（构建交给后台预热或显式调用，避免首次查询卡顿）。"""
    idx_path = _idx_path(Path(shard_path))
    if not idx_path.exists():
        return None
    terms = [t for t in dict.fromkeys(terms) if len(t) == 2]
    if not terms:
        return None
    try:
        with sqlite3.connect(f'file:{idx_path}?mode=ro', uri=True) as ic:
            uids = set()
            ph = ','.join('?' * len(terms))
            for row in ic.execute(
                    f'SELECT DISTINCT d.uid FROM grams g JOIN docs d ON d.rid=g.rid '
                    f'WHERE g.gram IN ({ph}) LIMIT ?', terms + [cap]):
                uids.add(row[0])
            return uids
    except sqlite3.Error:
        return None


def init_dirs(root=None):
    global ROOT,SHARD_DIR,STAGING_DIR
    if root:
        ROOT=Path(root);SHARD_DIR=ROOT/'shards';STAGING_DIR=ROOT/'staging'
    SHARD_DIR.mkdir(parents=True,exist_ok=True);STAGING_DIR.mkdir(parents=True,exist_ok=True)
    return ROOT


def canonical_text(text):
    return ' '.join(str(text or '').replace('\u3000',' ').split()).strip()


def text_uid(text):
    return hashlib.sha256(canonical_text(text).encode('utf-8')).hexdigest()


def create_staging(source_id, root=None):
    init_dirs(root)
    if source_id not in SOURCES or not SOURCES[source_id]['redistributable']:
        raise ValueError('source is not approved for body ingestion')
    path=STAGING_DIR/f'{source_id}-{time.time_ns()}.db'
    with _connect(path) as c:
        c.executescript(DDL)
        for k,v in {'schema_version':SCHEMA_VERSION,'source_id':source_id,'sealed':'0'}.items():
            c.execute('INSERT INTO meta VALUES(?,?)',(k,str(v)))
    return path


def add_records(path, records, source_id):
    """幂等写入 staging；返回 added/duplicate/rejected。达到目标大小由调用方密封轮换。"""
    policy=SOURCES.get(source_id)
    if not policy or not policy['redistributable']:raise ValueError('unapproved source')
    added=duplicate=rejected=0
    with _connect(path) as c:
        for r in records:
            text=canonical_text(r.get('text'))
            license_name=r.get('license') or policy['license']
            if not text or len(text)<2 or not license_name:
                rejected+=1;continue
            uid=text_uid(text)
            try:
                c.execute('''INSERT INTO sentences
                (uid,text,translation,language,source_id,source_item_id,source_url,title,author,
                 license,attribution,retrieved_at,content_hash,created_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                 (uid,text,r.get('translation'),r.get('language','jpn'),source_id,
                  str(r.get('source_item_id') or ''),r.get('source_url'),r.get('title'),r.get('author'),
                  license_name,r.get('attribution'),r.get('retrieved_at') or time.time(),uid,time.time()))
                added+=1
            except sqlite3.IntegrityError:duplicate+=1
    if path.stat().st_size>MAX_BYTES:
        raise RuntimeError('shard exceeded hard 80 MiB limit; seal more frequently')
    return {'added':added,'duplicate':duplicate,'rejected':rejected,'bytes':path.stat().st_size,
            'should_seal':path.stat().st_size>=TARGET_BYTES}


def seal(path):
    """VACUUM+完整性检查，写入行数后按文件内容哈希密封；同内容自然去重。"""
    path=Path(path);init_dirs()
    with _connect(path) as c:
        ok=c.execute('PRAGMA integrity_check').fetchone()[0]
        if ok!='ok':raise RuntimeError('integrity_check: '+ok)
        n=c.execute('SELECT COUNT(*) FROM sentences').fetchone()[0]
        if not n:raise ValueError('empty shard')
        c.execute("INSERT OR REPLACE INTO meta VALUES('sealed','1')")
        c.execute("INSERT OR REPLACE INTO meta VALUES('rows',?)",(str(n),))
        c.execute("INSERT OR REPLACE INTO meta VALUES('sealed_at',?)",(str(time.time()),))
        c.commit();c.execute('VACUUM')
    size=path.stat().st_size
    if size>MAX_BYTES:raise RuntimeError('sealed shard exceeds 80 MiB')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    dest=SHARD_DIR/f'corpus-{digest}.db'
    if dest.exists():path.unlink()
    else:
        os.replace(path,dest)
        try:dest.chmod(0o444)
        except OSError:pass
    rebuild_manifest()
    return {'path':str(dest),'sha256':digest,'bytes':size,'rows':n}


def inspect_shard(path, verify_hash=False):
    p=Path(path);name=p.stem.replace('corpus-','')
    if verify_hash and hashlib.sha256(p.read_bytes()).hexdigest()!=name:raise ValueError('hash mismatch')
    with _connect(p,True) as c:
        ok=c.execute('PRAGMA quick_check').fetchone()[0]
        if ok!='ok':raise ValueError('quick_check: '+ok)
        n=c.execute('SELECT COUNT(*) FROM sentences').fetchone()[0]
        sources={r['source_id']:r['n'] for r in c.execute('SELECT source_id,COUNT(*) n FROM sentences GROUP BY source_id')}
    return {'file':p.name,'sha256':name,'bytes':p.stat().st_size,'rows':n,'sources':sources}


def rebuild_manifest(root=None, verify=False):
    init_dirs(root);items=[]
    for p in sorted(SHARD_DIR.glob('corpus-*.db')):
        try:items.append(inspect_shard(p,verify))
        except Exception as e:items.append({'file':p.name,'error':str(e)})
    data={'schema_version':SCHEMA_VERSION,'generated_at':time.time(),'target_bytes':TARGET_BYTES,
          'max_bytes':MAX_BYTES,'shards':items,'rows':sum(x.get('rows',0) for x in items)}
    tmp=ROOT/'manifest.json.tmp';tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,ROOT/'manifest.json');return data


def query(q='',source=None,limit=50,offset=0,root=None):
    """跨片稳定归并查询。每片使用 text/source 索引候选；结果按 uid 去重。"""
    init_dirs(root);out={};limit=max(1,min(int(limit),500));offset=max(0,int(offset))
    fetch_n=limit+offset
    for p in SHARD_DIR.glob('corpus-*.db'):
        try:
            with _connect(p,True) as c:
                where=[];args=[]
                if q:where.append('text LIKE ?');args.append('%'+q+'%')
                if source:where.append('source_id=?');args.append(source)
                sql='SELECT * FROM sentences'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY uid LIMIT ?'
                for r in c.execute(sql,args+[fetch_n]):out.setdefault(r['uid'],dict(r))
        except (sqlite3.Error,OSError):continue
    rows=sorted(out.values(),key=lambda r:r['uid'])
    return {'total_lower_bound':len(rows),'rows':rows[offset:offset+limit],
            'shards':len(list(SHARD_DIR.glob('corpus-*.db')))}

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

# -*- coding: utf-8 -*-
"""kanji.db + 任意数量不可变语料分片的统一检索与融合排序。"""
import math
import re
import sqlite3
import time
from pathlib import Path
import corpus_shards
import db


def normalize(s):
    return re.sub(r'[\s　。、，,.!?！？「」『』（）()]','',str(s or '')).lower()


def grams(s):
    s=normalize(s)
    if not s:return set()
    return {s} if len(s)<2 else {s[i:i+2] for i in range(len(s)-1)}


def _score(q,text):
    qn,tn=normalize(q),normalize(text)
    if not qn or not tn:return 0.0
    exact=1.0 if qn in tn else 0.0
    a,b=grams(qn),grams(tn);dice=2*len(a&b)/max(1,len(a)+len(b))
    # 短文本略优先，避免整篇文档凭包含一个词压过精确例句。
    length=1/math.sqrt(max(1,len(tn)/max(1,len(qn))))
    return min(1.0,.62*exact+.30*dice+.08*length)


def _terms(q):
    qn=normalize(q)
    if len(qn)<=2:return [qn] if qn else []
    # 至多四个分散 bigram 作为 SQL 候选，不执行无界全片扫描。
    gs=[qn[i:i+2] for i in range(len(qn)-1)]
    if len(gs)<=4:return list(dict.fromkeys(gs))
    idx=[0,len(gs)//3,2*len(gs)//3,len(gs)-1]
    return list(dict.fromkeys(gs[i] for i in idx))


def _primary_candidates(q,source,cap):
    terms=_terms(q)
    if not terms:return []
    wh=['('+ ' OR '.join('text LIKE ?' for _ in terms)+')'];args=['%'+t+'%' for t in terms]
    if source:wh.append('source=?');args.append(source)
    sql='SELECT id,text,translation,source,url FROM sentences WHERE '+' AND '.join(wh)+' ORDER BY id DESC LIMIT ?'
    try:
        with db.get_conn() as c:return [dict(r) for r in c.execute(sql,args+[cap])]
    except sqlite3.Error:return []


def _shard_candidates(q,source,cap,root=None):
    terms=_terms(q);out=[]
    if not terms:return out
    corpus_shards.init_dirs(root)
    per=max(10,cap//max(1,len(list(corpus_shards.SHARD_DIR.glob('corpus-*.db')))))
    for p in corpus_shards.SHARD_DIR.glob('corpus-*.db'):
        try:
            with corpus_shards._connect(p,True) as c:
                wh=['('+ ' OR '.join('text LIKE ?' for _ in terms)+')'];args=['%'+t+'%' for t in terms]
                if source:wh.append('source_id=?');args.append(source)
                sql='SELECT * FROM sentences WHERE '+' AND '.join(wh)+' ORDER BY uid LIMIT ?'
                out.extend(dict(r) for r in c.execute(sql,args+[per]))
        except (sqlite3.Error,OSError):continue
    return out[:cap]


def search(q,limit=30,source=None,include_primary=True,include_shards=True,root=None):
    """跨库召回、内容哈希去重和统一排序；所有分片失败时仍返回主库结果。"""
    t0=time.time();q=str(q or '').strip();limit=max(1,min(int(limit),200));cap=max(80,limit*8)
    if not q:return {'ok':False,'error':'query required','rows':[]}
    merged={};raw={'primary':0,'shards':0}
    if include_primary:
        rows=_primary_candidates(q,source,cap);raw['primary']=len(rows)
        for r in rows:
            uid=corpus_shards.text_uid(r['text'])
            merged[uid]={'uid':uid,'id':r.get('id'),'text':r['text'],'translation':r.get('translation'),
                         'source':r.get('source'),'url':r.get('url'),'storage':'primary','read_only':False,
                         'provenance':[{'storage':'primary','source':r.get('source'),'url':r.get('url')}]}
    if include_shards:
        rows=_shard_candidates(q,source,cap,root);raw['shards']=len(rows)
        for r in rows:
            uid=r['uid'];prov={'storage':'shard','source':r.get('source_id'),'url':r.get('source_url'),
                               'license':r.get('license'),'source_item_id':r.get('source_item_id')}
            if uid in merged:
                merged[uid]['provenance'].append(prov)
            else:
                merged[uid]={'uid':uid,'id':None,'text':r['text'],'translation':r.get('translation'),
                             'source':r.get('source_id'),'url':r.get('source_url'),'license':r.get('license'),
                             'attribution':r.get('attribution'),'storage':'shard','read_only':True,
                             'provenance':[prov]}
    rows=list(merged.values())
    for r in rows:r['score']=round(_score(q,r['text']),4)
    rows=[r for r in rows if r['score']>=.08]
    rows.sort(key=lambda r:(-r['score'],0 if r['storage']=='primary' else 1,len(r['text']),r['uid']))
    return {'ok':True,'query':q,'rows':rows[:limit],'total_candidates':len(rows),'raw_candidates':raw,
            'sources':dict((s,sum(1 for r in rows if r.get('source')==s)) for s in {r.get('source') for r in rows}),
            'ms':round((time.time()-t0)*1000,2),'shards':len(list(corpus_shards.SHARD_DIR.glob('corpus-*.db')))}

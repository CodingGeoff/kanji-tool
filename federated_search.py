# -*- coding: utf-8 -*-
"""kanji.db + 任意数量不可变语料分片的统一检索与融合排序。"""
import math
import os
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


# v25：分片阶段的默认超时预算——不管分片数量/体积如何增长，跨分片候选召回最多只
# 花这么久就收工（用已收集到的结果排序），不再让单次检索被拖到 20+ 秒、甚至被
# 上游反向代理/应用服务器超时掐断连接（那正是「SyntaxError: Unexpected end of
# JSON input」的来源——响应还没写完，连接已经被杀）。可用环境变量覆盖。
SHARD_BUDGET_S = float(os.environ.get('RAG_SHARD_BUDGET_S', '1.2'))


def _shard_scan_like(conn, terms, source, per):
    wh=['('+ ' OR '.join('text LIKE ?' for _ in terms)+')'];args=['%'+t+'%' for t in terms]
    if source:wh.append('source_id=?');args.append(source)
    sql='SELECT * FROM sentences WHERE '+' AND '.join(wh)+' ORDER BY uid LIMIT ?'
    try:return [dict(r) for r in conn.execute(sql,args+[per])]
    except sqlite3.Error:return []


def _shard_candidates(q,source,cap,root=None,budget_s=None):
    terms=_terms(q);out=[]
    if not terms:return out
    corpus_shards.init_dirs(root)
    budget_s=SHARD_BUDGET_S if budget_s is None else budget_s
    shard_paths=list(corpus_shards.SHARD_DIR.glob('corpus-*.db'))
    per=max(10,cap//max(1,len(shard_paths)))
    t0=time.time()
    for p in shard_paths:
        if budget_s and (time.time()-t0)>budget_s:
            break   # 超预算：不再打开新分片；宁可少召回，不无限等待
        conn=corpus_shards.ro_conn(p)
        if conn is None:continue
        try:
            # 优先走 bigram 倒排索引（近似 O(命中量) 而非全表扫描）；索引缺失/失效
            # 时静默回退到原始 LIKE 全表扫描，保证功能永远可用，只是那一片会慢些。
            uids=corpus_shards.index_candidate_uids(p,terms,per*4)
            if uids is None:
                out.extend(_shard_scan_like(conn,terms,source,per))
            elif uids:
                ph=','.join('?'*len(uids))
                wh=[f'uid IN ({ph})'];args=list(uids)
                if source:wh.append('source_id=?');args.append(source)
                sql='SELECT * FROM sentences WHERE '+' AND '.join(wh)+' LIMIT ?'
                try:
                    out.extend(dict(r) for r in conn.execute(sql,args+[per]))
                except sqlite3.Error:
                    out.extend(_shard_scan_like(conn,terms,source,per))
        except (sqlite3.Error,OSError):continue
    return out[:cap]


def warm_shard_indices(root=None, budget_s=None, max_shards=None):
    """后台预热：为尚未建好倒排索引（或已过期）的分片补建索引，避免用户的第一次
    查询撞上"索引不存在→回退全表扫描"的慢路径。budget_s 限制单次预热总耗时，供
    后台线程分批调用；返回本次实际构建/确认最新的分片数。"""
    corpus_shards.init_dirs(root)
    t0=time.time();built=0;n=0
    for p in sorted(corpus_shards.SHARD_DIR.glob('corpus-*.db')):
        if max_shards and n>=max_shards:break
        if budget_s and (time.time()-t0)>budget_s:break
        n+=1
        if corpus_shards.ensure_shard_index(p) is not None:
            built+=1
    return built


def search(q,limit=30,source=None,include_primary=True,include_shards=True,root=None,budget_s=None):
    """跨库召回、内容哈希去重和统一排序；所有分片失败时仍返回主库结果。

    budget_s：分片扫描阶段的墙钟预算（默认 SHARD_BUDGET_S）；超时即停止打开新分片，
    用已收集到的候选继续排序返回，保证整体延迟有上界。"""
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
    t_shard0=time.time()
    if include_shards:
        rows=_shard_candidates(q,source,cap,root,budget_s);raw['shards']=len(rows)
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
    shard_ms=round((time.time()-t_shard0)*1000,2)
    rows=list(merged.values())
    for r in rows:r['score']=round(_score(q,r['text']),4)
    rows=[r for r in rows if r['score']>=.08]
    rows.sort(key=lambda r:(-r['score'],0 if r['storage']=='primary' else 1,len(r['text']),r['uid']))
    return {'ok':True,'query':q,'rows':rows[:limit],'total_candidates':len(rows),'raw_candidates':raw,
            'sources':dict((s,sum(1 for r in rows if r.get('source')==s)) for s in {r.get('source') for r in rows}),
            'ms':round((time.time()-t0)*1000,2),'shard_ms':shard_ms,
            'shards':len(list(corpus_shards.SHARD_DIR.glob('corpus-*.db')))}

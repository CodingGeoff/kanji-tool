# -*- coding: utf-8 -*-
"""
RAG 语义检索引擎（本地、零外部依赖）
================================================================
对全库语料构建 字符二元组(bigram) TF-IDF 向量索引，余弦相似度检索。
日语无空格分词场景下字符 n-gram 是经典有效的稠密度折衷方案：
  - 「勉強を始めた」与「学習を開始した」通过共现字符片段仍可召回
  - 索引全内存、构建 O(N)、查询毫秒级，语料增长时自动重建
用途：
  - 语义找句：输入任意日文/关键词，召回最相关例句
  - 相似例句：给定句子找语料库中的近义句（复习换句、举一反三）
"""
import math
import re
import threading

import db

_PUNCT = re.compile(r'[\s。、！？!?，,.．「」『』（）()・：;；…—0-9０-９]')


def _grams(text):
    t = _PUNCT.sub('', text)
    out = {}
    for i in range(len(t) - 1):
        g = t[i:i + 2]
        out[g] = out.get(g, 0) + 1
    # 单字也計入（短查询友好）
    for ch in t:
        out[ch] = out.get(ch, 0) + 0.5
    return out


class RagIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self._vecs = {}      # sid -> {gram: tfidf}
        self._norms = {}     # sid -> vector norm
        self._df = {}
        self._n = 0
        self._built_count = -1

    def _build(self):
        with db.get_conn() as c:
            rows = c.execute('SELECT id, text FROM sentences').fetchall()
        docs = {r['id']: _grams(r['text']) for r in rows}
        df = {}
        for g_map in docs.values():
            for g in g_map:
                df[g] = df.get(g, 0) + 1
        n = max(len(docs), 1)
        vecs, norms = {}, {}
        for sid, g_map in docs.items():
            v = {}
            for g, tf in g_map.items():
                idf = math.log((n + 1) / (df.get(g, 1) + 0.5))
                v[g] = (1 + math.log(tf)) * idf if tf > 0 else 0
            nrm = math.sqrt(sum(x * x for x in v.values())) or 1.0
            vecs[sid] = v
            norms[sid] = nrm
        self._vecs, self._norms, self._df, self._n = vecs, norms, df, n
        self._built_count = len(docs)

    def ensure(self):
        with self._lock:
            with db.get_conn() as c:
                cnt = c.execute('SELECT COUNT(*) n FROM sentences').fetchone()['n']
            # 语料变动超过5%或从未构建时重建
            if self._built_count < 0 or abs(cnt - self._built_count) > max(10, self._built_count * 0.05):
                self._build()

    def query(self, text, limit=10, exclude_sid=None):
        self.ensure()
        qv = {}
        for g, tf in _grams(text).items():
            idf = math.log((self._n + 1) / (self._df.get(g, 1) + 0.5))
            qv[g] = (1 + math.log(tf)) * idf if tf > 0 else 0
        qn = math.sqrt(sum(x * x for x in qv.values())) or 1.0
        scores = []
        for sid, v in self._vecs.items():
            if sid == exclude_sid:
                continue
            dot = 0.0
            small, big = (qv, v) if len(qv) < len(v) else (v, qv)
            for g, w in small.items():
                if g in big:
                    dot += w * big[g]
            if dot > 0:
                scores.append((dot / (qn * self._norms[sid]), sid))
        scores.sort(reverse=True)
        return [(sid, round(sc, 4)) for sc, sid in scores[:limit]]


INDEX = RagIndex()

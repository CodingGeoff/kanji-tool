# -*- coding: utf-8 -*-
"""临时调试：定位 tokens 缺失行 / 歌名行顺序 / 优先级排序"""
import json
import sys
import urllib.request

BASE = 'http://127.0.0.1:5097'


def rag(q, **kw):
    body = json.dumps(dict(q=q, **kw)).encode('utf-8')
    req = urllib.request.Request(BASE + '/api/rag/search', data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8'))


d = rag('世界', limit=6)
bad = []
for src, lst in (('rows', d['rows']), ('groups.lyric', d['groups']['lyric']),
                 ('groups.textbook', d['groups']['textbook']), ('groups.web', d['groups']['web'])):
    for i, x in enumerate(lst):
        if 'tokens' not in x:
            bad.append((src, i, x.get('type'), x.get('kind'), repr(x.get('text'))[:20]))
print('缺 tokens 的行:', bad)
print('rows 数:', len(d['rows']), 'groups 数:', {k: len(v) for k, v in d['groups'].items()})

title = '好きだよ。～100回の後悔～'
d2 = rag(title, limit=8)
print('\n-- titles.songs --')
for t in d2['titles']['songs']:
    print('   ', t['id'], t['title'], t['score'])
print('-- groups.lyric 前 5 --')
for x in d2['groups']['lyric'][:5]:
    print('   ', x.get('kind'), x.get('id'), x.get('title'), x.get('score'), x.get('title_match'))

d3 = rag('世界', limit=10, sources=['web', 'lyric', 'textbook'])
print('\n-- sort=priority（默认）· 优先级 web 优先：results 通道序列 --')
print([x['channel'] for x in d3['results']][:12])
print('scores', [x['score'] for x in d3['results']][:12])
print('prior', d3['meta']['prior'], 'sort', d3['meta']['sort'])
d4 = rag('世界', limit=10, sources=['lyric', 'textbook', 'web'])
print('-- 优先级 lyric 优先：results 通道序列 --')
print([x['channel'] for x in d4['results']][:12])
print('scores', [x['score'] for x in d4['results']][:12])
d5 = rag('世界', limit=10, sources=['lyric', 'web'], sort='score')
print('-- sort=score：results 通道序列 --')
print([x['channel'] for x in d5['results']][:12])
print('scores', [x['score'] for x in d5['results']][:12])
print('-- groups 是否都有 tokens --')
for k, v in d3['groups'].items():
    print('   ', k, all('tokens' in x for x in v), len(v))

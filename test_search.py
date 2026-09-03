# -*- coding: utf-8 -*-
"""省流模式 / 高级学习模式(含歌词) / 句子结构相似检索 测试"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, '.')

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


# ============ 1. 结构引擎单元 ============
import structsim as ss

print('== 句子判定 ==')
check(ss.is_sentence('私は毎日電車で学校に行く。') is True, '整句→句子')
check(ss.is_sentence('勉強') is False, '单词→非句子')
check(ss.is_sentence('美味しい') is False, '形容词→非句子')
check(ss.is_sentence('天気') is False, '名词→非句子')

print('== 结构相似度 ==')
a = ss.signature('私は本を読んだ。')
b = ss.signature('僕は歌を歌った。')
c = ss.signature('今日は良い天気だ。')
sc_same = ss.similarity(a, b, 9, 9)
sc_diff = ss.similarity(a, c, 9, 9)
check(sc_same > 0.7, f'结构同形相似度高 {sc_same:.2f}')
check(sc_same > sc_diff + 0.2, f'结构同形 > 结构异形 ({sc_same:.2f} vs {sc_diff:.2f})')

desc = ss.describe(a, '私は本を読んだ。')
check(desc['particles'] == ['は', 'を'], f"助词链={desc['particles']}")
check('名词' in desc['pos_chain'] and '动词' in desc['pos_chain'], '词性链含中文标签')

# ============ 2. API（临时库全链路） ============
print('== API 全链路 ==')
import sqlite3
import db
tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    c0.execute('DELETE FROM songs')
    # 旧库兼容：模拟无 settings 表的老库
    c0.execute('DROP TABLE IF EXISTS settings')
db.DB_PATH = api_db
import app as appmod
client = appmod.app.test_client()

# 2.1 旧库自动补建 settings 表
with sqlite3.connect(api_db) as c0:
    tabs = {r[0] for r in c0.execute("SELECT name FROM sqlite_master WHERE type='table'")}
check('settings' in tabs, '旧库升级后补建 settings 表')

# 2.2 省流模式开关
r = client.get('/api/settings')
check(r.get_json().get('data_saver') is False, '省流默认关闭')
r = client.post('/api/settings', json={'data_saver': True})
check(r.get_json().get('data_saver') is True, '省流开启')
check(db.get_setting('data_saver', '0') == '1', '省流设置已持久化')
r = client.get('/api/stats')
check(r.get_json().get('data_saver') is True, 'stats 暴露省流状态')
r = client.post('/api/settings', json={'data_saver': False})
check(r.get_json().get('data_saver') is False, '省流关闭')

# 2.3 导入两首歌（供歌词搜索 / 结构匹配）
blob = """《青い空》
私は歌を歌った
君と公園を歩いた

---

《赤い夕日》
僕は絵を描いた"""
r = client.post('/api/songs/import', json={'text': blob})
check(len(r.get_json()['created']) == 2, '导入 2 首测试歌')

# 2.4 歌词行搜索（高级学习模式）
r = client.get('/api/songs/search?q=歌った')
d = r.get_json()
check(d['total'] == 1 and d['rows'][0]['title'] == '青い空', f"歌词行搜索={d}")
check(any(t.get('r') for t in d['rows'][0]['tokens']), '歌词行带注音')
r = client.get('/api/songs/search?q=不存在的东西XYZ')
check(r.get_json()['total'] == 0, '无命中返回空')

# 2.5 RAG：关键词 → 无结构分析
r = client.post('/api/rag/search', json={'q': '勉強', 'limit': 3})
d = r.get_json()
check('struct' not in d and d.get('rows') is not None, '关键词→纯语义检索')

# 2.6 RAG：整句 → 成分分析 + 结构相似（歌词优先）
r = client.post('/api/rag/search', json={'q': '私は本を読んだ。', 'limit': 8})
d = r.get_json()
check('struct' in d, '整句→触发结构分析')
if 'struct' in d:
    st = d['struct']
    check(st['components']['particles'] == ['は', 'を'], f"成分助词={st['components']['particles']}")
    check(st['components']['ending'], '句尾形态非空')
    lyric_rows = [x for x in st['rows'] if x['type'] == 'lyric']
    check(any(x['text'] == '私は歌を歌った' for x in lyric_rows),
          f"结构同形歌词「私は歌を歌った」被召回 {[(x['type'], x['text']) for x in st['rows'][:5]]}")
    check('私は歌を歌った' in {x['text']: x for x in st['rows']} and
          {x['text']: x for x in st['rows']}['私は歌を歌った']['shared_particles'] == ['は', 'を'],
          '共用助词标注正确')
    # 歌词优先：同构歌词应排在前排（前3）
    top3 = [x['text'] for x in st['rows'][:3]]
    check('私は歌を歌った' in top3, f'歌词优先排序 {top3}')

# 2.7 语料库搜索合并歌词（前端逻辑，后端接口验证已覆盖）；清理
for srow in client.get('/api/songs').get_json()['songs']:
    client.delete(f"/api/songs/{srow['id']}")
shutil.rmtree(tmp, ignore_errors=True)

print()
if FAILS:
    print(f'===== 检索/省流测试: 失败 {len(FAILS)} 项 =====')
    sys.exit(1)
print('===== 检索/省流测试: 全部通过 =====')
sys.exit(0)

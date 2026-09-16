# -*- coding: utf-8 -*-
"""自建课本模块测试：自动拆分 / 字词句提取 / 截止日计划（艾宾浩斯曲线 + 容量保证）/
以前进度自动识别 / CRUD 全链路（临时库隔离，不碰真实数据）"""
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


import sqlite3
import db
import srs as srs_mod
tmp = tempfile.mkdtemp()
api_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    # 干净沙盘：清空课本相关表与 SRS/语料，保证测试可预期
    for t in ('books', 'book_lessons', 'book_sentences', 'book_kanji', 'book_words',
              'book_plan', 'book_progress', 'srs', 'sentences', 'fav_sentences'):
        try:
            c0.execute(f'DELETE FROM {t}')
        except sqlite3.OperationalError:
            pass
db.DB_PATH = api_db
import textbook
import app as appmod
client = appmod.app.test_client()

SAMPLE = """《東京散策》
作者：テスト
难度：N4
第1課
今日は良い天気ですね。東京タワーへ行きました。

第2課
桜が咲きました。春は美しい季節です。
---

《春の歌》
第1課
花見に行きます。お花見は楽しいです。"""

# ============ 1. 文本拆分（纯函数） ============
print('== 1. 课本拆分 ==')
books = textbook.parse_books(SAMPLE)
check(len(books) == 2, f'拆出 2 本，实际 {len(books)}')
b0 = books[0]
check(b0['title'] == '東京散策', f'书名，实际 {b0["title"]}')
check(b0['author'] == 'テスト', f'作者行识别，实际 {b0["author"]}')
check(b0['level'] == 'N4', f'难度行识别，实际 {b0["level"]}')
check(len(b0['lessons']) == 2, f'2 课，实际 {len(b0["lessons"])}')
check(b0['lessons'][0]['title'] == '第1課', f'课标题，实际 {b0["lessons"][0]["title"]}')
check(b0['lessons'][0]['sentences'] == ['今日は良い天気ですね。', '東京タワーへ行きました。'],
      f'句切分，实际 {b0["lessons"][0]["sentences"]}')
check(len(books[1]['lessons'][0]['sentences']) == 2, '第二本 2 句')

# 自动分课（无标题长文：一行长段落按句切分后分课）
auto = textbook.parse_books('自动分课本\n' + '。'.join(f'その{i}の話は長いです' for i in range(1, 19)) + '。')
check(auto[0]['title'] == '自动分课本', '自动分课：书名')
exp_lessons = -(-18 // textbook.AUTO_LESSON_SIZE)      # ⌈18/每课句数⌉
check(len(auto[0]['lessons']) == exp_lessons,
      f'18 句按 {textbook.AUTO_LESSON_SIZE} 句/课自动拆 {exp_lessons} 课，实际 {len(auto[0]["lessons"])} 课')

# 字词句提取
kj, wd = textbook.extract_units('今日は良い天気ですね。')
check(any(k == '今' and w == '今日' for k, w, _r in kj), f'字提取，实际 {kj}')
check(any(w == '天気' and r == 'てんき' for w, r, _k, _p in wd), f'词提取，实际 {wd}')
curve10_days = sum(srs_mod.INTERVALS_MIN) // 1440      # 10 阶段全程 ≈ 2个月曲线的累计天数
check(textbook.curve_days(1) == 0 and textbook.curve_days(10) == curve10_days,
      f'curve_days 边界: curve_days(10)={textbook.curve_days(10)} 应为 {curve10_days}')

# ============ 2. 预览 analyze ============
print('== 2. 导入前预览 ==')
r = client.post('/api/books/analyze', json={'text': SAMPLE})
d = r.get_json()
check(r.status_code == 200, f'analyze 200，实际 {r.status_code}')
check(d['book_count'] == 2 and d['sentences'] == 6 and d['lessons'] == 3, f'预览统计 {d}')
check(d['kanji'] > 0 and d['words'] > 0, '字词统计非零')

# ============ 3. 导入 ============
print('== 3. 导入（自动拆分 + 注音 + 索引） ==')
r = client.post('/api/books/import', json={'text': SAMPLE, 'deadline': '2026-10-15',
                                           'minutes_per_day': 30, 'target_stage': 5})
d = r.get_json()
check(r.status_code == 200 and d['ok'], f'导入 ok {d}')
check(len(d['books']) == 2, f'导入 2 本，实际 {len(d["books"])}')
idA, idB = d['books'][0]['id'], d['books'][1]['id']
check(d['books'][0]['sentences'] == 4 and d['books'][0]['kanji'] == 14, f'本书统计 {d["books"][0]}')

# 重复导入 → 去重不翻倍
r = client.post('/api/books/import', json={'text': SAMPLE})
d2 = r.get_json()
check(d2['books'][0]['new_sentences'] == 0 and d2['books'][0]['duplicated'] == 4,
      f'重复导入去重 {d2["books"][0]}')

# ============ 4. 列表与详情 ============
print('== 4. 书列表 / 详情 ==')
r = client.get('/api/books')
d = r.get_json()
check(len(d['rows']) == 2, f'列表 2 本，实际 {len(d["rows"])}')
row = [x for x in d['rows'] if x['id'] == idA][0]
check(row['lessons'] == 2 and row['sentences'] == 4 and row['kanji_total'] == 14, f'列表统计 {row}')

r = client.get(f'/api/books/{idA}')
det = r.get_json()
check(r.status_code == 200 and len(det['lessons_list']) == 2, '详情：课列表')
check(det['curve'] and len(det['curve']) == 10, '详情：完整 10 阶段记忆曲线')
per_lesson = [l['kanji'] for l in det['lessons_list']]
check(sum(per_lesson) == 14 and all(x > 0 for x in per_lesson),
      f'每课字数合计 14 {[(l["kanji"], l["title"]) for l in det["lessons_list"]]}')

# ============ 5. 截止日计划（核心算法） ============
print('== 5. 学习计划：曲线走完 + 每日容量 ==')
r = client.post('/api/books/plan', json={'book_ids': [idA], 'deadline': '2026-10-15',
                                         'minutes_per_day': 30, 'target_stage': 5})
p = r.get_json()
check(r.status_code == 200 and p['feasible'] is True, f'计划可行 {p.get("reason")}')
check(p['start'] == textbook.date.today().isoformat() and p['deadline'] == '2026-10-15', '计划区间')
curve5 = textbook.curve_days(5)
check(p['curve_days'] == curve5, f'curve_days={p["curve_days"]} 应为 {curve5}')
# 新字最晚引入日 + 曲线天数 = 截止日
check(textbook.date.fromisoformat(p['last_intro_day']).toordinal() + curve5 ==
      textbook.date.fromisoformat(p['deadline']).toordinal(), '最晚引入日 + 曲线 = 截止日')
days = p['per_day']
check(all(d0['load_min'] <= p['minutes_per_day'] + 0.01 for d0 in days), '每天负载不超容量')
last_new_idx = max(i for i, d0 in enumerate(days) if d0['new'])
intro_limit_idx = days.index(next(d0 for d0 in days if d0['day'] == p['last_intro_day']))
check(last_new_idx <= intro_limit_idx,
      f'新字须在曲线完成线（第 {intro_limit_idx} 天）前引入，实际最晚第 {last_new_idx} 天')
check(p['new_total'] == 14, f'14 个新字，实际 {p["new_total"]}')
# 计划落库
r = client.get(f'/api/books/plan?ids={idA}')
lp = r.get_json()
check(lp['ok'] and len(lp['per_day']) >= 8, f'计划已保存可读取（{len(lp.get("per_day") or [])} 天）')
check(lp['today_tasks'] and len(lp['today_tasks']['new']) > 0, '今日有新字任务')
check(lp['total_new'] == 14 and lp['progress'] == 0.0, f'进度初始 {lp["progress"]}%')

# 不可行：截止日早于曲线本身
r = client.post('/api/books/plan', json={'book_ids': [idA], 'deadline':
                  str(textbook.date.today().replace(year=2020)), 'target_stage': 10})
p2 = r.get_json()
check(p2['feasible'] is False and '截止日太早' in (p2['reason'] or ''), f'过早截止被识别 {p2.get("reason")}')
check(p2['need_days'] == textbook.curve_days(10) + 1, f'need_days {p2.get("need_days")}')

# ============ 6. 以前的学习进度自动识别 ============
print('== 6. 进度自动识别（全局 SRS 为准） ==')
prev_new = [it for d0 in lp['per_day'] for it in d0['new']]
k1, k2 = prev_new[0]['kanji'], prev_new[1]['kanji']
r = client.post('/api/learn', json={'kanji': [k1, k2]})   # 模拟以前学过这两个字
check(r.status_code == 200, '全局学习 2 字')
r = client.get(f'/api/books/plan?ids={idA}')
lp2 = r.get_json()
done_map = {it['kanji']: it['done'] for d0 in lp2['per_day'] for it in d0['new']}
check(done_map.get(k1) is True and done_map.get(k2) is True, f'已学字自动打勾 {k1},{k2}')
check(lp2['done_new'] == 2 and lp2['progress'] > 0, f'进度自动计入 {lp2["done_new"]}/{lp2["total_new"]}')
# 重新排程 → 已学字不再排新
r = client.post('/api/books/plan', json={'book_ids': [idA], 'deadline': '2026-10-15',
                                         'minutes_per_day': 30, 'target_stage': 5})
p3 = r.get_json()
check(p3['new_total'] == 12, f'重排后 12 新字（排除已学），实际 {p3["new_total"]}')

# ============ 7. 今日任务勾选 ============
print('== 7. 计划勾选 ==')
r = client.post('/api/books/plan/done', json={'book_ids': [idA], 'kanji': p3['per_day'][1]['new'][0]['kanji'],
                                              'done': True})
d = r.get_json()
check(r.status_code == 200 and d['updated'] >= 1, f'勾选 {d}')

# ============ 8. 句子（按课） ============
print('== 8. 课程句子 ==')
lid = det['lessons_list'][0]['id']
r = client.get(f'/api/books/{idA}/sentences?lesson_id={lid}')
d = r.get_json()
check(d['total'] == 2 and d['rows'][0]['tokens'], '按课取句带注音')
check(all(r0['book_title'] == '東京散策' for r0 in d['rows']), '句子带书名')

# ============ 9. 字/词总表 ============
print('== 9. 字词总表 ==')
r = client.get(f'/api/books/units?type=kanji&ids={idA}')
d = r.get_json()
check(d['total'] == 14 and all('srs_stage' in r0 for r0 in d['rows']), f'字表 {d["total"]}')
first = d['rows'][0]
check(first['kanji'] == '今' and first['word'] == '今日', f'按首次出现排序 {first["kanji"]}/{first["word"]}')
r = client.get(f'/api/books/units?type=words&ids={idA}')
d = r.get_json()
check(d['total'] == 9 and any(r0['word'] == '天気' for r0 in d['rows']), '词表')
r = client.get(f'/api/books/units?type=kanji&ids={idA},{idB}')
d = r.get_json()
check(d['total'] == 17, f'两本合并去重（14+4-1「行」重复），实际 {d["total"]}')

# ============ 10. 本书单字标记 ============
print('== 10. 单字标记（增改删） ==')
r = client.post('/api/books/progress', json={'book_id': idA, 'kanji': '今', 'state': 'done'})
check(r.status_code == 200, '标记 done')
r = client.get(f'/api/books/{idA}')
check(any(m['kanji'] == '今' and m['state'] == 'done' for m in r.get_json()['marks']), '标记可查')
r = client.get(f'/api/books/units?type=kanji&ids={idA}')
check([x for x in r.get_json()['rows'] if x['kanji'] == '今'][0]['progress'] == 'done', '字表带标记')
r = client.post('/api/books/progress', json={'book_id': idA, 'kanji': '今', 'state': ''})
check(r.status_code == 200, '清除标记')
r = client.get(f'/api/books/{idA}')
check(not r.get_json()['marks'], '标记已删')

# ============ 11. 选书模式（一本/多本） ============
print('== 11. 选书模式 ==')
r = client.post('/api/books/active', json={'book_ids': [idA], 'active': True})
check(r.status_code == 200, '选书 active')
r = client.post('/api/books/active', json={'book_ids': [idB], 'active': False})
check(r.status_code == 200, '取消 idB')
r = client.get('/api/books')
act = {x['id']: x['active'] for x in r.get_json()['rows']}
check(act[idA] == 1 and act[idB] == 0, f'active 状态 {act}')
# 计划默认只排 active 的书
r = client.post('/api/books/plan', json={'deadline': '2026-10-15', 'minutes_per_day': 30, 'target_stage': 5})
p4 = r.get_json()
check([b['id'] for b in p4['books']] == [idA], f'默认计划只含 active 书 {p4["books"]}')

# ============ 12. 课/书增删改查 + 重置 ============
print('== 12. CRUD ==')
r = client.put(f'/api/books/{idA}/lessons/{lid}', json={'title': '第一課(改)'})
check(r.status_code == 200, '课改名')
r = client.put(f'/api/books/{idA}', json={'title': '東京散策(改)', 'minutes_per_day': 45})
d = r.get_json()
check(r.status_code == 200 and d['book']['minutes_per_day'] == 45, '书参数更新')
r = client.post(f'/api/books/{idA}/reindex')
check(r.status_code == 200 and r.get_json()['kanji'] == 14, '重建索引')
r = client.post(f'/api/books/{idA}/reset')
check(r.status_code == 200, '重置计划与标记')
r = client.get(f'/api/books/plan?ids={idA}')
check(r.get_json()['empty'] is True, '重置后计划为空')
r = client.delete(f'/api/books/{idB}')
check(r.status_code == 200, '删书 idB')
r = client.get('/api/books')
check(len(r.get_json()['rows']) == 1, '剩 1 本')

# ============ 13. 版本号注入 ============
print('== 13. 版本标注 ==')
r = client.get('/')
html = r.get_data(as_text=True)
check('__APP_VERSION__' not in html and appmod.APP_VERSION in html,
      f'版本号 {appmod.APP_VERSION} 已注入页面')
check('id="tab-books"' in html and 'loadBooks' in html, '我的课本标签页存在')

# ============ 14. 学习配置 / 例句全库检索 / 语法抽取 / 挖空测验 ============
print('== 14. 学习配置与高级学习 ==')
r = client.get('/api/books/study-cfg')
cfg = r.get_json()
check(cfg['example_source'] == 'all' and cfg['grammar_min_level'] == 'N3'
      and cfg['cloze_min_level'] == 'N4' and cfg['cloze_enabled'] is True,
      f'默认配置（语法下限 N3 / 挖空下限 N4）{cfg}')
check(cfg['cloze_stats'] == [], f'初始挖空统计为空 {cfg["cloze_stats"]}')
r = client.post('/api/books/study-cfg', json={'example_limit': 3, 'cloze_scope': 'book',
                                              'cloze_per_day': 4, 'grammar_min_level': 'N3'})
cfg = r.get_json()
check(cfg['ok'] and cfg['cfg']['example_limit'] == 3 and cfg['cfg']['cloze_scope'] == 'book', f'保存配置 {cfg}')
r = client.get('/api/books/study-cfg')
cfg = r.get_json()
check(cfg['example_limit'] == 3 and cfg['cloze_scope'] == 'book', '配置持久化（settings JSON）')

# --- 例句：本书 / 全库 / 混合（本书优先 + 全库补足） ---
r = client.get(f'/api/books/examples?ids={idA}&kanji=今&source=book')
d = r.get_json()
check(d['rows'] and all(x['src'] == 'book' for x in d['rows']), f'本书例句 {len(d["rows"])} 条')
check(all('今' in x['text'] for x in d['rows']), '本书例句都含该字')
check(d['rows'][0]['tokens'], '例句带注音')
r = client.get(f'/api/books/examples?ids={idA}&kanji=今&source=corpus')
d2 = r.get_json()
check(d2['rows'] and all(x['src'] == 'corpus' for x in d2['rows']), f'全库例句 {len(d2["rows"])} 条')
r = client.get(f'/api/books/examples?ids={idA}&kanji=今&limit=1')
d3 = r.get_json()
check(len(d3['rows']) <= 1 and d3['rows'][0]['src'] == 'book', '混合模式本书优先 + limit 生效')

# --- 语法抽取：难度下限过滤（默认不抽 N5/N4 太简单的） ---
gbook = textbook.import_book({'title': '语法书', 'author': '', 'level': '', 'note': '',
                              'lessons': [{'title': '第1課', 'sentences': [
                                  '水を飲んでください。',
                                  '一緒に行きましょう。',
                                  'それは私の本ではない。',
                              ]}]})
gid = gbook['id']
r = client.get(f'/api/books/grammar?ids={gid}&min_level=N5')
gsb = r.get_json()['rows']
check(len(gsb) >= 2 and any(g['level'] == 'N5' for g in gsb), f'语法书抽到 {len(gsb)} 个语法点（含 N5）')
check(any(g['level'] == 'N4' for g in gsb), 'N4 句型（ではない）也被抽出')
check(all(g['example']['text'] and g['explain'] and g['structure'] for g in gsb), '语法点带书中例句/讲解/结构')
r = client.get(f'/api/books/grammar?ids={gid}&min_level=N3')
gs3 = r.get_json()['rows']
check(all(textbook._lv(g['level']) >= 2 for g in gs3), f'N3 下限只留 N3+ {[g["level"] for g in gs3]}')
r = client.get(f'/api/books/grammar?ids={gid}&min_level=N1')
check(all(textbook._lv(g['level']) == 4 for g in r.get_json()['rows']), 'N1 下限只留最高难度')

# --- 挖空测验：本书/全库题源 + 难度下限 + 4 选 1 ---
r = client.post('/api/books/cloze', json={'book_ids': [gid], 'scope': 'book', 'min_level': 'N4', 'count': 3})
qz = r.get_json()
check(qz['ok'] and qz['scope'] == 'book' and qz['count'] >= 1, f'本书题源出 {qz.get("count")} 题')
check(all(textbook._lv(q['level']) >= 1 for q in qz['questions']),
      f'挖空难度≥N4（不考 N5）{[q["level"] for q in qz["questions"]]}')
for q in qz['questions']:
    check(len(q['options']) == 4 and q['answer'] in q['options'] and len(set(q['options'])) == 4,
          f'选项 4 个、含答案、不重复 {q["options"]}')
    check(q['before'] is not None and q['after'] is not None and q['explain'], '挖空上下文与讲解齐全')
r = client.post('/api/books/cloze', json={'scope': 'corpus', 'min_level': 'N5', 'count': 5})
qz2 = r.get_json()
check(qz2['ok'] and qz2['scope'] == 'corpus' and qz2['count'] <= 5, f'全库题源 {qz2["count"]} 题')

# --- 计分 + 当日统计 ---
r = client.post('/api/books/cloze/answer', json={'results': [{'ok': True}, {'ok': False}, {'ok': True}]})
d = r.get_json()
check(d['ok'] and d['asked'] == 3 and d['correct'] == 2, f'计分 {d}')
r = client.get('/api/books/study-cfg')
st = r.get_json()['cloze_stats']
check(st and st[-1]['asked'] == 3 and st[-1]['correct'] == 2, f'当日统计落库 {st}')

# --- 配置开关：关闭挖空 → 服务端拒绝出题 ---
client.post('/api/books/study-cfg', json={'cloze_enabled': False})
r = client.post('/api/books/cloze', json={})
qz3 = r.get_json()
check(qz3.get('ok') is False and '关闭' in (qz3.get('reason') or ''), f'挖空关闭生效 {qz3}')
client.post('/api/books/study-cfg', json={'cloze_enabled': True})
r = client.post('/api/books/cloze', json={'scope': 'corpus', 'min_level': 'N5', 'count': 2})
check(r.get_json()['ok'] is True, '重新开启后可出题')

shutil.rmtree(tmp, ignore_errors=True)
print()
if FAILS:
    print(f'===== 课本模块测试: 失败 {len(FAILS)} 项 =====')
    sys.exit(1)
print('===== 课本模块测试: 全部通过 =====')
sys.exit(0)

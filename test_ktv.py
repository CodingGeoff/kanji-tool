# -*- coding: utf-8 -*-
"""KTV 歌词模块测试：自动整理 / 罗马音转片假名 / 注音 / API 全链路 / 旧库兼容"""
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


# ============ 1. 罗马音 → 片假名 ============
import ktv

ROMAJI_CASES = [
    ('konbanwa', 'コンバンワ'),
    ('konnichiwa', 'コンニチワ'),
    ('shinjuku', 'シンジュク'),
    ('ganbatte', 'ガンバッテ'),
    ('zutto', 'ズット'),
    ('sayounara', 'サヨウナラ'),
    ('arigatou', 'アリガトウ'),
    ('matcha', 'マッチャ'),
    ('gyuunyuu', 'ギュウニュウ'),          # n + 拗音 + 长音
    ('shin’ichi', 'シンイチ'),
    ("shin'ichi", 'シンイチ'),
    ('hon', 'ホン'),                       # 句尾 n → ン
    ('kiss me', 'キッs メ'),             # 英文残留字母原样保留
    ('la la la', 'ラ ラ ラ'),
    ('kyou made', 'キョウ マデ'),
    ('doushite', 'ドウシテ'),
    ('tōkyō', 'トーキョー'),              # 长音符
    ('Natsu no ame', 'ナツ ノ アメ'),     # 大小写
    ('itsuka kitto', 'イツカ キット'),
    ('hayaku', 'ハヤク'),
]
print('== 罗马音转片假名 ==')
for src, dst in ROMAJI_CASES:
    got = ktv.romaji_to_kana(src)
    check(got == dst, f'romaji_to_kana({src!r}) = {got!r}，期望 {dst!r}')

ROMAJI_LINE = [
    ('Kimi wa boku no hikari', True),
    ('wow wow wow', True),
    ('yoru no sora ni hoshi ga mabataku', True),
    ('夢ならばどれほどよかったでしょう', False),
    ('終わり', False),
    ('123', False),
    ('', False),
    ('LOVEマジー？', False),
]
print('== 罗马音行判定 ==')
for line, exp in ROMAJI_LINE:
    got = ktv.is_romaji_line(line)
    check(got == exp, f'is_romaji_line({line!r}) = {got}，期望 {exp}')

# ============ 2. 自动整理 parse_import ============
print('== 歌词自动整理 ==')

# 2.1 单首 + 《》标题 + 空行分段
blob1 = """《星の歌》
夜空に瞬く星を見上げて
あなたのことを思い出す

届かない想いだけが溢れて
涙が頬を伝って落ちた"""
songs = ktv.parse_import(blob1)
check(len(songs) == 1, f'2.1 应识别 1 首，得到 {len(songs)}')
if songs:
    check(songs[0]['title'] == '星の歌', f"2.1 标题={songs[0]['title']!r}")
    check('夜空に瞬く星を見上げて' in songs[0]['lyrics'], '2.1 歌词正文在')
    check('星の歌' not in songs[0]['lyrics'], '2.1 标题行已从正文剥离')
    check('\n\n' in songs[0]['lyrics'], '2.1 段落分隔保留')

# 2.2 --- 分隔的两首
blob2 = """曲名：春の風
歌手：テスト花子
春の風が頬を撫でる

新しい季節が始まる

---

【夏の海】
夏の海に飛び込んだ
冷たい水が気持ちいい"""
songs = ktv.parse_import(blob2)
check(len(songs) == 2, f'2.2 应识别 2 首，得到 {len(songs)}')
if len(songs) == 2:
    check(songs[0]['title'] == '春の風' and songs[0]['artist'] == 'テスト花子',
          f"2.2 第一首={songs[0]['title']!r}/{songs[0]['artist']!r}")
    check('曲名：' not in songs[0]['lyrics'] and '歌手：' not in songs[0]['lyrics'], '2.2 标签行已剥离')
    check(songs[1]['title'] == '夏の海', f"2.2 第二首标题={songs[1]['title']!r}")
    check(songs[1]['lyrics'].startswith('夏の海に'), '2.2 第二首正文正确')

# 2.3 编号曲目表 + 无分隔符内嵌《》
blob3 = """1. 夜の歌
静かな夜に月が昇る
《朝の歌》
朝の光が窓から差す
僕は今日も歩き出す"""
songs = ktv.parse_import(blob3)
check(len(songs) == 2, f'2.3 应识别 2 首（编号+内嵌《》），得到 {len(songs)}')
if len(songs) == 2:
    check(songs[0]['title'] == '夜の歌', f"2.3 编号标题={songs[0]['title']!r}")
    check(songs[1]['title'] == '朝の歌', f"2.3 内嵌标题={songs[1]['title']!r}")

# 2.3b 纯编号曲目表（无任何分隔符）+ 编号+歌手组合
blob3b = """1. Lemon - 米津玄師
夢ならばどれほどよかったでしょう
それでも僕は君を想う
2. 打上花火 - DAOKO
あの日見た花の名前を覚えてる
君といた夏の終わり"""
songs = ktv.parse_import(blob3b)
check(len(songs) == 2, f'2.3b 编号曲目表应拆 2 首，得到 {len(songs)}')
if len(songs) == 2:
    check(songs[0]['title'] == 'Lemon' and songs[0]['artist'] == '米津玄師',
          f"2.3b 第一首={songs[0]['title']!r}/{songs[0]['artist']!r}")
    check(songs[1]['title'] == '打上花火' and songs[1]['artist'] == 'DAOKO',
          f"2.3b 第二首={songs[1]['title']!r}/{songs[1]['artist']!r}")
    check('夢ならばどれほどよかったでしょう' in songs[0]['lyrics'], '2.3b 正文正确')

# 2.4 歌名 - 歌手
blob4 = """未来への翼 - サンプルバンド
高い空へ翼を広げて
風に乗って飛んでいく"""
songs = ktv.parse_import(blob4)
check(len(songs) == 1 and songs[0]['title'] == '未来への翼' and songs[0]['artist'] == 'サンプルバンド',
      f"2.4 dash 标题={songs[0] if songs else None}")

# 2.5 无标记：一首歌整体，CJK 短首行借用为歌名但保留在正文
blob5 = """冬の街
木の葉が舞い落ちる
あなたのいない街を歩く"""
songs = ktv.parse_import(blob5)
check(len(songs) == 1 and songs[0]['title'] == '冬の街', f"2.5 首行借用歌名={songs[0]['title'] if songs else None}")
check('木の葉が舞い落ちる' in songs[0]['lyrics'] and '冬の街' in songs[0]['lyrics'],
      '2.5 歌名行保留在正文中（不丢内容）')

# 2.6 歌词内含「引用」不误判标题；--- 内部分段不炸成多首
blob6 = """雪の詩
白い息が舞う夜に
「またね」と手を振った

---

忘れられない優しい声"""
songs = ktv.parse_import(blob6)
check(len(songs) == 1, f'2.6 无标题多块应合并为 1 首，得到 {len(songs)}')
if songs:
    check(songs[0]['title'] == '雪の詩', f"2.6 标题={songs[0]['title']!r}")
    check('「またね」と手を振った' in songs[0]['lyrics'], '2.6 「引用」行未被当标题')
    check('忘れられない優しい声' in songs[0]['lyrics'], '2.6 --- 后的内容并入同首')

# 2.7 CRLF 与多余空行
blob7 = "《テスト》\r\n歌詞一行目\r\n\r\n\r\n\r\n歌詞二行目\r\n"
songs = ktv.parse_import(blob7)
check(len(songs) == 1 and songs[0]['lyrics'] == '歌詞一行目\n\n歌詞二行目',
      f"2.7 规整结果={songs[0]['lyrics']!r}" if songs else '2.7 无结果')

# 2.8 纯罗马音歌词单首
blob8 = """Haru no kaze
Kaze ga fukinu"""
songs = ktv.parse_import(blob8)
check(len(songs) == 1, '2.8 罗马音一首')
check(songs and songs[0]['title'] == 'Haru no kaze', f"2.8 标题借用={songs[0]['title'] if songs else None}")

# ============ 3. 注音 annotate_lyrics ============
print('== 歌词注音（复用 furigana 引擎） ==')
lyr = "夜空に瞬く星を見上げて\n\nKimi wa boku no hikari\n屆かない想い"  # noqa: 混合
tokens, kcount = ktv.annotate_lyrics(lyr)
check(len(tokens) == 4 and tokens[1] is None, '3.1 tokens 与行对齐（空行=None）')
# 找 夜空 的注音
yozora = [t for t in tokens[0] if t['s'] == '夜空' or '夜空' in (t.get('w') or '')]
check(any(t.get('r') == 'よぞら' or t.get('wr') == 'よぞら' for t in yozora),
      f"3.2 夜空=よぞら，实际 {[(t['s'], t.get('r'), t.get('wr')) for t in tokens[0]][:6]}")
romaji_tok = tokens[2]
check(len(romaji_tok) == 1 and romaji_tok[0].get('k') == 'キミ ワ ボク ノ ヒカリ',
      f"3.3 罗马音行转片假名={romaji_tok}")
check(kcount > 0, '3.4 汉字计数>0')

# ============ 4. 旧库兼容迁移 ============
print('== 旧库兼容（无 songs 表的老 kanji.db） ==')
import db
tmp = tempfile.mkdtemp()
old_db = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), old_db)
import sqlite3
with sqlite3.connect(old_db) as c0:
    n_before = c0.execute('SELECT COUNT(*) FROM sentences').fetchone()[0]
    c0.execute('DROP TABLE IF EXISTS songs')
saved, db.DB_PATH = db.DB_PATH, old_db
try:
    db.init_db()
    db._migrate()
    with sqlite3.connect(old_db) as c0:
        tabs = {r[0] for r in c0.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        n_after = c0.execute('SELECT COUNT(*) FROM sentences').fetchone()[0]
    check('songs' in tabs, '4.1 老库升级后补建 songs 表')
    check(n_before == n_after, f'4.2 原语料无损（{n_before}→{n_after}）')
    # CRUD 冒烟
    sid = db.add_song('テスト曲', '某人', '歌詞\n\nテスト', [[{'s': '歌詞'}], None, [{'s': 'テスト'}]], 2)
    check(sid > 0, '4.3 add_song')
    row = db.get_song(sid)
    check(row and row['title'] == 'テスト曲' and row['kanji_count'] == 2, '4.4 get_song')
    db.update_song(sid, title='改名')
    check(db.get_song(sid)['title'] == '改名', '4.5 update_song')
    lst = db.list_songs('改名')
    check(len(lst) == 1 and lst[0]['lines'] == 3, f"4.6 list_songs 搜索/行数={lst}")
    check(db.song_exists('改名', '歌詞\n\nテスト'), '4.7 song_exists')
    db.delete_song(sid)
    check(db.get_song(sid) is None, '4.8 delete_song')
finally:
    db.DB_PATH = saved
    shutil.rmtree(tmp, ignore_errors=True)

# ============ 5. API 全链路（Flask test client + 临时库，不污染真实数据） ============
print('== API 全链路 ==')
tmp2 = tempfile.mkdtemp()
api_db = os.path.join(tmp2, 'kanji.db')
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kanji.db'), api_db)
with sqlite3.connect(api_db) as c0:
    c0.execute('DELETE FROM songs')          # 确保测试起点无歌
db.DB_PATH = api_db                           # 必须在 import app 之前切换
import app as appmod
client = appmod.app.test_client()

blob = """《夜空の花》
夜空に大きな花が咲いた
あなたと見た幻

Kimi to mita maboroshi

---

【朝の光】 - テスト歌手
朝の光が差し込む
新しい一日が始まる"""
r = client.post('/api/songs/import', json={'text': blob, 'dry_run': True})
d = r.get_json()
check(r.status_code == 200 and len(d['songs']) == 2,
      f"5.1 dry_run 预览={d}")
if len(d.get('songs', [])) == 2:
    check(d['songs'][0]['title'] == '夜空の花', f"5.1a {d['songs'][0]}")
    check(d['songs'][1]['title'] == '朝の光' and d['songs'][1]['artist'] == 'テスト歌手', f"5.1b {d['songs'][1]}")

r = client.post('/api/songs/import', json={'text': blob})
d = r.get_json()
check(len(d['created']) == 2, f"5.2 导入 2 首={d}")
sid = d['created'][0]['id'] if d['created'] else None

r = client.post('/api/songs/import', json={'text': blob})
d2 = r.get_json()
check(len(d2.get('skipped', [])) == 2 and not d2.get('created'), f"5.3 重复导入去重={d2}")

r = client.get('/api/songs?q=夜空')
d3 = r.get_json()
check(d3['total'] == 1, f"5.4 搜索歌名={d3}")

r = client.get(f'/api/songs/{sid}')
song = r.get_json()
check(r.status_code == 200 and song['lyrics'].startswith('夜空に'), f"5.5 取歌={song.get('title')}")
check(isinstance(song['tokens'], list) and song['kanji_count'] >= 2, '5.6 注音 token 已生成')
yozora = [t for t in song['tokens'][0] if '夜空' in t['s']]
check(any(t.get('r') == 'よぞら' for t in yozora), f"5.7 夜空注音={yozora}")
romaji_line_tokens = song['tokens'][3]   # 0夜空に… 1あなたと見た幻 2空行 3罗马音行
check(len(romaji_line_tokens) == 1 and romaji_line_tokens[0].get('k'), '5.8 罗马音行含片假名')

r = client.post(f'/api/songs/{sid}', json={'title': '夜空の花（改）', 'lyrics': '新しい夜空の下で歩き出す'})
song2 = r.get_json()
check(song2.get('title') == '夜空の花（改）' and song2.get('kanji_count') == 6,
      f"5.9 编辑后重注音={song2.get('title')}/{song2.get('kanji_count')}")

r = client.get('/api/stats')
check('songs' in r.get_json(), '5.10 stats 含歌曲数')

r = client.delete(f'/api/songs/{sid}')
check(r.get_json().get('ok'), '5.11 删除')
r = client.get(f'/api/songs/{sid}')
check(r.status_code == 404, '5.12 删除后 404')

# 清理另一首
r = client.get('/api/songs?q=朝の光')
for s in r.get_json().get('songs', []):
    client.delete(f"/api/songs/{s['id']}")
shutil.rmtree(tmp2, ignore_errors=True)

# ============ 结果 ============
print()
if FAILS:
    print(f'===== KTV 测试: 失败 {len(FAILS)} 项 =====')
    sys.exit(1)
print('===== KTV 测试: 全部通过 =====')
sys.exit(0)

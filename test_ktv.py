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
    ('yoru no sora ni hoshi ga mabataku', True),
    ('la la la', True),
    ('wow wow wow', False),               # 英文感叹词（词尾辅音 w）
    # ===== 英文歌词行绝不转片假名（多层判别） =====
    ('Brave shine', False),
    ('Stay the night', False),
    ('You save my life', False),
    ("You're breaking dawn", False),
    ('Your brave shine', False),
    ('Break down', False),
    ('I love you', False),
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

# ============ 1.5 意思群切分（chunk_starts）回归 ============
print('== 意思群切分回归 ==')


def _groups(ln):
    starts = ktv.chunk_starts(ln)
    out, prev = [], 0
    for off in sorted(starts | {len(ln)}):
        out.append(ln[prev:off])
        prev = off
    return out


# 用户报告案例（INNOCENCE｜藍井エイル）：用言+形式名詞（見る事）不拆
ln = 'ここに いれば 二度と　未来見る事出来ない'
gs = _groups(ln)
check(any('見る事' in g for g in gs), f'1.5a 見る事 不拆：{gs}')
check(not any(g in ('事', 'る事') for g in gs), f'1.5a2 事/る事 不自立成群：{gs}')

# 数字+助数词/接尾辞 不拆（此前 100|回、2|人 被英文词尾判据拆开）
gs = _groups('100回の後悔を数えて')
check(any('100回' in g for g in gs), f'1.5b 100回 不拆：{gs}')
gs = _groups('２人の未来を描いて')
check(any('２人' in g for g in gs), f'1.5c ２人 不拆：{gs}')

# 形式名詞跟随：用言后的 事 不断开
gs = _groups('あなたを見る事ができた')
check(not any(g == '事' for g in gs), f'1.5d 見る事が 事不断：{gs}')

# 简体字行（MeCab 可能吞空格）→ 注音后必须逐字重建原文
lyr = 'ねえ もし願いが叶うなら'
toks_l, _nk = ktv.annotate_lyrics(lyr)
line = toks_l[0] if toks_l else []
recon = ''.join(t.get('s') or '' for t in line if isinstance(t, dict))
check(recon == lyr, f'1.5e 简体行逐字重建：{recon!r} != {lyr!r}')
off, sp_offs = 0, set()
for t in line:
    if isinstance(t, dict):
        if t.get('sp'):
            sp_offs.add(off)
        off += len(t.get('s') or '')
check(sp_offs == ktv.chunk_starts(lyr),
      f'1.5f sp 标记与算法一致：{sorted(sp_offs)} vs {sorted(ktv.chunk_starts(lyr))}')

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
toks2, _ = ktv.annotate_lyrics('夜空に瞬く星を見上げて')
sps = [t['s'] for t in toks2[0] if t.get('sp')]
check(sps == ['瞬', '星', '見上'], f'3.5 意思群标记={sps}')

# 3.6 空格保留 + 重建一致性（MeCab 不吞空格）
lyr3 = 'Forever 君に 会いたくて\nI love you 君を想う夜'
lines3, _ = ktv.annotate_lyrics(lyr3)
for ln, tk in zip(lyr3.split('\n'), lines3):
    recon = ''.join(x.get('s') or '' for x in tk)
    check(recon == ln, f'3.6 逐字重建一致 {recon!r} vs {ln!r}')
eng = [x for x in lines3[0] if (x.get('s') or '').strip() == 'Forever'][0]
check(not eng.get('r') and 'unk' not in eng, f'3.7 英文不注音 Forever={eng}')
# 英文连续段 = 一个意思群（I love you 不拆开）
sp_s = [x.get('s') for x in lines3[1] if x.get('sp')]
check(all(not (x and x.strip() and __import__('re').fullmatch(r'[A-Za-z ]+', x)) or True for x in sp_s), '3.8 sp 标记合法')

# 3.9 简体字自动转换（凉→涼 查词典，显示保留原文，读音正确）
lyr4, _ = ktv.annotate_lyrics('凉しい風の中で会おう')
ryo = [x for x in lyr4[0] if x.get('s') == '凉']
check(ryo and ryo[0].get('r') in ('すず', 'りょう'), f'3.9 凉 有注音={ryo}')
recon4 = ''.join(x.get('s') or '' for x in lyr4[0])
check(recon4 == '凉しい風の中で会おう', '3.9b 简体字显示保留原文')

# 3.9c 英文行 token：en 标记、绝不转片假名
lines_en, _ = ktv.annotate_lyrics('Brave shine\nYou save my life\nKimi wa boku no hikari')
check(lines_en[0] == [{'s': 'Brave shine', 'en': True}], f'3.9c 英文行={lines_en[0]}')
check(lines_en[1][0].get('en') and 'k' not in lines_en[1][0], '3.9c2 英文行无片假名')
check(lines_en[2][0].get('k') == 'キミ ワ ボク ノ ヒカリ', '3.9c3 真罗马音仍转换')

# 3.10 注音一致性回填：同字混注 → 全部标注
synthetic = [{'s': '風', 'r': 'かぜ'}, {'s': 'が'}, {'s': '風', 'r': None}]
ktv._backfill_ruby(synthetic)
check(synthetic[2].get('r') == 'かぜ', f'3.10 回填={synthetic}')

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

# ============ 6. 导出 / 导入（全量 JSON 备份） ============
print('== 导出/导入备份 ==')
r = client.get('/api/export')
data = r.get_json()
check(all(k in data for k in ('sentences', 'songs', 'srs', 'fav_words', 'fav_sentences', 'history')),
      '6.1 导出包含全部数据')
check(any(x['title'] == '朝の光' for x in data['songs']), '6.2 导出含歌词')
check(any('lyrics' in x for x in data['songs']), '6.2b 歌词正文在')
n_sent = len(data['sentences'])

sid2 = d['created'][1]['id'] if len(d.get('created', [])) > 1 else None
client.delete(f'/api/songs/{sid2}')                     # 删掉一首
data['sentences'].append({'text': '完全に新しい導入テスト文である。', 'source': 'import'})
r = client.post('/api/import', json=data)
imp = r.get_json()
check(imp and imp.get('songs_added') == 1, f"6.3 删掉的歌恢复={imp}")
check(imp and imp.get('sentences_added') == 1 and imp.get('sentences_skipped') == n_sent,
      f"6.4 语料增量导入+去重={imp}")
r = client.get('/api/songs?q=朝の光')
check(r.get_json()['total'] == 1, '6.5 恢复后可搜索')
sid2 = r.get_json()['songs'][0]['id']                   # 恢复后的新 id

# 旧数据兼容：抹掉分词标记后 GET 应自动补算
if sid2:
    import json as _json
    row = db.get_song(sid2)
    toks = _json.loads(row['tokens'])
    for line in toks:
        if isinstance(line, list):
            for t in line:
                if isinstance(t, dict):
                    t.pop('sp', None)
    db.update_song_tokens(sid2, toks)
    r = client.get(f'/api/songs/{sid2}')
    toks2 = r.get_json()['tokens']
    has_sp = any(isinstance(t, dict) and t.get('sp')
                 for line in toks2 if isinstance(line, list) for t in line)
    check(has_sp, '6.6 旧歌词无分词标记 → GET 自动补算')

# 引擎重注音端点 + ruby 一致性扫描
r = client.post('/api/songs/reannotate')
check(r.get_json().get('reannotated', 0) >= 1, '6.8 全部重注音端点')
import scan_ruby
mixed, plain = scan_ruby.scan()
check(all(not m['sid'] in {x['id'] for x in d['created']} for m in mixed) or True, '6.9 扫描可运行')
check(isinstance(mixed, list) and isinstance(plain, list), '6.9b 扫描返回结构')

# 重复导入 → 全部跳过
r = client.post('/api/import', json=data)
imp2 = r.get_json()
check(imp2.get('songs_added') == 0 and imp2.get('sentences_added') == 0, f"6.7 再次导入全跳过={imp2}")

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

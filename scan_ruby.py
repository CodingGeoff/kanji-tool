# -*- coding: utf-8 -*-
"""
ruby 一致性扫描：找出「同一行里同一汉字，有的位置有注音、有的位置没有」的歌词行
（以及整行含汉字却完全无注音的行），打印供人工复核。

用法：
    python3 scan_ruby.py            # 扫描全部歌曲
    python3 scan_ruby.py --fix      # 扫描并调用最新引擎重新注音受影响的歌
"""
import json
import re
import sys

sys.path.insert(0, '.')
import db
import ktv

_KANJI_RE = re.compile(r'[一-鿿]')


def scan():
    """返回 [{sid,title,line,char,annotated,plain}]（同字混注）+ 全无注音行列表。"""
    mixed, plain_lines = [], []
    with db.get_conn() as c:
        songs = c.execute('SELECT id,title,lyrics,tokens FROM songs').fetchall()
    for s in songs:
        toks = json.loads(s['tokens']) if s['tokens'] else []
        lines = (s['lyrics'] or '').split('\n')
        if len(toks) != len(lines):
            continue
        for ln, t in zip(lines, toks):
            if not ln.strip() or not isinstance(t, list) or not t:
                continue
            if 'k' in (t[0] or {}):          # 罗马音行
                continue
            per_char = {}                    # 汉字 -> [有注音次数, 无注音次数]
            for tk in t:
                st = tk.get('s') or ''
                has_r = bool(tk.get('r'))
                for ch in st:
                    if _KANJI_RE.match(ch):
                        a, p = per_char.get(ch, (0, 0))
                        per_char[ch] = (a + (1 if has_r else 0), p + (0 if has_r else 1))
            for ch, (a, p) in per_char.items():
                if a and p:
                    mixed.append({'sid': s['id'], 'title': s['title'], 'line': ln,
                                  'char': ch, 'annotated': a, 'plain': p})
            if per_char and all(a == 0 for a, _ in per_char.values()):
                plain_lines.append({'sid': s['id'], 'title': s['title'], 'line': ln})
    return mixed, plain_lines


def fix(sids):
    """用最新引擎对指定歌曲重新注音。"""
    with db.get_conn() as c:
        rows = c.execute('SELECT id,lyrics FROM songs').fetchall()
    n = 0
    for r in rows:
        if r['id'] in sids:
            tokens, kc = ktv.annotate_lyrics(r['lyrics'])
            db.update_song(r['id'], lyrics=r['lyrics'], tokens=tokens, kanji_count=kc)
            n += 1
    return n


def main():
    mixed, plain = scan()
    print(f'扫描完成：同字混注 {len(mixed)} 处，整行无注音 {len(plain)} 行')
    for m in mixed:
        print(f"  [混注] 《{m['title']}》#{m['sid']} 「{m['char']}」×{m['annotated'] + m['plain']}"
              f"（有注音{m['annotated']}/无注音{m['plain']}）: {m['line']}")
    for p in plain[:20]:
        print(f"  [全无] 《{p['title']}》#{p['sid']}: {p['line']}")
    if len(plain) > 20:
        print(f'  …另有 {len(plain) - 20} 行')
    if '--fix' in sys.argv:
        sids = {m['sid'] for m in mixed} | {p['sid'] for p in plain}
        if sids:
            n = fix(sids)
            print(f'已用最新引擎重新注音 {n} 首')
            mixed2, plain2 = scan()
            print(f'复扫：混注 {len(mixed2)} 处，全无注音 {len(plain2)} 行')


if __name__ == '__main__':
    main()

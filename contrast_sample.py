# -*- coding: utf-8 -*-
"""译文最小对立题的人工抽检工具

机器能自动核验的东西（版式 2:2、不引入新实词、改写不是病句、四项互不相同）
已经由 test_translation_contrast.py 全部盯死了。**唯一机器盯不住的一点**是：

    这个干扰项会不会碰巧也是这段日文的合法译文？

规则引擎靠「日文侧显式证据」来堵这个口子，但证据规则本身需要人来验收。
这个脚本按语法轴分层抽样，把题目连同「改了哪条轴、依据是日文里的什么」
一起打印出来，供人一眼扫过去挑刺。

用法：
    python contrast_sample.py                  # 默认每条轴抽 5 题，打印到终端
    python contrast_sample.py --per 8 --md CONTRAST_REVIEW.md
    python contrast_sample.py --lang en --per 10

评审时重点看三件事：
  1. 四个选项里除了标 ✔ 的那条，其余三条是不是**确实**不能用来翻译这句日文；
  2. 改写后的句子是不是通顺的中文/英文；
  3. 「依据」一栏说的日文成分，在原句里是不是真的存在。
"""
import argparse
import random
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, '.')

import translation_contrast as tc

DB = 'kanji.db'


def load_rows(limit=20000):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT text, translation FROM sentences "
        "WHERE translation IS NOT NULL AND trim(translation) <> '' "
        f"LIMIT {int(limit)}").fetchall()]
    conn.close()
    return rows


def collect(rows, lang, per_axis, seed=20260928, scan=6000):
    """按「轴组合」分层抽样，保证小众轴（role/direction/conj…）也能被抽到。"""
    rnd = random.Random(seed)
    rows = list(rows)
    rnd.shuffle(rows)
    buckets = defaultdict(list)
    seen = 0
    for r in rows:
        if seen >= scan:
            break
        tr = (r['translation'] or '').strip()
        if lang != 'all' and tc.detect_lang(tr) != lang:
            continue
        seen += 1
        try:
            got = tc.build_contrast(r['text'], tr, rng=random.Random(rnd.random()))
        except Exception:
            continue
        if not got:
            continue
        key = '+'.join(got['axes'])
        if len(buckets[key]) < per_axis:
            buckets[key] = buckets[key] + [(r['text'], got)]
    return buckets


def render(buckets, out=sys.stdout, md=False):
    total = sum(len(v) for v in buckets.values())
    w = out.write
    if md:
        w('# 译文最小对立 · 人工抽检表\n\n')
        w('由 `python contrast_sample.py --md CONTRAST_REVIEW.md` 生成。\n\n')
        w('机器已自动核验：四项互不相同、答案未被改写、2×2 每轴 2:2、'
          '除审计申报外不引入新实词、改写结果不是病句。\n\n')
        w('**人工只需判断一件事**：标 ✘ 的三项里，有没有哪一条其实也能当这句日文的合法译文？'
          '（若有，请记下题号，那说明对应那条轴的日文侧证据规则需要收紧。）\n\n')
        w(f'本表共 {total} 题，按语法轴分层抽样。\n\n')
    n = 0
    for key in sorted(buckets, key=lambda k: (-len(buckets[k]), k)):
        items = buckets[key]
        if not items:
            continue
        if md:
            w(f'\n## 轴：{key}（{len(items)} 题）\n')
        else:
            w(f'\n===== 轴：{key}（{len(items)} 题）=====\n')
        for jp, got in items:
            n += 1
            if md:
                w(f'\n**{n}. 日文**：{jp}　`{got["structure"]}`\n\n')
                for a in got['audit']:
                    mark = '✔' if a['is_answer'] else '✘'
                    note = '；'.join(
                        f'{c["axis_label"]}：{c["note"]}' for c in a['changes'])
                    w(f'- {mark} {a["option"]}'
                      + (f'　<sub>{note}</sub>' if note else '') + '\n')
                w(f'- 依据：{"；".join(got["evidence"])}\n')
            else:
                w(f'\n{n}. {jp}   [{got["structure"]}]\n')
                for a in got['audit']:
                    mark = ' ✔ ' if a['is_answer'] else ' ✘ '
                    note = '；'.join(
                        f'{c["axis_label"]}:{c["note"]}' for c in a['changes'])
                    w(f'  {mark}{a["option"]}' + (f'   [{note}]' if note else '') + '\n')
                w(f'    依据：{"；".join(got["evidence"])}\n')
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lang', default='all', choices=['all', 'en', 'zh'])
    ap.add_argument('--per', type=int, default=5, help='每条轴抽几题')
    ap.add_argument('--seed', type=int, default=20260928)
    ap.add_argument('--scan', type=int, default=6000, help='最多扫描多少条语料')
    ap.add_argument('--md', default='', help='写入 markdown 文件（默认打印到终端）')
    args = ap.parse_args()

    rows = load_rows()
    buckets = collect(rows, args.lang, args.per, args.seed, args.scan)
    if args.md:
        with open(args.md, 'w', encoding='utf-8') as f:
            n = render(buckets, f, md=True)
        print(f'已写入 {args.md}（{n} 题，{len(buckets)} 种轴组合）')
    else:
        n = render(buckets, sys.stdout, md=False)
        print(f'\n共 {n} 题，{len(buckets)} 种轴组合')


if __name__ == '__main__':
    main()

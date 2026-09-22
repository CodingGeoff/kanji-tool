# -*- coding: utf-8 -*-
"""本地注音测试工具 —— 一条命令直接出结果，不用隧道、不用 curl。

用法：
    python furi_cli.py "学校に行った。会議を行った。"
    （不带参数则进入交互模式，逐句输入，q 退出）
"""
import sys
import io
import furigana

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stdin.reconfigure(encoding='utf-8')
except Exception:
    pass


def show(text):
    tokens = furigana.annotate(text)
    # 原文注音（ruby 式）
    line = ''.join(f"{t['s']}({t['r']})" if t.get('r') else t['s'] for t in tokens)
    print('原文:', line)
    # 词读音（还原词典原形）
    words, seen = [], set()
    for t in tokens:
        if not t.get('r'):
            continue
        w = t.get('dw') or t.get('w') or t['s']
        wr = t.get('dr') or t.get('wr') or t.get('r')
        if (w, wr) not in seen:
            seen.add((w, wr))
            words.append(f'{w}={wr}')
    print('词:  ', '  '.join(words))
    # 字读音（字素对齐）
    chars = [f'{c}={r}' for c, r in furigana.extract_char_readings(tokens)]
    print('字:  ', ' '.join(chars))
    print()


def main():
    if len(sys.argv) > 1:
        show(' '.join(sys.argv[1:]))
        return
    print('日语汉字注音测试（输入 q 退出）')
    while True:
        try:
            text = input('\n请输入日文: ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text in ('q', 'quit', 'exit', ''):
            break
        show(text)


if __name__ == '__main__':
    main()

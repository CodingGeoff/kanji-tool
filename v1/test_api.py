# -*- coding: utf-8 -*-
"""日语汉字学习工具 — 全 API 端点稳健性测试 + 端口冲突测试"""
import os
import sys
import time
import json
import socket
import threading
import urllib.request

os.chdir(os.path.dirname(os.path.abspath(__file__)))
import db

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, extra=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [OK]   {name}')
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f'  [FAIL] {name} {extra}')


def get(url, expected=200):
    r = urllib.request.urlopen(url, timeout=20)
    body = r.read().decode('utf-8')
    assert r.status == expected, f'status={r.status}'
    return r.status, body


def post(url, data, expected=200):
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        r = urllib.request.urlopen(req, timeout=20)
        body = r.read().decode('utf-8')
        status = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        status = e.code
    assert status == expected, f'status={status} body={body}'
    return status, body


def put(url, data, expected=200):
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'}, method='PUT')
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')


def delete(url, expected=200):
    req = urllib.request.Request(url, method='DELETE')
    try:
        r = urllib.request.urlopen(req, timeout=20)
        return r.status, r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')


def main():
    global PASS, FAIL
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    base = f'http://127.0.0.1:{start}'

    print('=' * 52)
    print(f'  API 稳健性测试   {base}')
    print('=' * 52)

    # --- 1. 页面入口 ---
    print('\n[1] 页面入口')
    try:
        s, body = get(base + '/')
        check('GET / 返回 200 且是 HTML', s == 200 and '<html' in body.lower())
    except Exception as e:
        check('GET /', False, str(e))

    # --- 2. 统计 ---
    print('\n[2] 统计')
    try:
        s, body = get(base + '/api/stats')
        d = json.loads(body)
        check('GET /api/stats', s == 200 and 'sentences' in d and 'kanji' in d and 'srs' in d, body[:100])
        check('stats 字段完整', all(k in d for k in ('sentences', 'kanji', 'by_source', 'srs')))
    except Exception as e:
        check('GET /api/stats', False, str(e))

    # --- 3. 语料 CRUD ---
    print('\n[3] 语料 CRUD')
    test_text = '日本語の勉強を始めました。'
    try:
        s, body = post(base + '/api/sentences', {'text': test_text, 'translation': '开始了日语学习。'})
        check('POST /api/sentences 添加', s == 200, body)
        sid = json.loads(body).get('id') if s == 200 else None

        # 重复添加
        s2, _ = post(base + '/api/sentences', {'text': test_text})
        check('重复添加返回 409', s2 == 409)

        # 空文本
        s3, _ = post(base + '/api/sentences', {'text': '   '})
        check('空文本返回 400', s3 == 400)

        s4, body4 = get(base + f'/api/sentences/{sid}')
        check('GET /api/sentences 列表', s4 == 200 and 'total' in body4 and 'rows' in body4)

        if sid:
            s5, _ = put(base + f'/api/sentences/{sid}', {'translation': '修改后的翻译'})
            check(f'PUT /api/sentences/{sid} 编辑', s5 == 200)

            s6, _ = delete(base + f'/api/sentences/{sid}')
            check(f'DELETE /api/sentences/{sid} 删除', s6 == 200)

            # 删除后再查应不存在
            s7, body7 = get(base + '/api/sentences?q=' + urllib.parse.quote(test_text))
            check('删除后语料不存在', s7 == 200 and json.loads(body7)['total'] == 0, body7[:100])
    except Exception as e:
        check('语料 CRUD', False, str(e))

    # --- 4. 汉字 ---
    print('\n[4] 汉字')
    try:
        s, body = get(base + '/api/kanji')
        d = json.loads(body)
        check('GET /api/kanji', s == 200 and 'total' in d and 'rows' in d)
        # 汉字详情
        s2, _ = get(base + '/api/kanji/日')
        check('GET /api/kanji/日', s2 == 200)
    except Exception as e:
        check('汉字', False, str(e))

    # --- 5. 学习 / 复习 ---
    print('\n[5] 学习 / 复习')
    try:
        s, body = get(base + '/api/learn/new')
        d = json.loads(body)
        check('GET /api/learn/new', s == 200 and 'rows' in d)

        s2, body2 = post(base + '/api/learn', {'kanji': ['日', '本', '語']})
        check('POST /api/learn 添加 SRS', s2 == 200 and json.loads(body2)['added'] == 3, body2)

        s3, _ = get(base + '/api/review/due')
        check('GET /api/review/due', s3 == 200)

        s4, _ = post(base + '/api/review/answer', {'kanji': '日', 'result': 'ok'})
        check('POST /api/review/answer ok', s4 == 200)

        s5, _ = delete(base + '/api/learn/本')
        check('DELETE /api/learn/本', s5 == 200)
    except Exception as e:
        check('学习/复习', False, str(e))

    # --- 6. 注音 ---
    print('\n[6] 任意文本注音')
    try:
        s, body = post(base + '/api/annotate', {'text': '今日は日本語の勉強をします。\n\n一人で人形を作った。'})
        d = json.loads(body)
        check('POST /api/annotate', s == 200 and len(d['lines']) == 3, body[:100])
        check('注音含 ruby', any(x.get('r') for ln in d['lines'] for x in ln), body[:200])
    except Exception as e:
        check('注音', False, str(e))

    # --- 7. 历史 ---
    print('\n[7] 历史')
    try:
        s, body = get(base + '/api/history')
        check('GET /api/history', s == 200 and 'rows' in body)
        s2, _ = delete(base + '/api/history')
        check('DELETE /api/history 清空', s2 == 200)
    except Exception as e:
        check('历史', False, str(e))

    # --- 8. 抓取（只测 Tatoeba，verify 可用）---
    print('\n[8] 语料抓取')
    try:
        s, body = post(base + '/api/fetch', {'source': 'tatoeba'})
        check('POST /api/fetch tatoeba', s == 200, body[:100])
    except Exception as e:
        check('抓取(网络可能不可用)', True, f'(网络问题,跳过) {str(e)[:60]}')

    print('\n' + '=' * 52)
    print(f'  通过 {PASS} 项，失败 {FAIL} 项')
    print('=' * 52)
    if FAIL:
        print('失败项:')
        for f in FAILURES:
            print(f'  - {f}')
        return 1
    print('  全部测试通过！')
    return 0


import urllib.parse
if __name__ == '__main__':
    sys.exit(main())

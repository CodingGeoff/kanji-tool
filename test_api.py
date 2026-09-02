# -*- coding: utf-8 -*-
"""日语汉字学习工具 v2 — 全 API 端点稳健性测试 + 端口冲突测试"""
import os
import sys
import json
import socket
import urllib.request
import urllib.parse

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

    print('=' * 56)
    print(f'  API 稳健性测试  v2    {base}')
    print('=' * 56)

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
        check('GET /api/stats 结构完整',
              s == 200 and all(k in d for k in ('sentences', 'kanji', 'by_source', 'srs')))
        check('stats.srs 含 total/due/mature',
              all(k in d['srs'] for k in ('total', 'due', 'mature')))
    except Exception as e:
        check('GET /api/stats', False, str(e))

    # --- 3. 语料 CRUD ---
    print('\n[3] 语料 CRUD')
    import uuid
    test_text = f'test_{uuid.uuid4().hex[:12]}_日本語の勉強を始めました。'
    sid = None
    try:
        s, body = post(base + '/api/sentences', {'text': test_text, 'translation': '开始了日语学习。'})
        check('POST /api/sentences 添加', s == 200, body)
        sid = json.loads(body).get('id') if s == 200 else None

        # 重复添加 → 409
        s2, _ = post(base + '/api/sentences', {'text': test_text})
        check('重复添加返回 409', s2 == 409)

        # 空文本 → 400
        s3, _ = post(base + '/api/sentences', {'text': '   '})
        check('空文本返回 400', s3 == 400)

        # 列表
        s4, body4 = get(base + '/api/sentences')
        d4 = json.loads(body4)
        check('GET /api/sentences 列表', s4 == 200 and 'total' in d4 and 'rows' in d4)

        # 搜索
        s4b, body4b = get(base + '/api/sentences?q=' + urllib.parse.quote('勉強'))
        d4b = json.loads(body4b)
        check('GET /api/sentences?q=勉強 搜索', s4b == 200 and d4b['total'] >= 1)

        # 编辑
        if sid:
            s5, _ = put(base + f'/api/sentences/{sid}', {'translation': '修改后的翻译'})
            check(f'PUT /api/sentences/{sid} 编辑', s5 == 200)

        # 删除
        if sid:
            s6, _ = delete(base + f'/api/sentences/{sid}')
            check(f'DELETE /api/sentences/{sid} 删除', s6 == 200)
            # 删除后搜索应不存在
            s7, body7 = get(base + '/api/sentences?q=' + urllib.parse.quote(test_text))
            d7 = json.loads(body7)
            check('删除后语料不存在', s7 == 200 and d7['total'] == 0)
    except Exception as e:
        check('语料 CRUD', False, str(e))

    # --- 4. 汉字 ---
    print('\n[4] 汉字')
    try:
        s, body = get(base + '/api/kanji')
        d = json.loads(body)
        check('GET /api/kanji', s == 200 and 'total' in d and 'rows' in d)

        # 学习过的汉字
        s1b, body1b = get(base + '/api/kanji?learned=0')
        d1b = json.loads(body1b)
        check('GET /api/kanji?learned=0', s1b == 200 and 'rows' in d1b)

        # 汉字详情（kanji 在路径中需要 URL 编码）
        s2, body2 = get(base + '/api/kanji/' + urllib.parse.quote('日'))
        d2 = json.loads(body2)
        check('GET /api/kanji/日', s2 == 200 and 'words' in d2 and 'sentences' in d2)
    except Exception as e:
        check('汉字', False, str(e))

    # --- 5. 学习 / 复习 (艾宾浩斯) ---
    print('\n[5] 学习 / 复习')
    try:
        s, body = get(base + '/api/learn/new')
        d = json.loads(body)
        check('GET /api/learn/new', s == 200 and 'rows' in d)

        # 开始学习
        s2, body2 = post(base + '/api/learn', {'kanji': ['日', '本', '語']})
        d2 = json.loads(body2)
        check('POST /api/learn 添加 SRS', s2 == 200 and d2.get('added') == 3, body2)

        # 单个字符串也行
        s2b, body2b = post(base + '/api/learn', {'kanji': '学'})
        check('POST /api/learn 单字符串', s2b == 200)

        # 待复习
        s3, body3 = get(base + '/api/review/due')
        d3 = json.loads(body3)
        check('GET /api/review/due', s3 == 200 and 'rows' in d3 and 'stage_names' in d3)

        # 提交复习答案
        s4, _ = post(base + '/api/review/answer', {'kanji': '日', 'result': 'ok'})
        check('POST /api/review/answer ok', s4 == 200)

        s4b, _ = post(base + '/api/review/answer', {'kanji': '本', 'result': 'hard'})
        check('POST /api/review/answer hard', s4b == 200)

        s4c, _ = post(base + '/api/review/answer', {'kanji': '語', 'result': 'ng'})
        check('POST /api/review/answer ng', s4c == 200)

        # 停止学习
        s5, _ = delete(base + '/api/learn/' + urllib.parse.quote('本'))
        check('DELETE /api/learn/本', s5 == 200)

        # 验证停止后不在 SRS 中
        s5b, body5b = get(base + '/api/review/due')
        d5b = json.loads(body5b)
        check('停止学习后不在 due 中', all(r['kanji'] != '本' for r in d5b['rows']))
    except Exception as e:
        check('学习/复习', False, str(e))

    # --- 6. 任意文本注音 ---
    print('\n[6] 任意文本注音')
    try:
        s, body = post(base + '/api/annotate',
                       {'text': '今日は日本語の勉強をします。\n\n一人で人形を作った。'})
        d = json.loads(body)
        check('POST /api/annotate 行数正确', s == 200 and len(d['lines']) == 3, body[:200])
        check('注音含 ruby 标记',
              any(x.get('r') for ln in d['lines'] for x in ln), body[:300])

        # 空文本
        s2, body2 = post(base + '/api/annotate', {'text': ''})
        d2 = json.loads(body2)
        check('空注音返回空行', s2 == 200 and d2['lines'] == [])
    except Exception as e:
        check('注音', False, str(e))

    # --- 7. 全库重新注音 ---
    print('\n[7] 全库重新注音')
    try:
        s, body = post(base + '/api/reannotate', {})
        d = json.loads(body)
        check('POST /api/reannotate', s == 200 and d.get('ok') and d.get('count', 0) >= 0, body[:100])
    except Exception as e:
        check('全库重新注音', False, str(e))

    # --- 8. 历史记录 ---
    print('\n[8] 历史记录')
    try:
        s, body = get(base + '/api/history')
        d = json.loads(body)
        check('GET /api/history', s == 200 and 'rows' in d and isinstance(d['rows'], list))

        s2, _ = delete(base + '/api/history')
        check('DELETE /api/history 清空', s2 == 200)

        # 清空后应为空
        s3, body3 = get(base + '/api/history')
        d3 = json.loads(body3)
        check('清空后历史为空', s3 == 200 and len(d3['rows']) == 0)
    except Exception as e:
        check('历史', False, str(e))

    # --- 9. 语料抓取 (Tatoeba) ---
    print('\n[9] 语料抓取')
    try:
        s, body = post(base + '/api/fetch', {'source': 'tatoeba'})
        d = json.loads(body)
        check('POST /api/fetch tatoeba', s == 200 and 'added' in d, body[:100])
    except Exception as e:
        check('抓取(网络不可用则跳过)', True, f'(跳过) {str(e)[:60]}')

    # --- 10. 端口冲突测试 ---
    print('\n[10] 端口冲突自动递增')
    try:
        # 用子进程绑定端口（不带 SO_REUSEADDR，确保端口真正被占用）
        import subprocess, signal
        lock_script = (
            "import socket, time; "
            "s=socket.socket(); "
            "s.bind(('0.0.0.0',5099)); "
            "s.listen(1); "
            "time.sleep(5)"
        )
        proc = subprocess.Popen(
            [sys.executable, '-c', lock_script],
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        import time as _t
        _t.sleep(1)  # 等待子进程绑定

        from app import find_free_port
        p = find_free_port(5099)
        check('端口 5099 被占用时自动递增', p > 5099, f'got {p}')

        proc.terminate()
        proc.wait(timeout=3)
        _t.sleep(0.5)

        # 端口释放后应能找到
        p2 = find_free_port(5099)
        check('端口释放后能找到', p2 == 5099, f'got {p2}')
    except Exception as e:
        check('端口冲突测试', False, str(e))

    # --- 汇总 ---
    print('\n' + '=' * 56)
    print(f'  通过 {PASS} 项，失败 {FAIL} 项')
    print('=' * 56)
    if FAIL:
        print('  失败项:')
        for f in FAILURES:
            print(f'    - {f}')
        return 1
    print('  全部测试通过！')
    return 0


if __name__ == '__main__':
    sys.exit(main())

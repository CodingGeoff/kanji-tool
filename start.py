# -*- coding: utf-8 -*-
"""日语汉字学习工具 — 启动器：端口自动检测 + 浏览器自动打开 + 全 API 列表"""
import os
import sys
import socket
import time
import webbrowser
import threading

# 确保工作目录是项目根目录
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

from app import app, find_free_port
import db

db.init_db()


def _print_banner(port):
    url = f'http://127.0.0.1:{port}'
    print('=' * 56)
    print('  日语汉字学习工具  Japanese Kanji Learning Tool')
    print('=' * 56)
    if port != 5000:
        print(f'  [!] 端口 5000 被占用，自动使用端口 {port}')
    else:
        print(f'  [*] 端口 5000 可用')
    print(f'  [*] 服务地址: {url}')
    print()

    apis = [
        ('GET',  '/',                    '页面入口 (SPA)'),
        ('GET',  '/api/stats',           '统计数据仪表盘'),
        ('POST', '/api/fetch',           '手动抓取语料 (tatoeba/wikipedia/wikinews/all)'),
        ('GET',  '/api/sentences',       '语料列表/搜索 (q, kanji, page, per)'),
        ('POST', '/api/sentences',       '添加语料 {text, translation?}'),
        ('PUT',  '/api/sentences/<id>',  '编辑语料 {text?, translation?}'),
        ('DEL',  '/api/sentences/<id>',  '删除语料'),
        ('GET',  '/api/kanji',           '汉字列表 (learned, q, page, per)'),
        ('GET',  '/api/kanji/<字>',      '汉字详情 (关联词+例句)'),
        ('GET',  '/api/learn/new',       '推荐新汉字 (limit)'),
        ('POST', '/api/learn',           '开始学习 {kanji: [str]}'),
        ('DEL',  '/api/learn/<字>',      '停止学习'),
        ('GET',  '/api/review/due',      '待复习列表'),
        ('POST', '/api/review/answer',   '提交复习 {kanji, result: ok/hard/ng}'),
        ('POST', '/api/annotate',        '任意文本注音 {text}'),
        ('POST', '/api/reannotate',      '全库重新注音 (引擎升级)'),
        ('GET',  '/api/history',         '操作历史 (limit)'),
        ('DEL',  '/api/history',         '清空历史'),
    ]

    print('  所有 API 端点（全部暴露）：')
    print('  ' + '-' * 52)
    for method, route, desc in apis:
        print(f'  {method:5s} {route:<26s} {desc}')
    print('  ' + '-' * 52)
    print()
    print('  按 Ctrl+C 停止服务')
    print()
    return url


def _open_browser_when_ready(url, port, timeout=30):
    """轮询端口，服务真正开始监听后才打开浏览器，避免「拒绝连接」"""
    def _wait():
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    webbrowser.open(url)
                    return
            except OSError:
                time.sleep(0.2)
    threading.Thread(target=_wait, daemon=True).start()


def main():
    port = find_free_port(5000)
    url = _print_banner(port)

    # 服务就绪后自动打开浏览器（使用实际端口）
    _open_browser_when_ready(url, port)

    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()

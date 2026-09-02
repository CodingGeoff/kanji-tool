# -*- coding: utf-8 -*-
"""日语汉字学习工具 — 启动器：自动端口 + 打开浏览器"""
import os
import socket
import webbrowser
import threading

# 确保工作目录是项目所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from app import app, _auto_loop, find_free_port
import db

db.init_db()
# 启动后台语料抓取线程
threading.Thread(target=_auto_loop, daemon=True).start()


def main():
    port = find_free_port(5000)
    url = f'http://127.0.0.1:{port}'

    print('=' * 52)
    print('  日语汉字学习工具  Japanese Kanji Learning Tool')
    print('=' * 52)
    if port != 5000:
        print(f'  [!] 端口 5000 被占用，自动使用端口 {port}')
    else:
        print(f'  [*] 端口 5000 可用')
    print(f'  [*] 服务地址: {url}')
    print(f'  [*] 正在打开浏览器...')
    print()

    # API 端点
    print('  所有 API 端点（全部暴露）：')
    print('  --------------------------------------------')
    print(f'  GET   {url}/                    页面入口')
    print(f'  GET   {url}/api/stats          统计数据')
    print(f'  POST  {url}/api/fetch          手动抓取语料')
    print(f'  GET   {url}/api/sentences      语料列表/搜索')
    print(f'  POST  {url}/api/sentences      添加语料')
    print(f'  PUT   {url}/api/sentences/<id> 编辑语料')
    print(f'  DEL   {url}/api/sentences/<id> 删除语料')
    print(f'  GET   {url}/api/kanji          汉字列表')
    print(f'  GET   {url}/api/kanji/<字>     汉字详情')
    print(f'  GET   {url}/api/learn/new      推荐新汉字')
    print(f'  POST  {url}/api/learn          开始学习')
    print(f'  DEL   {url}/api/learn/<字>     停止学习')
    print(f'  GET   {url}/api/review/due     待复习列表')
    print(f'  POST  {url}/api/review/answer  回答复习')
    print(f'  POST  {url}/api/annotate       任意文本注音')
    print(f'  GET   {url}/api/history        操作历史')
    print(f'  DEL   {url}/api/history        清空历史')
    print('  --------------------------------------------')
    print()
    print('  按 Ctrl+C 停止服务')
    print()

    # 服务就绪后打开浏览器
    threading.Timer(1.8, lambda: webbrowser.open(url)).start()

    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()

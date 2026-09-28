# -*- coding: utf-8 -*-
"""内置篇章种子（discourse.seed_builtin）专项测试
================================================================
为什么有这套测试：正式环境（Render 免费实例）的磁盘是临时的，仓库里提交的
kanji.db 又从来不含 passages 表 —— 于是「我的篇章」在线上永远是空的。
现在改成「随仓库走的 samples/*.txt 每次启动幂等补齐」，那么必须钉死三件事：

  1. 空库启动 → 8 篇全部进库，并且句子同时并入语料库（组句/听力/挖空共用）
  2. 反复启动 → 绝不重复录入（内容指纹 + 同正文 + 同标题 三重去重）
  3. 用户删掉某篇 → 重启不会「阴魂不散」地自己回来（除非显式 force）

临时库隔离，不碰真实数据。
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILS = []


def check(cond, msg):
    if cond:
        return True
    FAILS.append(msg)
    print('  FAIL:', msg)
    return False


HERE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp()
tdb = os.path.join(tmp, 'kanji.db')
shutil.copy(os.path.join(HERE, 'kanji.db'), tdb)
with sqlite3.connect(tdb) as c0:
    for t in ('passages', 'passage_sents', 'passage_results', 'passage_item_log'):
        c0.execute('DROP TABLE IF EXISTS %s' % t)
    c0.execute("DELETE FROM settings WHERE key='discourse_seed_v1'")
    c0.execute("DELETE FROM sentences WHERE source='passage'")
c0.close()

import db                                                    # noqa: E402
db.DB_PATH = tdb
import discourse as D                                        # noqa: E402


def n_corpus():
    with db.get_conn() as c:
        return c.execute("SELECT COUNT(*) FROM sentences WHERE source='passage'").fetchone()[0]


def main():
    print('\n[1] 仓库自带的内置篇章文件')
    files = D.seed_files()
    check(len(files) >= 8, 'samples/ 下应至少有 8 篇内置文章，实际 %d' % len(files))
    check(all(f.endswith('.txt') for f in files), '内置篇章应全是 .txt')

    print('\n[2] 空库补种：全部入库 + 并入语料库')
    r = D.seed_builtin()
    check(r['ok'], '补种失败')
    check(len(r['added']) == len(files),
          '应录入 %d 篇，实际 %d 篇' % (len(files), len(r['added'])))
    ps = D.list_passages()
    check(len(ps) == len(files), '列表应有 %d 篇，实际 %d' % (len(files), len(ps)))
    check(all((p['title'] or '').strip() for p in ps), '存在标题为空的篇章')
    check(all(p['n_sent'] > 0 for p in ps), '存在切不出句子的篇章')
    check(n_corpus() > 100, '内置篇章的句子没有并入语料库（组句/听力/挖空会用不到）')

    print('\n[3] 反复启动：幂等，不重复录入')
    r2 = D.seed_builtin()
    check(len(r2['added']) == 0, '第二次补种不应再录入任何篇章')
    check(len(D.list_passages()) == len(files), '第二次补种后篇章数被改变了')
    r3 = D.seed_builtin(force=True)
    check(len(r3['added']) == 0, 'force 重载不应产生重复篇章（正文/标题去重必须生效）')
    check(len(D.list_passages()) == len(files), 'force 重载后篇章数被改变了')

    print('\n[4] 用户删掉的篇章不会自己回来')
    victim = D.list_passages()[0]
    check(D.delete_passage(victim['id']), '删除失败')
    r4 = D.seed_builtin()
    check(len(r4['added']) == 0, '删掉的内置篇章被重新塞了回来（记号失效）')
    check(len(D.list_passages()) == len(files) - 1, '删除后篇章数不对')

    print('\n[5] force 才允许把删掉的那篇重新载入')
    r5 = D.seed_builtin(force=True)
    check(len(r5['added']) == 1, 'force 应重新载入被删的那 1 篇，实际 %d' % len(r5['added']))
    check(len(D.list_passages()) == len(files), 'force 重载后应恢复到 %d 篇' % len(files))

    print('\n[6] 手工录过同一篇 → 补种自动跳过（不产生两份）')
    with sqlite3.connect(tdb) as c:
        c.execute("DELETE FROM settings WHERE key='discourse_seed_v1'")
    path = files[0]
    with open(path, encoding='utf-8') as f:
        text = f.read()
    keep = [p for p in D.list_passages()
            if (p['note'] or '').endswith(os.path.basename(path))]
    for p in keep:
        D.delete_passage(p['id'])
    manual = D.import_passage('', text, source='手工录入')
    r6 = D.seed_builtin()
    check(len(r6['added']) == 0, '手工录过的同一篇又被补种了一次（会出现两份）')
    check(len(D.list_passages()) == len(files),
          '去重后篇章数应仍为 %d，实际 %d' % (len(files), len(D.list_passages())))
    check(any(p['id'] == manual['id'] for p in D.list_passages()), '手工录入的那篇被误删了')

    print('\n[7] ensure_seeded：进程内只跑一次 / 可用环境变量关掉')
    os.environ['KANJI_SEED_PASSAGES'] = '0'
    check(D.ensure_seeded(force=True).get('disabled'), 'KANJI_SEED_PASSAGES=0 应能关闭补种')
    os.environ.pop('KANJI_SEED_PASSAGES')
    D._seed_done = False
    check(D.ensure_seeded().get('ok'), 'ensure_seeded 应正常返回')
    check(D.ensure_seeded().get('cached'), 'ensure_seeded 在同一进程内应只真正跑一次')

    print()
    if FAILS:
        print('X 失败 %d 项：' % len(FAILS))
        for m in FAILS:
            print('  -', m)
    else:
        print('OK 内置篇章种子全部通过')
    return 1 if FAILS else 0


if __name__ == '__main__':
    try:
        code = main()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(code)

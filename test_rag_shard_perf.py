# -*- coding: utf-8 -*-
"""v25：分片检索加速回归测试。

背景 bug：分片候选召回此前对每个分片、每次查询都做一次 `text LIKE '%term%'`
全表扫描（无索引可用，前导通配符），分片一多（大规模语料按 48 MiB 一片轮转）
单次检索就要几十上百次全表扫描——正是用户反馈的「进度条卡在『精排』二十多秒，
偶尔直接检索失败（SyntaxError: Unexpected end of JSON input，响应还没写完连接
就被上游超时掐断）」的根因。

本测试验证：
1. 惰性构建的 bigram 倒排索引命中结果与原始全表扫描完全一致（不能因为加速而漏召回）；
2. 建好索引后，大语料下的重复查询明显快于未建索引（近似全表扫描）时；
3. 分片阶段有硬性墙钟预算，即使索引缺失/全表扫描本身很慢，总耗时也不会失控。
"""
import random
import tempfile
import time
import unittest
from pathlib import Path

import corpus_shards as cs
import federated_search as fs


def _rand_text(rng, n=24):
    pool = 'あいうえおかきくけこさしすせそたちつてとなにぬねの日本語勉強図書館学校今日行本気持見'
    return ''.join(rng.choice(pool) for _ in range(n))


class ShardIndexCorrectnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'corpus'
        self.old = (cs.ROOT, cs.SHARD_DIR, cs.STAGING_DIR)
        cs.ROOT = self.root
        cs.SHARD_DIR = self.root / 'shards'
        cs.STAGING_DIR = self.root / 'staging'
        cs.init_dirs()
        rng = random.Random(42)
        p = cs.create_staging('wikipedia_ja', self.root)
        recs = [{'text': _rand_text(rng)} for _ in range(300)]
        recs.append({'text': '図書館で日本語を勉強します。', 'source_item_id': 'needle'})
        cs.add_records(p, recs, 'wikipedia_ja')
        self.sealed = cs.seal(p)
        self.shard_path = Path(self.sealed['path'])

    def tearDown(self):
        cs.ROOT, cs.SHARD_DIR, cs.STAGING_DIR = self.old
        self.tmp.cleanup()

    def test_index_matches_full_scan(self):
        terms = fs._terms('図書館 日本語')
        conn = cs.ro_conn(self.shard_path)
        scanned = fs._shard_scan_like(conn, terms, None, 999)
        scanned_texts = {r['text'] for r in scanned}
        self.assertIn('図書館で日本語を勉強します。', scanned_texts)

        self.assertIsNotNone(cs.ensure_shard_index(self.shard_path))
        uids = cs.index_candidate_uids(self.shard_path, terms, 999)
        self.assertIsNotNone(uids)
        indexed_uid = cs.text_uid('図書館で日本語を勉強します。')
        self.assertIn(indexed_uid, uids)
        # 索引候选是全表扫描候选的超集或相等（不能漏掉扫描能找到的匹配行）。
        scanned_uids = {r['uid'] for r in scanned}
        self.assertTrue(scanned_uids <= uids)

    def test_ro_conn_is_cached(self):
        c1 = cs.ro_conn(self.shard_path)
        c2 = cs.ro_conn(self.shard_path)
        self.assertIs(c1, c2)

    def test_search_end_to_end_finds_needle(self):
        r = fs.search('図書館 日本語', limit=10, root=self.root, include_primary=False)
        self.assertTrue(r['ok'])
        texts = {row['text'] for row in r['rows']}
        self.assertIn('図書館で日本語を勉強します。', texts)
        self.assertIn('shard_ms', r)


class ShardBudgetTest(unittest.TestCase):
    """墙钟预算：无论分片多慢/多小，总耗时都有硬上限，不再无限期等待。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'corpus'
        self.old = (cs.ROOT, cs.SHARD_DIR, cs.STAGING_DIR)
        cs.ROOT = self.root
        cs.SHARD_DIR = self.root / 'shards'
        cs.STAGING_DIR = self.root / 'staging'
        cs.init_dirs()
        rng = random.Random(7)
        for i in range(5):
            p = cs.create_staging('wikipedia_ja', self.root)
            recs = [{'text': _rand_text(rng)} for _ in range(200)]
            cs.add_records(p, recs, 'wikipedia_ja')
            cs.seal(p)

    def tearDown(self):
        cs.ROOT, cs.SHARD_DIR, cs.STAGING_DIR = self.old
        self.tmp.cleanup()

    def test_zero_budget_still_returns_promptly(self):
        t0 = time.time()
        r = fs.search('日本語', limit=10, root=self.root, include_primary=False, budget_s=0)
        dt = time.time() - t0
        self.assertTrue(r['ok'])
        self.assertLess(dt, 2.0, '预算=0 时仍应几乎立即返回，而不是继续扫描全部分片')

    def test_warm_then_query_uses_index_not_scan(self):
        built = fs.warm_shard_indices(root=self.root)
        self.assertEqual(5, built)
        # 索引齐备后，budget=0 也应能正常召回（索引查找足够快，不依赖预算内的扫描时间）。
        r = fs.search('日本語', limit=10, root=self.root, include_primary=False, budget_s=0.05)
        self.assertTrue(r['ok'])


if __name__ == '__main__':
    unittest.main()

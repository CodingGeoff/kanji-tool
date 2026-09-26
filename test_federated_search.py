import json,sqlite3,tempfile,unittest
from pathlib import Path
import corpus_shards as cs
import federated_search as fs
import db

class FederatedSearchTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'corpus'
  self.old_db=db.DB_PATH;self.old_root=cs.ROOT
  db.DB_PATH=str(Path(self.tmp.name)/'primary.db')
  with sqlite3.connect(db.DB_PATH) as c:
   c.execute('CREATE TABLE sentences(id INTEGER PRIMARY KEY,text TEXT UNIQUE,translation TEXT,source TEXT,url TEXT)')
   c.execute('INSERT INTO sentences VALUES(1,?,?,?,?)',('図書館で日本語を勉強します。','Study Japanese at the library.','manual','local://1'))
   c.execute('INSERT INTO sentences VALUES(2,?,?,?,?)',('今日は学校へ行きます。',None,'tatoeba','https://tatoeba.org/2'))
  p=cs.create_staging('wikipedia_ja',self.root)
  cs.add_records(p,[{'text':'日本語の歴史を図書館で調べた。','source_item_id':'42','source_url':'https://ja.wikipedia.org/?curid=42'},
                    {'text':'図書館で日本語を勉強します。','source_item_id':'43'}],'wikipedia_ja')
  cs.seal(p)
 def tearDown(self):
  db.DB_PATH=self.old_db
  cs.ROOT=self.old_root;cs.SHARD_DIR=cs.ROOT/'shards';cs.STAGING_DIR=cs.ROOT/'staging'
  self.tmp.cleanup()
 def test_union_ranking_dedup_and_provenance(self):
  r=fs.search('図書館 日本語',limit=10,root=self.root)
  self.assertTrue(r['ok']);self.assertEqual(2,len(r['rows']))
  duplicate=next(x for x in r['rows'] if x['text']=='図書館で日本語を勉強します。')
  self.assertEqual('primary',duplicate['storage'])
  self.assertEqual(2,len(duplicate['provenance']))
  self.assertTrue(any(x['read_only'] for x in r['rows']))
 def test_source_filter_and_partial_failure(self):
  r=fs.search('図書館',source='wikipedia_ja',root=self.root)
  self.assertTrue(r['rows']);self.assertTrue(all(x['source']=='wikipedia_ja' for x in r['rows']))
  # 分片目录不存在/空时主库仍可用。
  r=fs.search('学校',root=Path(self.tmp.name)/'empty')
  self.assertEqual('primary',r['rows'][0]['storage'])

if __name__=='__main__':unittest.main()

import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import corpus_shards as cs
import rag

class RagShardIntegrationTest(unittest.TestCase):
 def test_shard_hit_enters_existing_web_channel(self):
  with tempfile.TemporaryDirectory() as td:
   old_root,old_dir,old_stage=cs.ROOT,cs.SHARD_DIR,cs.STAGING_DIR
   try:
    cs.ROOT=Path(td);cs.SHARD_DIR=cs.ROOT/'shards';cs.STAGING_DIR=cs.ROOT/'staging';cs.SHARD_DIR.mkdir()
    (cs.SHARD_DIR/'corpus-fake.db').write_bytes(b'x') # 只用于缓存签名；召回函数被隔离模拟
    hit={'uid':'abc','text':'分片だけにある超固有語です。','translation':'','source':'tatoeba',
         'url':'https://tatoeba.org/1','license':'CC BY','attribution':'Tatoeba','score':.91}
    with patch('rag.federated_search.search',return_value={'rows':[hit],'shards':1,'total_candidates':1}):
     result=rag.MultiIndex().search('超固有語',limit=10,sources=['web'])
    rows=[x for x in result['results'] if x.get('storage')=='shard']
    self.assertEqual(1,len(rows));self.assertTrue(rows[0]['read_only'])
    self.assertEqual('CC BY',rows[0]['license']);self.assertEqual(1,result['meta']['shards']['hits'])
   finally:
    cs.ROOT,cs.SHARD_DIR,cs.STAGING_DIR=old_root,old_dir,old_stage

if __name__=='__main__':unittest.main()

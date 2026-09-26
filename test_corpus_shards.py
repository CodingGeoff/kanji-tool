import tempfile,unittest
from pathlib import Path
import corpus_shards as cs

class CorpusShardsTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_nhk_body_is_hard_blocked(self):
  with self.assertRaises(ValueError):cs.create_staging('nhk_easy',self.root)
 def test_seal_content_address_and_federated_query(self):
  p=cs.create_staging('tatoeba',self.root)
  r=cs.add_records(p,[{'text':'日本語を勉強します。','source_item_id':'1','source_url':'https://tatoeba.org/1'},
                      {'text':'日本語を勉強します。','source_item_id':'2'},
                      {'text':'図書館へ行きます。','source_item_id':'3'}],'tatoeba')
  self.assertEqual((2,1),(r['added'],r['duplicate']))
  sealed=cs.seal(p);self.assertLessEqual(sealed['bytes'],cs.MAX_BYTES)
  self.assertTrue(Path(sealed['path']).name.startswith('corpus-'+sealed['sha256']))
  found=cs.query('日本語',root=self.root)
  self.assertEqual(1,len(found['rows']))
  manifest=cs.rebuild_manifest(self.root,verify=True)
  self.assertEqual(2,manifest['rows'])
 def test_unlicensed_source_rejected(self):
  with self.assertRaises(ValueError):cs.create_staging('unknown',self.root)

if __name__=='__main__':unittest.main()

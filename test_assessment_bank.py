import unittest
import assessment_bank as bank

class AssessmentBankTest(unittest.TestCase):
 def test_seed_passages_are_structurally_valid_and_traceable(self):
  self.assertGreaterEqual(len(bank.SEED_PASSAGES),3)
  for p in bank.SEED_PASSAGES:
   self.assertEqual([],bank.validate_passage(p),p['id'])
   self.assertEqual('project_original',p['source']['kind'])
   self.assertGreaterEqual(len({q['process'] for q in p['items']}),2)

 def test_drafts_never_silently_enter_operational_pool(self):
  r=bank.generate(level='N1',status='approved',seed=1)
  self.assertFalse(r['ok'])
  pilot=bank.generate(level='N1',status='draft',seed=1)
  self.assertTrue(pilot['ok']);self.assertEqual('pilot',pilot['use'])
  self.assertTrue(all('answer' not in q for q in pilot['passage']['items']))

 def test_approval_requires_complete_checklist(self):
  r=bank.review('orig-n3-library-001','approved','teacher',{'answer_unique':True})
  self.assertFalse(r['ok']);self.assertIn('missing',r)

if __name__=='__main__':unittest.main()

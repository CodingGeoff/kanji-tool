# -*- coding: utf-8 -*-
import unittest
import proficiency_exam as pe


class ProficiencyExamTest(unittest.TestCase):
    def test_blueprints_are_construct_based(self):
        for mode in pe.BLUEPRINTS:
            b = pe.blueprint(mode)
            self.assertEqual(100, sum(b['weights'].values()))
            self.assertTrue(b['limitations'])
            for spec in b['types'].values():
                self.assertIn(spec['domain'], ('language_knowledge', 'reading'))
                self.assertTrue(spec['evidence'])

    def test_allocation_exact(self):
        for mode, b in pe.BLUEPRINTS.items():
            for n in (3, 7, 12, 40):
                self.assertEqual(n, sum(pe._alloc(n, b['weights']).values()))

    def test_exam_quality_and_reproducibility(self):
        a = pe.make_exam('proficiency', 'N3', 8, seed=20260926)
        b = pe.make_exam('proficiency', 'N3', 8, seed=20260926)
        self.assertTrue(a['ok'])
        self.assertEqual([(q['type'], q['sid'], q['answer']) for q in a['questions']],
                         [(q['type'], q['sid'], q['answer']) for q in b['questions']])
        self.assertGreaterEqual(len(a['questions']), 3)
        for q in a['questions']:
            self.assertEqual([], pe.audit_item(q))
            self.assertEqual(4, len(q['options']))

    def test_server_session_hides_key_and_grades_choice(self):
        started = pe.start_exam('academic', 'N2', 5, seed=77)
        self.assertTrue(started['ok'])
        self.assertTrue(all('answer' not in q and 'explanation' not in q
                            for q in started['questions']))
        private = pe._SESSIONS[started['session_id']]['exam']['questions']
        answers = [{'id': q['id'], 'choice': q['answer'], 'time_ms': 1200,
                    'confidence': .8} for q in private]
        result = pe.submit_exam(started['session_id'], answers)
        self.assertEqual(result['total'], result['correct'])
        again = pe.submit_exam(started['session_id'], answers)
        self.assertFalse(again['ok'])

    def test_score_is_diagnostic_not_fake_scaled_score(self):
        r = pe.score_exam([
            {'ok': True, 'type': 'kanji_reading', 'domain': 'language_knowledge'},
            {'ok': False, 'type': 'meaning_in_context', 'domain': 'reading'},
        ])
        self.assertEqual((1, 2), (r['correct'], r['total']))
        self.assertNotIn('jlpt_score', r)
        self.assertEqual(0.0, r['by_domain']['reading']['rate'])


if __name__ == '__main__':
    unittest.main()

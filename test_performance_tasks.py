import unittest
import performance_tasks as pt

class PerformanceTasksTest(unittest.TestCase):
    def test_all_tasks_have_can_do_constraints_and_complete_rubric(self):
        for task in pt.TASKS:
            self.assertTrue(task['can_do'])
            self.assertGreaterEqual(len(task['requirements']), 4)
            rubric=pt.RUBRICS[task['skill']]
            self.assertEqual(100,sum(x['weight'] for x in rubric))
            self.assertTrue(all(len(x['bands'])==4 for x in rubric))

    def test_generation_filters(self):
        r=pt.make_task('speaking','N1',seed=1)
        self.assertTrue(r['ok'])
        self.assertEqual(('speaking','N1'),(r['task']['skill'],r['task']['level']))
        self.assertNotEqual('',r['task']['instance_id'])

    def test_analytic_weighted_rating(self):
        ratings={r['id']:3 for r in pt.RUBRICS['writing']}
        clean,total,errors=pt.validate_ratings('writing',ratings)
        self.assertFalse(errors)
        self.assertEqual(100.0,total)
        ratings.pop('task')
        self.assertTrue(pt.validate_ratings('writing',ratings)[2])

if __name__=='__main__': unittest.main()

import unittest

from boss.config import Filters
from boss.domain import Job
from boss.filters import JobFilter


class JobFilterTest(unittest.TestCase):
    def test_job_object_and_salary_units(self):
        policy = JobFilter(Filters(include_keywords=["Python"], min_salary=15))
        self.assertTrue(policy.check_job(Job("Python 开发", "1.5-2万")).accept)
        decision = policy.check_job(Job("Python 开发", "8千-12千"))
        self.assertFalse(decision.accept)
        self.assertIn("8K", decision.reason)

    def test_exclude_keyword_has_priority(self):
        policy = JobFilter(Filters(include_keywords=["开发"], exclude_keywords=["外包"]))
        decision = policy.check_job(Job("外包开发"))
        self.assertFalse(decision.accept)
        self.assertIn("排除词", decision.reason)


if __name__ == "__main__":
    unittest.main()

import logging
import unittest

from boss.application import ApplyService
from boss.config import AppConfig, Filters, Greeting, Limits, Safety
from boss.domain import Job


class FakeState:
    def __init__(self):
        self.applied_today = 0
        self.applied_keys = set()
        self.skipped_keys = set()

    def is_seen(self, key):
        return key in self.applied_keys or key in self.skipped_keys

    def mark_applied(self, keys):
        if isinstance(keys, str):
            keys = [keys]
        keys = list(keys)
        if not any(key in self.applied_keys for key in keys):
            self.applied_today += 1
        self.applied_keys.update(keys)

    def mark_skipped(self, keys):
        if isinstance(keys, str):
            keys = [keys]
        self.skipped_keys.update(keys)


class FakeHome:
    def __init__(self, cards):
        self.cards = list(cards)
        self.opened = False
        self.back_count = 0

    def open_recommend(self):
        self.opened = True
        return True

    def job_cards(self):
        if not self.cards:
            return []
        return [self.cards.pop(0)]

    def scroll(self):
        pass

    def job_delay(self):
        pass

    def human_delay(self):
        pass

    def back_to_list(self):
        self.back_count += 1
        return True


class FakeDetail:
    def __init__(self, job):
        self.job = job
        self.communicated = False

    def title(self):
        return self.job.title

    def salary(self):
        return self.job.salary

    def communicate(self):
        self.communicated = True
        return True

    def handle_after_communicate(self):
        pass


class FakeChat:
    def in_chat(self):
        return False


class FakeRecorder:
    def __init__(self):
        self.rows = []
        self.closed = False

    def add(self, *row):
        self.rows.append(row)

    def close(self):
        self.closed = True


class ApplyServiceTest(unittest.TestCase):
    def test_filter_and_apply_are_orchestrated_without_device(self):
        accepted = Job("Python 工程师", "15K", "甲公司")
        filtered = Job("销售代表", "20K", "乙公司")
        home = FakeHome([accepted, filtered])
        detail = FakeDetail(accepted)
        recorder = FakeRecorder()
        cfg = AppConfig(
            greeting=Greeting(),
            limits=Limits(max_apply_per_run=5, max_apply_per_day=5),
            safety=Safety(records_db=""),
            filters=Filters(exclude_keywords=["销售"]),
        )
        state = FakeState()
        service = ApplyService(
            home,
            detail,
            FakeChat(),
            cfg,
            state,
            logging.getLogger("test-application"),
            recorder=recorder,
        )
        service.max_rounds = 2

        self.assertEqual(service.run(), 1)
        self.assertTrue(detail.communicated)
        self.assertEqual(state.applied_today, 1)
        self.assertEqual(service.last_summary.filtered, 1)
        self.assertEqual(len([r for r in recorder.rows if r[0] == "applied"]), 1)
        self.assertTrue(recorder.closed)


if __name__ == "__main__":
    unittest.main()

import unittest
import datetime
import sys
from unittest.mock import MagicMock

# Mock dependencies to allow importing app.py
sys.modules["psutil"] = MagicMock()
sys.modules["requests"] = MagicMock()
sys.modules["google.cloud"] = MagicMock()
sys.modules["google.cloud.storage"] = MagicMock()
sys.modules["flask"] = MagicMock()

import app

class TestGetTargetTimes(unittest.TestCase):
    def test_sequential_hours(self):
        start_dt = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        hours = ["13", "14", "15"]
        expected = [
            datetime.datetime(2023, 1, 1, 13, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2023, 1, 1, 14, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2023, 1, 1, 15, 0, tzinfo=datetime.timezone.utc),
        ]
        self.assertEqual(app.get_target_times(start_dt, hours), expected)

    def test_day_rollover(self):
        start_dt = datetime.datetime(2023, 1, 1, 22, 0, tzinfo=datetime.timezone.utc)
        hours = ["23", "0", "1"]
        expected = [
            datetime.datetime(2023, 1, 1, 23, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2023, 1, 2, 0, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2023, 1, 2, 1, 0, tzinfo=datetime.timezone.utc),
        ]
        self.assertEqual(app.get_target_times(start_dt, hours), expected)

    def test_jumps(self):
        start_dt = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        hours = ["15", "18"]
        expected = [
            datetime.datetime(2023, 1, 1, 15, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2023, 1, 1, 18, 0, tzinfo=datetime.timezone.utc),
        ]
        self.assertEqual(app.get_target_times(start_dt, hours), expected)

    def test_same_hour(self):
        start_dt = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        hours = ["12", "12"]
        expected = [
            datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
        ]
        self.assertEqual(app.get_target_times(start_dt, hours), expected)

    def test_rollover_without_sequential(self):
        start_dt = datetime.datetime(2023, 1, 1, 23, 0, tzinfo=datetime.timezone.utc)
        hours = ["11"]
        expected = [
            datetime.datetime(2023, 1, 1, 11, 0, tzinfo=datetime.timezone.utc),
        ]
        self.assertEqual(app.get_target_times(start_dt, hours), expected)

        hours = ["10"]
        expected = [
            datetime.datetime(2023, 1, 2, 10, 0, tzinfo=datetime.timezone.utc),
        ]
        self.assertEqual(app.get_target_times(start_dt, hours), expected)

    def test_empty_hours(self):
        start_dt = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(app.get_target_times(start_dt, []), [])

    def test_int_hours(self):
        start_dt = datetime.datetime(2023, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
        hours = [13, 14]
        expected = [
            datetime.datetime(2023, 1, 1, 13, 0, tzinfo=datetime.timezone.utc),
            datetime.datetime(2023, 1, 1, 14, 0, tzinfo=datetime.timezone.utc),
        ]
        self.assertEqual(app.get_target_times(start_dt, hours), expected)

if __name__ == '__main__':
    unittest.main()

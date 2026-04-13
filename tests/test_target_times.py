import sys
import unittest
import datetime
from unittest.mock import MagicMock

# Mock dependencies to allow importing app.py in an environment where they are missing.
# This is necessary because app.py performs many top-level imports and initializations.
mock_modules = [
    'psutil',
    'google',
    'google.cloud',
    'google.cloud.storage',
    'flask',
    'requests'
]
for module in mock_modules:
    sys.modules[module] = MagicMock()

import app

class TestTargetTimes(unittest.TestCase):
    """
    Tests for get_target_times in app.py.
    This function converts a list of hour strings from the NWS API into a list of
    timezone-naive datetime objects, handling day boundaries.
    """

    def test_basic_progression(self):
        """Test a simple sequence of hours within the same day."""
        # start=2026-03-28 19:00, hours=["19", "20", "21"]
        # expected -> [2026-03-28 19:00, 2026-03-28 20:00, 2026-03-28 21:00]
        start = datetime.datetime(2026, 3, 28, 19, 0)
        hours = ["19", "20", "21"]
        expected = [
            datetime.datetime(2026, 3, 28, 19, 0),
            datetime.datetime(2026, 3, 28, 20, 0),
            datetime.datetime(2026, 3, 28, 21, 0)
        ]
        result = app.get_target_times(start, hours)
        self.assertEqual(result, expected)

    def test_forward_midnight(self):
        """Test transitioning from 23:00 to 00:00 (next day)."""
        # start=2026-03-28 22:00, hours=["22", "23", "0", "1"]
        # expected -> [2026-03-28 22:00, 2026-03-28 23:00, 2026-03-29 00:00, 2026-03-29 01:00]
        start = datetime.datetime(2026, 3, 28, 22, 0)
        hours = ["22", "23", "0", "1"]
        expected = [
            datetime.datetime(2026, 3, 28, 22, 0),
            datetime.datetime(2026, 3, 28, 23, 0),
            datetime.datetime(2026, 3, 29, 0, 0),
            datetime.datetime(2026, 3, 29, 1, 0)
        ]
        result = app.get_target_times(start, hours)
        self.assertEqual(result, expected)

    def test_backward_midnight_correction(self):
        """
        Test case where the forecast starts with an hour from the previous day.
        Example: Fetching at 00:30, but receiving a forecast starting at 23:00.
        Expected: The 23:00 entry should be for the previous day, not the current day.
        """
        # start=2026-03-29 00:30, hours=["23", "0", "1"]
        # expected -> [2026-03-28 23:00, 2026-03-29 00:00, 2026-03-29 01:00]
        start = datetime.datetime(2026, 3, 29, 0, 30)
        hours = ["23", "0", "1"]
        expected = [
            datetime.datetime(2026, 3, 28, 23, 0),
            datetime.datetime(2026, 3, 29, 0, 0),
            datetime.datetime(2026, 3, 29, 1, 0)
        ]
        result = app.get_target_times(start, hours)
        self.assertEqual(result, expected)

    def test_empty_hours(self):
        """Test that empty input returns an empty list."""
        start = datetime.datetime(2026, 3, 29, 0, 30)
        hours = []
        expected = []
        result = app.get_target_times(start, hours)
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()

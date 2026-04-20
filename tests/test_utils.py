import sys
import unittest
from unittest.mock import MagicMock, patch

def safe_import_app():
    if 'app' in sys.modules:
        return sys.modules['app']

    dependencies = [
        'psutil',
        'google',
        'google.cloud',
        'google.cloud.storage',
        'flask',
        'requests'
    ]

    missing_mocks = {}
    for dep in dependencies:
        try:
            __import__(dep)
        except ImportError:
            missing_mocks[dep] = MagicMock()

    if missing_mocks:
        with patch.dict(sys.modules, missing_mocks):
            import app
            return app
    else:
        import app
        return app

app = safe_import_app()

class TestUtils(unittest.TestCase):
    def test_percentile(self):
        # Empty list
        self.assertIsNone(app.percentile([], 0.5))

        # List with None
        self.assertEqual(app.percentile([1, None, 3], 0.5), 2.0)

        # Single value
        self.assertEqual(app.percentile([10], 0.5), 10.0)

        # q = 0
        self.assertEqual(app.percentile([1, 2, 3], 0), 1.0)

        # q = 1
        self.assertEqual(app.percentile([1, 2, 3], 1), 3.0)

        # Exact index (pos is integer)
        # (3-1) * 0.5 = 1.0 -> index 1
        self.assertEqual(app.percentile([10, 20, 30], 0.5), 20.0)

        # Interpolation
        # (2-1) * 0.5 = 0.5 -> between index 0 and 1
        self.assertEqual(app.percentile([10, 20], 0.5), 15.0)

        # q < 0 should behave like q = 0
        self.assertEqual(app.percentile([1, 2, 3], -0.1), 1.0)

        # q > 1 should behave like q = 1
        self.assertEqual(app.percentile([1, 2, 3], 1.1), 3.0)

    def test_parse_wind_speed(self):
        self.assertEqual(app.parse_wind_speed("20 mph"), 20)
        self.assertEqual(app.parse_wind_speed("15 to 25 mph"), 25)
        self.assertEqual(app.parse_wind_speed(""), 0)
        self.assertEqual(app.parse_wind_speed(None), 0)
        self.assertEqual(app.parse_wind_speed("calm"), 0)

    def test_parse_iso8601_duration(self):
        self.assertEqual(app.parse_iso8601_duration("P1D"), 24)
        self.assertEqual(app.parse_iso8601_duration("PT3H"), 3)
        self.assertEqual(app.parse_iso8601_duration("P1DT6H"), 30)
        self.assertEqual(app.parse_iso8601_duration("PT0H"), 1) # Default return 1 if total_hours <= 0
        self.assertEqual(app.parse_iso8601_duration("invalid"), 1)

if __name__ == '__main__':
    unittest.main()

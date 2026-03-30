import unittest
from unittest.mock import patch, MagicMock
import app

class AppTestCase(unittest.TestCase):
    def setUp(self):
        app.app.config['TESTING'] = True
        self.client = app.app.test_client()

    @patch('app.requests.get')
    def test_health_check_ok(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        response = self.client.get('/health-check')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok", "api.weather.gov": "ok"})

    @patch('app.requests.get')
    def test_health_check_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.RequestException("Mocked exception")

        response = self.client.get('/health-check')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json, {"status": "error", "api.weather.gov": "unreachable"})

    @patch('app.scrape_forecast')
    def test_index(self, mock_scrape_forecast):
        mock_scrape_forecast.return_value = {
            'hour': [12],
            'direction': ['NE'],
            'speed': [15],
            'temp': [80],
            'precip': [10],
            'icon': ['http://example.com/icon.png'],
            'short': ['Sunny']
        }
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'WAIKIKI', response.data)

    @patch('app.scrape_forecast')
    def test_forecast_ok(self, mock_scrape_forecast):
        expected_data = {
            'hour': [12],
            'direction': ['NE'],
            'speed': [15],
            'temp': [80],
            'precip': [10],
            'icon': ['http://example.com/icon.png'],
            'short': ['Sunny']
        }
        mock_scrape_forecast.return_value = expected_data
        response = self.client.get('/forecast')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, expected_data)

    @patch('app.scrape_forecast')
    def test_forecast_error(self, mock_scrape_forecast):
        import requests
        mock_scrape_forecast.side_effect = requests.RequestException("Upstream failed")
        response = self.client.get('/forecast')
        self.assertEqual(response.status_code, 502)
        self.assertIn('error', response.json)

    @patch('app.get_goes_airmass_url')
    def test_goes_airmass_ok(self, mock_get_goes_airmass_url):
        mock_get_goes_airmass_url.side_effect = lambda sector: f"http://example.com/{sector}.gif"
        response = self.client.get('/goes-airmass')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {
            'urls': {
                'hi': 'http://example.com/hi.gif',
                'tpw': 'http://example.com/tpw.gif'
            }
        })

    def test_screenshot(self):
        response = self.client.get('/screenshot.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'image/png')

    def test_robots(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'text/plain')
        self.assertIn(b'Allow: /', response.data)

    @patch('app.requests.get')
    def test_icon_ok(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake image content"
        mock_resp.headers = {'Content-Type': 'image/png'}
        mock_get.return_value = mock_resp

        response = self.client.get('/icon?url=https://api.weather.gov/icons/test.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'image/png')
        self.assertEqual(response.data, b"fake image content")

    def test_icon_missing_url(self):
        response = self.client.get('/icon')
        self.assertEqual(response.status_code, 400)

    def test_icon_invalid_url(self):
        response = self.client.get('/icon?url=https://example.com/icon.png')
        self.assertEqual(response.status_code, 403)

if __name__ == '__main__':
    unittest.main()

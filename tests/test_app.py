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

    @patch('app.get_forecast_urls')
    @patch('app.requests.get')
    def test_scrape_forecast_custom_wind_chill(self, mock_get, mock_get_forecast_urls):
        mock_get_forecast_urls.return_value = ('http://hourly', 'http://grid')

        # We need two responses: one for hourly, one for grid
        mock_hourly_resp = MagicMock()
        mock_hourly_resp.status_code = 200
        mock_hourly_resp.json.return_value = {
            'properties': {
                'periods': [
                    {
                        'startTime': '2026-03-28T19:00:00-10:00',
                        'windDirection': 'NE',
                        'windSpeed': '20 mph',
                        'temperature': 70,
                        'probabilityOfPrecipitation': {'value': 0},
                        'icon': 'icon.png',
                        'shortForecast': 'Sunny'
                    },
                    {
                        'startTime': '2026-03-28T20:00:00-10:00',
                        'windDirection': 'E',
                        'windSpeed': '5 mph',
                        'temperature': 85, # Too warm for adjustment
                        'probabilityOfPrecipitation': {'value': 0},
                        'icon': 'icon.png',
                        'shortForecast': 'Sunny'
                    },
                    {
                        'startTime': '2026-03-28T21:00:00-10:00',
                        'windDirection': 'E',
                        'windSpeed': '0 mph', # No wind
                        'temperature': 65,
                        'probabilityOfPrecipitation': {'value': 0},
                        'icon': 'icon.png',
                        'shortForecast': 'Sunny'
                    }
                ]
            }
        }

        mock_grid_resp = MagicMock()
        mock_grid_resp.status_code = 200
        # For apparentTemperature: 21.11C = 70F, 29.44C = 85F, 18.33C = 65F
        mock_grid_resp.json.return_value = {
            'properties': {
                'apparentTemperature': {
                    'values': [
                        {'validTime': '2026-03-28T19:00:00-10:00/PT1H', 'value': 21.11},
                        {'validTime': '2026-03-28T20:00:00-10:00/PT1H', 'value': 29.44},
                        {'validTime': '2026-03-28T21:00:00-10:00/PT1H', 'value': 18.33}
                    ]
                }
            }
        }

        mock_get.side_effect = [mock_hourly_resp, mock_grid_resp]

        data = app.scrape_forecast()

        self.assertEqual(len(data['apparent_temp']), 3)

    @patch('app.get_forecast_urls')
    @patch('app.requests.get')
    def test_wind_chill_drops_temp(self, mock_get, mock_get_forecast_urls):
        mock_get_forecast_urls.return_value = ('http://hourly', 'http://grid')
        mock_hourly_resp = MagicMock()
        mock_hourly_resp.status_code = 200
        mock_hourly_resp.json.return_value = {
            'properties': {
                'periods': [{
                    'startTime': '2026-03-28T19:00:00-10:00',
                    'windDirection': 'NE',
                    'windSpeed': '25 mph',
                    'temperature': 75,
                    'probabilityOfPrecipitation': {'value': 0},
                    'icon': 'icon.png',
                    'shortForecast': 'Cloudy'
                }]
            }
        }
        mock_grid_resp = MagicMock()
        mock_grid_resp.status_code = 200
        # 75 F -> 23.88 C
        mock_grid_resp.json.return_value = {
            'properties': {
                'apparentTemperature': {
                    'values': [
                        {'validTime': '2026-03-28T19:00:00-10:00/PT1H', 'value': 23.8888}
                    ]
                },
                'relativeHumidity': {
                    'values': [
                        {'validTime': '2026-03-28T19:00:00-10:00/PT1H', 'value': 50}
                    ]
                }
            }
        }
        mock_get.side_effect = [mock_hourly_resp, mock_grid_resp]
        data = app.scrape_forecast()

        apparent = data['apparent_temp'][0]
        # At 75F, 50% RH, and 25mph wind, the Australian AT is ~62.3F (62F)
        self.assertEqual(apparent, 62)

if __name__ == '__main__':
    unittest.main()

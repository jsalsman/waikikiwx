import re
import requests
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder='.')

LAT = 21.3069
LON = -157.8583

POINTS_URL = f'https://api.weather.gov/points/{LAT},{LON}'
HOURS_WANTED = 48
GOES_SECTOR_URL = 'https://www.star.nesdis.noaa.gov/goes/sector.php?sat=G18&sector=hi'
GOES_CDN_PREFIX = 'https://cdn.star.nesdis.noaa.gov/'

# Cache the hourly forecast URL — gridpoint mapping never changes
_forecast_hourly_url = None

HEADERS = {
    'User-Agent': 'waikikiwx (github.com/jsalsman/waikikiwx)',
    'Accept': 'application/geo+json',
}


def get_forecast_hourly_url():
    global _forecast_hourly_url
    if _forecast_hourly_url:
        return _forecast_hourly_url
    resp = requests.get(POINTS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    _forecast_hourly_url = resp.json()['properties']['forecastHourly']
    return _forecast_hourly_url


def parse_wind_speed(s):
    # "20 mph" or "15 to 20 mph" — take the higher number
    import re
    nums = re.findall(r'\d+', s or '')
    return max(int(n) for n in nums) if nums else 0


def hour_from_iso(iso):
    # "2026-03-28T19:00:00-10:00" → 19
    return int(iso.split('T')[1][:2])


def scrape_forecast():
    url = get_forecast_hourly_url()
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    periods = resp.json()['properties']['periods'][:HOURS_WANTED]
    if not periods:
        raise ValueError('No forecast periods returned from API')

    return {
        'hour':      [hour_from_iso(p['startTime']) for p in periods],
        'direction': [p['windDirection'] for p in periods],
        'speed':     [parse_wind_speed(p['windSpeed']) for p in periods],
        'temp':      [p['temperature'] for p in periods],
        'precip':    [p['probabilityOfPrecipitation']['value'] or 0 for p in periods],
        'icon':      [p.get('icon', '') for p in periods],
        'short':     [p.get('shortForecast', '') for p in periods],
    }


def get_goes_airmass_url():
    resp = requests.get(GOES_SECTOR_URL, timeout=15)
    resp.raise_for_status()
    html = resp.text
    matches = re.findall(r'(?:https://cdn\.star\.nesdis\.noaa\.gov/)?GOES18/ABI/SECTOR/hi/AirMass/[A-Za-z0-9._/-]+?\.gif', html)
    if not matches:
        raise ValueError('No GOES Air Mass GIF URL found on NOAA sector page')
    latest = matches[-1]
    return latest if latest.startswith('http') else GOES_CDN_PREFIX + latest


@app.route('/debug')
def debug():
    try:
        url = get_forecast_hourly_url()
        resp = requests.get(url, headers=HEADERS, timeout=15)
        import json
        snippet = json.dumps(resp.json()['properties']['periods'][:2], indent=2)
        return f'<pre>Status: {resp.status_code}\nURL: {url}\n\n{snippet}</pre>'
    except Exception as e:
        return f'<pre>Error: {e}</pre>', 500


@app.route('/')
def index():
    return send_from_directory('.', 'index.html', mimetype='text/html')


@app.route('/forecast')
def forecast():
    try:
        data = scrape_forecast()
        return jsonify(data)
    except requests.RequestException as e:
        msg = f'Upstream request failed: {e}'
        app.logger.error(msg)
        return jsonify({'error': msg}), 502
    except (ValueError, KeyError) as e:
        msg = f'Parse error: {e}'
        app.logger.error(msg)
        return jsonify({'error': msg}), 502


@app.route('/goes-airmass')
def goes_airmass():
    try:
        return jsonify({'url': get_goes_airmass_url()})
    except requests.RequestException as e:
        msg = f'Upstream request failed: {e}'
        app.logger.error(msg)
        return jsonify({'error': msg}), 502
    except ValueError as e:
        msg = f'Parse error: {e}'
        app.logger.error(msg)
        return jsonify({'error': msg}), 502


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

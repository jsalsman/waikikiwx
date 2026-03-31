import re
import requests
from flask import Flask, jsonify, send_from_directory, render_template, request, Response

app = Flask(__name__, template_folder='.')

LAT = 21.3069
LON = -157.8583

POINTS_URL = f'https://api.weather.gov/points/{LAT},{LON}'
HOURS_WANTED = 48

GOES_CDN_PREFIX = 'https://cdn.star.nesdis.noaa.gov/'
GOES_SECTORS = ('hi', 'tpw')

# Cache the URLs — gridpoint mapping never changes
_forecast_hourly_url = None
_forecast_grid_data_url = None

HEADERS = {
    'User-Agent': 'waikikiwx (github.com/jsalsman/waikikiwx)',
    'Accept': 'application/geo+json',
}

def get_forecast_urls():
    global _forecast_hourly_url, _forecast_grid_data_url
    if _forecast_hourly_url and _forecast_grid_data_url:
        return _forecast_hourly_url, _forecast_grid_data_url
    resp = requests.get(POINTS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    props = resp.json()['properties']
    _forecast_hourly_url = props['forecastHourly']
    _forecast_grid_data_url = props['forecastGridData']
    return _forecast_hourly_url, _forecast_grid_data_url

import datetime

WIND_SPEED_RE = re.compile(r'\d+')
def parse_wind_speed(s):
    # "20 mph" or "15 to 20 mph" — take the higher number
    nums = WIND_SPEED_RE.findall(s or '')
    return max(int(n) for n in nums) if nums else 0

def hour_from_iso(iso):
    # "2026-03-28T19:00:00-10:00" → 19
    return int(iso.split('T')[1][:2])

def parse_iso8601_duration(d):
    # e.g., P1D, PT3H, P1DT6H
    # Returns total duration in hours
    days = 0
    hours = 0

    # Extract days
    m_days = re.search(r'P(\d+)D', d)
    if m_days:
        days = int(m_days.group(1))

    # Extract hours
    m_hours = re.search(r'T(?:.*?(\d+)H)?', d)
    if m_hours and m_hours.group(1):
        hours = int(m_hours.group(1))

    total_hours = (days * 24) + hours
    return total_hours if total_hours > 0 else 1

def map_grid_series_to_hourly(series_values, hourly_dts, converter=None):
    # series_values: [{'validTime': '2026-03-30T10:00:00+00:00/PT3H', 'value': 21.6}, ...]
    # hourly_dts: list of datetime objects (timezone-aware)
    # returns list of values matching hourly_dts

    parsed_series = []
    for item in series_values:
        val = item.get('value')
        if val is None:
            continue
        vt = item.get('validTime')
        if not vt or '/' not in vt:
            continue
        dt_str, dur_str = vt.split('/')
        start_dt = datetime.datetime.fromisoformat(dt_str)
        dur_h = parse_iso8601_duration(dur_str)
        end_dt = start_dt + datetime.timedelta(hours=dur_h)
        parsed_series.append((start_dt, end_dt, val))

    res = []
    for dt in hourly_dts:
        matched_val = None
        for start_dt, end_dt, val in parsed_series:
            # We assume dt is timezone aware and so are start_dt/end_dt
            if start_dt <= dt < end_dt:
                matched_val = val
                break
        if matched_val is not None and converter is not None:
            matched_val = converter(matched_val)
        res.append(matched_val)
    return res

def scrape_forecast():
    hourly_url, grid_url = get_forecast_urls()

    # 1. Fetch hourly
    resp_hourly = requests.get(hourly_url, headers=HEADERS, timeout=15)
    resp_hourly.raise_for_status()

    periods = resp_hourly.json()['properties']['periods'][:HOURS_WANTED]
    if not periods:
        raise ValueError('No forecast periods returned from API')

    hourly_dts = [datetime.datetime.fromisoformat(p['startTime']) for p in periods]

    # 2. Fetch grid for apparentTemp and windGust
    resp_grid = requests.get(grid_url, headers=HEADERS, timeout=15)
    resp_grid.raise_for_status()
    grid_props = resp_grid.json().get('properties', {})

    raw_apparent = grid_props.get('apparentTemperature', {}).get('values', [])
    # C to F converter
    def c_to_f(c): return round(c * 9/5 + 32)
    apparent_temp = map_grid_series_to_hourly(raw_apparent, hourly_dts, converter=c_to_f)

    raw_gust = grid_props.get('windGust', {}).get('values', [])
    # km/h to mph converter
    def kmh_to_mph(kmh): return round(kmh / 1.60934)
    wind_gust = map_grid_series_to_hourly(raw_gust, hourly_dts, converter=kmh_to_mph)

    raw_qpf = grid_props.get('quantitativePrecipitation', {}).get('values', [])
    # mm to inches converter
    def mm_to_in(mm): return round(mm / 25.4, 2)
    precip_in = map_grid_series_to_hourly(raw_qpf, hourly_dts, converter=mm_to_in)

    # In case there's no gust data or missing values, we'll fill None with speed
    speed = [parse_wind_speed(p['windSpeed']) for p in periods]
    for i in range(len(wind_gust)):
        if wind_gust[i] is None:
            wind_gust[i] = speed[i]
        elif wind_gust[i] < speed[i]:
            wind_gust[i] = speed[i]

    temp = [p['temperature'] for p in periods]
    for i in range(len(apparent_temp)):
        if apparent_temp[i] is None:
            apparent_temp[i] = temp[i]

        # Custom wind chill adjustment for apparent temp between 50F and 80F
        t = apparent_temp[i]
        v = speed[i]
        if 50 <= t <= 80 and v > 3:
            # Standard NWS wind chill formula applied to higher temps
            wc = 35.74 + (0.6215 * t) - (35.75 * (v**0.16)) + (0.4275 * t * (v**0.16))
            if wc < t:
                apparent_temp[i] = round(wc)

    for i in range(len(precip_in)):
        if precip_in[i] is None:
            precip_in[i] = 0.0

    return {
        'hour':          [hour_from_iso(p['startTime']) for p in periods],
        'direction':     [p['windDirection'] for p in periods],
        'speed':         speed,
        'gust':          wind_gust,
        'temp':          temp,
        'apparent_temp': apparent_temp,
        'precip':        [p['probabilityOfPrecipitation']['value'] or 0 for p in periods],
        'precip_in':     precip_in,
        'icon':          [p.get('icon', '') for p in periods],
        'short':         [p.get('shortForecast', '') for p in periods],
    }

def get_goes_airmass_url(sector):
    sector_url = f'https://www.star.nesdis.noaa.gov/goes/sector.php?sat=G18&sector={sector}'
    resp = requests.get(sector_url, timeout=15)
    resp.raise_for_status()
    html = resp.text
    matches = re.findall(
        rf'(?:https://cdn\.star\.nesdis\.noaa\.gov/)?GOES18/ABI/SECTOR/{sector}/AirMass/[A-Za-z0-9._/-]+?\.gif',
        html,
    )
    if not matches:
        raise ValueError(f'No GOES Air Mass GIF URL found on NOAA sector page for sector={sector}')
    latest = matches[-1]
    return latest if latest.startswith('http') else GOES_CDN_PREFIX + latest

@app.route('/health-check')
def health_check():
    try:
        resp = requests.get('https://api.weather.gov/', headers=HEADERS, timeout=5)
        resp.raise_for_status()
        return jsonify({"status": "ok", "api.weather.gov": "ok"})
    except requests.RequestException as e:
        app.logger.error(f'api.weather.gov health check failed: {e}')
        return jsonify({"status": "error", "api.weather.gov": "unreachable"}), 500

@app.route('/')
def index():
    data = None
    try:
        data = scrape_forecast()
    except Exception as e:
        app.logger.error(f'Failed to fetch initial forecast: {e}')
    
    return render_template('index.html', data=data)

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
        urls = {sector: get_goes_airmass_url(sector) for sector in GOES_SECTORS}
        return jsonify({'urls': urls})
    except requests.RequestException as e:
        msg = f'Upstream request failed: {e}'
        app.logger.error(msg)
        return jsonify({'error': msg}), 502
    except ValueError as e:
        msg = f'Parse error: {e}'
        app.logger.error(msg)
        return jsonify({'error': msg}), 502

@app.route('/screenshot.png')
def screenshot():
    return send_from_directory('.', 'screenshot.png')

@app.route('/robots.txt')
def robots():
    return Response("User-agent: *\nAllow: /\n", content_type="text/plain")

@app.route('/icon')
def fetch_icon():
    url = request.args.get('url')
    if not url:
        return "No url parameter provided", 400
    if not url.startswith('https://api.weather.gov/'):
        return "Invalid URL domain", 403
    try:
        # NWS blocks standard User-Agents, spoofing it here
        req_headers = {'User-Agent': HEADERS['User-Agent']}
        resp = requests.get(url, headers=req_headers, timeout=15)
        resp.raise_for_status()
        return Response(resp.content, content_type=resp.headers.get('Content-Type'))
    except Exception as e:
        app.logger.error(f"Failed to fetch icon from {url}: {e}")
        return "Failed to fetch icon", 502

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

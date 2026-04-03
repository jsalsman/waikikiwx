import collections, datetime, json, math, os, re, requests, statistics, tempfile, uuid
from google.cloud import storage
from flask import Flask, jsonify, send_from_directory, render_template, request, Response

HST = datetime.timezone(datetime.timedelta(hours=-10))

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

def percentile(N, percent, key=lambda x:x):
    if not N:
        return None
    N.sort(key=key)
    k = (len(N)-1) * percent
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return key(N[int(k)])
    d0 = key(N[int(f)]) * (c-k)
    d1 = key(N[int(c)]) * (k-f)
    return d0+d1

def get_target_times(start_dt, hours):
    times = []
    current = start_dt.replace(minute=0, second=0, microsecond=0)
    if not hours:
        return times

    prev_h = current.hour
    for h_str in hours:
        h = int(h_str)
        if h < prev_h and (prev_h - h) > 12:
            current += datetime.timedelta(days=1)
        current = current.replace(hour=h)
        times.append(current)
        prev_h = h
    return times

def percentile(values, q):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if q <= 0:
        return vals[0]
    if q >= 1:
        return vals[-1]
    pos = (len(vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return vals[int(pos)]
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac

def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def build_proxy_observations_from_hour0(historical_forecasts):
    """
    Uses each later snapshot's lead-0/current-conditions value as the realized value
    for that target time. This is a proxy. If you have a real observations feed,
    pass observed_by_target into calculate_ci_from_history() instead.
    """
    observed_by_target = {}
    for hf in sorted(historical_forecasts, key=lambda x: x["time"]):
        data = hf["data"]
        hours = data.get("hour", [])
        target_times = get_target_times(hf["time"], hours)  # assumes this already exists
        if not target_times:
            continue

        t0 = target_times[0]
        temp0 = to_float(data.get("temp", [None])[0] if len(data.get("temp", [])) > 0 else None)
        precip0 = to_float(data.get("precip", [None])[0] if len(data.get("precip", [])) > 0 else None)
        speed0 = to_float(data.get("speed", [None])[0] if len(data.get("speed", [])) > 0 else None)

        observed_by_target[t0] = {
            "temp": temp0,
            "precip": precip0,
            "speed": speed0,
        }
    return observed_by_target

def neighbor_pool(errors_by_lead, lead_idx, var_name, min_samples, excluded_leads=None):
    excluded_leads = excluded_leads or set()
    for radius in (0, 1, 2, 4, 8, 47):
        pooled = []
        lo = max(0, lead_idx - radius)
        hi = min(47, lead_idx + radius)
        for j in range(lo, hi + 1):
            if j in excluded_leads:
                continue
            pooled.extend(errors_by_lead[j][var_name])
        if len(pooled) >= min_samples or radius == 47:
            return pooled
    return []

def calculate_ci_from_history(historical_forecasts, observed_by_target=None, coverage=0.50, min_samples=50):
    """
    Returns residual quantiles by lead:
        error_low/error_high = quantiles of (observed - forecast)

    To build a prediction interval for a new forecast value f:
        lower = f + error_low
        upper = f + error_high

    If observed_by_target is None, this uses later lead-0 values as a proxy for the
    realized weather at each target time.
    """
    using_proxy_observations = observed_by_target is None
    if observed_by_target is None:
        observed_by_target = build_proxy_observations_from_hour0(historical_forecasts)

    vars_ = ("temp", "precip", "speed")
    errors_by_lead = collections.defaultdict(lambda: {v: [] for v in vars_})

    for hf in sorted(historical_forecasts, key=lambda x: x["time"]):
        f_time = hf["time"]
        data = hf["data"]
        hours = data.get("hour", [])
        target_times = get_target_times(f_time, hours)  # assumes this already exists

        for lead_idx, t_time in enumerate(target_times[:48]):
            if using_proxy_observations and lead_idx == 0:
                # Otherwise lead 0 would be tautologically perfect because it is also the proxy truth source.
                continue

            obs = observed_by_target.get(t_time)
            if not obs:
                continue

            for var_name in vars_:
                forecast_values = data.get(var_name, [])
                if lead_idx >= len(forecast_values):
                    continue

                forecast_val = to_float(forecast_values[lead_idx])
                observed_val = to_float(obs.get(var_name))
                if forecast_val is None or observed_val is None:
                    continue

                # Residual = realized - forecast
                errors_by_lead[lead_idx][var_name].append(observed_val - forecast_val)

    alpha = (1.0 - coverage) / 2.0
    excluded_leads = {0} if using_proxy_observations else set()
    ci_bounds = {}

    for lead_idx in range(48):
        row = {}
        for var_name in vars_:
            raw_errors = errors_by_lead[lead_idx][var_name]

            if using_proxy_observations and lead_idx == 0:
                used_errors = []
            else:
                used_errors = (
                    raw_errors
                    if len(raw_errors) >= min_samples
                    else neighbor_pool(errors_by_lead, lead_idx, var_name, min_samples, excluded_leads)
                )

            low = percentile(used_errors, alpha)
            high = percentile(used_errors, 1.0 - alpha)

            row[f"{var_name}_error_low"] = 0.0 if low is None else low
            row[f"{var_name}_error_high"] = 0.0 if high is None else high
            row[f"{var_name}_n"] = len(raw_errors)
            row[f"{var_name}_n_used"] = len(used_errors)
            row[f"{var_name}_bias"] = statistics.fmean(raw_errors) if raw_errors else 0.0
            row[f"{var_name}_mae"] = statistics.fmean(abs(e) for e in raw_errors) if raw_errors else 0.0

        ci_bounds[str(lead_idx)] = row

    return ci_bounds
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
    def c_to_f(c): return round(c * 9/5 + 32)
    apparent_temp = map_grid_series_to_hourly(raw_apparent, hourly_dts, converter=c_to_f)

    raw_gust = grid_props.get('windGust', {}).get('values', [])
    def kmh_to_mph(kmh): return round(kmh / 1.60934)
    wind_gust = map_grid_series_to_hourly(raw_gust, hourly_dts, converter=kmh_to_mph)

    raw_qpf = grid_props.get('quantitativePrecipitation', {}).get('values', [])
    def mm_to_in(mm): return round(mm / 25.4, 2)
    precip_in = map_grid_series_to_hourly(raw_qpf, hourly_dts, converter=mm_to_in)

    raw_rh = grid_props.get('relativeHumidity', {}).get('values', [])
    rh_hourly = map_grid_series_to_hourly(raw_rh, hourly_dts)

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

        t_f = apparent_temp[i]
        v_mph = speed[i]
        rh = rh_hourly[i] if rh_hourly and i < len(rh_hourly) and rh_hourly[i] is not None else 50

        if 50 <= t_f <= 80 and v_mph > 0:
            t_c = (t_f - 32) * 5 / 9
            v_ms = v_mph * 0.44704
            e = (rh / 100) * 6.105 * math.exp((17.27 * t_c) / (237.7 + t_c))
            at_c = t_c + (0.33 * e) - (0.70 * v_ms) - 4.00
            at_f = (at_c * 9 / 5) + 32

            if at_f < t_f:
                apparent_temp[i] = round(at_f)

    precip = []
    for p in periods:
        pop = p.get('probabilityOfPrecipitation', {})
        val = pop.get('value')
        precip.append(val if val is not None else 0)

    for i in range(len(precip_in)):
        if precip_in[i] is None:
            precip_in[i] = 0.0

    def hour_from_iso(iso):
        return int(iso.split('T')[1][:2])

    forecast_data = {
        'hour': [hour_from_iso(p['startTime']) for p in periods],
        'temp': temp,
        'apparent_temp': apparent_temp,
        'precip': precip,
        'precip_in': precip_in,
        'speed': speed,
        'gust': wind_gust,
        'direction': [p['windDirection'] for p in periods],
        'icon': [p.get('icon', '') for p in periods],
        'short': [p.get('shortForecast', '') for p in periods]
    }

    # Fetch pre-calculated confidence intervals from GCS
    ci_bounds = {}
    try:
        if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') and not os.environ.get('KUBERNETES_SERVICE_HOST'):
            pass
        else:
            client = storage.Client()
            bucket = client.bucket('waikikiwx')
            blob = bucket.blob('confidence-intervals.json')
            if blob.exists():
                ci_bounds = json.loads(blob.download_as_string())
    except Exception as e:
        app.logger.warning(f"Failed to fetch confidence intervals from GCS: {e}")

    temp_lower, temp_upper = [], []
    precip_lower, precip_upper = [], []
    speed_lower, speed_upper = [], []

    for i in range(len(forecast_data['hour'])):
        bounds = ci_bounds.get(str(i), {
            'temp_error_low': 0, 'temp_error_high': 0,
            'precip_error_low': 0, 'precip_error_high': 0,
            'speed_error_low': 0, 'speed_error_high': 0,
        })

        c_temp = forecast_data['temp'][i] if i < len(forecast_data['temp']) else 0
        c_precip = forecast_data['precip'][i] if i < len(forecast_data['precip']) else 0
        c_speed = forecast_data['speed'][i] if i < len(forecast_data['speed']) else 0

        # Lower bound = current forecast + lower bound error (which is negative)
        temp_lower.append(round(c_temp + bounds['temp_error_low']))
        temp_upper.append(round(c_temp + bounds['temp_error_high']))

        precip_lower.append(max(0, min(100, round(c_precip + bounds['precip_error_low']))))
        precip_upper.append(max(0, min(100, round(c_precip + bounds['precip_error_high']))))

        speed_lower.append(max(0, round(c_speed + bounds['speed_error_low'])))
        speed_upper.append(max(0, round(c_speed + bounds['speed_error_high'])))

    forecast_data['temp_ci_lower'] = temp_lower
    forecast_data['temp_ci_upper'] = temp_upper
    forecast_data['precip_ci_lower'] = precip_lower
    forecast_data['precip_ci_upper'] = precip_upper
    forecast_data['speed_ci_lower'] = speed_lower
    forecast_data['speed_ci_upper'] = speed_upper

    return forecast_data

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

FORECAST_NAME_RE = re.compile(r"^forecast-(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})\.json$")

def parse_forecast_blob_time(blob_name):
    m = FORECAST_NAME_RE.match(blob_name)
    if not m:
        return None
    y, mo, d, h, mi = map(int, m.groups())
    return datetime.datetime(y, mo, d, h, mi, tzinfo=HST)

@app.route("/cron/collect-forecast")
def cron_collect_forecast():
    expected_key = os.environ.get("COLLECT_FORECAST_KEY")
    if not expected_key:
        app.logger.error("COLLECT_FORECAST_KEY environment variable is not set")
        return "Server misconfigured", 500

    if request.args.get("key") != expected_key:
        return "Unauthorized", 401

    try:
        data = scrape_forecast()
        saved_data = {
            "hour": data.get("hour", []),
            "temp": data.get("temp", []),
            "precip": data.get("precip", []),
            "speed": data.get("speed", []),
        }

        now_hst = datetime.datetime.now(HST).replace(second=0, microsecond=0)
        blob_path = f"forecast-{now_hst.strftime('%Y-%m-%d-%H-%M')}.json"

        storage_client = storage.Client()
        bucket = storage_client.bucket("waikikiwx")
        bucket.blob(blob_path).upload_from_string(
            json.dumps(saved_data),
            content_type="application/json",
        )
        app.logger.info("Uploaded gs://waikikiwx/%s", blob_path)

        cutoff = now_hst - datetime.timedelta(days=90)
        historical_forecasts = []

        for hblob in bucket.list_blobs(prefix="forecast-"):
            f_time = parse_forecast_blob_time(hblob.name)
            if f_time is None or f_time < cutoff:
                continue

            try:
                hdata = json.loads(hblob.download_as_text())
            except Exception as e:
                app.logger.warning("Skipping unreadable blob %s: %s", hblob.name, e)
                continue

            historical_forecasts.append({"time": f_time, "data": hdata})

        # The just-uploaded forecast is already in list_blobs(); do not append it again.
        # If you later add a real observations feed, build observed_by_target and pass it here.
        ci_data = calculate_ci_from_history(
            historical_forecasts,
            observed_by_target=None,
            coverage=0.50,
            min_samples=50,
        )

        bucket.blob("confidence-intervals.json").upload_from_string(
            json.dumps(ci_data),
            content_type="application/json",
        )
        app.logger.info("Uploaded gs://waikikiwx/confidence-intervals.json")

        return jsonify({"status": "success", "file": f"gs://waikikiwx/{blob_path}"}), 200

    except Exception as e:
        msg = f"Failed to collect and upload forecast: {e}"
        app.logger.exception(msg)
        return jsonify({"error": msg}), 500

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


import json, os, re, requests, datetime, math, collections, tempfile, uuid
from flask import Flask, jsonify, send_from_directory, render_template, request, Response, stream_with_context
from google.cloud import storage
import subprocess, time, signal
from playwright.sync_api import sync_playwright

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
        elif h > prev_h and (h - prev_h) > 12:
            current -= datetime.timedelta(days=1)
        current = current.replace(hour=h)
        times.append(current)
        prev_h = h
    return times

def calculate_ci_from_history(historical_forecasts):
    predictions_by_target = collections.defaultdict(list)
    for hf in historical_forecasts:
        f_time = hf['time']
        data = hf['data']
        hours = data.get('hour', [])
        target_times = get_target_times(f_time, hours)

        for i, t_time in enumerate(target_times):
            temp_val = data['temp'][i] if i < len(data.get('temp', [])) else None
            precip_val = data['precip'][i] if i < len(data.get('precip', [])) else None
            speed_val = data['speed'][i] if i < len(data.get('speed', [])) else None

            predictions_by_target[t_time].append({
                'fetch_time': f_time,
                'lead_index': i,
                'temp': temp_val,
                'precip': precip_val,
                'speed': speed_val,
            })

    errors_by_lead = collections.defaultdict(lambda: {'temp': [], 'precip': [], 'speed': []})

    for t_time, preds in predictions_by_target.items():
        if not preds: continue
        most_recent_pred = max(preds, key=lambda x: x['fetch_time'])

        for p in preds:
            if p == most_recent_pred:
                continue

            lead_idx = p['lead_index']
            if p['temp'] is not None and most_recent_pred['temp'] is not None:
                errors_by_lead[lead_idx]['temp'].append(p['temp'] - most_recent_pred['temp'])
            if p['precip'] is not None and most_recent_pred['precip'] is not None:
                errors_by_lead[lead_idx]['precip'].append(p['precip'] - most_recent_pred['precip'])
            if p['speed'] is not None and most_recent_pred['speed'] is not None:
                errors_by_lead[lead_idx]['speed'].append(p['speed'] - most_recent_pred['speed'])

    ci_bounds = {}

    for lead_idx in range(48):
        lead_errors = errors_by_lead.get(lead_idx, {'temp': [], 'precip': [], 'speed': []})

        ci_bounds[str(lead_idx)] = {
            'temp_error_low': percentile(lead_errors['temp'], 0.25) or 0,
            'temp_error_high': percentile(lead_errors['temp'], 0.75) or 0,
            'precip_error_low': percentile(lead_errors['precip'], 0.25) or 0,
            'precip_error_high': percentile(lead_errors['precip'], 0.75) or 0,
            'speed_error_low': percentile(lead_errors['speed'], 0.25) or 0,
            'speed_error_high': percentile(lead_errors['speed'], 0.75) or 0,
        }

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

        # Error = forecast - truth. Therefore, Truth = forecast - error.
        # Lower bound of Truth = forecast - high_error
        # Upper bound of Truth = forecast - low_error
        temp_lower.append(round(c_temp - bounds['temp_error_high']))
        temp_upper.append(round(c_temp - bounds['temp_error_low']))

        precip_lower.append(max(0, min(100, round(c_precip - bounds['precip_error_high']))))
        precip_upper.append(max(0, min(100, round(c_precip - bounds['precip_error_low']))))

        speed_lower.append(max(0, round(c_speed - bounds['speed_error_high'])))
        speed_upper.append(max(0, round(c_speed - bounds['speed_error_low'])))

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

@app.route('/cron/collect-forecast')
def cron_collect_forecast():
    # Require a simple API key query parameter to prevent unauthorized execution
    expected_key = os.environ.get('COLLECT_FORECAST_KEY')
    if not expected_key:
        app.logger.error("COLLECT_FORECAST_KEY environment variable is not set")
        return "Server misconfigured", 500

    key = request.args.get('key')
    if not key or key != expected_key:
        return "Unauthorized", 401

    try:
        # Fetch the complete forecast dataset
        data = scrape_forecast()

        # We only need specific fields for confidence intervals
        saved_data = {
            'hour': data.get('hour', []),
            'temp': data.get('temp', []),
            'precip': data.get('precip', []),
            'speed': data.get('speed', [])
        }

        # Determine HST time (UTC - 10 hours)
        hst = datetime.timezone(datetime.timedelta(hours=-10))
        now_hst = datetime.datetime.now(hst)

        # Construct the GCS object path: forecast-YYYY-MM-DD-HH-MM.json
        date_str = now_hst.strftime('%Y-%m-%d')
        time_str = now_hst.strftime('%H-%M')
        blob_path = f'forecast-{date_str}-{time_str}.json'

        # Upload to Google Cloud Storage
        storage_client = storage.Client()
        bucket = storage_client.bucket('waikikiwx')
        blob = bucket.blob(blob_path)

        json_payload = json.dumps(saved_data)
        blob.upload_from_string(json_payload, content_type='application/json')

        app.logger.info(f"Successfully uploaded forecast to gs://waikikiwx/{blob_path}")

        # Now compute the confidence intervals
        try:
            blobs = list(bucket.list_blobs(prefix='forecast-'))
            cutoff = datetime.datetime.now() - datetime.timedelta(days=90)

            historical_forecasts = []
            for hblob in blobs:
                m = re.match(r'forecast-(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})\.json', hblob.name)
                if m:
                    y, mth, d, h, mnt = map(int, m.groups())
                    dt = datetime.datetime(y, mth, d, h, mnt)
                    if dt >= cutoff:
                        try:
                            hdata = json.loads(hblob.download_as_string())
                            historical_forecasts.append({'time': dt, 'data': hdata})
                        except Exception as parse_e:
                            pass

            if historical_forecasts:
                # Include the newly saved current forecast so it can be compared to past
                historical_forecasts.append({'time': now_hst.replace(tzinfo=None), 'data': saved_data})
                ci_data = calculate_ci_from_history(historical_forecasts)

                # Save just the derived bounds
                ci_blob = bucket.blob('confidence-intervals.json')
                ci_blob.upload_from_string(json.dumps(ci_data), content_type='application/json')
                app.logger.info(f"Successfully uploaded confidence intervals to gs://waikikiwx/confidence-intervals.json")

        except Exception as ci_err:
            app.logger.error(f"Failed to generate confidence intervals: {ci_err}")

        return jsonify({"status": "success", "file": f"gs://waikikiwx/{blob_path}"}), 200

    except Exception as e:
        msg = f"Failed to collect and upload forecast: {e}"
        app.logger.error(msg)
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

@app.route('/live-stream')
def live_stream():
    expected_key = os.environ.get('COLLECT_FORECAST_KEY')
    if not expected_key:
        app.logger.error("COLLECT_FORECAST_KEY environment variable is not set")
        return "Server misconfigured", 500

    key = request.args.get('cfkey')
    if not key or key != expected_key:
        return "Unauthorized", 401

    try:
        duration_minutes = float(request.args.get('duration', 1))
    except ValueError:
        return "Invalid duration", 400

    stream_key = os.environ.get('YOUTUBE_STREAM_KEY')
    if not stream_key:
        app.logger.error("YOUTUBE_STREAM_KEY environment variable is not set")
        return "YouTube stream key not configured", 500

    def generate():
        log_lines = []
        
        def log_msg(msg):
            timestamp = datetime.datetime.now().isoformat()
            line = f"[{timestamp}] {msg}"
            app.logger.info(line)
            log_lines.append(line)
            return line + "\n"
            
        def get_memory_status():
            try:
                with open('/proc/meminfo', 'r') as f:
                    lines = f.readlines()
                mem_info = {line.split(':')[0]: line.split(':')[1].strip() for line in lines if ':' in line}
                return f"MemAvailable: {mem_info.get('MemAvailable', 'N/A')}, MemTotal: {mem_info.get('MemTotal', 'N/A')}"
            except Exception as e:
                return f"Memory check error: {e}"

        start_time = time.time()
        duration_seconds = duration_minutes * 60

        # We will set up Xvfb, Playwright, and FFmpeg
        xvfb_proc = None
        playwright_context_mgr = None
        playwright_browser = None
        ffmpeg_proc = None
        
        xvfb_log_fd, xvfb_log_path = tempfile.mkstemp(prefix='xvfb_', suffix='.log')
        os.close(xvfb_log_fd)
        ffmpeg_log_fd, ffmpeg_log_path = tempfile.mkstemp(prefix='ffmpeg_', suffix='.log')
        os.close(ffmpeg_log_fd)

        try:
            yield log_msg("Starting live stream process")
            yield log_msg(f"Initial Memory: {get_memory_status()}")
            
            yield log_msg("Starting Xvfb...")
            # Use a random display port to allow concurrent executions
            display_num = str(uuid.uuid4().int % 10000 + 100)
            display = f":{display_num}"
            with open(xvfb_log_path, 'w') as xvfb_log_file:
                xvfb_proc = subprocess.Popen(["Xvfb", display, "-screen", "0", "1920x1080x24"], stdout=xvfb_log_file, stderr=subprocess.STDOUT)
            
            time.sleep(1) # Wait for Xvfb to start
            if xvfb_proc.poll() is not None:
                yield log_msg(f"Failed to start Xvfb on {display}. Exit code: {xvfb_proc.returncode}")
                return

            # Use a specific env dict for playwright rather than modifying global os.environ
            pw_env = os.environ.copy()
            pw_env["DISPLAY"] = display

            yield log_msg("Starting Playwright...")
            try:
                playwright_context_mgr = sync_playwright()
                p = playwright_context_mgr.start()
                playwright_browser = p.chromium.launch(headless=False, env=pw_env, args=['--window-size=1920,1080', '--window-position=0,0', '--no-sandbox'])
                context = playwright_browser.new_context(viewport={"width": 1920, "height": 1080})
                page = context.new_page()

                # Use local URL to capture the site directly
                yield log_msg("Navigating to site...")
                page.goto("http://127.0.0.1:8080/")
                # Wait a few seconds for data to load and render
                time.sleep(5)
            except Exception as pw_err:
                yield log_msg(f"Playwright error: {pw_err}")
                raise

            yield log_msg("Starting FFmpeg stream...")
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "x11grab",
                "-s", "1920x1080",
                "-framerate", "30",
                "-i", display,
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-b:v", "2500k",
                "-maxrate", "2500k",
                "-bufsize", "5000k",
                "-pix_fmt", "yuv420p",
                "-g", "60",
                "-c:a", "aac",
                "-b:a", "128k",
                "-ar", "44100",
                "-f", "flv",
                f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
            ]
            with open(ffmpeg_log_path, 'w') as ffmpeg_log_file:
                ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=ffmpeg_log_file, stderr=subprocess.STDOUT)

            yield log_msg(f"Streaming for {duration_minutes} minutes...")
            while time.time() - start_time < duration_seconds:
                if ffmpeg_proc.poll() is not None:
                    yield log_msg(f"FFmpeg process exited unexpectedly with code: {ffmpeg_proc.returncode}")
                    break
                if xvfb_proc.poll() is not None:
                    yield log_msg(f"Xvfb process exited unexpectedly with code: {xvfb_proc.returncode}")
                    break
                
                elapsed = int(time.time() - start_time)
                if elapsed % 60 < 5:  # Log memory every minute
                    yield log_msg(f"Streaming... {elapsed}s elapsed. {get_memory_status()}")
                else:
                    yield log_msg(f"Streaming... {elapsed}s elapsed.")
                time.sleep(5)

            if xvfb_proc.poll() is None and ffmpeg_proc.poll() is None:
                yield log_msg("Streaming completed successfully.")

        except Exception as e:
            msg = f"Error during live stream: {e}"
            app.logger.error(msg)
            yield log_msg(msg)
        finally:
            log_msg(f"Final Memory: {get_memory_status()}")
            if ffmpeg_proc:
                if ffmpeg_proc.poll() is None:
                    ffmpeg_proc.terminate()
                    try:
                        ffmpeg_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        ffmpeg_proc.kill()
                        ffmpeg_proc.wait()
                log_msg(f"FFmpeg final exit code: {ffmpeg_proc.returncode}")
                
            if playwright_browser:
                try:
                    playwright_browser.close()
                    log_msg("Playwright browser closed.")
                except Exception as e:
                    log_msg(f"Error closing Playwright browser: {e}")
                    
            if playwright_context_mgr:
                try:
                    playwright_context_mgr.stop()
                    log_msg("Playwright context manager stopped.")
                except Exception as e:
                    log_msg(f"Error stopping Playwright context manager: {e}")
                    
            if xvfb_proc:
                if xvfb_proc.poll() is None:
                    xvfb_proc.terminate()
                    try:
                        xvfb_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        xvfb_proc.kill()
                        xvfb_proc.wait()
                log_msg(f"Xvfb final exit code: {xvfb_proc.returncode}")
            
            # Read and append log files
            try:
                with open(xvfb_log_path, 'r') as f:
                    xvfb_out = f.read()
                    log_lines.append("\n--- Xvfb Output ---\n")
                    log_lines.append(xvfb_out if xvfb_out else "(No output)\n")
            except Exception as e:
                log_lines.append(f"\nError reading Xvfb log: {e}\n")
            
            try:
                with open(ffmpeg_log_path, 'r') as f:
                    ffmpeg_out = f.read()
                    log_lines.append("\n--- FFmpeg Output ---\n")
                    log_lines.append(ffmpeg_out if ffmpeg_out else "(No output)\n")
            except Exception as e:
                log_lines.append(f"\nError reading FFmpeg log: {e}\n")

            # Clean up temp files
            for p in [xvfb_log_path, ffmpeg_log_path]:
                try:
                    os.remove(p)
                except OSError:
                    pass
            
            # Upload to GCS
            try:
                client = storage.Client()
                bucket = client.bucket('waikikiwx')
                blob = bucket.blob('live-stream-results.txt')
                blob.upload_from_string("".join(log_lines), content_type='text/plain')
                app.logger.info("Successfully uploaded live-stream-results.txt to GCS")
            except Exception as e:
                app.logger.error(f"Failed to upload live-stream logs to GCS: {e}")

    response = Response(stream_with_context(generate()), mimetype='text/plain')
    response.headers['X-Accel-Buffering'] = 'no'
    return response

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

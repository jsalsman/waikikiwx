import re
import requests
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder='.')

NWS_URL = (
    'https://forecast.weather.gov/MapClick.php'
    '?lat=21.3069&lon=-157.8583&unit=0&lg=english&FcstType=digital'
)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.weather.gov/',
    'Connection': 'keep-alive',
}

HOURS_WANTED = 48


def extract_row(line, label, n):
    suffix = r'.*?<b>([^<]+)</b>' * n
    pattern = re.compile(label + suffix, re.DOTALL)
    m = pattern.search(line)
    return list(m.groups()) if m else ['--'] * n


def scrape_forecast():
    # Try up to 3 times in case NWS is flaky
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(
                NWS_URL,
                headers=HEADERS,
                timeout=20,
                allow_redirects=True,
            )
            resp.raise_for_status()

            lines = [l for l in resp.text.splitlines() if '<b>Date' in l]
            if not lines:
                raise ValueError(
                    f'Forecast table not found (HTTP {resp.status_code}, '
                    f'{len(resp.text)} bytes)'
                )

            out = {'hour': [], 'direction': [], 'speed': [], 'temp': [], 'precip': []}

            for line in lines:
                remaining = HOURS_WANTED - len(out['hour'])
                if remaining <= 0:
                    break
                n = min(remaining, 24)

                hours = extract_row(line, 'Hour', n)
                if not hours or hours[0] == '--':
                    continue

                out['hour']     .extend(int(h) for h in hours)
                out['direction'].extend(extract_row(line, 'Wind Dir',                n))
                out['speed']    .extend(int(v) for v in extract_row(line, 'Surface Wind',            n))
                out['temp']     .extend(int(v) for v in extract_row(line, 'Temperature',             n))
                out['precip']   .extend(int(v) for v in extract_row(line, 'Precipitation Potential', n))

            if not out['hour']:
                raise ValueError('Regex extracted no data from NWS response')

            return out

        except (requests.RequestException, ValueError) as e:
            last_err = e
            continue

    raise last_err


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
    except (ValueError, re.error) as e:
        msg = f'Parse error: {e}'
        app.logger.error(msg)
        return jsonify({'error': msg}), 502


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

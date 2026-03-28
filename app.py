import requests
from flask import Flask, send_from_directory, Response

app = Flask(__name__, static_folder='.')

NWS_URL = (
    'https://forecast.weather.gov/MapClick.php'
    '?lat=21.3069&lon=-157.8583&unit=0&lg=english&FcstType=digital'
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.weather.gov/',
}

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/forecast')
def forecast():
    try:
        r = requests.get(NWS_URL, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        return Response(f'Upstream error: {e}', status=502)
    return Response(r.text, status=200, mimetype='text/html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

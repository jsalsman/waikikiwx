import requests

url = "https://api.weather.gov/icons/land/day/rain_showers,20?size=small"

headers = {
    "User-Agent": "WaikikiWx (https://github.com/jsalsman/waikikiwx, jsalsman@gmail.com)"
}

try:
    response = requests.get(url, headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
except Exception as e:
    print(f"Error: {e}")

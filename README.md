# waikikiwx

Single-page live 48-hour weather forecast dashboard for Waikiki, Oahu, Hawaii.

[![Try on Google Cloud Run](https://img.shields.io/badge/Try_on_Google_Cloud_Run-darkgreen)](https://waikikiwx.live/)
[![App health](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fwaikikiwx.live%2Fhealth-check&query=%24.status&label=App%20health&color=brightgreen&labelColor=indigo)](https://waikikiwx.live/health-check)
[![Python version 3.14](https://img.shields.io/badge/Python-3.14-blue?logo=python)](https://www.python.org/downloads/)
[![Flask version 3.1](https://img.shields.io/badge/Flask-3.1-black?logo=flask)](https://flask.palletsprojects.com/)
[![MIT License](https://img.shields.io/badge/License-MIT-brightgreen)](https://opensource.org/licenses/MIT)
[![Donate](https://img.shields.io/badge/Donate-gold?logo=paypal)](https://paypal.me/jsalsman)

![Screenshot of the project](screenshot.png)

## Local run

```bash
python -m pip install -r requirements.txt
python app.py
```

Then open:

- `http://127.0.0.1:8080/` for the dashboard
- `http://127.0.0.1:8080/debug` to inspect a raw NOAA/NWS period sample
- `http://127.0.0.1:8080/forecast` for JSON consumed by the front-end
- `http://127.0.0.1:8080/goes-airmass` for latest GOES West HI Air Mass GIF URL
- `http://127.0.0.1:8080/health-check` for application health status
- `http://127.0.0.1:8080/icon?url=...` for NWS icon proxying

## What is shown

- 48 hours of hourly forecast data from `api.weather.gov`
- Header “now” values (Hour, Wind Dir, Wind mph, Temp, Precip)
- Current `shortForecast` summary text below the five header metrics
- Current hourly forecast icon shown left of the **WAIKIKI** title
- The same current icon is applied as the browser favicon dynamically
- GOES West Hawaii Air Mass animation overlay over the lower (25–48h) table zone

## Quick validation checklist

1. Start app and request `/forecast`; confirm JSON includes:
   - `hour`, `direction`, `speed`, `temp`, `precip`
   - `icon` and `short` arrays for hourly icon + shortForecast text
2. Load `/` and view source/DOM to confirm:
   - `<img id="loc-icon">` exists in header left of title
   - `<div id="now-summary">` exists under the center metric row
   - `<link rel="icon">` updates to current hour `icon` URL after refresh
3. Confirm mobile portrait layout stacks charts first, then tables.

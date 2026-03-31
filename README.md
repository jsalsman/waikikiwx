# waikikiwx

Single-page live 48-hour weather forecast dashboard for Waikiki, Honolulu, Oahu, Hawaii.

[![Try it on Google Cloud Run](https://img.shields.io/badge/Try_it_on_Google_Cloud_Run-darkgreen)](https://waikikiwx.live/)
[![App health](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fwaikikiwx.live%2Fhealth-check&query=%24.status&label=App%20health&color=brightgreen&labelColor=indigo)](https://waikikiwx.live/health-check)
[![Python version 3.14](https://img.shields.io/badge/Python-3.14-blue?logo=python)](https://www.python.org/downloads/)
[![Flask version 3.1](https://img.shields.io/badge/Flask-3.1-black?logo=flask)](https://flask.palletsprojects.com/)
[![MIT License](https://img.shields.io/badge/License-MIT-brightgreen)](https://opensource.org/licenses/MIT)
[![Donate](https://img.shields.io/badge/Donate-gold?logo=paypal)](https://paypal.me/jsalsman)

URL: https://WaikikiWX.live

![Screenshot of the project](screenshot.png)

## What is shown

- 48 hours of hourly forecast data from `api.weather.gov`
- Header “now” values (Hour, Wind Dir, Wind mph, Temp, Precip)
- Current `shortForecast` summary text below the five header metrics
- Current hourly forecast icon shown left of the **WAIKIKI** title
- The same current icon is applied as the browser favicon dynamically
- GOES West Hawaii Air Mass animation overlay over the lower (25–48h) table zone

The primary data source for this dashboard is the National Weather Service (NWS) API (`api.weather.gov`). By querying the specific grid coordinates for Waikiki, the application retrieves highly localized, hourly forecast data. This includes quantitative metrics such as expected temperature, wind speed and direction, wind gusts, apparent temperature (incorporating heat index and wind chill), precipitation probability, and expected precipitation amount. The NWS API also supplies qualitative data in the form of `shortForecast` text summaries and corresponding weather icons for each forecasted hour.

In addition to the localized forecast, the dashboard integrates satellite imagery from the NOAA GOES West satellite, specifically sourced from the NESDIS STAR (Center for Satellite Applications and Research) content delivery network. The application dynamically fetches the latest "Air Mass"-colored animated GIFs for the Hawaii and Tropical Pacific West sectors. Air Mass imagery highlights the temperature and moisture characteristics of different air masses, making it easier to visually analyze large-scale weather systems, fronts, and atmospheric dynamics leading to precipitation.

These distinct data streams are synthesized into a comprehensive and unified visual display. The numerical NWS data is rendered into precise hourly tables and SVG graphs, where primary metrics (temperature, precipitation probability, and wind speed) are shown as solid lines or solid bars, and secondary metrics (apparent temperature, expected precipitation amount, and wind gust speed) are depicted as dashed lines or dashed overlays. The GOES Air Mass satellite animations are strategically applied as semi-transparent, looping background overlays on top of the lower table zone (representing forecast hours 25 through 48), providing users with a macro-level visual context of the atmospheric conditions.

## Local run

```bash
python -m pip install -r requirements.txt
python app.py
```

Then open:

- `http://127.0.0.1:8080/` for the dashboard
- `http://127.0.0.1:8080/forecast` for JSON consumed by the front-end
- `http://127.0.0.1:8080/goes-airmass` for latest GOES West HI Air Mass GIF URL
- `http://127.0.0.1:8080/health-check` for application health status
- `http://127.0.0.1:8080/icon?url=...` for NWS icon proxying
- `http://127.0.0.1:8080/screenshot.png` for the open graph screenshot image
- `http://127.0.0.1:8080/robots.txt` for crawler rules

## Quick validation checklist

1. Start app and request `/forecast`; confirm JSON includes:
   - `hour`, `direction`, `speed`, `temp`, `precip`
   - `icon` and `short` arrays for hourly icon + shortForecast text
2. Load `/` and view source/DOM to confirm:
   - `<img id="loc-icon">` exists in header left of title
   - `<div id="now-summary">` exists under the center metric row
   - `<link rel="icon">` updates to current hour `icon` URL after refresh
3. Confirm mobile portrait layout stacks charts first, then tables.

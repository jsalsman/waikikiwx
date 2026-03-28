# waikikiwx

Single-page live 48-hour weather forecast dashboard for Waikiki, Oahu, Hawaii.

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

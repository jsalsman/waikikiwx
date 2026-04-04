# waikikiwx

Single-page live 48-hour weather forecast dashboard for Waikiki, Honolulu, Oahu, Hawaii.

[![Try it on Google Cloud Run](https://img.shields.io/badge/Try_it_on_Google_Cloud_Run-darkgreen)](https://waikikiwx.live/)
[![App health](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fwaikikiwx.live%2Fhealth-check&query=%24.status&label=App%20health&color=brightgreen&labelColor=indigo)](https://waikikiwx.live/health-check)
[![Build status](https://img.shields.io/github/check-runs/jsalsman/waikikiwx/main?label=Build&labelColor=indigo)](https://console.cloud.google.com/cloud-build/builds)
[![weather.gov API version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.weather.gov%2Fopenapi.json&query=%24.info.version&label=weather.gov%20API&color=blue)](https://www.weather.gov/documentation/services-web-api)
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

The primary data source for this dashboard is the National Weather Service (NWS) API (`api.weather.gov`). By querying the specific grid coordinates for Waikiki, the application retrieves highly localized, hourly forecast data. This includes quantitative metrics such as expected temperature, wind speed and direction, wind gusts, apparent temperature (incorporating heat index and wind chill), precipitation probability, and expected precipitation amount. Notably, the standard NWS data does not calculate wind chill for temperatures above 50°F, and the standard formula mathematically fails to reduce perceived temperatures in warm conditions; to compensate for this and provide a more accurate localized apparent temperature, the dashboard fetches grid `relativeHumidity` and automatically applies the Australian Apparent Temperature formula to apparent temperatures between 50°F and 80°F whenever wind is present. The NWS API also supplies qualitative data in the form of `shortForecast` text summaries and corresponding weather icons for each forecasted hour.

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
- `http://127.0.0.1:8080/cron/collect-forecast?key=YOUR_SECRET_KEY` for triggering the GCS forecast export

## Live YouTube Streaming

The dashboard supports live streaming directly to YouTube via RTMPS by using the standalone `stream.py` script.

### Executing as a Cloud Run Job
To run the live stream automatically without managing infrastructure, you can package `stream.py` and its dependencies into a container image and deploy it as a Cloud Run Job. Note that running an isolated headless browser and FFmpeg encoding is resource-intensive; the Job requires at least **2GB of memory**.

1. Build a container image using a custom Dockerfile that installs system dependencies (`ffmpeg`, `xvfb`), Playwright browsers, and copies `stream.py`. An example `stream.Dockerfile` might look like this:

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy
WORKDIR /app
RUN apt-get update && apt-get install -y ffmpeg xvfb && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt playwright google-cloud-storage
COPY stream.py ./
CMD ["python", "stream.py", "--duration", "1"]
```

2. Push the image to Google Artifact Registry:
   ```bash
   # Set your Google Cloud project ID and region
   export PROJECT_ID="your-project-id"
   export REGION="us-west1"
   export ARTIFACT_REPO="waikikiwx-repo"

   # Authenticate Docker to Artifact Registry
   gcloud auth configure-docker ${REGION}-docker.pkg.dev

   # Build and push the image using standard docker commands
   docker build -f stream.Dockerfile -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/waikikiwx-stream:latest .
   docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/waikikiwx-stream:latest
   ```

3. Create a Cloud Run Job using the pushed image:
   ```bash
   export YOUTUBE_STREAM_KEY="your-stream-key"

   gcloud run jobs create waikikiwx-stream-job \
     --image ${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/waikikiwx-stream:latest \
     --region ${REGION} \
     --memory 2Gi \
     --set-env-vars YOUTUBE_STREAM_KEY=${YOUTUBE_STREAM_KEY} \
     --task-timeout 5m \
     --max-retries 0
   ```
   *Note: Ensure the service account running the job has write access to the `waikikiwx` Google Cloud Storage bucket so it can save logs.*

4. Create a Google Cloud Scheduler job to trigger your Cloud Run Job periodically (e.g., every 10 minutes):
   ```bash
   gcloud scheduler jobs create http waikikiwx-stream-trigger \
     --location ${REGION} \
     --schedule "*/10 * * * *" \
     --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/waikikiwx-stream-job:run" \
     --http-method POST \
     --oauth-service-account-email "your-service-account@${PROJECT_ID}.iam.gserviceaccount.com"
   ```

The `stream.py` script starts an Xvfb virtual display, opens a Playwright browser window pointing to `https://waikikiwx.live/`, and uses FFmpeg to stream the visual display directly to the YouTube RTMPS endpoint. It will also concatenate all logs and upload them to [`gs://waikikiwx/live-stream-results.txt`](https://storage.googleapis.com/waikikiwx/live-stream-results.txt).

## Historical Data Collection

The application includes a specialized endpoint (`/cron/collect-forecast?key=YOUR_SECRET_KEY`) designed to periodically save forecast snapshots to a Google Cloud Storage bucket (`waikikiwx`). This historical dataset will eventually be used to compute 50% confidence intervals for temperature, precipitation probability, and wind speed.

### Configuration
1. Set the `COLLECT_FORECAST_KEY` environment variable in your Google Cloud Run service to a secure, random string (e.g., `YOUR_SECRET_KEY`).
2. The service account running the Cloud Run application must have write access to the `waikikiwx` GCS bucket.

### Automation via Google Cloud Scheduler
To automate this collection using [Google Cloud Scheduler](https://cloud.google.com/scheduler/docs/creating):
1. Create a new Cloud Scheduler job.
2. Set the frequency to every 10 minutes (e.g., `*/10 * * * *`).
3. Set the target type to HTTP and the URL to `https://waikikiwx.live/cron/collect-forecast?key=YOUR_SECRET_KEY` (replacing `YOUR_SECRET_KEY` with the exact string you used for the `COLLECT_FORECAST_KEY` environment variable).

The endpoint saves a JSON file for each execution at `gs://waikikiwx/forecast-YYYY-MM-DD-HH-MM.json` (using Hawaii-Aleutian Standard Time). See https://storage.googleapis.com/waikikiwx/ for a listing in XML.

### Forecast Confidence Intervals

The historical dataset collected by the `/cron/collect-forecast` endpoint is used to compute historical forecast errors and generate 50% confidence bounds for temperature, precipitation probability, and wind speed.

#### Statistical Goals and Assumptions

The statistical goal is to quantify the historical uncertainty of the weather forecast at each lead time (0 to 47 hours ahead). By analyzing past forecast errors, the system provides users with a realistic prediction interval alongside the deterministic forecast, allowing them to gauge the reliability of the predicted conditions.

The method assumes:
1. **Proxy Observations:** In the absence of a verified, real-time observational data feed, the analysis uses the *lead-0 (current conditions)* values from subsequent forecast snapshots as the "realized" proxy truth for that target hour.
2. **Persistence of Error Distributions:** The distribution of forecast errors (observed minus forecasted) from the recent past (last 90 days) is representative of the expected errors for current forecasts.

#### Data Structure and Meaning

During each run of `/cron/collect-forecast`, the script calculates the 50% confidence intervals (the 25th and 75th percentiles of the error distribution) for each of the 48 lead hours. The result is saved to [`gs://waikikiwx/confidence-intervals.json`](https://storage.googleapis.com/waikikiwx/confidence-intervals.json).

The resulting JSON file contains a dictionary keyed by the lead hour index (0 to 47). Each hour contains three sets of error bounds corresponding to the three forecast variables:
- `temp_error_low`, `temp_error_high`
- `precip_error_low`, `precip_error_high`
- `speed_error_low`, `speed_error_high`

A 50% confidence interval means there is a 50% probability that the actual weather outcome will fall within these bounds, based on historical error distributions. If a specific lead hour does not have a minimum number of samples (e.g., 50), the system dynamically pools errors from neighboring lead times to ensure a robust distribution.

#### Visualization

The confidence intervals are downloaded by the backend and merged into the `/forecast` API payload as `*_ci_lower` and `*_ci_upper` arrays.

On the front end, these intervals are plotted as shaded regions on the SVG graphs. The graphing function overlays a semi-transparent band bounded by the lower and upper confidence limits. This shaded area gives users an immediate visual indication of the forecast's confidence level—a wider shaded band signifies higher uncertainty, while a narrow band indicates high confidence based on recent historical performance.

## Quick validation checklist

1. Start app and request `/forecast`; confirm JSON includes:
   - `hour`, `direction`, `speed`, `temp`, `precip`
   - `icon` and `short` arrays for hourly icon + shortForecast text
2. Load `/` and view source/DOM to confirm:
   - `<img id="loc-icon">` exists in header left of title
   - `<div id="now-summary">` exists under the center metric row
   - `<link rel="icon">` updates to current hour `icon` URL after refresh
3. Confirm mobile portrait layout stacks charts first, then tables.

## Repository file tree and component descriptions

```text
waikikiwx/
├── app.py                  # Flask application: routes, upstream API fetch logic, parsing, and JSON/template responses
├── index.html              # Single-page Jinja template containing all markup, styles, and dashboard client-side logic
├── Dockerfile              # Container build definition for production Cloud Run execution with Gunicorn
├── cloudbuild.yaml         # Google Cloud Build pipeline for smoke tests, image build/push, and Cloud Run deploy
├── requirements.txt        # Python dependency lock list used locally, in Docker, and in CI
├── tests/
│   ├── test_app.py         # Backend/unit-style endpoint coverage using Flask test_client + API mocking
│   └── test_playwright.py  # End-to-end Playwright UI validation with screenshot/video artifacts
├── screenshot.png          # Open Graph/social preview image served by the app
├── stream.py               # Standalone script for live streaming dashboard to YouTube
├── LICENSE                 # MIT license terms for project usage and distribution
├── README.md               # Project overview, usage, validation steps, and architecture notes
└── AGENTS.md               # Repository automation instructions used by development agents
```

`app.py` is the backend control plane for the whole project. It initializes Flask, defines canonical Waikiki coordinates, discovers the weather.gov forecast/grid endpoints from the points API, and normalizes heterogeneous upstream data into a consistent 48-hour hourly payload consumed by the front end. It includes helper parsing utilities for wind strings and ISO-8601 valid-time windows, merges hourly and grid datasets (temperature, apparent temperature, gusts, precipitation probability, and quantitative precipitation), and applies sensible fallback behavior when sparse values are missing. It also provides operational and support endpoints (`/health-check`, `/icon`, `/goes-airmass`, `/screenshot.png`, `/robots.txt`, and `/cron/collect-forecast`) in addition to serving `/` and `/forecast`, so the single module effectively handles rendering, API aggregation, and proxy-safe access patterns in one place.

The `index.html` template is intentionally a self-contained UI surface: Jinja injects initial forecast data while vanilla JavaScript performs refresh/update behavior, DOM binding, icon updates, GOES overlay swapping, and SVG graph drawing without any framework dependency. Its CSS uses a responsive, terminal-inspired layout with flexbox, viewport-aware scaling variables, and explicit mobile portrait behavior so the same document works on phones, tablets, and desktop displays. The page combines four stacked forecast table blocks, three chart panels, and a dynamic “now” status strip, while also managing favicon updates and weather icon rendering for immediate visual context. In short, this file is both the view layer and the client runtime for the dashboard.

The `Dockerfile` packages the app for production in a minimal Python 3.14 slim image, prioritizing predictable startup and safer runtime defaults. It sets Python environment flags for cleaner container behavior, creates and runs as a non-root `appuser`, installs requirements in a cache-friendly layer, and copies only the files needed at runtime (`app.py`, `index.html`, `screenshot.png`). The container exposes port 8080 and starts Gunicorn with 3 workers and a bounded timeout. The main application is extremely lightweight, requiring only 512MB of memory for the 3 concurrent Gunicorn workers. This aligns with Cloud Run expectations while preserving a simple image build path that mirrors local behavior.

`cloudbuild.yaml` defines the CI/CD pipeline from validation through deployment. The first step (`Smoketests`) runs inside `python:3.14-slim` and does more than a superficial ping: it compiles all Python files, creates a virtual environment, installs dependencies, starts the Flask development server, installs `curl`, and verifies that the homepage response contains an expected sentinel string (`and/or fork:`), failing fast with response diagnostics if not. After this gate passes, the pipeline builds a no-cache Docker image, pushes it to Artifact Registry, and updates the Cloud Run service in `us-west1` using commit-based image tags and deployment labels for traceability. That smoketests stage is therefore the quality gate that protects the deploy stages from shipping obviously broken application behavior.

`stream.py` is a standalone utility isolated from the main application to handle continuous live streaming. It launches an Xvfb virtual display to simulate a desktop environment and runs a headless Chromium browser via Playwright Sync API to load the live dashboard (`https://waikikiwx.live/`). It then leverages FFmpeg to capture the X11 screen buffer and stream it as an RTMPS feed to YouTube Live. It handles robust isolation for these subprocesses, monitors memory usage over its execution window to prevent OOM errors, and uploads the aggregate execution and subprocess logs to a Google Cloud Storage bucket ([`gs://waikikiwx/live-stream-results.txt`](https://storage.googleapis.com/waikikiwx/live-stream-results.txt)) for later inspection. This separation of concerns ensures that heavy video-encoding tasks do not degrade the performance of the main web application.

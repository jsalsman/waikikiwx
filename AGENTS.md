# AGENTS.md

## Scope
These instructions apply to the entire repository.

## Architecture
- The project is a weather dashboard using a Python Flask backend (`app.py`) and a single-file frontend (`index.html`) utilizing Jinja templates, vanilla JavaScript, and CSS flexbox.

## Testing workflow
1. Install dependencies before runtime checks:
   - `python -m pip install -r requirements.txt`
2. Run basic syntax check:
   - `python -m py_compile app.py`
3. Run Flask endpoint sanity check using `app.test_client()` for:
   - `/` (HTML)
   - `/forecast`
   - `/goes-airmass`
   - `/health-check`
   - `/icon`
   - `/screenshot.png`
   - `/robots.txt`
4. Validate HTML output (not only JSON):
   - Inspect returned HTML from `/` and ensure key UI nodes exist (`loc-icon`, `now-summary`, `tbl-col`, charts SVG ids).
   - Confirm favicon link is present and updated in runtime JS using current forecast icon URL.
5. Visual Verification:
   - When modifying the frontend UI, serve the app (e.g., using `gunicorn`), use Playwright to capture the changes, and visually inspect the results using the `frontend_verification_instructions` tool before committing.

## Pre-Commit and Cleanup
- Ensure the workspace is cleaned of temporary test scripts, unneeded dependencies (e.g., `node_modules`, `package.json` for ad-hoc tests), cache directories (e.g., `__pycache__`), and local log files (e.g., `gunicorn.log`) before completing pre-commit steps.

## Notes
- Prefer concise patches and keep styling/JS in `index.html` unless a larger refactor is requested.
- If tests cannot be run because dependencies are missing, install from `requirements.txt` first.

# AGENTS.md

## Scope
These instructions apply to the entire repository.

## Testing workflow
1. Install dependencies before runtime checks:
   - `python -m pip install -r requirements.txt`
2. Run basic syntax check:
   - `python -m py_compile app.py`
3. Run Flask endpoint sanity check using `app.test_client()` for:
   - `/forecast`
   - `/goes-airmass`
   - `/` (HTML)
4. Validate HTML output (not only JSON):
   - Inspect returned HTML from `/` and ensure key UI nodes exist (`loc-icon`, `now-summary`, `tbl-col`, charts SVG ids).
   - Confirm favicon link is present and updated in runtime JS using current forecast icon URL.
   - If you have a `browser_container` you can use that to make a screenshot.

## Notes
- Prefer concise patches and keep styling/JS in `index.html` unless a larger refactor is requested.
- If tests cannot be run because dependencies are missing, install from `requirements.txt` first.

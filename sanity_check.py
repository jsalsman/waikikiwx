from app import app
import re

client = app.test_client()

# Check endpoints
for ep in ['/forecast', '/goes-airmass', '/']:
    res = client.get(ep)
    print(f"Endpoint {ep} Status: {res.status_code}")

# Check HTML elements
html_res = client.get('/')
html_content = html_res.data.decode('utf-8')

elements = [
    'id="loc-icon"',
    'id="now-summary"',
    'id="tbl-col"',
    'id="cTemp"',
    'id="cPrecip"',
    'id="cWind"',
    'link rel="icon"'
]

for el in elements:
    if el in html_content:
        print(f"Found {el}")
    else:
        print(f"MISSING {el}")

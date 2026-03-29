from playwright.sync_api import sync_playwright
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # log console messages to debug icon loading
        page.on("console", lambda msg: print(f"Console: {msg.text}"))
        page.on("pageerror", lambda exc: print(f"Uncaught exception: {exc}"))
        page.on("requestfailed", lambda req: print(f"Request failed: {req.url} - {req.failure}"))

        page.goto('http://127.0.0.1:8080')
        print("Waiting for data to load...")
        time.sleep(15) # 15 seconds to allow polling to complete

        page.screenshot(path="verification_layout.png")
        browser.close()

run()

import sys
import uuid
import os
from playwright.sync_api import sync_playwright

def verify():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})
        page.goto("http://127.0.0.1:8080/")
        page.wait_for_timeout(3000)

        screenshot_dir = "/home/jules/verification/screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshot_dir, "verification_fixed2.png")
        page.screenshot(path=screenshot_path)
        print("Screenshot saved to", screenshot_path)
        browser.close()

if __name__ == "__main__":
    verify()

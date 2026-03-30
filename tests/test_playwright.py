import unittest
import os
import time
import subprocess
import requests
from playwright.sync_api import sync_playwright

class PlaywrightTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure verification directory exists
        os.makedirs('tests/verification', exist_ok=True)

        # Start the app server in the background
        env = os.environ.copy()
        # Set a different port if needed, but the requirements use 8080
        cls.server_process = subprocess.Popen(['python', 'app.py'], env=env)

        # Wait for the server to become available
        for _ in range(10):
            try:
                # We expect the server to be listening on port 8080
                requests.get('http://127.0.0.1:8080/health-check', timeout=2)
                break
            except requests.exceptions.RequestException:
                time.sleep(1)
        else:
            cls.server_process.kill()
            raise RuntimeError("Server did not start in time")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.context = cls.browser.new_context()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'context') and cls.context:
            cls.context.close()
        if hasattr(cls, 'browser') and cls.browser:
            cls.browser.close()
        if hasattr(cls, 'playwright') and cls.playwright:
            cls.playwright.stop()
        if hasattr(cls, 'server_process') and cls.server_process:
            cls.server_process.terminate()
            cls.server_process.wait()

    def test_ui_elements(self):
        page = self.context.new_page()
        page.goto('http://127.0.0.1:8080/')

        # Assert title
        self.assertIn("Waikiki Weather", page.title())

        # Assert key UI nodes exist
        self.assertTrue(page.locator('#loc-icon').is_visible())
        self.assertTrue(page.locator('#now-summary').is_visible())
        self.assertTrue(page.locator('.ftr-fork').is_visible())

        # Check that the fork link contains the expected text
        fork_text = page.locator('.ftr-fork').inner_text()
        self.assertIn("and/or fork:", fork_text)

        # Take a screenshot for verification
        page.screenshot(path='tests/verification/screenshot.png')
        page.close()

    def test_video_capture(self):
        # Create a new context specifically for video recording
        context = self.browser.new_context(record_video_dir="tests/verification/")
        page = context.new_page()
        page.goto('http://127.0.0.1:8080/')

        # Wait for 30 seconds to capture the movie
        page.wait_for_timeout(30000)

        # Close the context to ensure the video is saved
        context.close()

    def test_mobile_screenshot(self):
        # Create a new context with a mobile viewport
        context = self.browser.new_context(
            viewport={'width': 375, 'height': 812},
            is_mobile=True,
            has_touch=True
        )
        page = context.new_page()
        page.goto('http://127.0.0.1:8080/')

        # Take a mobile screenshot for verification
        page.screenshot(path='tests/verification/mobile_screenshot.png')
        context.close()

if __name__ == '__main__':
    unittest.main()

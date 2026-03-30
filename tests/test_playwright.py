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

if __name__ == '__main__':
    unittest.main()

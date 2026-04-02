import argparse
import datetime
import logging
import os
import subprocess
import time
import tempfile
import uuid
import sys
from google.cloud import storage

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def get_memory_status():
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
        mem_info = {line.split(':')[0]: line.split(':')[1].strip() for line in lines if ':' in line}
        return f"MemAvailable: {mem_info.get('MemAvailable', 'N/A')}, MemTotal: {mem_info.get('MemTotal', 'N/A')}"
    except Exception as e:
        return f"Memory check error: {e}"

def main():
    parser = argparse.ArgumentParser(description="Live stream Waikiki Weather to YouTube")
    parser.add_argument("--duration", type=float, default=1.0, help="Duration of the stream in minutes")
    args = parser.parse_args()

    duration_minutes = args.duration
    duration_seconds = duration_minutes * 60

    stream_key = os.environ.get('YOUTUBE_STREAM_KEY')
    if not stream_key:
        logging.error("YOUTUBE_STREAM_KEY environment variable is not set")
        sys.exit(1)

    log_lines = []
    def log_msg(msg):
        timestamp = datetime.datetime.now().isoformat()
        line = f"[{timestamp}] {msg}"
        logging.info(msg)
        log_lines.append(line + "\n")

    start_time = time.time()

    xvfb_proc = None
    playwright_proc = None
    ffmpeg_proc = None

    xvfb_log_fd, xvfb_log_path = tempfile.mkstemp(prefix='xvfb_', suffix='.log')
    os.close(xvfb_log_fd)
    ffmpeg_log_fd, ffmpeg_log_path = tempfile.mkstemp(prefix='ffmpeg_', suffix='.log')
    os.close(ffmpeg_log_fd)
    pw_script_fd, pw_script_path = tempfile.mkstemp(prefix='pw_script_', suffix='.py')
    os.close(pw_script_fd)
    pw_log_fd, pw_log_path = tempfile.mkstemp(prefix='pw_log_', suffix='.log')
    os.close(pw_log_fd)

    try:
        log_msg("Starting live stream process")
        log_msg(f"Initial Memory: {get_memory_status()}")

        log_msg("Starting Xvfb...")
        display_num = str(uuid.uuid4().int % 10000 + 100)
        display = f":{display_num}"
        with open(xvfb_log_path, 'w') as xvfb_log_file:
            xvfb_proc = subprocess.Popen(["Xvfb", display, "-screen", "0", "1920x1080x24"], stdout=xvfb_log_file, stderr=subprocess.STDOUT)

        time.sleep(1)
        if xvfb_proc.poll() is not None:
            log_msg(f"Failed to start Xvfb on {display}. Exit code: {xvfb_proc.returncode}")
            return

        pw_env = os.environ.copy()
        pw_env["DISPLAY"] = display

        log_msg("Starting Playwright (isolated process)...")
        pw_script_content = f"""
from playwright.sync_api import sync_playwright
import time

def on_console(msg):
    print(f"BROWSER CONSOLE [{{msg.type}}]: {{msg.text}}", flush=True)

def on_pageerror(err):
    print(f"BROWSER ERROR: {{err}}", flush=True)

try:
    print("Playwright script starting...", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=['--window-size=1920,1080', '--window-position=0,0', '--no-sandbox'])
        print("Browser launched.", flush=True)
        context = browser.new_context(viewport={{"width": 1920, "height": 1080}})
        page = context.new_page()

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

        print("Navigating to https://waikikiwx.live/...", flush=True)
        response = page.goto("https://waikikiwx.live/")
        print(f"Page loaded with status: {{response.status if response else 'Unknown'}}", flush=True)
        print(f"Page title: {{page.title()}}", flush=True)

        print("Holding browser open for stream...", flush=True)
        time.sleep({duration_seconds + 300})
except Exception as e:
    print("Playwright error:", e, flush=True)
"""
        with open(pw_script_path, "w") as f:
            f.write(pw_script_content)

        try:
            with open(pw_log_path, "w") as pw_log_file:
                playwright_proc = subprocess.Popen(["python", pw_script_path], env=pw_env, stdout=pw_log_file, stderr=subprocess.STDOUT)
            time.sleep(5)
        except Exception as pw_err:
            log_msg(f"Playwright subprocess launch error: {pw_err}")
            raise

        log_msg("Starting FFmpeg stream...")
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "x11grab",
            "-s", "1920x1080",
            "-framerate", "30",
            "-i", display,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-b:v", "2500k",
            "-maxrate", "2500k",
            "-bufsize", "5000k",
            "-pix_fmt", "yuv420p",
            "-g", "60",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-f", "flv",
            f"rtmps://a.rtmp.youtube.com:443/live2/{stream_key}"
        ]
        with open(ffmpeg_log_path, 'w') as ffmpeg_log_file:
            ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=ffmpeg_log_file, stderr=subprocess.STDOUT)

        log_msg(f"Streaming for {duration_minutes} minutes...")
        while time.time() - start_time < duration_seconds:
            if ffmpeg_proc.poll() is not None:
                log_msg(f"FFmpeg process exited unexpectedly with code: {ffmpeg_proc.returncode}")
                break
            if xvfb_proc.poll() is not None:
                log_msg(f"Xvfb process exited unexpectedly with code: {xvfb_proc.returncode}")
                break

            elapsed = int(time.time() - start_time)
            if elapsed % 60 < 5:
                log_msg(f"Streaming... {elapsed}s elapsed. {get_memory_status()}")
            time.sleep(5)

        if xvfb_proc.poll() is None and ffmpeg_proc.poll() is None:
            log_msg("Streaming completed successfully.")

    except Exception as e:
        msg = f"Error during live stream: {e}"
        logging.error(msg)
        log_msg(msg)
    finally:
        log_msg(f"Final Memory: {get_memory_status()}")
        if ffmpeg_proc:
            if ffmpeg_proc.poll() is None:
                ffmpeg_proc.terminate()
                try:
                    ffmpeg_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ffmpeg_proc.kill()
                    ffmpeg_proc.wait()
            log_msg(f"FFmpeg final exit code: {ffmpeg_proc.returncode}")

        if playwright_proc:
            if playwright_proc.poll() is None:
                playwright_proc.terminate()
                try:
                    playwright_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    playwright_proc.kill()
                    playwright_proc.wait()
            log_msg(f"Playwright final exit code: {playwright_proc.returncode}")

        if xvfb_proc:
            if xvfb_proc.poll() is None:
                xvfb_proc.terminate()
                try:
                    xvfb_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    xvfb_proc.kill()
                    xvfb_proc.wait()
            log_msg(f"Xvfb final exit code: {xvfb_proc.returncode}")

        try:
            with open(xvfb_log_path, 'r') as f:
                xvfb_out = f.read()
                log_lines.append("\n--- Xvfb Output ---\n")
                log_lines.append(xvfb_out if xvfb_out else "(No output)\n")
        except Exception as e:
            log_lines.append(f"\nError reading Xvfb log: {e}\n")

        try:
            with open(ffmpeg_log_path, 'r') as f:
                ffmpeg_out = f.read()
                log_lines.append("\n--- FFmpeg Output ---\n")
                log_lines.append(ffmpeg_out if ffmpeg_out else "(No output)\n")
        except Exception as e:
            log_lines.append(f"\nError reading FFmpeg log: {e}\n")

        try:
            with open(pw_log_path, 'r') as f:
                pw_out = f.read()
                log_lines.append("\n--- Playwright Output ---\n")
                log_lines.append(pw_out if pw_out else "(No output)\n")
        except Exception as e:
            log_lines.append(f"\nError reading Playwright log: {e}\n")

        for p in [xvfb_log_path, ffmpeg_log_path, pw_script_path, pw_log_path]:
            try:
                os.remove(p)
            except OSError:
                pass

        try:
            client = storage.Client()
            bucket = client.bucket('waikikiwx')
            blob = bucket.blob('live-stream-results.txt')
            blob.upload_from_string("".join(log_lines), content_type='text/plain')
            logging.info("Successfully uploaded live-stream-results.txt to GCS")
        except Exception as e:
            logging.error(f"Failed to upload live-stream logs to GCS: {e}")

if __name__ == "__main__":
    main()

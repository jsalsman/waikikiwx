import os
import subprocess
import json
from datetime import datetime
from playwright.sync_api import sync_playwright
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_project_id():
    import google.auth
    _, project_id = google.auth.default()
    return project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")

def get_secret(secret_id, version_id="latest"):
    """Fetch secret from Google Cloud Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    project_id = get_project_id()
    if not project_id:
        raise Exception("Could not determine Google Cloud Project ID for Secret Manager.")

    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def record_video():
    """Record a 60s video of the website using Playwright."""
    print("Recording video...")
    webm_path = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Create context with 1920x1080 (16:9) for standard YouTube video
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=".",
            record_video_size={"width": 1920, "height": 1080}
        )
        page = context.new_page()
        page.goto("https://waikikiwx.live")

        # Wait 10 seconds for animations/widgets to load fully
        page.wait_for_timeout(10000)

        # Record for 60 seconds
        page.wait_for_timeout(60000)

        # Get path of saved video
        page.close()
        context.close()
        browser.close()

        # The video file is randomly named by playwright inside the record_video_dir
        for file in os.listdir("."):
            if file.endswith(".webm"):
                webm_path = file
                break

    if not webm_path:
        raise Exception("Failed to record video using Playwright.")

    print(f"Recorded video saved to: {webm_path}")
    return webm_path

def process_video(input_webm, output_mp4="output_short.mp4"):
    """Process video using ffmpeg: loop/trim to 60s, convert to h264/aac."""
    print("Processing video with FFmpeg...")
    # -stream_loop -1 loops the input infinitely if it's too short.
    # -sseof -60 seeks to 60 seconds from the end, ensuring we drop the initial loading state.
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-60",
        "-stream_loop", "-1",
        "-i", input_webm,
        "-t", "60",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        output_mp4
    ]
    subprocess.run(cmd, check=True)
    print(f"Processed video saved to: {output_mp4}")
    return output_mp4

def upload_to_youtube(video_path):
    """Upload the video to YouTube."""
    print("Authenticating with YouTube API...")

    try:
        client_id = get_secret("YOUTUBE_CLIENT_ID")
        client_secret = get_secret("YOUTUBE_CLIENT_SECRET")
        refresh_token = get_secret("YOUTUBE_REFRESH_TOKEN")
    except Exception as e:
        print(f"Error fetching secrets: {e}")
        print("Cannot upload to YouTube without credentials. Exiting gracefully.")
        return

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )

    youtube = build("youtube", "v3", credentials=credentials)

    date_str = datetime.now().strftime("%Y-%m-%d")
    title = f"Waikiki Live Weather - {date_str}"
    description = "Automated daily weather update for Waikiki. #Waikiki #Weather"

    print(f"Uploading '{title}' to YouTube...")

    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": "28"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        },
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    print("Upload Complete!")
    print(f"Video ID: {response.get('id')}")

if __name__ == "__main__":
    try:
        webm_file = record_video()
        mp4_file = process_video(webm_file)
        upload_to_youtube(mp4_file)
    except Exception as e:
        print(f"Error during daily video automation: {e}")
        import sys
        sys.exit(1)
    finally:
        # Cleanup
        for file in os.listdir("."):
            if file.endswith(".webm") or file.endswith(".mp4"):
                try:
                    os.remove(file)
                except:
                    pass

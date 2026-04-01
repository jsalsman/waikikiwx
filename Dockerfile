FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install system dependencies (ffmpeg and playwright browser dependencies)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Create non-root user 
RUN useradd --create-home --no-log-init appuser

# Install dependencies for a separate cacheable docker layer
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Install Playwright browser dependencies (requires root)
RUN playwright install-deps chromium

# Grant appuser permissions to the working directory so daily_short.py can save video files
RUN chown -R appuser:appuser /app

USER appuser

# Install Playwright browsers (as appuser)
RUN playwright install chromium

COPY --chown=appuser:appuser app.py index.html screenshot.png daily_video.py ./
EXPOSE 8080
CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "--timeout", "30", "app:app"]

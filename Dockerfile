FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Install dependencies as root for a separate cacheable docker layer
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
# Create non-root user first so we can use it in COPY --chown
RUN useradd --create-home --no-log-init appuser
# Copy application files with appuser ownership
COPY --chown=appuser:appuser app.py index.html screenshot.png .
USER appuser
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "--timeout", "30", "app:app"]

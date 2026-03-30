FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Create non-root user 
RUN useradd --no-log-init --home-dir /app appuser
USER appuser

# Install dependencies for a separate cacheable docker layer
COPY --chown=appuser:appuser requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser app.py index.html screenshot.png ./
EXPOSE 8080
CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "--timeout", "30", "app:app"]

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Create non-root user 
RUN useradd --create-home --no-log-init appuser
# Install dependencies for a separate cacheable docker layer
COPY requirements.txt ./
USER appuser
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appuser app.py index.html screenshot.png ./
USER appuser
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "--timeout", "30", "app:app"]

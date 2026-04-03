FROM python:3.14-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Create non-root user 
RUN useradd --create-home --no-log-init appuser
# Grant appuser permissions to the working directory
RUN chown -R appuser:appuser /app
USER appuser

# Install dependencies for a separate cacheable docker layer
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser app.py index.html screenshot.png ./
EXPOSE 8080
CMD ["python", "-m", "gunicorn", "-b", "0.0.0.0:8080", "-w", "3", "app:app"]

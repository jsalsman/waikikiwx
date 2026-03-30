FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py index.html screenshot.png ./
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "3", "--timeout", "30", "app:app"]

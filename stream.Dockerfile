FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy
WORKDIR /app
RUN apt-get update && apt-get install -y ffmpeg xvfb && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt playwright google-cloud-storage
COPY stream.py ./
CMD ["python", "stream.py", "--duration", "1"]

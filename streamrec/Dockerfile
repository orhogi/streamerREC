FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app

# Install dependencies directly since you don't have a requirements.txt
RUN pip install --no-cache-dir uvicorn fastapi

COPY main.py .
COPY index.html .

RUN mkdir -p /recordings

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
FROM python:3.12-slim

LABEL org.opencontainers.image.title="StreamRec" \
      org.opencontainers.image.description="Self-hosted live stream recorder with web UI" \
      org.opencontainers.image.source="https://github.com/orhogi/streamerREC" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp \
    && chmod a+rx /usr/local/bin/yt-dlp

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY index.html .

RUN mkdir -p /recordings && \
    useradd --system --home-dir /app --shell /usr/sbin/nologin streamrec && \
    chown -R streamrec:streamrec /app /recordings

USER streamrec

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:8080/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--limit-concurrency", "20", "--timeout-keep-alive", "10"]

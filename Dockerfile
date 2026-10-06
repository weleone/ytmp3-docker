FROM python:3.12-alpine

RUN apk add --no-cache ffmpeg && \
    pip install --no-cache-dir flask yt-dlp && \
    yt-dlp --version && ffmpeg -version | head -1

WORKDIR /app
COPY app.py ./
COPY static/ ./static/

ENV PORT=8080 \
    WORK_DIR=/tmp/ytmp3 \
    CLEANUP_AFTER=3600

EXPOSE 8080
CMD ["python", "app.py"]

FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      chromium \
      chromium-driver \
      fonts-nanum fonts-noto fonts-noto-cjk \
      curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV GOOGLE_CHROME_BIN=/usr/bin/chromium
ENV CHROME_BIN=/usr/bin/chromium
ENV CACHE_DIR=/data
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV PORT=8080
EXPOSE 8080

CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:8080", "predict_back:app"]


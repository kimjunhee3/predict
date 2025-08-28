FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver fonts-nanum fonts-noto-cjk \
    ca-certificates curl unzip gnupg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_BIN=/usr/bin/chromedriver
ENV PYTHONUNBUFFERED=1

CMD ["bash","-lc","gunicorn predict_back:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 120"]

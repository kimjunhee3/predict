FROM python:3.11-slim

# Chromium + Chromedriver + 필요한 라이브러리 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libcairo2 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libxkbcommon0 libxshmfence1 libu2f-udev \
    libvulkan1 xdg-utils \
 && rm -rf /var/lib/apt/lists/*

# Selenium이 브라우저 경로를 찾도록 ENV 지정
ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Gunicorn으로 앱 실행 (Railway가 $PORT 넣어줌)
CMD exec gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-8080} predict_back:app

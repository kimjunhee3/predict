FROM python:3.11-slim

# 1) 시스템 패키지: chromium & chromedriver 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver fonts-nanum fonts-noto-cjk ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# 2) 크롬 경로 환경변수 (셀레니움이 찾을 수 있게)
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER=/usr/bin/chromedriver

# 3) 파이썬 의존성
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4) 앱 소스
COPY . .

# 5) 런타임 환경
ENV PORT=8080
ENV WEB_CONCURRENCY=2
# 배포에서 Statiz ON (원하면 Railway Variables에서 ENABLE_STATIZ=1로도 제어 가능)
ENV ENABLE_STATIZ=1

# 6) 실행 (Gunicorn가 Railway의 $PORT를 바인딩)
CMD sh -c 'gunicorn -w ${WEB_CONCURRENCY:-2} -k gthread -b 0.0.0.0:${PORT} predict_back.py:app'

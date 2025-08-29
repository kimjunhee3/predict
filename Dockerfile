# Dockerfile
FROM python:3.11-slim

# 시스템 패키지 업데이트 및 Chromium 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      chromium \
      chromium-driver \
      fonts-nanum fonts-noto fonts-noto-cjk \
      curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# 환경변수: Chrome 바이너리 위치(배포 컨테이너에서 사용)
ENV GOOGLE_CHROME_BIN=/usr/bin/chromium
ENV CHROME_BIN=/usr/bin/chromium
# Railway Volume 경로를 기본 CACHE_DIR로 사용(있으면 statiz_predict가 자동 감지)
ENV CACHE_DIR=/data
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 앱 복사
COPY . /app

# 포트
ENV PORT=8080
EXPOSE 8080

# Gunicorn으로 Flask 앱 실행
# (predict_back:app 형태로 모듈:어플리케이션 객체 지정)
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:8080", "predict_back:app"]

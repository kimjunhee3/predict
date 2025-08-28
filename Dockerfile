# Dockerfile
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 기본값: 캐시만 사용 / 디버그 비노출
ENV STATIZ_CACHE_ONLY=1
ENV ENABLE_STATIZ=1
# APP_DEBUG=1 로 바꾸면 /debug 노출됨

CMD gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT:-8080} predict_back:app

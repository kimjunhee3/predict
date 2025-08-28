# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
# Railway가 실제 포트를 주입하지만, 로컬용 기본값도 넣어둡니다.
ENV PORT=8080
ENV WEB_CONCURRENCY=2

# ★ shell form으로 변경해서 $PORT가 런타임에 치환되도록 함
CMD sh -c 'gunicorn -w ${WEB_CONCURRENCY:-2} -k gthread -b 0.0.0.0:${PORT} predict_back:app'

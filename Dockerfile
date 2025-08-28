FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
# 서버는 캐시 우선 사용
ENV ENABLE_STATIZ=1
# /debug 노출은 필요시에만
# ENV APP_DEBUG=1

EXPOSE 8080
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:8080", "predict_back:app"]

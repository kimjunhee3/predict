FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# 런타임 환경
ENV PORT=8080
# ENV REMOTE_CACHE_URL=https://raw.githubusercontent.com/<USER>/<REPO>/<BRANCH>/statiz_cache.json
ENV CACHE_TTL_MIN=30

EXPOSE 8080
CMD ["gunicorn", "-w", "2", "-k", "gthread", "-b", "0.0.0.0:8080", "predict_back:app"]

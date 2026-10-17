# API image (ARCHITECTURE D47). Build context: the repository root.
#   docker compose --profile full up -d --build
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY shared shared
COPY data/curated data/curated
COPY pipeline pipeline
COPY backend backend
COPY deploy/api-entrypoint.sh /usr/local/bin/api-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/api-entrypoint && chmod +x /usr/local/bin/api-entrypoint
EXPOSE 8010
ENTRYPOINT ["api-entrypoint"]

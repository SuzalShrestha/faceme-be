FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get purge -y --auto-remove build-essential && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

ARG PREWARM_MODEL=true
ENV LOCAL_STORAGE_ROOT=/app/storage
ENV INSIGHTFACE_HOME=/models/insightface
ENV APP_MODULE=app.main:app
ENV UVICORN_WORKERS=1

RUN mkdir -p /app/storage/uploads /app/storage/faces /models/insightface \
    && if [ "$PREWARM_MODEL" = "true" ]; then python -m app.prewarm; fi

EXPOSE 8000

CMD ["sh", "-c", "uvicorn ${APP_MODULE} --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS}"]

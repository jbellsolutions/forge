FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY . /app
RUN pip install --upgrade pip && pip install ".[dashboard]"

EXPOSE 8000
CMD ["sh", "-c", "python -m forge.dashboard.bootstrap && uvicorn forge.dashboard.server:app --host 0.0.0.0 --port ${PORT:-8000}"]

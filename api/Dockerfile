# RAHBAR api: FastAPI, reads the index, never writes it.
# Build context: api/      Run: uvicorn on :8000 as uid 10001, read-only root filesystem.
FROM python:3.12.15-slim-trixie AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12.15-slim-trixie
LABEL org.opencontainers.image.title="rahbar-api" \
      org.opencontainers.image.description="RAHBAR grounded RAG API"
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* && \
    groupadd --system --gid 10001 rahbar && \
    useradd --system --uid 10001 --gid rahbar --no-create-home rahbar
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY app ./app
USER 10001:10001
EXPOSE 8000
# exec form: SIGTERM reaches uvicorn (PID 1) and it drains in-flight requests
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "20"]

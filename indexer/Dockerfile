# RAHBAR indexer: the Job's image and the ONLY writer to Chroma. Runs once and exits.
# Build context: indexer/. OCR needs system packages, not only pip packages.
FROM python:3.12.15-slim-trixie AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12.15-slim-trixie
LABEL org.opencontainers.image.title="rahbar-indexer" \
      org.opencontainers.image.description="RAHBAR indexing Job: extract, clean, chunk, embed, store"
# tesseract-ocr: OCR for image-only pages; poppler-utils: pdf2image renders pages
RUN apt-get update && \
    apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils && \
    apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CORPUS_DIR=/corpus \
    OMP_THREAD_LIMIT=1
RUN groupadd --system --gid 10001 rahbar && \
    useradd --system --uid 10001 --gid rahbar --no-create-home rahbar
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY pipeline ./pipeline
# Documents are NOT baked in: they reach the Job from a volume mounted at /corpus
# (a PVC on the cluster, a ConfigMap of eval/fixtures in CI). See docs/PIPELINE.md.
USER 10001:10001
ENTRYPOINT ["python", "-m", "pipeline.run"]
CMD []

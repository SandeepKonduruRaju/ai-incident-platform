# syntax=docker/dockerfile:1
# Single stage on purpose: every dependency installs from a prebuilt wheel (no compiler in the image), so a
# separate wheel-building stage would remove nothing. Pinned to a patch release on Debian 13 (trixie).
FROM python:3.13.16-slim-trixie

# No .pyc files in the image; print logs immediately instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached until requirements.txt changes.
COPY requirements.txt .
# pip is needed only to build this layer, so it is uninstalled at the end: the copies of certifi, urllib3,
# msgpack and setuptools vendored inside pip were the image's only fixable CVEs (Trivy, 2026-10). pip 26.2.2 is
# still upgraded first so the install itself runs with a patched pip.
# Pillow 13.0.0 over fastembed's pillow<13 cap: Pillow 12.x has fixable CRITICAL CVEs (CVE-2026-112393,
# -112403, -112900; JPEG decoder) and no fastembed release allows 13 yet. fastembed imports PIL but our text
# embedding/reranking never decodes images; the model-download steps below import fastembed with 13.0.0, so an
# incompatibility fails this build. Remove the override once a fastembed release allows pillow>=13.
RUN pip install --no-cache-dir --upgrade pip==26.2.2 \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps pillow==13.0.0 \
    && pip uninstall --yes pip

# Run as an unprivileged user, not root.
RUN useradd --create-home --uid 10001 worker

# Bake the embedding model into the image at build time: containers start without downloading
# ~70MB from Hugging Face, work without internet access, and every replica uses the same files.
# Own layer before COPY app: it stays cached while only the code changes.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_CACHE_DIR=/opt/models
RUN python -c "import os; from fastembed import TextEmbedding; TextEmbedding(os.environ['EMBEDDING_MODEL'], cache_dir=os.environ['EMBEDDING_CACHE_DIR'])" \
    && chown -R worker:worker /opt/models
# Same for the cross-encoder reranker (~80MB), in its own layer: changing one model keeps the other cached.
ARG RERANKER_MODEL=Xenova/ms-marco-MiniLM-L-6-v2
ENV RERANKER_MODEL=${RERANKER_MODEL}
RUN python -c "import os; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextCrossEncoder(os.environ['RERANKER_MODEL'], cache_dir=os.environ['EMBEDDING_CACHE_DIR'])" \
    && chown -R worker:worker /opt/models
# From here on, never try to reach Hugging Face: a missing model fails fast instead of downloading.
ENV HF_HUB_OFFLINE=1

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app
# Synthetic evidence for "python -m app.ingest" inside the container.
COPY data ./data

USER worker

EXPOSE 8000

# OCI labels last: build args change on every commit and would otherwise bust the cache of later layers.
ARG VERSION=dev
ARG REVISION=unknown
ARG CREATED=unknown
ARG SOURCE=https://github.com/SandeepKonduruRaju/ai-incident-platform
LABEL org.opencontainers.image.title="investigation-worker" \
      org.opencontainers.image.description="Kafka consumer: hybrid retrieval + LangGraph/Claude incident investigation" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.version="${VERSION}"

# Migrate first (like Flyway on Spring Boot startup), then serve. "exec" makes uvicorn PID 1,
# so it receives Docker's SIGTERM and runs the lifespan shutdown (graceful consumer stop).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]

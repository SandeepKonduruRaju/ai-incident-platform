FROM python:3.13-slim

# No .pyc files in the image; print logs immediately instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

# Run as an unprivileged user, not root.
RUN useradd --create-home --uid 10001 worker
USER worker

EXPOSE 8000
# Migrate first (like Flyway on Spring Boot startup), then serve. "exec" makes uvicorn PID 1,
# so it receives Docker's SIGTERM and runs the lifespan shutdown (graceful consumer stop).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]

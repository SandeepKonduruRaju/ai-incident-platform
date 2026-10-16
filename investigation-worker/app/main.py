import logging

from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s : %(message)s",
)

app = FastAPI(title="investigation-worker")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

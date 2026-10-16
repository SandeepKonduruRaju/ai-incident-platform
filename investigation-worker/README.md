# investigation-worker

Python service that will consume `IncidentCreated` events from Kafka (topic `incident-events`)
and investigate incidents. Right now it has a health endpoint and the event models only.

## Setup (Windows PowerShell, Python 3.13)

```powershell
cd investigation-worker
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

If PowerShell refuses to run `Activate.ps1`, allow local scripts for your user once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Run locally (port 8001)

```powershell
uvicorn app.main:app --reload --port 8001
Invoke-RestMethod http://localhost:8001/health
```

## Test

```powershell
python -m pytest
```

## Configuration (environment variables)

| Variable | Default |
|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` |
| `KAFKA_TOPIC` | `incident-events` |
| `KAFKA_GROUP_ID` | `investigation-worker` |
| `LOG_LEVEL` | `INFO` |

## Docker (port 8000 inside the container)

```powershell
docker build -t investigation-worker .
docker run --rm -p 8001:8000 investigation-worker
```

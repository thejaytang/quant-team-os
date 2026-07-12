FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/app /app/apps/api/app
COPY apps/workers /app/apps/workers
COPY data_contracts /app/data_contracts
COPY .dvc /app/.dvc
ENV PYTHONPATH=/app/apps/api:/app/apps/workers
RUN pip install --no-cache-dir -e /app/apps/api
CMD ["python", "-m", "worker_main"]

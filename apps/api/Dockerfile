FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY apps/api/pyproject.toml /app/pyproject.toml
COPY apps/api/app /app/app
COPY data_contracts /app/data_contracts
COPY .dvc /app/.dvc
RUN pip install --no-cache-dir -e .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

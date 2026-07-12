FROM python:3.11-slim

WORKDIR /app
COPY apps/openbb-backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY apps/openbb-backend/app.py /app/app.py
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8010"]

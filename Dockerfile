FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx python-multipart

COPY app.py .
COPY static/ static/

EXPOSE 2026

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "2026"]

FROM python:3.10-slim

# Verhindert .pyc Dateien und puffert Output nicht (schnelleres Logging)
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT 8080
CMD exec gunicorn --bind :$PORT --worker-class eventlet --workers 1 app:app

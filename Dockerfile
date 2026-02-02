# Verwendung eines schlanken Python-Images für minimale Ladezeiten
FROM python:3.10-slim

# Performance-Optimierung: Verhindert Bytecode-Erzeugung und puffert Logs nicht
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Arbeitsverzeichnis im Container festlegen
WORKDIR /app

# Layer-Caching: Erst Anforderungen installieren, dann Code kopieren
# Beschleunigt den Build-Prozess erheblich
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieren der restlichen Applikationsdateien
COPY . .

# Port-Definition für Google Cloud Run (Standard 8080)
ENV PORT 8080

# Hochleistungs-Startbefehl für Gunicorn:
# --worker-class eventlet: Optimiert für WebSockets/Socket.io
# --workers 1: Cloud Run skaliert horizontal, daher ist 1 Worker pro Container optimal
# --worker-connections 1000: Erlaubt bis zu 1000 gleichzeitige Verbindungen pro Instanz
# --keep-alive 5: Hält Verbindungen für schnellere Folgeanfragen offen
CMD exec gunicorn \
    --bind :$PORT \
    --worker-class eventlet \
    --workers 1 \
    --worker-connections 1000 \
    --keep-alive 5 \
    app:app

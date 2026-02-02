# Basis-Image wählen
FROM python:3.10-slim

# Arbeitsverzeichnis im Container
WORKDIR /app

# Abhängigkeiten kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Den gesamten Code kopieren
COPY . .

# Port-Umgebungsvariable für Cloud Run
ENV PORT 8080

# Startbefehl mit Gunicorn und Eventlet-Support
CMD exec gunicorn --bind :$PORT --worker-class eventlet --workers 1 app:app

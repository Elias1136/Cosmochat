# Verwende ein sehr leichtes Image für maximale Geschwindigkeit
FROM nginx:alpine

# Kopiere deine App (die index.html) in den Server-Ordner
COPY index.html /usr/share/nginx/html/index.html

# Öffne den Standard-Port für Cloud Run (normalerweise 8080)
# Cloud Run setzt die PORT Umgebungsvariable automatisch, Nginx lauscht standardmäßig auf 80.
# Wir konfigurieren Nginx kurz um, damit es Cloud Run Standards entspricht:
RUN sed -i 's/listen       80;/listen       8080;/' /etc/nginx/conf.d/default.conf

# Startbefehl
CMD ["nginx", "-g", "daemon off;"]

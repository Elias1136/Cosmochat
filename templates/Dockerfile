# Verwende ein sehr leichtes Image für maximale Geschwindigkeit
FROM nginx:alpine

# Kopiere deine App (die index.html) in den Server-Ordner
COPY index.html /usr/share/nginx/html/index.html

# Erstelle eine eigene Konfiguration direkt für Port 8080.
# Das ist viel sicherer als der vorherige 'sed' Befehl, da es
# garantiert, dass Nginx auf dem richtigen Port für Cloud Run lauscht.
RUN echo "server { \
    listen 8080; \
    server_name localhost; \
    location / { \
        root /usr/share/nginx/html; \
        index index.html index.htm; \
    } \
    error_page 500 502 503 504 /50x.html; \
    location = /50x.html { \
        root /usr/share/nginx/html; \
    } \
}" > /etc/nginx/conf.d/default.conf

# Startbefehl
CMD ["nginx", "-g", "daemon off;"]

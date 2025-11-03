from flask import Flask, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# Ein geheimer Schlüssel ist gut für die Produktion
app.config['SECRET_KEY'] = 'dein_super_geheimer_schluessel_123!' 
# Wir erlauben alle Herkünfte (Origins), damit deine lokale index.html funktioniert
socketio = SocketIO(app, cors_allowed_origins="*")

# Hält die Namen der verbundenen Benutzer
user_names = {}

@app.route('/')
def index():
    # Sende einfach eine "Hallo"-Nachricht, damit der Server nicht abstürzt
    return "Der CosmoChat-Server ist online und läuft."

@socketio.on('user_join')
def handle_user_join(data):
    """Wird aufgerufen, wenn ein Benutzer seinen Namen setzt."""
    username = data.get('name', 'Unbekannt')
    user_names[request.sid] = username
    print(f"Benutzer {username} (SID: {request.sid}) ist beigetreten.")
    
    # Systemnachricht an alle senden
    system_msg = {
        'user': 'System',
        'text': f'<strong>{username}</strong> ist dem Chat beigetreten!',
        'color': '#00ff88',
        'isSystem': True
    }
    emit('message', system_msg, broadcast=True)

@socketio.on('message')
def handle_message(data):
    """Empfängt eine Nachricht und sendet sie an alle ANDEREN."""
    print(f"Nachricht empfangen: {data}")
    # Sende an alle (broadcast=True), außer an den Absender selbst (skip_sid)
    emit('message', data, broadcast=True, skip_sid=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    """Wird aufgerufen, wenn ein Benutzer die Verbindung trennt."""
    username = user_names.pop(request.sid, 'Ein Benutzer') # Holt & entfernt den Namen
    print(f"Benutzer {username} (SID: {request.sid}) hat die Verbindung getrennt.")
    
    system_msg = {
        'user': 'System',
        'text': f'<strong>{username}</strong> hat den Chat verlassen.',
        'color': '#00ff88',
        'isSystem': True
    }
    emit('message', system_msg, broadcast=True)
    

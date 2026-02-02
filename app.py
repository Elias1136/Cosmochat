import os
import json
import random
import time
import requests
from datetime import datetime
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'cosmo-ultimate-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- DATEI-SPEICHERUNG (JSON) ---
DATA_FILE = 'cosmo_data.json'

def load_db():
    if not os.path.exists(DATA_FILE):
        return {'users': {}, 'chats': {}}
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'users': {}, 'chats': {}}

def save_db(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except: pass

# --- KI KONFIGURATION ---
# Füge hier deinen API Key ein, wenn du ihn hast. Sonst bleibt es leer.
API_KEY = os.environ.get('GEMINI_API_KEY', '') 
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"

def ask_gemini(prompt):
    if not API_KEY: return "KI-System offline (Kein Key)."
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        res = requests.post(GEMINI_URL, json=payload, timeout=10)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
    except: pass
    return "Verbindung zum KI-Kern verloren."

# --- HILFSFUNKTIONEN ---
def generate_id(existing_ids):
    while True:
        # Erstellt garantiert eine 6-stellige Zahl (100000 bis 999999)
        new_id = str(random.randint(100000, 999999))
        if new_id not in existing_ids:
            return new_id

def get_room_id(id1, id2):
    # Erstellt einen eindeutigen Raum-Namen für zwei Personen (z.B. "123456-987654")
    return "-".join(sorted([str(id1), str(id2)]))

# --- SERVER EVENTS ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def on_connect():
    print(f"Verbindung hergestellt: {request.sid}")

@socketio.on('login')
def handle_login(data):
    # Versuch, die alte ID aus dem Browser zu laden
    stored_id = data.get('id')
    db = load_db()
    
    my_id = None
    
    if stored_id and stored_id in db['users']:
        my_id = stored_id
    else:
        # Neue ID generieren
        my_id = generate_id(db['users'])
        # User anlegen
        db['users'][my_id] = {
            'name': 'Cosmonaut', 
            'friends': [], 
            'color': '#00ff88',
            'status': 'online'
        }
        save_db(db)
    
    session['uid'] = my_id
    
    # Nutzerdaten zurücksenden
    user = db['users'][my_id]
    
    # Freundesliste aufbereiten (Namen holen)
    friends_data = []
    for fid in user['friends']:
        if fid in db['users']:
            friends_data.append({
                'id': fid, 
                'name': db['users'][fid]['name'],
                'status': 'online' # Hier könnte man echte Online-Logik einbauen
            })

    emit('login_success', {
        'id': my_id, 
        'name': user['name'],
        'friends': friends_data
    })

@socketio.on('add_friend')
def handle_add_friend(data):
    my_id = session.get('uid')
    friend_id = data.get('friend_id')
    
    if not my_id or not friend_id: return
    if my_id == friend_id: return # Man kann sich nicht selbst hinzufügen
    
    db = load_db()
    
    if friend_id not in db['users']:
        emit('error', {'msg': 'Diese ID existiert nicht im Universum.'})
        return
    
    # Hinzufügen (bei mir)
    if friend_id not in db['users'][my_id]['friends']:
        db['users'][my_id]['friends'].append(friend_id)
    
    # Hinzufügen (beim Freund - damit er mich auch sieht)
    if my_id not in db['users'][friend_id]['friends']:
        db['users'][friend_id]['friends'].append(my_id)
        
    save_db(db)
    
    # Erfolgreich zurückmelden
    friend_name = db['users'][friend_id]['name']
    emit('friend_added', {'id': friend_id, 'name': friend_name, 'status': 'online'})

@socketio.on('join_chat')
def handle_join_chat(data):
    my_id = session.get('uid')
    target_id = data.get('target_id')
    
    if not my_id or not target_id: return
    
    # Raum-ID erstellen
    room = get_room_id(my_id, target_id)
    join_room(room)
    
    # Alte Nachrichten laden
    db = load_db()
    history = db['chats'].get(room, [])
    
    emit('chat_history', {'room': room, 'messages': history, 'partner': target_id})

@socketio.on('send_msg')
def handle_msg(data):
    my_id = session.get('uid')
    text = data.get('text')
    room = data.get('room') # Die Raum-ID (z.B. "123-456")
    
    if not my_id or not text or not room: return
    
    timestamp = datetime.now().strftime('%H:%M')
    msg_obj = {'from': my_id, 'text': text, 'time': timestamp}
    
    # Speichern
    db = load_db()
    if room not in db['chats']:
        db['chats'][room] = []
    db['chats'][room].append(msg_obj)
    save_db(db)
    
    # Senden an den Raum
    emit('new_msg', msg_obj, room=room)
    
    # KI Logik (nur wenn wir im KI Chat sind oder global)
    if text.lower().startswith("@ai"):
        prompt = text[3:].strip()
        answer = ask_gemini(prompt)
        ai_msg = {'from': 'ai', 'text': answer, 'time': timestamp}
        emit('new_msg', ai_msg, room=room)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

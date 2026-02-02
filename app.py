from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import os
import json
import random
import html # Für Sicherheit gegen Hacker-Code
from datetime import datetime

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'cosmo-super-secret-key-999'
socketio = SocketIO(app, cors_allowed_origins="*")

# Datei zum Speichern der Daten
DATA_FILE = 'cosmo_data.json'
online_users = {} # Speichert wer gerade online ist

# --- DATENBANK FUNKTIONEN ---
def load_data():
    if not os.path.exists(DATA_FILE): return {'users': {}, 'chats': {}}
    try:
        with open(DATA_FILE, 'r') as f: return json.load(f)
    except: return {'users': {}, 'chats': {}}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f: json.dump(data, f, indent=4)
    except: pass

def get_room_id(id1, id2):
    # Erstellt einen einzigartigen Raum für zwei Personen
    return "-".join(sorted([str(id1), str(id2)]))

# --- ROUTEN ---
@app.route('/')
def index():
    return render_template('index.html')

# --- SOCKET EVENTS ---
@socketio.on('connect')
def on_connect():
    print(f"Verbindung: {request.sid}")

@socketio.on('login')
def handle_login(data):
    db = load_data()
    uid = data.get('id')
    
    # 1. 6-stellige ID prüfen oder neu erstellen
    if not uid or uid not in db['users']:
        while True:
            uid = str(random.randint(100000, 999999))
            if uid not in db['users']: break
        
        # Neuen Nutzer anlegen
        db['users'][uid] = {'name': 'Neuer Nutzer', 'friends': [], 'color': '#00ff88'}
        save_data(db)
    
    session['uid'] = uid
    online_users[uid] = request.sid
    join_room(uid) # Eigener Raum für Benachrichtigungen
    
    # Status an Freunde senden (Ich bin online!)
    user = db['users'][uid]
    for friend_id in user['friends']:
        if friend_id in online_users:
            emit('friend_status', {'id': uid, 'status': 'online'}, room=online_users[friend_id])

    # Freundesliste für Frontend vorbereiten
    friend_list = []
    for fid in user['friends']:
        if fid in db['users']:
            fname = db['users'][fid]['name']
            fstatus = 'online' if fid in online_users else 'offline'
            friend_list.append({'id': fid, 'name': fname, 'status': fstatus})

    emit('init_data', {'id': uid, 'name': user['name'], 'friends': friend_list})

@socketio.on('set_name')
def handle_set_name(data):
    uid = session.get('uid')
    if not uid: return
    # Sicherheit: HTML entfernen
    new_name = html.escape(data.get('name', '')).strip()
    if new_name:
        db = load_data()
        db['users'][uid]['name'] = new_name
        save_data(db)
        emit('name_updated', {'name': new_name})

@socketio.on('add_friend')
def handle_add_friend(data):
    uid = session.get('uid')
    target_id = data.get('target_id')
    
    if not uid or not target_id: return
    if uid == target_id: return # Sich selbst adden geht nicht
    
    db = load_data()
    
    if target_id not in db['users']:
        emit('error_msg', {'text': 'Diese ID existiert nicht!'})
        return
    
    # Freundschaft speichern (beidseitig)
    if target_id not in db['users'][uid]['friends']:
        db['users'][uid]['friends'].append(target_id)
    if uid not in db['users'][target_id]['friends']:
        db['users'][target_id]['friends'].append(uid)
        
    save_data(db)
    
    # Mir den Freund schicken
    target_name = db['users'][target_id]['name']
    target_status = 'online' if target_id in online_users else 'offline'
    emit('friend_added', {'id': target_id, 'name': target_name, 'status': target_status})
    
    # Dem Freund mich schicken (wenn online)
    if target_id in online_users:
        my_name = db['users'][uid]['name']
        emit('friend_added', {'id': uid, 'name': my_name, 'status': 'online'}, room=online_users[target_id])

@socketio.on('remove_friend')
def handle_remove_friend(data):
    uid = session.get('uid')
    target_id = data.get('target_id')
    
    db = load_data()
    if target_id in db['users'][uid]['friends']:
        db['users'][uid]['friends'].remove(target_id)
        save_data(db)
        emit('friend_removed', {'id': target_id})

@socketio.on('join_chat')
def handle_join_chat(data):
    uid = session.get('uid')
    target_id = data.get('target_id')
    room = get_room_id(uid, target_id)
    join_room(room)
    
    db = load_data()
    msgs = db['chats'].get(room, [])
    emit('chat_history', {'room': room, 'messages': msgs, 'partner': target_id})

@socketio.on('send_message')
def handle_send_message(data):
    uid = session.get('uid')
    text = html.escape(data.get('text', '')).strip() # Hacker Schutz
    room = data.get('room')
    
    if not uid or not text or not room: return
    
    msg = {
        'from': uid,
        'text': text,
        'time': datetime.now().strftime('%H:%M')
    }
    
    db = load_data()
    if room not in db['chats']: db['chats'][room] = []
    db['chats'][room].append(msg)
    save_data(db)
    
    emit('new_message', msg, room=room)

@socketio.on('disconnect')
def on_disconnect():
    uid = session.get('uid')
    if uid:
        if uid in online_users: del online_users[uid]
        # Freunde benachrichtigen
        db = load_data()
        if uid in db['users']:
            for friend_id in db['users'][uid]['friends']:
                if friend_id in online_users:
                    emit('friend_status', {'id': uid, 'status': 'offline'}, room=online_users[friend_id])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)

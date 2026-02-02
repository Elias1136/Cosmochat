import os
import json
import random
import requests
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'cosmo-secret-key-999'
socketio = SocketIO(app, cors_allowed_origins="*")

# Einfache Datenspeicherung in einer JSON-Datei (für den Start)
DATA_FILE = 'cosmo_db.json'

def load_db():
    if not os.path.exists(DATA_FILE): return {'users': {}, 'chats': {}}
    try:
        with open(DATA_FILE, 'r') as f: return json.load(f)
    except: return {'users': {}, 'chats': {}}

def save_db(data):
    try:
        with open(DATA_FILE, 'w') as f: json.dump(data, f)
    except: pass

# KI-Funktion
def ask_gemini(prompt):
    key = os.environ.get('GEMINI_API_KEY')
    if not key: return "KI ist nicht konfiguriert."
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={key}"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=5)
        if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text']
    except: pass
    return "KI antwortet nicht."

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('login')
def handle_login(data):
    db = load_db()
    uid = data.get('id')
    
    # 6-stellige ID generieren, falls nicht vorhanden
    if not uid or uid not in db['users']:
        while True:
            uid = str(random.randint(100000, 999999))
            if uid not in db['users']: break
        db['users'][uid] = {'name': 'Cosmonaut', 'friends': []}
        save_db(db)
    
    session['uid'] = uid
    user = db['users'][uid]
    
    # Freundesliste bauen
    friend_list = []
    for fid in user['friends']:
        if fid in db['users']:
            friend_list.append({'id': fid, 'name': db['users'][fid]['name']})
            
    emit('init_data', {'id': uid, 'friends': friend_list})

@socketio.on('add_friend')
def add_friend(data):
    uid = session.get('uid')
    fid = data.get('friend_id')
    db = load_db()
    
    if uid and fid and fid in db['users'] and fid != uid:
        if fid not in db['users'][uid]['friends']:
            db['users'][uid]['friends'].append(fid)
            # Gegenseitig hinzufügen
            if uid not in db['users'][fid]['friends']:
                db['users'][fid]['friends'].append(uid)
            save_db(db)
            emit('friend_added', {'id': fid, 'name': db['users'][fid]['name']})

@socketio.on('join_chat')
def join_chat(data):
    uid = session.get('uid')
    target = data.get('target_id')
    room = "-".join(sorted([uid, target]))
    join_room(room)
    
    db = load_db()
    msgs = db['chats'].get(room, [])
    emit('chat_history', {'room': room, 'messages': msgs})

@socketio.on('send_message')
def send_msg(data):
    uid = session.get('uid')
    text = data.get('text')
    room = data.get('room')
    
    if uid and text and room:
        msg = {'from': uid, 'text': text}
        
        db = load_db()
        if room not in db['chats']: db['chats'][room] = []
        db['chats'][room].append(msg)
        save_db(db)
        
        emit('new_message', {**msg, 'room': room}, room=room)
        
        if "@ai" in text.lower():
            ai_text = ask_gemini(text.replace("@ai", ""))
            ai_msg = {'from': 'ai', 'text': ai_text}
            emit('new_message', {**ai_msg, 'room': room}, room=room)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)

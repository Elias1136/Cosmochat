import os
import random
import time
import requests
import html
from datetime import datetime
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
from google.cloud import firestore

# App Setup
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'cosmo-ultimate-key-2025'

# WICHTIG: cors_allowed_origins="*" fixt das Verbindungsproblem!
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- KONFIGURATION ---
API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
APP_ID = "cosmochat_v8_ultimate"

# Datenbank Setup (mit Fallback, falls Cloud noch nicht aktiv)
try:
    db = firestore.Client()
    print("Firestore verbunden!")
except:
    db = None
    print("Achtung: Firestore nicht verbunden (Lokalmodus?)")

# --- HILFSFUNKTIONEN ---
def get_user_ref(uid):
    if db: return db.collection('artifacts').document(APP_ID).collection('users').document(uid)
    return None

def get_msg_ref():
    if db: return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')
    return None

def ask_gemini(prompt):
    if not API_KEY: return "KI ist nicht konfiguriert."
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": "Du bist CosmoAI. Antworte kurz und hilfreich auf Deutsch."}]}
    }
    try:
        res = requests.post(GEMINI_URL, json=payload, timeout=10)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
    except: pass
    return "KI antwortet gerade nicht."

# --- EVENTS ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect_event():
    print(f"Client verbunden: {request.sid}")

@socketio.on('user_connect')
def handle_user_init(data):
    # ID Laden oder Generieren
    uid = data.get('id')
    
    # Erzwinge 6-stellige ID
    if not uid or len(str(uid)) != 6:
        uid = str(random.randint(100000, 999999))
        if db:
            get_user_ref(uid).set({'created': datetime.now()})
            
    session['uid'] = uid
    join_room('global')
    
    # WICHTIG: Sende ID sofort zurück!
    emit('init_data', {'id': uid})

@socketio.on('send_message')
def handle_msg(payload):
    uid = session.get('uid')
    text = payload.get('text', '').strip()
    if not uid or not text: return

    safe_text = html.escape(text)
    msg_id = str(int(time.time() * 1000))
    
    msg_data = {
        'id': msg_id,
        'from_id': uid,
        'text': safe_text,
        'time': datetime.now().strftime('%H:%M'),
        'timestamp': firestore.SERVER_TIMESTAMP if db else None
    }
    
    if db: get_msg_ref().document(msg_id).set(msg_data)
    emit('receive_message', msg_data, room='global')

@socketio.on('ask_ai')
def handle_ai(payload):
    prompt = payload.get('text', '').strip()
    if not prompt: return
    
    ans = ask_gemini(prompt)
    ai_msg = {
        'id': f"ai_{time.time()}",
        'from_id': 'ai_bot',
        'from_name': 'CosmoAI 🤖',
        'text': html.escape(ans),
        'time': datetime.now().strftime('%H:%M'),
        'is_ai': True
    }
    emit('receive_message', ai_msg, room='global')

@socketio.on('load_history')
def load_hist():
    if not db: return
    try:
        docs = get_msg_ref().order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).stream()
        msgs = sorted([d.to_dict() for d in docs], key=lambda x: x.get('id', ''))
        # Bereinige Timestamps für JSON
        for m in msgs: 
            if 'timestamp' in m: del m['timestamp']
        emit('chat_history', msgs)
    except: pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

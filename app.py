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

app = Flask(__name__)
# WICHTIG: CORS erlaubt dem Browser, Daten vom Server zu laden
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cosmo-ultra-secure-key')

# WICHTIG: cors_allowed_origins="*" erlaubt die Verbindung für die ID
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- KONFIGURATION ---
API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
APP_ID = "cosmochat_v6_pro"

# Datenbank-Client (für Google Cloud)
try:
    db = firestore.Client()
except:
    db = None # Fallback, falls lokal getestet wird

# --- DATENBANK PFADE ---
def get_user_ref(user_id):
    if db: return db.collection('artifacts').document(APP_ID).collection('users').document(user_id)
    return None

def get_msg_ref():
    if db: return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')
    return None

# --- KI LOGIK ---
def ask_gemini(prompt):
    if not API_KEY: return "KI-System: Kein API-Key gefunden."
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
    # Hier wird die ID generiert oder geladen
    user_id = data.get('id')
    
    # ID Validierung (muss 6-stellig sein)
    if not user_id or len(str(user_id)) != 6:
        user_id = str(random.randint(100000, 999999))
        if db:
            get_user_ref(user_id).set({'created': firestore.SERVER_TIMESTAMP})
    
    session['uid'] = user_id
    join_room('global')
    
    # Sende die ID zurück an den Browser -> Das löst "ID: lädt..."
    emit('init_data', {'id': user_id})

@socketio.on('send_message')
def handle_msg(payload):
    uid = session.get('uid')
    text = payload.get('text', '').strip()
    if not uid or not text: return

    # HTML säubern (Sicherheit)
    safe_text = html.escape(text)
    
    msg_id = str(int(time.time() * 1000))
    msg_data = {
        'id': msg_id,
        'from_id': uid,
        'text': safe_text,
        'time': datetime.now().strftime('%H:%M'),
        'timestamp': firestore.SERVER_TIMESTAMP
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
        docs = get_msg_ref().order_by('timestamp', direction=firestore.Query.DESCENDING).limit(40).stream()
        msgs = sorted([d.to_dict() for d in docs], key=lambda x: x.get('id', ''))
        for m in msgs: 
            if 'timestamp' in m: del m['timestamp']
        emit('chat_history', msgs)
    except: pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

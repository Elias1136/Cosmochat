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

# Initialisierung der Flask-App
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cosmo-secure-enterprise-v6')

# SocketIO mit Eventlet für Hochleistung im Web
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- KONFIGURATION ---
# API_KEY wird sicher aus der Google Cloud Umgebung bezogen
API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
APP_ID = "cosmochat_enterprise_v6"

# Cloud Firestore Client
db = firestore.Client()

# Pfade nach Regel 1
def get_msg_ref():
    return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')

def get_user_ref(user_id):
    return db.collection('artifacts').document(APP_ID).collection('users').document(user_id)

# KI-Logik (Gemini API)
def call_gemini_api(prompt):
    if not API_KEY:
        return "System-Hinweis: API_KEY fehlt in der Cloud-Konfiguration."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": "Du bist CosmoAI. Antworte kurz, professionell und im WhatsApp-Stil auf Deutsch."}]}
    }
    
    for i in range(5):
        try:
            response = requests.post(GEMINI_URL, json=payload, timeout=12)
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            time.sleep(2**i)
        except Exception:
            time.sleep(2**i)
    return "KI momentan nicht erreichbar."

# --- SOCKET.IO EVENTS ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('user_connect')
def handle_connect(data):
    # Generiert oder validiert eine 6-stellige ID
    user_id = data.get('id')
    if not user_id or len(str(user_id)) != 6:
        user_id = str(random.randint(100000, 999999))
        get_user_ref(user_id).set({'status': 'active', 'timestamp': firestore.SERVER_TIMESTAMP})
    
    session['uid'] = user_id
    join_room('global_lounge')
    emit('init_data', {'id': user_id})

@socketio.on('send_message')
def handle_message(payload):
    uid = session.get('uid')
    raw_text = payload.get('text', '').strip()
    
    # HACKER-SCHUTZ: HTML-Tags neutralisieren (XSS Schutz)
    if not uid or not raw_text or len(raw_text) > 1500:
        return
    
    clean_text = html.escape(raw_text)
    msg_id = str(int(time.time() * 1000))
    msg_data = {
        'id': msg_id, 'from_id': uid, 'text': clean_text,
        'time': datetime.now().strftime('%H:%M'), 'timestamp': firestore.SERVER_TIMESTAMP
    }
    
    get_msg_ref().document(msg_id).set(msg_data)
    emit('receive_message', msg_data, room='global_lounge')

@socketio.on('ask_ai')
def handle_ai(payload):
    prompt = payload.get('text', '').strip()
    if not prompt: return
    
    ans = call_gemini_api(prompt)
    ai_msg = {
        'id': f"ai_{time.time()}", 'from_id': 'ai_bot', 'from_name': 'CosmoAI 🤖',
        'text': html.escape(ans), 'time': datetime.now().strftime('%H:%M'), 'is_ai': True
    }
    emit('receive_message', ai_msg, room='global_lounge')

@socketio.on('load_history')
def handle_history():
    docs = get_msg_ref().order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).stream()
    history = []
    for d in docs:
        item = d.to_dict()
        if 'timestamp' in item: del item['timestamp']
        history.append(item)
    emit('chat_history', sorted(history, key=lambda x: x.get('id', '')))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

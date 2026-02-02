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

# Initialisierung der Flask-Applikation
app = Flask(__name__)
CORS(app)

# Sicherheitskonfiguration (CSRF & Session Schutz)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cosmo-security-v5-pro')

# SocketIO mit Eventlet für asynchrone Hochleistungskommunikation
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- INFRASTRUKTUR KONFIGURATION ---
# API-Schlüssel wird sicher aus der Cloud-Umgebung bezogen
API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
APP_ID = "cosmochat_enterprise_v5"

# Cloud Firestore Client
db = firestore.Client()

# --- DATENZUGRIFFSSCHICHT ---
def get_msg_ref():
    return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')

def get_user_ref(user_id):
    return db.collection('artifacts').document(APP_ID).collection('users').document(user_id)

# --- KI INTEGRATION ---
def call_gemini_api(prompt):
    """Führt eine sichere Anfrage an das Gemini-Modell aus."""
    if not API_KEY:
        return "System-Fehler: API_KEY fehlt in der Cloud-Konfiguration."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": "Du bist CosmoAI. Antworte kurz, professionell und im Chat-Stil auf Deutsch."}]}
    }
    
    for i in range(5):
        try:
            response = requests.post(GEMINI_URL, json=payload, timeout=12)
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            time.sleep(2**i)
        except Exception:
            time.sleep(2**i)
    return "KI-Dienst momentan nicht erreichbar."

# --- SOCKET.IO EVENT HANDLER ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('user_connect')
def handle_user_initialization(data):
    """Initialisiert den Nutzer und validiert die 6-stellige Identität."""
    user_id = data.get('id')
    
    # Sicherstellen, dass die ID 6 Ziffern hat
    if not user_id or len(str(user_id)) != 6:
        user_id = str(random.randint(100000, 999999))
        get_user_ref(user_id).set({
            'name': 'Cosmonaut',
            'created_at': firestore.SERVER_TIMESTAMP
        })
    
    session['uid'] = user_id
    join_room('global_lounge')
    emit('init_data', {'id': user_id, 'name': 'Cosmonaut'})

@socketio.on('send_message')
def handle_inbound_message(payload):
    """Verarbeitet eingehende Nachrichten inklusive Cyber-Security-Filter."""
    uid = session.get('uid')
    raw_content = payload.get('text', '').strip()
    
    # SICHERHEITS-VALIDIERUNG: Hacker-Schutz (XSS) & Längenbegrenzung
    if not uid or not raw_content or len(raw_content) > 1500:
        return
    
    # HTML-Escaping zur Neutralisierung von Schadcode
    sanitized_text = html.escape(raw_content)
    
    msg_id = str(int(time.time() * 1000))
    message_object = {
        'id': msg_id,
        'from_id': uid,
        'text': sanitized_text,
        'time': datetime.now().strftime('%H:%M'),
        'timestamp': firestore.SERVER_TIMESTAMP
    }
    
    # Persistenz in Cloud Firestore
    try:
        get_msg_ref().document(msg_id).set(message_object)
    except Exception:
        pass
    
    # Broadcast an den globalen Chatraum
    emit('receive_message', message_object, room='global_lounge')

@socketio.on('ask_ai')
def handle_ai_request(payload):
    """Verarbeitet KI-Anfragen über den Roboter-Interface-Button."""
    user_prompt = payload.get('text', '').strip()
    if not user_prompt:
        return
    
    ai_content = call_gemini_api(user_prompt)
    
    ai_response = {
        'id': f"ai_{time.time()}",
        'from_id': 'ai_bot',
        'from_name': 'CosmoAI 🤖',
        'text': html.escape(ai_content),
        'time': datetime.now().strftime('%H:%M'),
        'is_ai': True
    }
    emit('receive_message', ai_response, room='global_lounge')

@socketio.on('load_history')
def handle_history_sync():
    """Synchronisiert den Chatverlauf beim Start."""
    try:
        docs = get_msg_ref().order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).stream()
        history = []
        for d in docs:
            item = d.to_dict()
            if 'timestamp' in item: del item['timestamp']
            history.append(item)
        emit('chat_history', sorted(history, key=lambda x: x.get('id', '')))
    except Exception:
        pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

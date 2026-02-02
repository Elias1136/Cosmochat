import os
import random
import time
import requests
from datetime import datetime
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from google.cloud import firestore

# Initialisierung der Flask-App
app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'cosmo-sky-2025-key'

# SocketIO Setup für Echtzeit-Kommunikation
socketio = SocketIO(app, cors_allowed_origins="*")

# --- KONFIGURATION ---
# Der API_KEY wird aus den Google Cloud Umgebungsvariablen gelesen
API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
APP_ID = "cosmochat_v4"

# Firestore Datenbank-Client
db = firestore.Client()

def get_msg_ref():
    # Pfad nach Regel 1: artifacts/{appId}/public/data/messages
    return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')

# KI-Funktion für Gemini
def ask_gemini(prompt):
    if not API_KEY:
        return "Hinweis: Kein API_KEY in den Umgebungsvariablen gefunden."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": "Du bist CosmoAI. Antworte kurz, freundlich und hilfsbereit auf Deutsch."}]}
    }
    
    # Exponential Backoff für API-Anfragen
    for i in range(5):
        try:
            response = requests.post(GEMINI_URL, json=payload, timeout=10)
            if response.status_code == 200:
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            time.sleep(2**i)
        except:
            time.sleep(2**i)
    return "KI-Dienst momentan nicht erreichbar."

# --- SOCKET.IO EVENTS ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('user_connect')
def handle_connect(data):
    # Generiert eine ID, falls keine im LocalStorage vorhanden war
    uid = data.get('id') if data else str(random.randint(100000, 999999))
    session['uid'] = uid
    emit('init_data', {'id': uid, 'name': 'Cosmonaut'})

@socketio.on('send_message')
def handle_msg(payload):
    uid = session.get('uid')
    text = payload.get('text', '').strip()
    if not uid or not text: return

    msg_id = str(int(time.time() * 1000))
    msg_data = {
        'id': msg_id,
        'from_id': uid,
        'text': text,
        'time': datetime.now().strftime('%H:%M'),
        'timestamp': firestore.SERVER_TIMESTAMP
    }
    
    # Speichern in Firestore
    get_msg_ref().document(msg_id).set(msg_data)
    
    # Nachricht an alle senden
    emit('receive_message', msg_data, broadcast=True)

@socketio.on('ask_ai')
def handle_ai(payload):
    prompt = payload.get('text')
    if not prompt: return
    
    answer = ask_gemini(prompt)
    ai_msg = {
        'from_id': 'ai_bot',
        'from_name': 'CosmoAI 🤖',
        'text': answer,
        'time': datetime.now().strftime('%H:%M')
    }
    emit('receive_message', ai_msg, broadcast=True)

@socketio.on('load_history')
def load_hist():
    # Letzte 30 Nachrichten laden (Regel 2: Einfache Query)
    docs = get_msg_ref().order_by('timestamp', direction=firestore.Query.DESCENDING).limit(30).stream()
    msgs = sorted([d.to_dict() for d in docs], key=lambda x: x.get('id', ''))
    for m in msgs:
        if 'timestamp' in m: del m['timestamp']
    emit('chat_history', msgs)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

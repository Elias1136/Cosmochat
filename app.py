import os
import random
import time
import requests
from datetime import datetime
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
from google.cloud import firestore

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'cosmochat-pro-sky-blue'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- KONFIGURATION ---
# Die API_KEY wird in der Google Cloud automatisch erkannt
API_KEY = "" 
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
IMAGEN_URL = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={API_KEY}"
APP_ID = "cosmochat"

# Firestore Datenbank
db = firestore.Client()

# Firestore Pfade nach Regel 1
def get_user_ref(user_id):
    return db.collection('artifacts').document(APP_ID).collection('users').document(user_id)

def get_msg_ref():
    return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')

# --- KI LOGIK ---
def ask_gemini(prompt):
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": "Du bist CosmoAI. Antworte kurz, freundlich und in einem hellblauen Chat-Stil auf Deutsch."}]}
    }
    try:
        res = requests.post(GEMINI_URL, json=payload, timeout=10)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text']
    except: pass
    return "Meine KI-Antenne hat gerade keinen Empfang!"

def generate_image(prompt):
    payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}}
    try:
        res = requests.post(IMAGEN_URL, json=payload, timeout=30)
        if res.status_code == 200:
            b64 = res.json()['predictions'][0]['bytesBase64Encoded']
            return f"data:image/png;base64,{b64}"
    except: return None

# --- SERVER EVENTS ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('user_connect')
def handle_connect(data):
    uid = data.get('id')
    if uid:
        doc = get_user_ref(uid).get()
        if doc.exists:
            user_data = doc.to_dict()
        else: uid = None
    
    if not uid:
        uid = str(random.randint(100000, 999999))
        user_data = {'name': 'Cosmonaut', 'color': '#0ea5e9'}
        get_user_ref(uid).set(user_data)
    
    session['uid'] = uid
    emit('init_data', {'id': uid, 'name': user_data['name']})

@socketio.on('send_message')
def handle_msg(payload):
    uid = session.get('uid')
    text = payload.get('text', '').strip()
    if not uid or not text: return

    # Bild generieren mit /imagine
    if text.lower().startswith("/imagine"):
        prompt = text[8:].strip()
        emit('new_message', {'from_id': 'sys', 'text': '🎨 Ich male das Bild für dich...', 'time': datetime.now().strftime('%H:%M')}, broadcast=True)
        img = generate_image(prompt)
        if img:
            msg = {'from_id': 'ai', 'text': f'Hier ist dein Bild: {prompt}', 'img': img, 'time': datetime.now().strftime('%H:%M')}
            emit('new_message', msg, broadcast=True)
        return

    # Normaler Chat
    msg_id = str(int(time.time() * 1000))
    msg_data = {
        'id': msg_id, 'from_id': uid, 'text': text, 
        'time': datetime.now().strftime('%H:%M'), 'timestamp': firestore.SERVER_TIMESTAMP
    }
    get_msg_ref().document(msg_id).set(msg_data)
    emit('new_message', msg_data, broadcast=True)

@socketio.on('ask_ai')
def handle_ai(payload):
    ans = ask_gemini(payload.get('text'))
    emit('new_message', {'from_id': 'ai', 'text': ans, 'time': datetime.now().strftime('%H:%M')}, broadcast=True)

@socketio.on('load_history')
def load_hist():
    docs = get_msg_ref().order_by('timestamp', direction=firestore.Query.DESCENDING).limit(30).stream()
    msgs = sorted([d.to_dict() for d in docs], key=lambda x: x.get('id', ''))
    for m in msgs: m.pop('timestamp', None)
    emit('chat_history', msgs)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

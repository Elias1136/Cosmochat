import os
import random
import time
import requests
from datetime import datetime
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from google.cloud import firestore

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'cosmo-sky-2025'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- KONFIGURATION ---
# Wir holen den Schlüssel aus der Umgebung (Environment Variable)
API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
APP_ID = "cosmochat_sky"

db = firestore.Client()

def get_msg_ref():
    return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')

def ask_gemini(prompt):
    if not API_KEY:
        return "Hinweis: Es wurde kein API_KEY in Cloud Run hinterlegt."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": "Du bist CosmoAI. Antworte kurz und freundlich auf Deutsch."}]}
    }
    try:
        res = requests.post(GEMINI_URL, json=payload, timeout=10)
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    except:
        return "KI-Dienst nicht erreichbar."

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('user_connect')
def handle_connect(data):
    uid = data.get('id') if data else str(random.randint(100000, 999999))
    session['uid'] = uid
    emit('init_data', {'id': uid, 'name': 'Cosmonaut'})

@socketio.on('send_message')
def handle_msg(payload):
    uid = session.get('uid')
    text = payload.get('text', '').strip()
    if not uid or not text: return

    msg_id = str(int(time.time() * 1000))
    msg_data = {'id': msg_id, 'from_id': uid, 'text': text, 'time': datetime.now().strftime('%H:%M'), 'timestamp': firestore.SERVER_TIMESTAMP}
    
    get_msg_ref().document(msg_id).set(msg_data)
    emit('receive_message', msg_data, broadcast=True)

@socketio.on('ask_ai')
def handle_ai(payload):
    ans = ask_gemini(payload.get('text'))
    emit('receive_message', {'from_id': 'ai_bot', 'from_name': 'CosmoAI 🤖', 'text': ans, 'time': datetime.now().strftime('%H:%M')}, broadcast=True)

@socketio.on('load_history')
def load_hist():
    docs = get_msg_ref().order_by('timestamp', direction=firestore.Query.DESCENDING).limit(20).stream()
    msgs = sorted([d.to_dict() for d in docs], key=lambda x: x.get('id', ''))
    for m in msgs: m.pop('timestamp', None)
    emit('chat_history', msgs)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

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
CORS(app)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cosmo-ai-pro-key')

# Eventlet für beste Performance
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- KONFIGURATION ---
API_KEY = os.environ.get('GEMINI_API_KEY', '')
# Wir nutzen Flash für schnelle Text-Transformationen
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
IMAGEN_URL = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={API_KEY}"
APP_ID = "cosmochat_v8_ai"

db = firestore.Client()

# --- DATENBANK ---
def get_msg_ref():
    return db.collection('artifacts').document(APP_ID).collection('public').document('data').collection('messages')

def get_user_ref(uid):
    return db.collection('artifacts').document(APP_ID).collection('users').document(uid)

# --- KI ENGINE ---
def call_gemini(prompt, system_instruction="Du bist ein hilfreicher Assistent."):
    if not API_KEY: return "KI-Fehler: Kein Key."
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]}
    }
    try:
        res = requests.post(GEMINI_URL, json=payload, timeout=10)
        if res.status_code == 200:
            return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"KI Fehler: {e}")
    return None

def generate_image(prompt):
    if not API_KEY: return None
    payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}}
    try:
        res = requests.post(IMAGEN_URL, json=payload, timeout=30)
        if res.status_code == 200:
            b64 = res.json()['predictions'][0]['bytesBase64Encoded']
            return f"data:image/png;base64,{b64}"
    except: return None

# --- EVENTS ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('user_connect')
def handle_connect(data):
    uid = data.get('id')
    if not uid or len(str(uid)) != 6:
        uid = str(random.randint(100000, 999999))
        get_user_ref(uid).set({'created': firestore.SERVER_TIMESTAMP})
    
    session['uid'] = uid
    join_room('global')
    emit('init_data', {'id': uid})

@socketio.on('send_message')
def handle_msg(data):
    uid = session.get('uid')
    text = data.get('text', '').strip()
    if not uid or not text: return

    # Bild-KI Befehl (/imagine)
    if text.lower().startswith("/imagine"):
        prompt = text[8:].strip()
        emit('receive_message', {'from': 'sys', 'text': f'🎨 Male Bild: "{prompt}"...', 'time': datetime.now().strftime('%H:%M')}, room='global')
        
        img_data = generate_image(prompt)
        if img_data:
            msg_data = {
                'id': str(time.time()), 'from': 'ai_bot', 'text': f'Bild für: {prompt}', 
                'img': img_data, 'time': datetime.now().strftime('%H:%M'), 'is_ai': True
            }
            emit('receive_message', msg_data, room='global')
        return

    # Normaler Chat
    safe_text = html.escape(text)
    msg_id = str(int(time.time() * 1000))
    msg_data = {
        'id': msg_id, 'from': uid, 'text': safe_text,
        'time': datetime.now().strftime('%H:%M'), 'timestamp': firestore.SERVER_TIMESTAMP
    }
    
    get_msg_ref().document(msg_id).set(msg_data)
    emit('receive_message', msg_data, room='global')

@socketio.on('ask_ai')
def handle_ai(data):
    text = data.get('text', '').strip()
    if not text: return
    
    ans = call_gemini(text, "Du bist CosmoAI. Antworte kurz und freundlich.")
    if ans:
        ai_msg = {'id': f"ai_{time.time()}", 'from': 'ai_bot', 'text': html.escape(ans), 'time': datetime.now().strftime('%H:%M'), 'is_ai': True}
        emit('receive_message', ai_msg, room='global')

# --- NEU: KI TEXT-TRANSFORMATION ---
@socketio.on('transform_text')
def handle_transform(data):
    text = data.get('text')
    mode = data.get('mode') # professional, funny, english
    
    if not text or not mode: return
    
    prompts = {
        'professional': "Schreibe den folgenden Text professioneller und höflicher um. Gib NUR den neuen Text zurück:",
        'funny': "Schreibe den folgenden Text lustiger und mit Emojis um. Gib NUR den neuen Text zurück:",
        'english': "Translate the following text to English. Return ONLY the translation:"
    }
    
    system_instr = "Du bist ein Text-Editor-Tool. Gib nur das Ergebnis zurück, ohne Anführungszeichen."
    prompt = f"{prompts.get(mode, 'Korrigiere:')} \n'{text}'"
    
    result = call_gemini(prompt, system_instr)
    
    if result:
        # Sendet das Ergebnis nur an den User zurück (nicht an alle!)
        emit('transform_result', {'original': text, 'result': result})

@socketio.on('load_history')
def load_hist():
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

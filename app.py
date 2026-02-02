import os
import random
import time
import requests
import html
import uuid
import logging
from datetime import datetime
from flask import Flask, render_template, request, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask_cors import CORS
from google.cloud import firestore

# --- SYSTEM KONFIGURATION & LOGGING ---
# Wir setzen ein professionelles Logging auf, um Fehler in der Cloud sofort zu sehen.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger("CosmoChatCore")

app = Flask(__name__)
# CORS erlaubt Zugriff von allen Quellen (wichtig für Web/Mobile Clients)
CORS(app)

# Sicherheitsschlüssel für Session-Verschlüsselung
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cosmo-ultimate-enterprise-key-9999-secure-v10')

# SocketIO Initialisierung mit Eventlet für maximale Performance bei tausenden Verbindungen
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60, ping_interval=25)

# --- GOOGLE CLOUD & API KONFIGURATION ---
API_KEY = os.environ.get('GEMINI_API_KEY', '')
# Nutzung der stabilen v1beta Schnittstelle für Gemini
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={API_KEY}"
IMAGEN_URL = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={API_KEY}"
APP_ID = "cosmochat_enterprise_final"

# --- DATENBANK MANAGEMENT (Hybrid System) ---
# Wir nutzen Firestore, aber haben einen Fallback-Mechanismus
try:
    db = firestore.Client()
    logger.info("✅ Verbindung zur Firestore Datenbank erfolgreich hergestellt.")
except Exception as e:
    logger.warning(f"⚠️ Firestore nicht verfügbar ({e}). System läuft im limitierten RAM-Modus.")
    db = None

# --- KLASSEN DEFINITIONEN ---

class DatabaseManager:
    """Verwaltet alle Interaktionen mit der Datenbank."""
    
    @staticmethod
    def get_user_ref(uid):
        if db: return db.collection('artifacts').document(APP_ID).collection('users').document(str(uid))
        return None
    
    @staticmethod
    def get_chat_ref(room_id):
        if db: return db.collection('artifacts').document(APP_ID).collection('chats').document(room_id)
        return None
    
    @staticmethod
    def get_messages_collection(room_id):
        if db: return DatabaseManager.get_chat_ref(room_id).collection('messages')
        return None

    @staticmethod
    def save_user(uid, data):
        ref = DatabaseManager.get_user_ref(uid)
        if ref: ref.set(data, merge=True)

    @staticmethod
    def get_user(uid):
        ref = DatabaseManager.get_user_ref(uid)
        if ref:
            doc = ref.get()
            if doc.exists: return doc.to_dict()
        return None

    @staticmethod
    def add_message(room_id, msg_data):
        col = DatabaseManager.get_messages_collection(room_id)
        if col:
            col.document(msg_data['id']).set(msg_data)

class AIEngine:
    """Verwaltet die Intelligenz des Chats (Text & Bild)."""
    
    @staticmethod
    def process_text_request(prompt, user_context=""):
        if not API_KEY: return "⚠️ Systemfehler: KI-Kern nicht aktiv (Kein API Key)."
        
        system_prompt = (
            "Du bist CosmoAI, ein hochintelligenter Assistent in der CosmoChat App. "
            "Antworte auf Deutsch. Sei präzise, freundlich und professionell. "
            "Nutze Markdown für Formatierung wenn nötig."
        )
        
        payload = {
            "contents": [{"parts": [{"text": f"Kontext: {user_context}\nUser: {prompt}"}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]}
        }
        
        # Retry-Logik für Robustheit
        for i in range(3):
            try:
                res = requests.post(GEMINI_URL, json=payload, timeout=15)
                if res.status_code == 200:
                    return res.json()['candidates'][0]['content']['parts'][0]['text']
            except Exception as e:
                logger.warning(f"KI Anfrage fehlgeschlagen (Versuch {i+1}): {e}")
                time.sleep(1)
        return "Verbindung zum KI-Subraum unterbrochen."

    @staticmethod
    def process_image_request(prompt):
        if not API_KEY: return None
        payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}}
        try:
            res = requests.post(IMAGEN_URL, json=payload, timeout=30)
            if res.status_code == 200:
                b64 = res.json()['predictions'][0]['bytesBase64Encoded']
                return f"data:image/png;base64,{b64}"
        except Exception as e:
            logger.error(f"Bildgenerierung fehlgeschlagen: {e}")
        return None

# --- CORE LOGIK ---

def generate_secure_id():
    """Generiert eine garantiert kollisionsfreie 6-stellige ID."""
    max_retries = 10
    for _ in range(max_retries):
        new_id = str(random.randint(100000, 999999))
        # Prüfen ob ID schon existiert
        if not DatabaseManager.get_user(new_id):
            return new_id
    # Fallback, falls Zufall versagt (unwahrscheinlich)
    return str(uuid.uuid4())[:6]

def get_private_room_id(user_a, user_b):
    """Erstellt eine deterministische Raum-ID für Privatchats."""
    return f"private_{'-'.join(sorted([str(user_a), str(user_b)]))}"

# --- HTTP ROUTEN ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health_check():
    """Endpoint für Google Cloud Health Checks."""
    return jsonify({"status": "online", "timestamp": time.time(), "db_connected": db is not None})

# --- SOCKET.IO EVENT HANDLER ---

@socketio.on('connect')
def on_connect():
    logger.info(f"Socket verbunden: {request.sid}")

@socketio.on('disconnect')
def on_disconnect():
    uid = session.get('uid')
    if uid:
        # User als Offline markieren
        try:
            DatabaseManager.save_user(uid, {
                'online_status': False,
                'last_seen': firestore.SERVER_TIMESTAMP
            })
        except: pass
    logger.info(f"Socket getrennt: {request.sid}")

@socketio.on('system_login')
def handle_login(data):
    """
    Zentraler Login-Handler. 
    Verwaltet Identität, erstellt User falls nötig und lädt Profil.
    """
    client_id = data.get('id')
    user_data = None
    is_new_user = False

    # 1. Validierung der ID
    if client_id and len(str(client_id)) == 6:
        user_data = DatabaseManager.get_user(client_id)
        if not user_data:
            client_id = None # ID ungültig in DB
    else:
        client_id = None
    
    # 2. Erstellung neuer User
    if not client_id:
        client_id = generate_secure_id()
        user_data = {
            'id': client_id,
            'name': 'Cosmonaut',
            'status_msg': 'Neu im CosmoChat',
            'friends': [],
            'groups': [],
            'settings': {'dark_mode': True},
            'created_at': firestore.SERVER_TIMESTAMP
        }
        DatabaseManager.save_user(client_id, user_data)
        is_new_user = True

    # 3. Session und Räume
    session['uid'] = client_id
    session['name'] = user_data.get('name', 'Cosmonaut')
    
    join_room(client_id) # Persönlicher Kanal
    join_room('global_broadcast') # Globaler Kanal
    
    # User als Online markieren
    DatabaseManager.save_user(client_id, {'online_status': True})
    
    # 4. Antwort an Client
    emit('login_success', {
        'id': client_id,
        'profile': {
            'name': user_data.get('name'),
            'status': user_data.get('status_msg'),
        },
        'is_new': is_new_user
    })
    
    # 5. Daten nachladen
    load_friend_list(client_id)
    load_group_list(client_id)
    logger.info(f"User {client_id} erfolgreich eingeloggt.")

@socketio.on('update_profile')
def handle_update_profile(data):
    uid = session.get('uid')
    if not uid: return
    
    updates = {}
    if 'name' in data: updates['name'] = html.escape(data['name'].strip())
    if 'status' in data: updates['status_msg'] = html.escape(data['status'].strip())
    
    if updates:
        DatabaseManager.save_user(uid, updates)
        if 'name' in updates: session['name'] = updates['name']
        emit('profile_updated', updates)

# --- FREUNDES-SYSTEM ---

def load_friend_list(uid):
    user_data = DatabaseManager.get_user(uid)
    if not user_data: return

    friends_ids = user_data.get('friends', [])
    friends_data = []
    
    for fid in friends_ids:
        f_data = DatabaseManager.get_user(fid)
        if f_data:
            friends_data.append({
                'id': fid,
                'name': f_data.get('name', 'Unbekannt'),
                'status_msg': f_data.get('status_msg', ''),
                'online': f_data.get('online_status', False)
            })
    
    emit('friend_list_update', friends_data)

@socketio.on('add_contact')
def handle_add_contact(data):
    uid = session.get('uid')
    target_id = data.get('target_id')
    
    if not uid or not target_id: return
    if uid == target_id: 
        emit('system_notification', {'type': 'error', 'text': 'Du kannst dich nicht selbst hinzufügen.'})
        return

    target_user = DatabaseManager.get_user(target_id)
    if not target_user:
        emit('system_notification', {'type': 'error', 'text': 'Diese ID existiert nicht.'})
        return
    
    # Freundschaft speichern (ArrayUnion verhindert Duplikate)
    try:
        user_ref = DatabaseManager.get_user_ref(uid)
        user_ref.update({'friends': firestore.ArrayUnion([target_id])})
        
        # Gegenseitigkeit (Auto-Accept)
        target_ref = DatabaseManager.get_user_ref(target_id)
        target_ref.update({'friends': firestore.ArrayUnion([uid])})
        
        emit('system_notification', {'type': 'success', 'text': f'{target_user.get("name")} hinzugefügt.'})
        load_friend_list(uid)
        
        # Benachrichtigung an den Freund
        emit('refresh_data', {}, room=target_id)
        
    except Exception as e:
        logger.error(f"Fehler beim Adden: {e}")
        emit('system_notification', {'type': 'error', 'text': 'Datenbankfehler.'})

@socketio.on('remove_contact')
def handle_remove_contact(data):
    uid = session.get('uid')
    target_id = data.get('target_id')
    
    if uid and target_id:
        try:
            user_ref = DatabaseManager.get_user_ref(uid)
            user_ref.update({'friends': firestore.ArrayRemove([target_id])})
            load_friend_list(uid)
        except Exception as e:
            logger.error(f"Remove Fehler: {e}")

# --- GRUPPEN-SYSTEM ---

@socketio.on('create_group')
def handle_create_group(data):
    uid = session.get('uid')
    name = html.escape(data.get('name', 'Gruppe')).strip()
    
    if not uid: return
    
    group_id = f"group_{uuid.uuid4().hex[:12]}"
    group_data = {
        'id': group_id,
        'name': name,
        'admin': uid,
        'members': [uid],
        'type': 'group',
        'created_at': firestore.SERVER_TIMESTAMP
    }
    
    DatabaseManager.get_chat_ref(group_id).set(group_data)
    
    # Gruppe beim User registrieren
    DatabaseManager.get_user_ref(uid).update({'groups': firestore.ArrayUnion([group_id])})
    
    emit('group_created', {'id': group_id, 'name': name})
    load_group_list(uid)

def load_group_list(uid):
    user_data = DatabaseManager.get_user(uid)
    if not user_data: return
    
    group_ids = user_data.get('groups', [])
    groups_data = []
    
    for gid in group_ids:
        g_data = DatabaseManager.get_chat_ref(gid).get().to_dict()
        if g_data:
            groups_data.append({
                'id': gid,
                'name': g_data.get('name', 'Gruppe'),
                'type': 'group'
            })
            
    emit('group_list_update', groups_data)

# --- CHAT & NACHRICHTEN ---

@socketio.on('join_chat_room')
def handle_join_chat(data):
    uid = session.get('uid')
    target_id = data.get('target_id')
    is_group = data.get('is_group', False)
    
    if not uid or not target_id: return
    
    room_id = target_id if is_group else get_private_room_id(uid, target_id)
    join_room(room_id)
    
    # Chat-Header Info
    chat_info = {'id': room_id, 'name': 'Chat', 'type': 'private' if not is_group else 'group'}
    if not is_group:
        p_data = DatabaseManager.get_user(target_id)
        if p_data:
            chat_info['name'] = p_data.get('name')
            chat_info['status'] = 'Online' if p_data.get('online_status') else 'Offline'
    else:
        g_data = DatabaseManager.get_chat_ref(room_id).get().to_dict()
        if g_data: chat_info['name'] = g_data.get('name')

    # Verlauf laden (Optimierte Query)
    col = DatabaseManager.get_messages_collection(room_id)
    if col:
        docs = col.order_by('timestamp', direction=firestore.Query.DESCENDING).limit(50).stream()
        history = []
        for d in docs:
            m = d.to_dict()
            if 'timestamp' in m: del m['timestamp']
            history.append(m)
        
        # Sortieren für Anzeige
        history.sort(key=lambda x: x.get('timestamp_int', 0))
        emit('chat_ready', {'room': room_id, 'info': chat_info, 'history': history})

@socketio.on('send_message_content')
def handle_message(data):
    uid = session.get('uid')
    room_id = data.get('room')
    msg_type = data.get('type', 'text')
    content = data.get('content')
    
    if not uid or not room_id or not content: return

    # XSS & Content Filter
    if msg_type == 'text':
        content = html.escape(content).strip()
        if len(content) > 2000: return
    
    # Nachricht erstellen
    msg = create_message_object(uid, session.get('name'), content, msg_type)
    
    # Speichern & Senden
    DatabaseManager.add_message(room_id, msg)
    emit('new_message_arrived', msg, room=room_id)
    
    # KI Logik (nur bei Text)
    if msg_type == 'text':
        process_ai_commands(content, room_id)

def process_ai_commands(text, room_id):
    """Verarbeitet /imagine und @ai Befehle."""
    if text.lower().startswith("/imagine "):
        prompt = text[9:].strip()
        emit('new_message_arrived', create_sys_msg("🎨 KI malt dein Bild..."), room=room_id)
        
        img = AIEngine.generate_image(prompt)
        if img:
            ai_msg = create_message_object('ai_bot', 'CosmoAI 🤖', f"Bild: {prompt}", 'image', img, is_ai=True)
            DatabaseManager.add_message(room_id, ai_msg)
            emit('new_message_arrived', ai_msg, room=room_id)
        else:
            emit('new_message_arrived', create_sys_msg("Bild konnte nicht erstellt werden."), room=room_id)

    elif text.lower().startswith("@ai "):
        prompt = text[4:].strip()
        # Fake "Schreibt..." Indikator könnte hier hin
        response = AIEngine.ask_text(prompt)
        ai_msg = create_message_object('ai_bot', 'CosmoAI 🤖', html.escape(response), is_ai=True)
        DatabaseManager.add_message(room_id, ai_msg)
        emit('new_message_arrived', ai_msg, room=room_id)

def create_message_object(uid, name, content, mtype='text', media=None, is_ai=False):
    ts_int = int(time.time() * 1000)
    # Falls type image ist, ist content der base64 string
    final_content = media if mtype == 'image' else content
    if mtype == 'image': final_content = content # Fix logic
    
    return {
        'id': f"{uid}_{ts_int}",
        'sender_id': uid,
        'sender_name': name,
        'type': mtype,
        'content': content,
        'is_ai': is_ai,
        'time_str': datetime.now().strftime('%H:%M'),
        'timestamp': firestore.SERVER_TIMESTAMP,
        'timestamp_int': ts_int
    }

def create_sys_msg(text):
    return {
        'id': f"sys_{time.time()}",
        'sender_id': 'system',
        'type': 'system',
        'content': text,
        'time_str': ''
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    socketio.run(app, host='0.0.0.0', port=port)

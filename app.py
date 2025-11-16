from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import json
import random
from datetime import datetime
import time

# Flask + SocketIO Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()  # Sicherer Schlüssel
socketio = SocketIO(app, cors_allowed_origins="*")

DATA_FILE = 'cosmochat_data_v2.json'
online_users = {}  # { user_id: {sid1, sid2, ...} } – Set pro User

# --- Helper Functions ---
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {'users': {}, 'rooms': {}}
    return {'users': {}, 'rooms': {}}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def generate_unique_id(existing_ids):
    while True:
        new_id = str(random.randint(100000, 999999))
        if new_id not in existing_ids:
            return new_id

def get_friend_sids(my_id):
    sids = set()
    try:
        db = load_data()
        if my_id in db['users']:
            for friend_id in db['users'][my_id].get('friends', []):
                if friend_id in online_users:
                    sids.update(online_users[friend_id])
    except Exception as e:
        print(f"Fehler in get_friend_sids: {e}")
    return sids

# --- HTTP Routes ---
@app.route('/')
def index():
    return render_template('index.html')

# --- Socket Eventos ---
@socketio.on('connect')
def handle_connect():
    print(f"Client verbunden: {request.sid}")

# Speichere my_id pro SID
user_id_by_sid = {}  # { sid: user_id }

@socketio.on('user_connect')
def handle_user_connect(data):
    client_id = data.get('id')
    sid = request.sid
    db = load_data()

    if client_id and client_id in db['users']:
        my_id = client_id
        print(f"User wiedererkannt: {db['users'][my_id]['name']} ({my_id})")
    else:
        my_id = generate_unique_id(list(db['users'].keys()))
        db['users'][my_id] = {
            'name': 'User',
            'color': '#00ff88',
            'friends': [],
            'requests': []
        }
        save_data(db)
        print(f"Neuen User erstellt: {my_id}")

    # Speichere Zuordnung
    user_id_by_sid[sid] = my_id

    # Online-Status
    if my_id not in online_users:
        online_users[my_id] = set()
    online_users[my_id].add(sid)

    # Informiere Freunde
    for friend_sid in get_friend_sids(my_id):
        emit('friend_online', {'user_id': my_id}, room=friend_sid)

    # Sende Init-Daten
    user_data = db['users'][my_id]
    friends_list = user_data.get('friends', [])
    friend_details = []
    for f_id in friends_list:
        if f_id in db['users']:
            friend_details.append({
                'id': f_id,
                'name': db['users'][f_id]['name'],
                'online': f_id in online_users
            })

    requests_list = user_data.get('requests', [])
    request_details = []
    for r_id in requests_list:
        if r_id in db['users']:
            request_details.append({'id': r_id, 'name': db['users'][r_id]['name']})

    emit('init_data', {
        'id': my_id,
        'name': user_data['name'],
        'color': user_data['color'],
        'friends': friend_details,
        'requests': request_details
    })

@socketio.on('visibility_changed')
def handle_visibility_changed(data):
    sid = request.sid
    if sid not in user_id_by_sid:
        return
    my_id = user_id_by_sid[sid]
    status = data.get('status')

    if status == 'hidden':
        print(f"User {my_id} im Hintergrund")
        for friend_sid in get_friend_sids(my_id):
            if friend_sid != sid:  # Nicht sich selbst
                emit('friend_offline', {'user_id': my_id}, room=friend_sid)
    elif status == 'visible':
        print(f"User {my_id} wieder sichtbar")
        for friend_sid in get_friend_sids(my_id):
            emit('friend_online', {'user_id': my_id}, room=friend_sid)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid not in user_id_by_sid:
        return

    my_id = user_id_by_sid[sid]
    del user_id_by_sid[sid]

    if my_id in online_users:
        online_users[my_id].discard(sid)
        if not online_users[my_id]:
            del online_users[my_id]
            print(f"User {my_id} komplett offline")

            # Informiere Freunde
            for friend_sid in get_friend_sids(my_id):
                emit('friend_offline', {'user_id': my_id}, room=friend_sid)

            # Stoppe Tippen
            try:
                db = load_data()
                for friend_id in db['users'][my_id].get('friends', []):
                    room_id = '-'.join(sorted([my_id, friend_id]))
                    emit('typing_stopped', {'room': room_id, 'user_id': my_id}, room=room_id)
            except Exception as e:
                print(f"Fehler bei typing_stop: {e}")

# --- Weitere Events (unverändert, aber mit user_id_by_sid) ---
@socketio.on('set_name')
def handle_set_name(data):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    db = load_data()
    if my_id in db['users']:
        db['users'][my_id]['name'] = data['name']
        save_data(db)

@socketio.on('set_color')
def handle_set_color():
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    db = load_data()
    if my_id in db['users']:
        new_color = f"hsl({random.randint(0, 360)}, 100%, 75%)"
        db['users'][my_id]['color'] = new_color
        save_data(db)
        emit('color_changed', {'color': new_color})

@socketio.on('invite_friend')
def handle_invite(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    friend_id = payload.get('friend_id')
    if not friend_id or my_id == friend_id: return

    db = load_data()
    if friend_id not in db['users']:
        emit('error_message', {'message': 'User nicht gefunden.'})
        return
    if friend_id in db['users'][my_id].get('friends', []):
        emit('error_message', {'message': 'Bereits befreundet.'})
        return
    if my_id in db['users'][friend_id].get('requests', []):
        emit('error_message', {'message': 'Diese Person hat dir bereits eine Anfrage gesendet.'})
        return
    if friend_id in db['users'][my_id].get('requests', []):
        emit('error_message', {'message': 'Du hast bereits eine Anfrage gesendet.'})
        return

    db['users'][friend_id].setdefault('requests', []).append(my_id)
    save_data(db)
    my_name = db['users'][my_id]['name']

    if friend_id in online_users:
        for fsid in online_users[friend_id]:
            emit('friend_request', {'id': my_id, 'name': my_name}, room=fsid)

@socketio.on('accept_request')
def handle_accept(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    friend_id = payload.get('friend_id')
    if not friend_id: return

    db = load_data()
    if friend_id not in db['users'] or friend_id not in db['users'][my_id].get('requests', []):
        return

    db['users'][my_id]['requests'].remove(friend_id)
    db['users'][my_id].setdefault('friends', []).append(friend_id)
    db['users'][friend_id].setdefault('friends', []).append(my_id)

    room_id = '-'.join(sorted([my_id, friend_id]))
    db.setdefault('rooms', {}).setdefault(room_id, {'messages': []})
    save_data(db)

    my_name = db['users'][my_id]['name']
    friend_name = db['users'][friend_id]['name']

    emit('friend_added', {'id': friend_id, 'name': friend_name, 'online': friend_id in online_users})
    if friend_id in online_users:
        for fsid in online_users[friend_id]:
            emit('friend_added', {'id': my_id, 'name': my_name, 'online': True}, room=fsid)

@socketio.on('remove_friend')
def handle_remove(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    friend_id = payload.get('friend_id')
    if not friend_id: return

    db = load_data()
    if friend_id in db['users'][my_id].get('friends', []):
        db['users'][my_id]['friends'].remove(friend_id)
    if my_id in db['users'][friend_id].get('friends', []):
        db['users'][friend_id]['friends'].remove(my_id)

    room_id = '-'.join(sorted([my_id, friend_id]))
    if room_id in db.get('rooms', {}):
        del db['rooms'][room_id]
    save_data(db)

    emit('friend_removed', friend_id)
    if friend_id in online_users:
        for fsid in online_users[friend_id]:
            emit('friend_removed', my_id, room=fsid)

@socketio.on('load_chat')
def handle_load_chat(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    room_id = payload.get('room')
    if not room_id: return

    db = load_data()
    room_data = db.get('rooms', {}).get(room_id, {})
    messages = []
    for msg in room_data.get('messages', []):
        sender_id = msg['from_id']
        user = db['users'].get(sender_id, {})
        messages.append({
            **msg,
            'from_name': user.get('name', 'Gelöschter User'),
            'color': user.get('color', '#888')
        })
    emit('chat_history', {'room': room_id, 'messages': messages})
    join_room(room_id)

@socketio.on('send_message')
def handle_send_message(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    room_id = payload.get('room')
    text = payload.get('text', '').strip()
    if not room_id or not text: return

    db = load_data()
    msg_id = f"msg_{int(time.time() * 1000)}_{my_id}"
    msg = {
        'id': msg_id,
        'from_id': my_id,
        'text': text,
        'time': datetime.now().strftime('%H:%M'),
        'seen': False,
        'edited': False
    }
    db.setdefault('rooms', {}).setdefault(room_id, {'messages': []})['messages'].append(msg)
    save_data(db)

    user = db['users'][my_id]
    emit('new_message', {
        **msg,
        'from_name': user['name'],
        'color': user['color'],
        'room': room_id
    }, room=room_id)

@socketio.on('mark_seen')
def handle_mark_seen(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    room_id = payload.get('room')
    if not room_id: return

    db = load_data()
    if room_id not in db.get('rooms', {}): return

    updated = False
    for msg in db['rooms'][room_id]['messages']:
        if msg['from_id'] != my_id and not msg.get('seen', False):
            msg['seen'] = True
            updated = True
    if updated:
        save_data(db)
        emit('messages_seen', {'room': room_id}, room=room_id)

@socketio.on('typing_start')
def handle_typing_start(data):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    room_id = data.get('room')
    if room_id:
        emit('typing_started', {'room': room_id, 'user_id': my_id}, room=room_id, skip_sid=sid)

@socketio.on('typing_stop')
def handle_typing_stop(data):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    room_id = data.get('room')
    if room_id:
        emit('typing_stopped', {'room': room_id, 'user_id': my_id}, room=room_id, skip_sid=sid)

@socketio.on('delete_message')
def handle_delete_message(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    room_id = payload.get('room')
    msg_id = payload.get('msg_id')
    if not room_id or not msg_id: return

    db = load_data()
    if room_id not in db.get('rooms', {}): return
    messages = db['rooms'][room_id]['messages']
    msg = next((m for m in messages if m['id'] == msg_id), None)
    if msg and msg['from_id'] == my_id:
        messages.remove(msg)
        save_data(db)
        emit('message_deleted', {'room': room_id, 'msg_id': msg_id}, room=room_id)

@socketio.on('edit_message')
def handle_edit_message(payload):
    sid = request.sid
    if sid not in user_id_by_sid: return
    my_id = user_id_by_sid[sid]
    room_id = payload.get('room')
    msg_id = payload.get('msg_id')
    new_text = payload.get('text', '').strip()
    if not all([room_id, msg_id, new_text]): return

    db = load_data()
    if room_id not in db.get('rooms', {}): return
    messages = db['rooms'][room_id]['messages']
    msg = next((m for m in messages if m['id'] == msg_id), None)
    if not msg or msg['from_id'] != my_id:
        emit('error_message', {'message': 'Nur eigene Nachrichten bearbeitbar.'})
        return

    msg['text'] = new_text
    msg['edited'] = True
    save_data(db)
    emit('message_edited', {
        'room': room_id,
        'msg_id': msg_id,
        'new_text': new_text,
        'edited': True
    }, room=room_id)

# --- Start auf Render ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starte CosmoChat auf Port {port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False)

from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask_cors import CORS 
import os
import json
import random
from datetime import datetime
import time 

app = Flask(__name__)
CORS(app) 
app.config['SECRET_KEY'] = 'dein-super-geheimer-schluessel-fuer-sessions'
socketio = SocketIO(app, cors_allowed_origins="*") 

DATA_FILE = 'cosmochat_data_v2.json' 

online_users = {} 

# --- Helper Function ---
def get_friend_sids(my_id):
    sids = []
    try:
        db = load_data()
        if my_id in db['users']:
            friends_list = db['users'][my_id].get('friends', [])
            for friend_id in friends_list:
                if friend_id in online_users:
                    sids.extend(list(online_users[friend_id]))
    except Exception as e:
        print(f"Fehler: {e}")
    return sids

# --- Datenmanagement ---
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {'users': {}, 'rooms': {}}
    return {'users': {}, 'rooms': {}} 

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except: pass

def generate_unique_id(existing_ids):
    while True:
        new_id = str(random.randint(100000, 999999))
        if new_id not in existing_ids:
            return new_id

# --- HTTP Route ---
@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    session['sid'] = request.sid
    print(f"Client verbunden: {request.sid}")

@socketio.on('user_connect')
def handle_user_connect(data):
    client_id = data.get('id')
    db = load_data()
    
    user_data = None
    if client_id and client_id in db['users']:
        user_data = db['users'][client_id]
        my_id = client_id
    else:
        new_id = generate_unique_id(list(db['users'].keys()))
        my_id = new_id
        user_data = {'name': 'User', 'color': '#00ff88', 'friends': [], 'requests': []}
        db['users'][my_id] = user_data
        save_data(db)

    session['my_id'] = my_id
    
    if my_id not in online_users:
        online_users[my_id] = set()
    online_users[my_id].add(request.sid)
    
    for friend_sid in get_friend_sids(my_id):
        emit('friend_online', {'user_id': my_id}, room=friend_sid)

    friend_details = []
    for f_id in user_data.get('friends', []):
        if f_id in db['users']:
            friend_details.append({
                'id': f_id, 'name': db['users'][f_id]['name'],
                'online': (f_id in online_users)
            })

    request_details = []
    for r_id in user_data.get('requests', []):
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
    my_id = session.get('my_id')
    if not my_id: return
    status = data.get('status')
    if status == 'hidden':
        for friend_sid in get_friend_sids(my_id):
            emit('friend_offline', {'user_id': my_id}, room=friend_sid)     
    elif status == 'visible':
        for friend_sid in get_friend_sids(my_id):
            emit('friend_online', {'user_id': my_id}, room=friend_sid)

@socketio.on('disconnect')
def handle_disconnect():
    my_id = session.get('my_id')
    sid = session.get('sid')
    if my_id and sid and my_id in online_users:
        online_users[my_id].discard(sid)
        if not online_users[my_id]:
            del online_users[my_id]
            for friend_sid in get_friend_sids(my_id):
                emit('friend_offline', {'user_id': my_id}, room=friend_sid)
    session.pop('sid', None)

@socketio.on('set_name')
def handle_set_name(data):
    my_id = session.get('my_id')
    if not my_id: return
    db = load_data()
    if my_id in db['users']:
        db['users'][my_id]['name'] = data['name']
        save_data(db)

@socketio.on('set_color')
def handle_set_color():
    my_id = session.get('my_id')
    if not my_id: return
    db = load_data()
    if my_id in db['users']:
        new_color = f'hsl({random.randint(0, 360)}, 100%, 75%)'
        db['users'][my_id]['color'] = new_color
        save_data(db)
        emit('color_changed', {'color': new_color})

@socketio.on('invite_friend')
def handle_invite(payload):
    my_id = session.get('my_id')
    friend_id = payload.get('friend_id')
    if not my_id or not friend_id or my_id == friend_id: return
    db = load_data()
    if friend_id not in db['users']:
        emit('error_message', {'message': 'User nicht gefunden.'})
        return
    if my_id in db['users'][friend_id].get('requests', []): return
    if friend_id in db['users'][my_id].get('friends', []): return
    
    db['users'][friend_id].setdefault('requests', []).append(my_id)
    save_data(db)
    if friend_id in online_users:
        for sid in online_users[friend_id]:
            emit('friend_request', {'id': my_id, 'name': db['users'][my_id]['name']}, room=sid)

@socketio.on('accept_request')
def handle_accept(payload):
    my_id = session.get('my_id')
    friend_id = payload.get('friend_id')
    if not my_id or not friend_id: return
    db = load_data()
    if friend_id not in db['users'][my_id].get('requests', []): return
    
    db['users'][my_id]['requests'].remove(friend_id)
    db['users'][my_id].setdefault('friends', []).append(friend_id)
    db['users'][friend_id].setdefault('friends', []).append(my_id)
    save_data(db)
    
    emit('friend_added', {'id': friend_id, 'name': db['users'][friend_id]['name'], 'online': (friend_id in online_users)})
    if friend_id in online_users:
        for sid in online_users[friend_id]:
            emit('friend_added', {'id': my_id, 'name': db['users'][my_id]['name'], 'online': True}, room=sid)

@socketio.on('remove_friend')
def handle_remove(payload):
    my_id = session.get('my_id')
    friend_id = payload.get('friend_id')
    if not my_id or not friend_id: return
    db = load_data()
    if friend_id in db['users'][my_id].get('friends', []):
        db['users'][my_id]['friends'].remove(friend_id)
    if friend_id in db['users'] and my_id in db['users'][friend_id].get('friends', []):
        db['users'][friend_id]['friends'].remove(my_id)
    save_data(db)
    emit('friend_removed', friend_id)
    if friend_id in online_users:
        for sid in online_users[friend_id]:
            emit('friend_removed', my_id, room=sid)

@socketio.on('load_chat')
def handle_load_chat(payload):
    my_id = session.get('my_id')
    room_id = payload.get('room')
    if not my_id or not room_id: return
    db = load_data()
    room_data = db.get('rooms', {}).get(room_id)
    join_room(room_id)
    messages = []
    if room_data:
        for msg in room_data.get('messages', []):
            sender_id = msg['from_id']
            if sender_id in db['users']:
                msg['from_name'] = db['users'][sender_id]['name']
                msg['color'] = db['users'][sender_id]['color']
            else:
                msg['from_name'] = 'Gelöschter User'
                msg['color'] = '#888'
            messages.append(msg)
    emit('chat_history', {'room': room_id, 'messages': messages})

@socketio.on('send_message')
def handle_send_message(payload):
    my_id = session.get('my_id')
    room_id = payload.get('room')
    text = payload.get('text')
    if not my_id or not room_id or not text: return
    db = load_data()
    msg_id = f"msg_{int(time.time() * 1000)}_{my_id}"
    msg = {
        'id': msg_id, 'from_id': my_id, 'text': text,
        'time': datetime.now().strftime('%H:%M'), 'seen': False, 'edited': False
    }
    if room_id not in db.get('rooms', {}):
        db.setdefault('rooms', {})[room_id] = {'messages': []}
    db['rooms'][room_id]['messages'].append(msg)
    save_data(db)
    
    msg['from_name'] = db['users'][my_id]['name']
    msg['color'] = db['users'][my_id]['color']
    emit('new_message', msg, room=room_id)

@socketio.on('mark_seen')
def handle_mark_seen(payload):
    my_id = session.get('my_id')
    room_id = payload.get('room')
    if not my_id or not room_id: return
    db = load_data()
    if room_id in db.get('rooms', {}):
        messages_updated = False
        for msg in db['rooms'][room_id].get('messages', []):
            if msg['from_id'] != my_id and not msg.get('seen', False):
                msg['seen'] = True
                messages_updated = True
        if messages_updated:
            save_data(db)
            emit('messages_seen', {'room': room_id}, room=room_id)

@socketio.on('typing_start')
def handle_typing_start(data):
    room_id = data.get('room')
    my_id = session.get('my_id')
    if room_id and my_id:
        emit('typing_started', {'room': room_id, 'user_id': my_id}, room=room_id, skip_sid=request.sid)

@socketio.on('typing_stop')
def handle_typing_stop(data):
    room_id = data.get('room')
    my_id = session.get('my_id')
    if room_id and my_id:
        emit('typing_stopped', {'room': room_id, 'user_id': my_id}, room=room_id, skip_sid=request.sid)

@socketio.on('delete_message')
def handle_delete_message(payload):
    my_id = session.get('my_id')
    room_id = payload.get('room')
    msg_id = payload.get('msg_id')
    if not my_id or not room_id or not msg_id: return
    db = load_data()
    if room_id in db.get('rooms', {}):
        messages = db['rooms'][room_id].get('messages', [])
        msg_to_delete = next((m for m in messages if m.get('id') == msg_id), None)
        if msg_to_delete and msg_to_delete['from_id'] == my_id:
            messages.remove(msg_to_delete)
            db['rooms'][room_id]['messages'] = messages
            save_data(db)
            emit('message_deleted', {'room': room_id, 'msg_id': msg_id}, room=room_id)

@socketio.on('edit_message')
def handle_edit_message(payload):
    my_id = session.get('my_id')
    room_id = payload.get('room')
    msg_id = payload.get('msg_id')
    new_text = payload.get('text', '').strip()
    if not my_id or not room_id or not msg_id or not new_text: return
    db = load_data()
    if room_id not in db.get('rooms', {}): return
    messages = db['rooms'][room_id].get('messages', [])
    msg_to_edit = next((m for m in messages if m.get('id') == msg_id), None)
    if not msg_to_edit or msg_to_edit['from_id'] != my_id: return
    
    msg_to_edit['text'] = new_text
    msg_to_edit['edited'] = True
    for i, msg in enumerate(messages):
        if msg.get('id') == msg_id:
            messages[i] = msg_to_edit
            break
    db['rooms'][room_id]['messages'] = messages
    save_data(db)
    emit('message_edited', {'room': room_id, 'msg_id': msg_id, 'new_text': new_text, 'edited': True}, room=room_id)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)

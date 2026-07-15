from flask import request, session, Blueprint, jsonify
from ext import *
from db import *
from flask_socketio import emit, join_room, leave_room
from voice_token import make_token
from ratelimit import limit_event

app = Blueprint("bcalls", "bcalls")

calls = {}
in_call = []
servers = {
    "Moscow, RU": "moscow.clody.lol",
    "Tel Aviv, IS": "israil.clody.lol"
}

def unauthorized():
    emit("error", {"cause": "Not Authorized"})

def detach_user(call, user_id):
    if user_id in call["members"]:
        call["members"].remove(user_id)
    if user_id in call["waiting"]:
        call["waiting"].remove(user_id)
    if user_id in call["mic_off"]:
        call["mic_off"].remove(user_id)

    call["sharing_screen"].pop(user_id, None)
    for watchers in call["sharing_screen"].values():
        if user_id in watchers:
            watchers.remove(user_id)

def settle_call(call_id):
    call = calls.get(call_id)
    if call is None:
        return

    if call["members"]:
        socketio.emit("update", call, namespace="/bcalls", to=call_id)
    else:
        for waiting in call["waiting"]:
            socketio.emit("stop_call", {"id": call_id}, to=waiting)
        calls.pop(call_id, None)

@socketio.on("start_call")
@limit_event(10, burst=3)
def start_call(data):
    if not check_session(session):
        unauthorized()
        return

    id = data.get("id")
    server = data.get("server_addr")
    if id is None:
        emit("error", {"cause": "Bad Request"})
        return

    branch = Branch.query.filter_by(id=id).first()
    if branch is None:
        emit("error", {"cause": "This branch doesn't exist"})
        return
    elif session["user"]["id"] not in (branch.members or []):
        emit("error", {"cause": "You aren't member"})
        return
    elif calls.get(id):
        emit("error", {"cause": "This branch has a call"})
        return

    if server is not None and server not in servers.values():
        emit("error", {"cause": "Bad Request"})
        return

    members = [m for m in (branch.members or []) if m != session["user"]["id"]]

    calls[id] = {
        "id": id,
        "members": [session["user"]["id"]],
        "waiting": members,
        "mic_off": [],
        "sharing_screen": {},
        "server_addr": server
    }

    for member in members:
        emit("new_call", calls[id], to=member)

    emit("started_call", calls[id])

@socketio.on("connect", namespace="/bcalls")
def bcall_connect():
    if session.get("user") is None:
        raise ConnectionRefusedError("Not Authorized")
    elif session["user"]["id"] in in_call:
        emit("error", {"cause": "You are in voice"})
        return

    in_call.append(session["user"]["id"])

    user_id = session["user"]["id"]
    for call_id, call in calls.items():
        if user_id in call["members"]:
            join_room(call_id, namespace="/bcalls")

@socketio.on("disconnect", namespace="/bcalls")
def bcall_disconnect():
    if session.get("user") is None:
        return

    user_id = session["user"]["id"]

    if user_id in in_call:
        in_call.remove(user_id)

    for call_id in list(calls.keys()):
        call = calls.get(call_id)
        if call is None:
            continue
        if user_id not in call["members"] and user_id not in call["waiting"]:
            continue

        detach_user(call, user_id)
        settle_call(call_id)

@socketio.on("mic_toggle", namespace="/bcalls")
@limit_event(60, burst=15)
def toggle_mic(data):
    if not check_session(session):
        unauthorized()
        return

    id = data.get("id")
    off = data.get("off")
    if id is None or off is None:
        emit("error", {"cause": "Bad Request"})
        return
    elif calls.get(id) is None:
        emit("error", {"cause": "This call doesn't exist"})
        return
    elif session["user"]["id"] not in calls[id]["members"]:
        emit("error", {"cause": "You aren't member"})
        return

    if off:
        if session["user"]["id"] not in calls[id]["mic_off"]:
            calls[id]["mic_off"].append(session["user"]["id"])
    else:
        if session["user"]["id"] in calls[id]["mic_off"]:
            calls[id]["mic_off"].remove(session["user"]["id"])

    emit("update", calls[id], namespace="/bcalls", to=id)

@socketio.on("toggle_screen_sharing", namespace="/bcalls")
@limit_event(30, burst=10)
def toggle_ss(data):
    if not check_session(session):
        unauthorized()
        return

    id = data.get("id")
    off = data.get("off")
    if id is None or off is None:
        emit("error", {"cause": "Bad Request"})
        return
    elif calls.get(id) is None:
        emit("error", {"cause": "This call doesn't exist"})
        return
    elif session["user"]["id"] not in calls[id]["members"]:
        emit("error", {"cause": "You aren't member"})
        return

    if not off:
        calls[id]["sharing_screen"][session["user"]["id"]] = []
    else:
        calls[id]["sharing_screen"].pop(session["user"]["id"], None)

    emit("update", calls[id], namespace="/bcalls", to=id)

@socketio.on("toggle_watching_screen_sharing", namespace="/bcalls")
@limit_event(60, burst=20)
def toggle_ss_watching(data):
    if not check_session(session):
        unauthorized()
        return

    id = data.get("id")
    off = data.get("off")
    author = data.get("author")
    if id is None or off is None or author is None:
        emit("error", {"cause": "Bad Request"})
        return
    elif calls.get(id) is None:
        emit("error", {"cause": "This call doesn't exist"})
        return
    elif session["user"]["id"] not in calls[id]["members"]:
        emit("error", {"cause": "You aren't member"})
        return
    elif calls[id]["sharing_screen"].get(author) is None:
        emit("error", {"cause": "Bad Request"})
        return

    watchers = calls[id]["sharing_screen"][author]
    if not off:
        if session["user"]["id"] not in watchers:
            watchers.append(session["user"]["id"])
    else:
        if session["user"]["id"] in watchers:
            watchers.remove(session["user"]["id"])

    emit("update", calls[id], namespace="/bcalls", to=id)

@socketio.on("join_call", namespace="/bcalls")
@limit_event(20, burst=5)
def join_call(data):
    if not check_session(session):
        unauthorized()
        return

    id = data.get("id")
    if id is None:
        emit("error", {"cause": "Bad Request"})
        return
    elif calls.get(id) is None:
        emit("error", {"cause": "This call doesn't exist"})
        return

    branch = Branch.query.filter_by(id=id).first()
    if branch is None or session["user"]["id"] not in (branch.members or []):
        emit("error", {"cause": "You aren't member"})
        return

    join_room(id, namespace="/bcalls")

    if session["user"]["id"] not in calls[id]["members"]:
        calls[id]["members"].append(session["user"]["id"])
    if session["user"]["id"] in calls[id]["waiting"]:
        calls[id]["waiting"].remove(session["user"]["id"])

    emit("update", calls[id], namespace="/bcalls", to=id)

@socketio.on("leave_call", namespace="/bcalls")
@limit_event(20, burst=5)
def leave_call(data):
    if not check_session(session):
        unauthorized()
        return

    id = data.get("id")
    if id is None:
        emit("error", {"cause": "Bad Request"})
        return
    elif calls.get(id) is None:
        emit("error", {"cause": "This call doesn't exist"})
        return
    elif session["user"]["id"] not in calls[id]["members"]:
        emit("error", {"cause": "You aren't member"})
        return

    detach_user(calls[id], session["user"]["id"])
    settle_call(id)

    leave_room(id, namespace="/bcalls")

@socketio.on("reject_call", namespace="/bcalls")
@limit_event(20, burst=5)
def reject_call(data):
    if not check_session(session):
        unauthorized()
        return

    id = data.get("id")
    if id is None:
        emit("error", {"cause": "Bad Request"})
        return
    elif calls.get(id) is None:
        emit("error", {"cause": "This call doesn't exist"})
        return
    elif session["user"]["id"] not in calls[id]["waiting"]:
        emit("error", {"cause": "You aren't waiting"})
        return

    calls[id]["waiting"].remove(session["user"]["id"])

    emit("update", calls[id], namespace="/bcalls",  to=id)


@app.route("/api/calls/get", methods=["POST"])
def get_calls():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    branch = Branch.query.filter_by(id=id).first()
    if branch is None or session["user"]["id"] not in (branch.members or []):
        return jsonify("Forbidden"), 403

    return jsonify(calls.get(id)), 200

@app.route("/api/calls/servers")
def get_servers():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    return jsonify(servers), 200

@app.route("/api/calls/token", methods=["POST"])
def call_token():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    branch = Branch.query.filter_by(id=id).first()
    if branch is None or session["user"]["id"] not in branch.members:
        return jsonify("Forbidden"), 403

    token = make_token(session["user"]["id"], id)
    return jsonify({"token": token}), 200
from flask import Blueprint, request, session, jsonify
from ext import *
from db import *
import json

app = Blueprint("friends", "friends")
requests = {}

@app.route("/api/friends/get")
def friends_get():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    friends = data.get("friends") or []
    enemies = data.get("enemies") or []

    return jsonify({
        "friends": friends,
        "enemies": enemies,
        "friend_requests": requests.get(user.id, []),
    }), 200

@app.route("/api/friends/send_request", methods=["POST"])
def send_request():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    to = request.json.get("to")
    if to is None:
        return jsonify("Bad Request"), 400

    to_user = User.query.filter_by(username=to).first()
    user = User.query.filter_by(id=session["user"]["id"]).first()

    if to_user is None:
        return jsonify("User hasn't found"), 404

    if to_user.id == session["user"]["id"]:
        return jsonify("Bad Request"), 400

    to_data = load_data(to_user)

    if not (to_data.get("settings") or {}).get("accepts_friend_requests", True) or user.id in (to_data.get("enemies") or []):
        return jsonify("User doesn't love getting a friend's requests"), 403

    existing_friends = load_data(user).get("friends") or []
    if to_user.id in existing_friends:
        return jsonify("Already friends"), 403

    if requests.get(to_user.id) is None:
        requests[to_user.id] = []

    if session["user"]["id"] not in requests[to_user.id]:
        requests[to_user.id].append(session["user"]["id"])

    socketio.emit("friend_request", {"who": session["user"]["id"], "display_name": user.display_name}, to=to_user.id)

    return jsonify("Success"), 200

@app.route("/api/users/get", methods=["POST"])
def get_user():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    username = request.json.get("username")
    id = request.json.get("id")

    if username is None and id is None:
        return jsonify("Bad Requests"), 400

    if id == 0:
        return jsonify({
        "username": "clody",
        "id": 0,
        "display_name": "Clody",
        "is_friend": False,
        "is_enemy": False,
        "online": True,
        "avatar": "/favicon.ico",
    })

    query = User.query
    if id is not None:
        query = query.filter_by(id=id)
    else:
        query = query.filter_by(username=username)

    need = query.first()
    user = User.query.filter_by(id=session["user"]["id"]).first()

    if need is None:
        return jsonify("Not Found"), 404

    data = load_data(need)
    user_data = load_data(user)

    about = {
        "username": need.username,
        "id": need.id,
        "display_name": need.display_name,
        "is_friend": need.id in (user_data.get("friends") or []),
        "is_enemy": need.id in (user_data.get("enemies") or []),
        "online": data.get("online", False),
        "avatar": need.avatar,
        "thought": data.get("thought") or "",
        "color": data.get("color") or "",
        "description": data.get("description") or "",
    }

    is_self = need.id == user.id

    if not is_self and not about["is_friend"] and not (data.get("settings") or {}).get("accepts_friend_requests", True):
        return jsonify("Forbidden"), 403

    return jsonify(about), 200

@app.route("/api/friends/request", methods=["POST"])
def set_request():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    type_request = request.json.get("type")

    if id is None or type_request is None:
        return jsonify("Bad Request"), 400

    pending = requests.get(session["user"]["id"], [])

    if id not in pending:
        return jsonify("Not Found"), 404

    if type_request == 1:
        user = User.query.filter_by(id=session["user"]["id"]).first()
        friend = User.query.filter_by(id=id).first()

        if friend is None:
            return jsonify("Not Found"), 404

        user_data = load_data(user)
        friend_data = load_data(friend)

        user_friends = user_data.get("friends") or []
        friend_friends = friend_data.get("friends") or []

        if friend.id not in user_friends:
            user_friends.append(friend.id)
        if user.id not in friend_friends:
            friend_friends.append(user.id)

        user_data["friends"] = user_friends
        friend_data["friends"] = friend_friends

        user.data = json.dumps(user_data)
        friend.data = json.dumps(friend_data)

        db.session.commit()

        pending.remove(friend.id)

        socketio.emit("accept_request", {"id": user.id}, to=friend.id)
    else:
        pending.remove(id)

        socketio.emit("reject_request", {"id": session["user"]["id"]}, to=id)

    return jsonify("Success"), 200

@app.route("/api/friends/unfriend", methods=["POST"])
def unfriend():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")

    if id is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    unfriend_user = User.query.filter_by(id=id).first()

    if unfriend_user is None:
        return jsonify("Not Found"), 404

    user_data = load_data(user)
    unfriend_data = load_data(unfriend_user)

    user_friends = user_data.get("friends") or []
    other_friends = unfriend_data.get("friends") or []

    if unfriend_user.id in user_friends:
        user_friends.remove(unfriend_user.id)
    if user.id in other_friends:
        other_friends.remove(user.id)

    user_data["friends"] = user_friends
    unfriend_data["friends"] = other_friends

    user.data = json.dumps(user_data)
    unfriend_user.data = json.dumps(unfriend_data)

    db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/friends/set_enemy", methods=["POST"])
def set_enemy():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    type_request = request.json.get("type")

    if id is None or type_request is None or id == session["user"]["id"]:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    enemy = User.query.filter_by(id=id).first()

    if enemy is None:
        return jsonify("Not Found"), 404

    user_data = load_data(user)
    user_friends = user_data.get("friends") or []
    user_enemies = user_data.get("enemies") or []

    if type_request == 1:
        if enemy.id not in user_enemies:
            user_enemies.append(enemy.id)
        if enemy.id in user_friends:
            user_friends.remove(enemy.id)

        enemy_data = load_data(enemy)
        enemy_friends = enemy_data.get("friends") or []
        if user.id in enemy_friends:
            enemy_friends.remove(user.id)
        enemy_data["friends"] = enemy_friends
        enemy.data = json.dumps(enemy_data)
    else:
        if enemy.id in user_enemies:
            user_enemies.remove(enemy.id)

    user_data["friends"] = user_friends
    user_data["enemies"] = user_enemies
    user.data = json.dumps(user_data)

    db.session.commit()
    return jsonify("Success"), 200

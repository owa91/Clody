import time

from flask import Blueprint, request, session, jsonify
from ext import *
from db import *
import json

app = Blueprint("settings", "settings")

@app.route("/api/settings/get")
def get_settings():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    return jsonify({
        "settings": data.get("settings") or {},
        "username": user.username,
        "display_name": user.display_name,
        "avatar": user.avatar,
    }), 200

@app.route("/api/settings/set", methods=["POST"])
def set_settings():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    settings = request.json.get("settings")
    display_name = request.json.get("display_name")

    user = User.query.filter_by(id=session["user"]["id"]).first()

    data = load_data(user)
    if settings is not None:
        data["settings"] = settings
    user.data = json.dumps(data)

    if display_name:
        user.display_name = display_name

    db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/settings/logout_all_devices", methods=["POST"])
def logout_devices():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    data = load_data(user)
    data["logout_devices_at"] = int(time.time())
    user.data = json.dumps(data)

    db.session.commit()

    socketio.emit("logout", to=session["user"]["id"])

    return jsonify("Success"), 200

@app.route("/api/logout", methods=["POST"])
def logout():
    session["user"] = None

    return jsonify("Success"), 200

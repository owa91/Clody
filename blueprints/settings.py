import time
import re

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
        "description": data.get("description") or "",
        "color": data.get("color") or "",
        "thought": data.get("thought") or "",
    }), 200

DESCRIPTION_MAX = 300
THOUGHT_MAX = 100

def clean_color(value):
    if not value:
        return ""
    value = str(value).strip()
    if re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value):
        return value
    return None

@app.route("/api/settings/set", methods=["POST"])
def set_settings():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    body = request.json or {}
    settings = body.get("settings")
    display_name = body.get("display_name")

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    if settings is not None:
        data["settings"] = settings

    if "description" in body:
        text = (body.get("description") or "").strip()
        if len(text) > DESCRIPTION_MAX:
            return jsonify("Too Long"), 400
        data["description"] = text
    if "thought" in body:
        text = (body.get("thought") or "").strip()
        if len(text) > THOUGHT_MAX:
            return jsonify("Too Long"), 400
        data["thought"] = text
    if "color" in body:
        color = clean_color(body.get("color"))
        if color is None:
            return jsonify("Bad Color"), 400
        data["color"] = color

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

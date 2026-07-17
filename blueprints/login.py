from flask import Blueprint, request, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from db import *
from ext import *
from flask_socketio import emit, join_room
import json
import time
from dotenv import load_dotenv
import os
import requests

load_dotenv()

app = Blueprint("login", "login")

@app.route("/api/login", methods=["POST"])
def login():
    username = request.json.get("username")
    password = request.json.get("password")

    if username is None or password is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(username=username).first()

    if user is None:
        return jsonify("Not Found"), 404

    if check_password_hash(user.password, password):
        session.permanent = True
        session["user"] = {"id": user.id, "login_at": time.time()}
        return jsonify("Success"), 200
    else:
        return jsonify("Wrong Password"), 403

@app.route("/api/register", methods=["POST"])
def register():
    username = request.json.get("username")
    password = request.json.get("password")
    token = request.json.get("token")

    if username is None or password is None or token is None:
        return jsonify("Bad Request"), 400
    elif username == "clody" or username == "Clody":
        return jsonify("Username is taken"), 403

    username = username.strip()

    if not username or not password:
        return jsonify("Bad Request"), 400

    request_r = requests.post("https://www.google.com/recaptcha/api/siteverify", data={"secret": os.getenv("RECAPTCHA_TOKEN"), "response": token, "remoteip": request.remote_addr})

    if request_r.status_code == 200:
        if not request_r.json()["success"]:
            return jsonify("You are bot"), 403
    else:
        return jsonify("Recaptcha doesn't work"), 503

    if User.query.filter_by(username=username).first():
        return jsonify("Username is taken"), 403

    user = User(username=username, display_name=username, password=generate_password_hash(password))

    db.session.add(user)
    db.session.commit()

    session.permanent = True
    session["user"] = {"id": user.id, "login_at": time.time()}

    return jsonify("Success"), 200

@socketio.on("connect")
def connect():
    if session.get("user") is None:
        raise ConnectionRefusedError("Not Authorized")

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if user is None:
        raise ConnectionRefusedError("Not Authorized")

    data = load_data(user)

    if data.get("online"):
        raise ConnectionRefusedError("You are online")
    elif data.get("logout_devices_at") is not None and data.get("logout_devices_at") >= session["user"]["login_at"]:
        raise ConnectionRefusedError("Logged out of all sessions")
    elif data.get("warns") is None:
        data["warns"] = []

    if len(data["warns"]) > 5:
        emit("You are banned", data["warns"])
        return

    data["online"] = True

    user.data = json.dumps(data)
    db.session.commit()

    emit("success")
    join_room(user.id)

@socketio.on("disconnect")
def disconnect():
    if session.get("user") is None:
        return

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if user is None:
        return

    data = load_data(user)

    data["online"] = False

    user.data = json.dumps(data)
    db.session.commit()

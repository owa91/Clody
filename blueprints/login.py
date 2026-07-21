from flask import Blueprint, request, session, jsonify, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from db import *
from ext import *
from flask_socketio import emit, join_room
import json
import time
from dotenv import load_dotenv
import os
import requests
import random
import re
import resend
from ua_parser import user_agent_parser

load_dotenv()

app = Blueprint("login", "login")

logins = {}
email_codes = {}

CODE_TTL = 600
RESEND_COOLDOWN = 60
MAX_ATTEMPTS = 5

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

resend.api_key = os.getenv("EMAIL_API_KEY")

def new_code():
    return f"{random.randint(0, 9999):04d}"

def codes_match(stored, given):
    return str(stored) == str(given).strip()

def entry_valid(entry):
    return entry is not None and entry["expires_at"] >= time.time()

def send_email(to, subject, template, **context):
    try:
        resend.Emails.send({
            "from": "noreply@clody.lol",
            "to": to,
            "subject": subject,
            "html": render_template(template, **context),
        })
        return True
    except Exception:
        return False

def describe_device(user_agent):
    if not user_agent:
        return "Неизвестное устройство"
    parsed = user_agent_parser.Parse(user_agent)
    browser = parsed["user_agent"]["family"]
    system = parsed["os"]["family"]
    if browser == "Other" and system == "Other":
        return "Неизвестное устройство"
    return f"{browser} · {system}"

@app.route("/api/verification/set_email", methods=["POST"])
def set_email():
    if not check_session(session, allow_unverified=True):
        return jsonify("Not Authorized"), 400

    email = (request.json.get("email") or "").strip().lower()
    if not email or not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    if data.get("email"):
        return jsonify("Email is linked"), 403

    for other in User.query.all():
        if other.id != user.id and load_data(other).get("email") == email:
            return jsonify("This email is taken"), 403

    pending = email_codes.get(user.id)
    if pending and time.time() - pending["sent_at"] < RESEND_COOLDOWN:
        wait = int(RESEND_COOLDOWN - (time.time() - pending["sent_at"]))
        return jsonify(f"You can generate a new code in {wait} sec."), 429

    code = new_code()
    email_codes[user.id] = {
        "code": code,
        "email": email,
        "expires_at": time.time() + CODE_TTL,
        "attempts": 0,
        "sent_at": time.time(),
    }

    if not send_email(email, "Код для подтверждения аккаунта", "verificate_email.html",
                      code=code, minutes=CODE_TTL // 60):
        del email_codes[user.id]
        return jsonify("Не удалось отправить письмо"), 503

    return jsonify({"email": email, "expires_in": CODE_TTL}), 200

@app.route("/api/verification", methods=["POST"])
def confirm_email():
    if not check_session(session, allow_unverified=True):
        return jsonify("Not Authorized"), 400

    code = request.json.get("code")
    if code is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)
    entry = email_codes.get(user.id)

    if entry is None:
        return jsonify("Forbitten"), 403
    elif not entry_valid(entry):
        del email_codes[user.id]
        return jsonify("Time is up"), 403

    if not codes_match(entry["code"], code):
        entry["attempts"] += 1
        if entry["attempts"] >= MAX_ATTEMPTS:
            del email_codes[user.id]
            return jsonify("Too many requests"), 403
        return jsonify("Неверный код"), 403

    data["email"] = entry["email"]
    data["logout_devices_at"] = int(time.time())
    user.data = json.dumps(data)
    db.session.commit()
    del email_codes[user.id]

    session["user"] = {"id": user.id, "login_at": time.time() + 1}
    session.permanent = True

    return jsonify("Success"), 200

@app.route("/api/verification/login", methods=["POST"])
def send_login_code():
    username = (request.json.get("username") or "").strip()
    password = request.json.get("password")

    if not username or password is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(username=username).first()

    if user is None or not check_password_hash(user.password, password):
        return jsonify("Incorrect username or password"), 403

    data = load_data(user)
    email = data.get("email")
    if not email:
        session.permanent = True
        session["user"] = {"id": user.id, "login_at": time.time()}
        return jsonify({"logged_in": True, "needs_email": True}), 200

    pending = logins.get(username)
    if pending and time.time() - pending.get("sent_at", 0) < RESEND_COOLDOWN:
        wait = int(RESEND_COOLDOWN - (time.time() - pending["sent_at"]))
        return jsonify(f"You can generate a new code in {wait} sec."), 429

    code = new_code()
    logins[username] = {
        "id": user.id,
        "code": code,
        "expires_at": time.time() + CODE_TTL,
        "attempts": 0,
        "sent_at": time.time(),
    }

    if not send_email(email, "Код для входа в аккаунт", "login_to.html",
                      code=code, minutes=CODE_TTL // 60, username=username,
                      device=describe_device(request.headers.get("User-Agent")),
                      ip=request.remote_addr):
        del logins[username]
        return jsonify("Не удалось отправить письмо"), 503

    name, _, domain = email.partition("@")
    hint = f"{name[0]}{'*' * max(1, len(name) - 2)}{name[-1] if len(name) > 1 else ''}@{domain}"

    return jsonify({"email_hint": hint, "expires_in": CODE_TTL}), 200

@app.route("/api/login", methods=["POST"])
def login():
    username = (request.json.get("username") or "").strip()
    code = request.json.get("code")

    if not username or code is None:
        return jsonify("Bad Request"), 400

    entry = logins.get(username)

    if entry is None:
        return jsonify("Сначала запросите код"), 403
    elif not entry_valid(entry):
        del logins[username]
        return jsonify("Срок действия кода истёк"), 403

    if not codes_match(entry["code"], code):
        entry["attempts"] += 1
        if entry["attempts"] >= MAX_ATTEMPTS:
            del logins[username]
            return jsonify("Слишком много попыток — запросите новый код"), 403
        return jsonify("Неверный код"), 403

    user = User.query.filter_by(id=entry["id"]).first()
    if user is None:
        del logins[username]
        return jsonify("Not Found"), 404

    del logins[username]

    session.permanent = True
    session["user"] = {"id": user.id, "login_at": time.time()}

    return jsonify("Success"), 200

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

    if data.get("email") is None:
        emit("verification_required")
        return

    if len(data["warns"]) > 5:
        emit("banned", data["warns"])
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

@app.route("/api/version")
def get_version():
    return os.getenv("VERSION")

# What the cookie is worth, without failing. /app/ asks this before deciding
# where to send someone: the session cookie is HttpOnly, so the client cannot
# read it and has to be told. Always 200 — "not signed in" is an answer, not an
# error, and a 4xx here would show up as a failed request on every cold load.
@app.route("/api/session")
def session_state():
    anonymous = {"authenticated": False, "verified": False}

    if session.get("user") is None:
        return jsonify(anonymous), 200

    user = User.query.filter_by(id=session["user"]["id"]).first()
    if user is None:
        return jsonify(anonymous), 200

    data = load_data(user)
    logged_out_at = data.get("logout_devices_at")
    if logged_out_at is not None and logged_out_at >= session["user"]["login_at"]:
        return jsonify(anonymous), 200

    return jsonify({
        "authenticated": True,
        # False for accounts that predate email verification: they hold a valid
        # cookie but every other route stays closed to them.
        "verified": data.get("email") is not None,
        "username": user.username,
    }), 200

import eventlet
eventlet.monkey_patch()

from flask import Flask, send_file
import db
import ext
import ratelimit
from ext import socketio
from blueprints import static, login, friends, branches, bmessages, cdn, settings, bcall, adminpanel, picnics, pmessages, comments
from dotenv import load_dotenv
import os
import sys
import subprocess
from datetime import timedelta

load_dotenv()

DEBUG = True


def spawn_voice_server():
    if not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_server.py")]
        )


spawn_voice_server()

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.secret_key = os.getenv("SECRET_KEY")
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
db.init_app(app)
ext.init_app(app)

app.register_blueprint(static.app)
app.register_blueprint(login.app)
app.register_blueprint(friends.app)
app.register_blueprint(branches.app)
app.register_blueprint(bmessages.app)
app.register_blueprint(cdn.app)
app.register_blueprint(settings.app)
app.register_blueprint(bcall.app)
app.register_blueprint(adminpanel.app)
app.register_blueprint(picnics.app)
app.register_blueprint(pmessages.app)
app.register_blueprint(comments.app)

(
    ratelimit.HttpLimits(default_per_minute=200, default_burst=60)
    .exempt("/socket.io")
    .route("/api/login", 10, burst=5)
    .route("/api/register", 5, burst=3)
    .route("/api/cdn/avatars/upload", 5, burst=3)
    .route("/api/cdn/benches/upload", 30, burst=10)
    .route("/api/cdn/picnics/upload", 30, burst=10)
    .route("/api/message/report", 10, burst=5)
    .route("/api/picnic/create", 5, burst=3)
    .route("/api/picnic/search", 30, burst=10)
    .route("/cdn/", 600, burst=200)
    .init_app(app)
)

app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.route("/favicon.ico")
def get_favicon():
    return send_file("favicon.ico")

socketio.run(app, debug=DEBUG, allow_unsafe_werkzeug=True, host="0.0.0.0", port=20001)
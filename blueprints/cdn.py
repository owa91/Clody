from flask import Blueprint, request, session, jsonify, send_from_directory, abort
from ext import check_session, load_data, socketio
from db import *
from urllib.parse import urlparse
import requests
import secrets
import os

app = Blueprint("cdn", "cdn")

MAX_FILES_PER_MESSAGE = 10

@app.post("/api/cdn/benches/gif")
def attach_bench_gif():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id_bench = request.json.get("id_bench")
    url = request.json.get("url")
    if id_bench is None or not url:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    if id_bench not in (load_data(user).get("branches") or []):
        return jsonify("Forbidden"), 403

    host = (urlparse(url).hostname or "").lower()
    if not (host == "giphy.com" or host.endswith(".giphy.com")):
        return jsonify("Bad Request"), 400

    try:
        resp = requests.get(url, timeout=10, stream=True)
        if resp.status_code != 200:
            return jsonify("Could not fetch GIF"), 502
        content = resp.content
    except Exception:
        return jsonify("Could not fetch GIF"), 502

    if len(content) > 15 * 1024 * 1024:
        return jsonify("GIF too large"), 400

    filename = secrets.token_hex(16) + ".gif"
    os.makedirs(f"cdn/benches/{id_bench}", exist_ok=True)
    with open(os.path.join(f"cdn/benches/{id_bench}", filename), "wb") as f:
        f.write(content)

    return jsonify({"filename": filename}), 200

@app.post("/api/cdn/benches/upload")
def upload_bench_file():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    if "file" not in request.files:
        return jsonify("Bad Request"), 400

    file = request.files["file"]
    id_bench = request.form.get("id_bench")

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > 30*1024*1024:
        return jsonify("Bad Request"), 400

    if file.filename == "" or id_bench is None or not id_bench.isdigit():
        return jsonify("Bad Request"), 400

    id_bench = int(id_bench)

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if id_bench not in (load_data(user).get("branches") or []):
        return jsonify("Forbidden"), 403

    _, file_extension = os.path.splitext(file.filename)

    filename = secrets.token_hex(16) + file_extension.lower()

    os.makedirs(f"cdn/benches/{id_bench}", exist_ok=True)

    file.save(os.path.join(f"cdn/benches/{id_bench}", filename))

    return jsonify({"filename": filename, "original_name": file.filename}), 200

@app.post("/api/cdn/picnics/upload")
def upload_picnic_file():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    if "file" not in request.files:
        return jsonify("Bad Request"), 400

    file = request.files["file"]
    id_picnic = request.form.get("id_picnic")

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > 30*1024*1024:
        return jsonify("Bad Request"), 400

    if file.filename == "" or id_picnic is None or not id_picnic.isdigit():
        return jsonify("Bad Request"), 400

    id_picnic = int(id_picnic)

    picnic = Picnic.query.filter_by(id=id_picnic).first()

    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []):
        return jsonify("Forbidden"), 403

    _, file_extension = os.path.splitext(file.filename)

    filename = secrets.token_hex(16) + file_extension.lower()

    os.makedirs(f"cdn/picnics/{id_picnic}", exist_ok=True)

    file.save(os.path.join(f"cdn/picnics/{id_picnic}", filename))

    return jsonify({"filename": filename, "original_name": file.filename}), 200

@app.post("/api/cdn/avatars/upload")
def upload_avatar():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    if "file" not in request.files:
        return jsonify("Bad Request"), 400

    file = request.files["file"]


    if file.filename == "":
        return jsonify("Bad Request"), 400

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > 30 * 1024 * 1024:
        return jsonify("Bad Request"), 400

    _, file_extension = os.path.splitext(file.filename)

    filename = secrets.token_hex(16) + file_extension.lower()

    os.makedirs("cdn/avatars", exist_ok=True)

    file.save(os.path.join("cdn/avatars", filename))

    user = User.query.filter_by(id=session["user"]["id"]).first()
    user.avatar = filename
    db.session.commit()

    return jsonify({"filename": filename, "original_name": file.filename}), 200

@app.post("/api/cdn/picnics/avatars/upload")
def upload_picnic_avatar():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    if "file" not in request.files:
        return jsonify("Bad Request"), 400

    file = request.files["file"]
    id_picnic = request.form.get("id_picnic")

    if file.filename == "" or id_picnic is None or not id_picnic.isdigit():
        return jsonify("Bad Request"), 400

    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > 5 * 1024 * 1024:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=int(id_picnic)).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif picnic.owner != session["user"]["id"]:
        return jsonify("Forbidden"), 403

    _, file_extension = os.path.splitext(file.filename)
    filename = secrets.token_hex(16) + file_extension.lower()

    os.makedirs("cdn/avatars", exist_ok=True)
    file.save(os.path.join("cdn/avatars", filename))

    picnic.avatar = filename
    db.session.commit()

    for member_id in (picnic.members or []):
        from blueprints.picnics import picnic_summary
        socketio.emit("update_picnic", picnic_summary(picnic, member_id), to=member_id)

    return jsonify({"filename": filename, "original_name": file.filename}), 200

@app.get("/cdn/benches/<int:bench>/<filename>")
def get_file_bench(filename, bench):
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if bench not in (load_data(user).get("branches") or []):
        return abort(403)

    try:
        return send_from_directory(
            f"cdn/benches/{bench}",
            filename,
            as_attachment=False
        )
    except FileNotFoundError:
        abort(404)

@app.get("/cdn/picnics/<int:picnic>/<filename>")
def get_file_picnic(filename, picnic):
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    if Picnic.query.filter_by(id=picnic).first() is None:
        return abort(404)

    try:
        return send_from_directory(
            f"cdn/picnics/{picnic}",
            filename,
            as_attachment=False
        )
    except FileNotFoundError:
        abort(404)

@app.get("/cdn/avatar/<filename>")
def get_avatar(filename):
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    try:
        return send_from_directory(
            "cdn/avatars",
            filename,
            as_attachment=False
        )
    except FileNotFoundError:
        abort(404)

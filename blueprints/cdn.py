from flask import Blueprint, request, session, jsonify, send_from_directory, abort
from ext import check_session, load_data
from db import *
import secrets
import os

app = Blueprint("cdn", "cdn")

MAX_FILES_PER_MESSAGE = 10

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

import db
from flask import Blueprint, request, session, jsonify
from db import *
from ext import *
import json
import time

app = Blueprint("pmessages", "pmessages")

def message_data(message):
    if not message.data:
        return {}
    try:
        return json.loads(message.data)
    except (TypeError, ValueError):
        return {}

# A пикник speaks in one voice: who actually wrote a post is admin-only, so
# `author` goes out to admins and is None for everyone else. Admins still need
# it — the client uses it to skip counting an author's view of their own post,
# and only an admin can ever be one.
#
# `read` is a view counter, not a delivery receipt, so it never goes out as a
# list of ids — just the total, plus whether the asking viewer is in it.
# viewer_id is left None for socket broadcasts: they fan out to every member
# from whichever request triggered them, so the sender's session can't stand in
# for the recipient's. A freshly created post is unread by everyone anyway.
def message_summary(message, viewer_id=None, viewer_is_admin=False):
    return {
        "id": message.id,
        "picnic": message.picnic,
        "author": message.author if viewer_is_admin else None,
        "content": message.content,
        "cdn": message.cdn or [],
        "edited": message.edited,
        "created_at": message.created_at,
        "views": len(message.read or []),
        "read_by_me": viewer_id is not None and viewer_id in (message.read or []),
        "data": message_data(message),
    }

def is_admin_of(picnic):
    return session["user"]["id"] in (picnic.admins or [])

# One payload per member rather than a single room broadcast: `author` is
# admin-only, so what each member may see differs.
def broadcast(picnic, event, message):
    admins = picnic.admins or []
    for member_id in (picnic.members or []):
        socketio.emit(event, message_summary(message, viewer_is_admin=member_id in admins), to=member_id)

@app.route("/api/pm/list", methods=["POST"])
def list_pm():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    picnic = request.json.get("picnic")
    if picnic is None:
        return jsonify("Bad Request"), 400

    picnic_row = Picnic.query.filter_by(id=picnic).first()
    if picnic_row is None:
        return jsonify("Not Found"), 404

    messages = PMessage.query.filter_by(picnic=picnic).order_by(PMessage.created_at.asc()).all()
    viewer_is_admin = is_admin_of(picnic_row)

    return jsonify(
        [message_summary(m, session["user"]["id"], viewer_is_admin) for m in messages]
    ), 200

@app.route("/api/pm/get", methods=["POST"])
def get_pm():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    message = PMessage.query.filter_by(id=id).first()
    if message is None:
        return jsonify("Not Found"), 404

    picnic = Picnic.query.filter_by(id=message.picnic).first()
    if picnic is None:
        return jsonify("Not Found"), 404

    return jsonify(message_summary(message, session["user"]["id"], is_admin_of(picnic))), 200

@app.route("/api/pm/get_author", methods=["POST"])
def get_author():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    message = PMessage.query.filter_by(id=id).first()
    if message is None:
        return jsonify("Not Found"), 404

    picnic = Picnic.query.filter_by(id=message.picnic).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []):
        return jsonify("Forbidden"), 403

    return jsonify(message.author), 200

@app.route("/api/pm/create", methods=["POST"])
def create_pm():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    picnic_id = request.json.get("picnic")
    content = request.json.get("content")
    cdn = request.json.get("cdn") or []

    if picnic_id is None or content is None or len(cdn) > 10:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=picnic_id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []):
        return jsonify("Forbidden"), 403

    message = PMessage(
        content=content,
        picnic=picnic.id,
        cdn=cdn,
        read=[],
        created_at=int(time.time()),
        author=session["user"]["id"],
    )

    db.session.add(message)
    db.session.commit()

    picnic.messages = (picnic.messages or []) + [message.id]
    db.session.commit()

    broadcast(picnic, "new_pmessage", message)

    return jsonify(message_summary(message, session["user"]["id"], True)), 200

@app.route("/api/pm/edit", methods=["POST"])
def edit_pm():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    content = request.json.get("content")

    if id is None or content is None:
        return jsonify("Bad Request"), 400

    message = PMessage.query.filter_by(id=id).first()
    if message is None:
        return jsonify("Not Found"), 404

    picnic = Picnic.query.filter_by(id=message.picnic).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []):
        return jsonify("Forbidden"), 403

    message.content = content
    message.edited = True
    db.session.commit()

    broadcast(picnic, "update_pmessage", message)

    return jsonify(message_summary(message, session["user"]["id"], True)), 200

@app.route("/api/pm/mark_read", methods=["POST"])
def mark_read():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    message = PMessage.query.filter_by(id=id).first()
    if message is None:
        return jsonify("Not Found"), 404

    if session["user"]["id"] not in (message.read or []):
        message.read = (message.read or []) + [session["user"]["id"]]
        db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/pm/i_read", methods=["POST"])
def i_read():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    message = PMessage.query.filter_by(id=id).first()
    if message is None:
        return jsonify("Not Found"), 404

    return jsonify(session["user"]["id"] in (message.read or [])), 200

@app.route("/api/pm/delete", methods=["POST"])
def delete_pm():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    message = PMessage.query.filter_by(id=id).first()
    if message is None:
        return jsonify("Not Found"), 404

    picnic = Picnic.query.filter_by(id=message.picnic).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []) and session["user"]["id"] != message.author:
        return jsonify("Forbidden"), 403

    message_id = message.id
    picnic_id = message.picnic

    db.session.delete(message)
    picnic.messages = [m for m in (picnic.messages or []) if m != message_id]
    db.session.commit()

    for member_id in (picnic.members or []):
        socketio.emit("delete_pmessage", {"id": message_id, "picnic_id": picnic_id}, to=member_id)

    return jsonify("Success"), 200

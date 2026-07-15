import db
from flask import Blueprint, request, session, jsonify
from db import *
from ext import *
import json
import time

app = Blueprint("bmessages", "bmessages")

def message_data(message):
    if not message.data:
        return {}
    try:
        return json.loads(message.data)
    except (TypeError, ValueError):
        return {}

def message_summary(message):
    return {
        "id": message.id,
        "branch": message.branch,
        "author": message.author,
        "content": message.content,
        "cdn": message.cdn,
        "edited": message.edited,
        "created_at": message.created_at,
        "read": message.read,
        "data": message_data(message),
    }

def user_branches(session):
    user = User.query.filter_by(id=session["user"]["id"]).first()
    return load_data(user).get("branches") or []

@app.route("/api/bm/list", methods=["POST"])
def list_messages():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    branch = request.json.get("branch")
    user = User.query.filter_by(id=session["user"]["id"]).first()

    if branch is None:
        return jsonify("Bad Request"), 400

    if branch not in user_branches(session) and not user.isadmin:
        return jsonify("Forbidden"), 403

    messages = BMessage.query.filter_by(branch=branch).order_by(BMessage.created_at.asc()).all()

    return jsonify([message_summary(m) for m in messages]), 200

@app.route("/api/bm/get", methods=["POST"])
def get_message():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")

    if id is None:
        return jsonify("Bad Request"), 400

    message = BMessage.query.filter_by(id=id).first()
    user = User.query.filter_by(id=session["user"]["id"]).first()

    if message is None:
        return jsonify("Not Found"), 404

    if message.branch not in user_branches(session) and not user.isadmin:
        return jsonify("Forbidden"), 403

    return jsonify(message_summary(message)), 200

@app.route("/api/bm/create", methods=["POST"])
def create_message():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    branch = request.json.get("branch")
    content = request.json.get("content")
    cdn = request.json.get("cdn") or []
    answer_to = request.json.get("answer_to")

    if branch is None or content is None or len(cdn) > 10:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if branch not in user_branches(session):
        return jsonify("Forbidden"), 403

    if answer_to is not None:
        answered = BMessage.query.filter_by(id=answer_to).first()
        if answered is None or answered.branch != branch:
            return jsonify("Not Found"), 404

    data = {
        "answer_to": answer_to
    }

    branch_row = Branch.query.filter_by(id=branch).first()

    if branch_row.owner == 0:
        return jsonify("Forbitten"), 403

    message = BMessage(content=content, branch=branch, cdn=cdn, created_at=int(time.time()), author=user.id, data=json.dumps(data))

    db.session.add(message)
    db.session.commit()

    for member_id in (branch_row.members or []):
        socketio.emit("new_bmessage", message_summary(message), to=member_id)

    return jsonify(message_summary(message)), 200

@app.route("/api/bm/mark_read", methods=["POST"])
def mark_read():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    message = BMessage.query.filter_by(id=id).first()
    user = User.query.filter_by(id=session["user"]["id"]).first()

    if message is None:
        return jsonify("Not Found"), 404
    elif message.branch not in (load_data(user).get("branches") or []):
        return jsonify("Forbidden"), 403

    if user.id not in (message.read or []):
        message.read = (message.read or []) + [user.id]
        db.session.commit()

        branch = Branch.query.filter_by(id=message.branch).first()
        for member_id in (branch.members or []):
            socketio.emit("update_bmessage", message_summary(message), to=member_id)

    return jsonify("Success"), 200

@app.route("/api/bm/edit", methods=["POST"])
def edit_message():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    new_content = request.json.get("new_content")

    if id is None or new_content is None:
        return jsonify("Bad Request"), 400

    message = BMessage.query.filter_by(id=id).first()

    if message is None:
        return jsonify("Not Found"), 404
    elif message.author != session["user"]["id"]:
        return jsonify("Forbidden"), 403

    message.content = new_content
    message.edited = True
    db.session.commit()

    branch = Branch.query.filter_by(id=message.branch).first()

    for member_id in (branch.members or []):
        socketio.emit("update_bmessage", message_summary(message), to=member_id)

    return jsonify(message_summary(message)), 200

@app.route("/api/bm/delete", methods=["POST"])
def delete_message():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")

    if id is None:
        return jsonify("Bad Request"), 400

    message = BMessage.query.filter_by(id=id).first()

    if message is None:
        return jsonify("Not Found"), 404
    elif message.author != session["user"]["id"]:
        return jsonify("Forbidden"), 403

    branch = Branch.query.filter_by(id=message.branch).first()
    message_id = message.id
    branch_id = message.branch

    db.session.delete(message)
    db.session.commit()

    for member_id in (branch.members or []):
        socketio.emit("delete_bmessage", {"id": message_id, "branch_id": branch_id}, to=member_id)

    return jsonify("Success"), 200

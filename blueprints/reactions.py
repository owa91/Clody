import db
from flask import Blueprint, request, session, jsonify
from db import *
from ext import *
import json
import time
import emoji as emoji_lib

app = Blueprint("reactions", "reactions")

MAX_PER_MESSAGE = 50

def reaction_summary(reaction):
    return {
        "id": reaction.id,
        "message": reaction.message,
        "ispicnic": reaction.ispicnic,
        "emoji": reaction.emoji,
        "author": reaction.author,
    }

# Reactions hang off two different message tables, and each one lives inside a
# different container with its own membership list. Resolve both at once: the
# members double as the socket fan-out list.
def resolve_target(id, ispicnic, viewer_id):
    if ispicnic:
        message = PMessage.query.filter_by(id=id).first()
        if message is None:
            return None, None
        picnic = Picnic.query.filter_by(id=message.picnic).first()
        if picnic is None:
            return None, None
        return message, list(picnic.members or [])

    message = BMessage.query.filter_by(id=id).first()
    if message is None:
        return None, None
    branch = Branch.query.filter_by(id=message.branch).first()
    if branch is None:
        return None, None
    return message, list(branch.members or [])

def broadcast(event, payload, members):
    for member_id in members:
        socketio.emit(event, payload, to=member_id)

@app.route("/api/reactions/get", methods=["POST"])
def get_reactions():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    ispicnic = bool(request.json.get("is_picnic"))
    # One message (`id`) or a whole page of them (`ids`) — the client asks for a
    # page at a time, so a per-message round trip would be 30 requests.
    ids = request.json.get("ids")
    if ids is None:
        id = request.json.get("id")
        if id is None:
            return jsonify("Bad Request"), 400
        ids = [id]

    if not isinstance(ids, list) or len(ids) > 200:
        return jsonify("Bad Request"), 400

    ids = [int(i) for i in ids]
    viewer = session["user"]["id"]

    # Access is per-container, and a page can only ever come from one, so
    # checking the first message covers the batch.
    if ids:
        message, members = resolve_target(ids[0], ispicnic, viewer)
        if message is None:
            return jsonify("Not Found"), 404
        elif viewer not in members:
            return jsonify("Forbidden"), 403

    rows = Reaction.query.filter(
        Reaction.ispicnic == ispicnic, Reaction.message.in_(ids)
    ).all() if ids else []

    data = {}
    for reaction in rows:
        data.setdefault(str(reaction.message), []).append(reaction_summary(reaction))

    return jsonify(data), 200

@app.route("/api/reaction/create", methods=["POST"])
def create_reaction():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    ispicnic = bool(request.json.get("is_picnic"))
    id = request.json.get("id")
    char = request.json.get("emoji")

    if id is None or char is None:
        return jsonify("Bad Request"), 400
    elif char not in emoji_lib.EMOJI_DATA:
        return jsonify("This isn't emoji"), 400

    viewer = session["user"]["id"]
    message, members = resolve_target(id, ispicnic, viewer)

    if message is None:
        return jsonify("Not Found"), 404
    elif viewer not in members:
        return jsonify("You need to be a member"), 403

    # Reacting twice with the same emoji is a no-op, not a second row — the UI
    # toggles, and a double click must not stack.
    existing = Reaction.query.filter_by(
        message=id, ispicnic=ispicnic, emoji=char, author=viewer
    ).first()
    if existing is not None:
        return jsonify(reaction_summary(existing)), 200

    if Reaction.query.filter_by(message=id, ispicnic=ispicnic).count() >= MAX_PER_MESSAGE:
        return jsonify("Too many reactions"), 400

    reaction = Reaction(message=id, ispicnic=ispicnic, emoji=char, author=viewer)
    db.session.add(reaction)
    db.session.commit()

    payload = reaction_summary(reaction)
    broadcast("new_reaction", payload, members)

    return jsonify(payload), 200

@app.route("/api/reaction/delete", methods=["POST"])
def delete_reaction():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    viewer = session["user"]["id"]
    id = request.json.get("id")

    if id is not None:
        reaction = Reaction.query.filter_by(id=id).first()
    else:
        # The chips only know which emoji they carry, so let the client remove
        # its own reaction by (message, emoji) without tracking row ids.
        message_id = request.json.get("message")
        char = request.json.get("emoji")
        if message_id is None or char is None:
            return jsonify("Bad Request"), 400
        reaction = Reaction.query.filter_by(
            message=message_id,
            ispicnic=bool(request.json.get("is_picnic")),
            emoji=char,
            author=viewer,
        ).first()

    if reaction is None:
        return jsonify("Not Found"), 404
    elif reaction.author != viewer:
        return jsonify("Forbidden"), 403

    payload = reaction_summary(reaction)
    _, members = resolve_target(reaction.message, reaction.ispicnic, viewer)

    db.session.delete(reaction)
    db.session.commit()

    broadcast("delete_reaction", payload, members or [viewer])

    return jsonify("Success"), 200

import db
from flask import Blueprint, request, session, jsonify, abort, url_for
from db import *
from ext import *
import json

app = Blueprint("picnics", "picnics")

def picnic_summary(picnic):
    return {
        "id": picnic.id,
        "name": picnic.name,
        "avatar": picnic.avatar,
        "members_count": len(picnic.members),
        "link": picnic.link,
        "supports_comments": picnic.comments is not None,
    }

def user_picnics(user):
    return load_data(user).get("picnics") or []

def set_user_picnics(user, picnics):
    data = load_data(user)
    data["picnics"] = picnics
    user.data = json.dumps(data)

@app.route("/api/picnics/get")
def get_picnics():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    if data.get("picnics") is None:
        data["picnics"] = []
        user.data = json.dumps(data)
        db.session.commit()

    return jsonify(data["picnics"]), 200

@app.route("/api/picnic/get", methods=["POST"])
def get_info_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404

    return jsonify(picnic_summary(picnic)), 200

@app.route("/@/<link>")
def relink(link):
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    picnic = Picnic.query.filter_by(link=link).first()
    if picnic is None:
        abort(404)

    return url_for(f"https://clody.lol/app/picnics/{picnic.id}"), 200

@app.route("/api/picnic/search", methods=["POST"])
def search_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    name = request.json.get("name")
    if name is None:
        return jsonify("Bad Request"), 400

    needle = name.strip().lower()
    if not needle:
        return jsonify([]), 200

    picnics = [p for p in Picnic.query.all() if needle in (p.name or "").lower()][:50]

    return jsonify([picnic_summary(p) for p in picnics]), 200

@app.route("/api/picnic/create", methods=["POST"])
def create_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    name = request.json.get("name")
    avatar = request.json.get("avatar")
    link = request.json.get("link")
    comments = request.json.get("support_comments")

    if name is None or comments is None:
        return jsonify("Bad Request"), 400

    name = name.strip()
    if not name:
        return jsonify("Bad Request"), 400

    link = (link or "").strip() or None
    if link is not None and Picnic.query.filter_by(link=link).first() is not None:
        return jsonify("Link is taken"), 403

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    if len(data.get("warns") or []) > 2:
        return jsonify("You have 3 or more warns"), 403

    picnic = Picnic(
        name=name,
        avatar=avatar,
        link=link,
        members=[user.id],
        bans=[],
        messages=[],
        admins=[user.id],
        owner=user.id,
        comments=[] if comments else None,
    )

    db.session.add(picnic)
    db.session.commit()

    set_user_picnics(user, user_picnics(user) + [picnic.id])
    db.session.commit()

    socketio.emit("added_picnic", picnic_summary(picnic), to=user.id)

    return jsonify(picnic_summary(picnic)), 200

@app.route("/api/picnic/edit", methods=["POST"])
def edit_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    name = request.json.get("name")
    avatar = request.json.get("avatar")
    link = request.json.get("link")
    comments = request.json.get("support_comments")
    admins = request.json.get("admins")

    if id is None or name is None or comments is None or admins is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif picnic.owner != session["user"]["id"]:
        return jsonify("Forbidden"), 403

    name = name.strip()
    if not name:
        return jsonify("Bad Request"), 400

    link = (link or "").strip() or None
    if link is not None:
        taken = Picnic.query.filter_by(link=link).first()
        if taken is not None and taken.id != picnic.id:
            return jsonify("Link is taken"), 403

    admins = [a for a in dict.fromkeys(admins) if a in (picnic.members or [])]
    if picnic.owner not in admins:
        admins = [picnic.owner] + admins

    picnic.name = name
    picnic.avatar = avatar
    picnic.link = link
    picnic.admins = admins

    if comments and picnic.comments is None:
        picnic.comments = []
    elif not comments and picnic.comments is not None:
        picnic.comments = None

    db.session.commit()

    for member_id in (picnic.members or []):
        socketio.emit("update_picnic", picnic_summary(picnic), to=member_id)

    return jsonify(picnic_summary(picnic)), 200

@app.route("/api/picnic/ban", methods=["POST"])
def ban_user():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    ban_id = request.json.get("ban_id")

    if id is None or ban_id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []):
        return jsonify("Forbidden"), 403
    elif ban_id == picnic.owner:
        return jsonify("Can't ban the owner"), 403
    elif ban_id in (picnic.admins or []):
        return jsonify("Remove role Admin"), 403
    elif ban_id in (picnic.bans or []):
        return jsonify("Already banned"), 400

    picnic.bans = (picnic.bans or []) + [ban_id]

    if ban_id in (picnic.members or []):
        picnic.members = [m for m in picnic.members if m != ban_id]

        banned = User.query.filter_by(id=ban_id).first()
        if banned is not None:
            set_user_picnics(banned, [p for p in user_picnics(banned) if p != picnic.id])

        db.session.commit()

        send_message(ban_id, f"Привет!\nВы были забанеты на пикнике **{picnic.name}**. Мы не знаем почему так случилось\nВы до сих пор можете просматривать сообщения от данного пикника, но не участвовать или писать комментарии в нём")
        socketio.emit("banned_from_picnic", {"id": picnic.id, "name": picnic.name}, to=ban_id)

    db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/picnic/bans", methods=["POST"])
def get_bans():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []):
        return jsonify("Forbidden"), 403

    return jsonify(picnic.bans or []), 200

@app.route("/api/picnic/unban", methods=["POST"])
def unban_user():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    unban_id = request.json.get("unban_id")

    if id is None or unban_id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.admins or []):
        return jsonify("Forbidden"), 403
    elif unban_id not in (picnic.bans or []):
        return jsonify("That is not banned"), 404

    picnic.bans = [b for b in picnic.bans if b != unban_id]
    db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/picnic/join", methods=["POST"])
def join_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] in (picnic.bans or []):
        return jsonify("You are banned"), 403
    elif session["user"]["id"] in (picnic.members or []):
        return jsonify("You are member"), 403

    user = User.query.filter_by(id=session["user"]["id"]).first()

    picnic.members = (picnic.members or []) + [user.id]
    set_user_picnics(user, user_picnics(user) + [picnic.id])

    db.session.commit()

    socketio.emit("added_picnic", picnic_summary(picnic), to=user.id)

    return jsonify(picnic_summary(picnic)), 200

@app.route("/api/picnic/leave", methods=["POST"])
def leave_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in (picnic.members or []):
        return jsonify("Bad Request"), 400
    elif picnic.owner == session["user"]["id"]:
        return jsonify("You are owner"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    picnic.members = [m for m in picnic.members if m != user.id]
    picnic.admins = [a for a in (picnic.admins or []) if a != user.id]
    set_user_picnics(user, [p for p in user_picnics(user) if p != picnic.id])

    db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/picnic/delete", methods=["POST"])
def delete_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif picnic.owner != session["user"]["id"]:
        return jsonify("Forbidden"), 403

    members = list(picnic.members or [])

    for member_id in members:
        member = User.query.filter_by(id=member_id).first()
        if member is not None:
            set_user_picnics(member, [p for p in user_picnics(member) if p != picnic.id])

    PMessage.query.filter_by(picnic=picnic.id).delete()
    db.session.delete(picnic)
    db.session.commit()

    for member_id in members:
        socketio.emit("deleted_picnic", {"id": id}, to=member_id)

    return jsonify("Success"), 200

@app.route("/api/picnic/comments", methods=["POST"])
def get_comments():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] in (picnic.bans or []):
        return jsonify("Forbidden"), 403

    return jsonify(picnic.comments), 200

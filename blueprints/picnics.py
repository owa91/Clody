import db
from flask import Blueprint, request, session, jsonify, abort
from db import *
from ext import *
import json
import time

app = Blueprint("picnics", "picnics")

@app.route("/api/picnics/get")
def get_picnics():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = json.loads(user.data)

    if data.get("picnics") is None:
        data["picnics"] = []
        user.data = json.dumps(data)
        db.session.commit()

    return data["picnics"]

@app.route("/api/picnic/get")
def get_info_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404

    return jsonify({
        "name": picnic.name,
        "avatar": picnic.avatar,
        "messages": picnic.messages,
        "link": picnic.link
    }), 200

@app.route("/@/<link>")
def relink(link):
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    picnic = Picnic.query.filter_by(link=link).first()
    if picnic is None:
        abort(404)

    return jsonify(picnic.id), 200

@app.route("/api/picnic/search")
def search_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    name = request.json.get("name")
    if name is None:
        return jsonify("Bad Request"), 400

    picnics = Picnic.query.filter_by(name=name).all()
    data = []
    for picnic in picnics:
        data.append(picnic.id)

    return jsonify(data), 200

@app.route("/api/picnic/create")
def create_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    name = request.json.get("name")
    avatar = request.json.get("avatar")
    link = request.json.get("link")
    comments = request.json.get("support_comments")
    if name is None or comments is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = json.loads(user.data)
    if len(data["warns"]) > 2:
        return jsonify("You have 3 or more warns"), 403

    picnic = Picnic(name=name, avatar=avatar, link=link, members=[user.id], admins=[user.id], owner=user.id)
    if comments:
        picnic.comments = []

    db.session.add(picnic)
    data["picnics"].append(picnic.id)
    user.data = json.dumps(data)

    db.session.commit()

    return jsonify(picnic.id), 200

@app.route("/api/picnic/edit")
def edit_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    name = request.json.get("name")
    avatar = request.json.get("avatar")
    link = request.json.get("link")
    comments = request.json.get("support_comments")
    admins = request.json.get("admins")
    if name is None or comments is None or admins is None and id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif picnic.owner != session["user"]["id"]:
        return jsonify("Forbitten"), 403

    picnic.name = name
    picnic.avatar = avatar
    picnic.link = link
    picnic.admins = admins

    if comments and picnic.comments is None:
        picnic.comments = []
    elif not comments and picnic.comments is not None:
        picnic.comments = None

    db.session.commit()
    return jsonify("Success"), 200

@app.route("/api/picnic/ban")
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
    elif session["user"]["id"] not in picnic.admin:
        return jsonify("Forbitten"), 403
    elif ban_id not in picnic.admin:
        return jsonify("Remove role Admin"), 403

    bans = picnic.bans.copy()
    bans.append(ban_id)
    picnic.bans = bans

    if ban_id in picnic.members:
        picnic.members.remove(ban_id)
        send_message(ban_id, f"Привет!\nВы были забанеты на пикнике **{picnic.name}**. Мы не знаем почему так случилось\nВы до сих пор можете просматривать сообщения от данного пикника, но не участвовать или писать комментарии в нём")

    return jsonify("Success"), 200

@app.route("/api/picnic/join")
def join_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] in picnic.bans or session["user"]["id"] in picnic.members:
        return jsonify("Forbitten"), 403

    members = picnic.members.copy()
    members.append(session["user"]["id"])
    picnic.members = members

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = json.loads(user.data)
    data["picnics"].append(picnic.id)
    user.data = json.dumps(data)

    db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/picnic/leave")
def leave_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] not in picnic.members:
        return jsonify("Bad Request"), 400

    members = picnic.members.copy()
    members.remove(session["user"]["id"])
    picnic.members = members

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = json.loads(user.data)
    data["picnics"].remove(picnic.id)
    user.data = json.dumps(data)

    db.session.commit()

    return jsonify("Success"), 200

@app.route("/api/picnic/comments")
def get_comments():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404
    elif session["user"]["id"] in picnic.bans:
        return jsonify("Forbitten"), 403

    return jsonify(picnic.comments), 200
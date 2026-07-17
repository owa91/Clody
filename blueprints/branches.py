import db
from flask import Blueprint, request, session, jsonify
from db import *
from ext import *
import json

app = Blueprint("branches", "branches")

def branch_summary(branch):
    return {
        "id": branch.id,
        "members": branch.members,
        "data": branch.data,
        "ispm": branch.ispm,
        "owner": branch.owner,
        "name": branch.name,
    }

@app.route("/api/branch/get", methods=["POST"])
def get_branch():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")

    if id is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    if id not in (data.get("branches") or []):
        return jsonify("Forbidden"), 403

    branch = Branch.query.filter_by(id=id).first()

    if branch is None:
        return jsonify("Not Found"), 404

    return jsonify(branch_summary(branch)), 200

@app.route("/api/branches/get")
def get_branches():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    data = load_data(user)

    if data.get("branches") is None:
        data["branches"] = []
        user.data = json.dumps(data)
        db.session.commit()

    return jsonify(data["branches"]), 200

@app.route("/api/branches/overview")
def branches_overview():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    ids = [b for b in (load_data(user).get("branches") or []) if b is not None]

    result = []
    for bid in ids:
        branch = Branch.query.filter_by(id=bid).first()
        if branch is None:
            continue
        messages = BMessage.query.filter_by(branch=bid).all()
        unread = sum(1 for m in messages if m.author != user.id and user.id not in (m.read or []))
        last_at = max((m.created_at or 0 for m in messages), default=0)
        result.append({**branch_summary(branch), "unread": unread, "last_at": last_at})

    return jsonify(result), 200

@app.route("/api/branch/create", methods=["POST"])
def create_branch():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    members = request.json.get("members")
    name = request.json.get("name")
    ispm = request.json.get("ispm")

    if members is None or ispm is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()
    user_data = load_data(user)
    user_friends = user_data.get("friends") or []

    for member_id in members:
        if member_id not in user_friends:
            return jsonify("Anybody isn't friend"), 403
        elif User.query.filter_by(id=member_id).first() is None:
            return jsonify(f"{member_id} hasn't found"), 404

    all_member_ids = list(dict.fromkeys([user.id, *members]))

    branch = Branch(name=name or None, members=all_member_ids, messages=[], ispm=ispm, owner=user.id)
    db.session.add(branch)
    db.session.commit()

    for member_id in all_member_ids:
        member = User.query.filter_by(id=member_id).first()
        member_data = load_data(member)
        member_branches = member_data.get("branches") or []
        if branch.id not in member_branches:
            member_branches.append(branch.id)
        member_data["branches"] = member_branches
        member.data = json.dumps(member_data)
        db.session.commit()

        socketio.emit("added_branch", branch_summary(branch), to=member_id)

    return jsonify(branch_summary(branch)), 200

@app.route("/api/branch/rename", methods=["POST"])
def rename_branch():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    name = request.json.get("name")

    if id is None:
        return jsonify("Bad Request"), 400

    branch = Branch.query.filter_by(id=id).first()

    if branch is None:
        return jsonify("Not Found"), 404
    if session["user"]["id"] not in (branch.members or []):
        return jsonify("Forbidden"), 403

    branch.name = name or None
    db.session.commit()

    for member_id in branch.members:
        socketio.emit("update_branch", {"branch_id": branch.id}, to=member_id)

    return jsonify(branch_summary(branch)), 200

@app.route("/api/branch/add_member", methods=["POST"])
def add_member():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    member_id = request.json.get("member")
    id = request.json.get("id")

    if member_id is None or id is None:
        return jsonify("Bad Request"), 400

    member = User.query.filter_by(id=member_id).first()
    branch = Branch.query.filter_by(id=id).first()

    if member is None or branch is None:
        return jsonify("Not Found"), 404

    if session["user"]["id"] not in (branch.members or []):
        return jsonify("Forbidden"), 403

    user_data = load_data(User.query.filter_by(id=session["user"]["id"]).first())

    if member_id not in (user_data.get("friends") or []):
        return jsonify("This isn't your friend"), 403
    elif branch.ispm:
        return jsonify("This is PM"), 403

    member_data = load_data(member)
    member_branches = member_data.get("branches") or []
    if branch.id not in member_branches:
        member_branches.append(branch.id)
    member_data["branches"] = member_branches
    member.data = json.dumps(member_data)

    members = list(branch.members or [])
    if member.id not in members:
        members = members + [member.id]
    branch.members = members

    db.session.commit()

    socketio.emit("added_branch", branch_summary(branch), to=member.id)

    return jsonify("Success"), 200

@app.route("/api/branch/kick", methods=["POST"])
def kick_member():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    member_id = request.json.get("member")
    id = request.json.get("id")

    if member_id is None or id is None:
        return jsonify("Bad Request"), 400

    member = User.query.filter_by(id=member_id).first()
    branch = Branch.query.filter_by(id=id).first()

    if member is None or branch is None:
        return jsonify("Not Found"), 404

    if branch.owner != session["user"]["id"]:
        return jsonify("Forbidden"), 403

    if member.id == branch.owner:
        return jsonify("Can't kick the owner"), 400

    if member.id not in (branch.members or []):
        return jsonify("That is not a member"), 404

    members = [m for m in branch.members if m != member.id]
    branch.members = members

    member_data = load_data(member)
    member_branches = member_data.get("branches") or []
    if branch.id in member_branches:
        member_branches.remove(branch.id)
    member_data["branches"] = member_branches
    member.data = json.dumps(member_data)

    db.session.commit()

    socketio.emit("kicked_from_branch", {"id": branch.id, "name": branch.name}, to=member.id)

    return jsonify("Success"), 200

@app.route("/api/branch/leave", methods=["POST"])
def leave_branch():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")

    if id is None:
        return jsonify("Bad Request"), 400

    branch = Branch.query.filter_by(id=id).first()
    user = User.query.filter_by(id=session["user"]["id"]).first()

    if branch is None:
        return jsonify("Not Found"), 404
    elif branch.owner == user.id:
        return jsonify("You are owner"), 400
    elif branch.owner == 0:
        return jsonify("Forbitten"), 403

    members = [m for m in (branch.members or []) if m != user.id]
    branch.members = members

    user_data = load_data(user)
    user_branches = user_data.get("branches") or []
    if branch.id in user_branches:
        user_branches.remove(branch.id)
    user_data["branches"] = user_branches
    user.data = json.dumps(user_data)

    db.session.commit()

    for member_id in members:
        socketio.emit("left_branch", {"id": branch.id, "member": user.display_name}, to=member_id)

    return jsonify("Success"), 200

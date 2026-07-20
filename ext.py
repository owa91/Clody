import time

from flask_socketio import SocketIO
from db import *
import json

socketio = SocketIO()

token_p_avatars = {}

def init_app(app):
    socketio.init_app(app)

def load_data(user):
    if not user.data:
        return {}
    try:
        return json.loads(user.data)
    except (TypeError, ValueError):
        return {}

def check_session(session, allow_unverified=False):
    if session.get("user") is None:
        return False

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if user is None:
        return False

    data = load_data(user)

    if data.get("logout_devices_at") is not None and data.get("logout_devices_at") >= session["user"]["login_at"]:
        return False

    if not allow_unverified and data.get("email") is None:
        return False

    return True

def is_anonymous(user_id):
    user = User.query.filter_by(id=user_id).first()
    if user is None:
        return False
    return not (load_data(user).get("settings") or {}).get("accepts_friend_requests", True)

def are_friends(a_id, b_id):
    user = User.query.filter_by(id=a_id).first()
    if user is None:
        return False
    return b_id in (load_data(user).get("friends") or [])

def visible_author(author_id, viewer_id):
    if author_id == viewer_id:
        return author_id
    if not is_anonymous(author_id):
        return author_id
    if are_friends(author_id, viewer_id):
        return author_id
    return None

def send_message(id, message):
    user = User.query.filter_by(id=id).first()
    if user is None:
        return

    data = load_data(user)

    branch = None
    if data.get("system_branch") is not None:
        branch = Branch.query.filter_by(id=data["system_branch"]).first()

    created = branch is None
    if created:
        branch = Branch(members=[id, 0], owner=0, ispm=True, messages=[])
        db.session.add(branch)
        db.session.flush()

        branches = [b for b in (data.get("branches") or []) if b is not None]
        if branch.id not in branches:
            branches.append(branch.id)

        data["branches"] = branches
        data["system_branch"] = branch.id
        user.data = json.dumps(data)

    bmessage = BMessage(branch=branch.id, content=message, created_at=int(time.time()), author=0)
    db.session.add(bmessage)
    db.session.flush()

    messages = list(branch.messages or [])
    messages.append(bmessage.id)
    branch.messages = messages

    db.session.commit()

    if created:
        socketio.emit(
            "added_branch",
            {
                "id": branch.id,
                "members": branch.members,
                "data": branch.data,
                "ispm": branch.ispm,
                "owner": branch.owner,
                "name": branch.name,
            },
            to=id,
        )

    socketio.emit(
        "new_bmessage",
        {
            "id": bmessage.id,
            "branch": bmessage.branch,
            "author": bmessage.author,
            "content": bmessage.content,
            "cdn": bmessage.cdn or [],
            "edited": bmessage.edited,
            "created_at": bmessage.created_at,
            "read": bmessage.read or [],
            "data": {},
        },
        to=id,
    )
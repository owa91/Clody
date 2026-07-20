import time
import db
from flask import Blueprint, request, session, jsonify
from db import *
from ext import *
import json
import emoji

app = Blueprint("comments", "comments")

COMMENT_PAGE = 20

def comment_summary(comment, viewer_id):
    return {
        "id": comment.id,
        "picnic": comment.picnic,
        "message": comment.message,
        "author": visible_author(comment.author, viewer_id),
        "content": comment.content,
        "answer_to": comment.answer_to,
        "created_at": comment.created_at,
        "edited": comment.edited,
        "likes": len(comment.likes or []),
        "liked_by_me": viewer_id in (comment.likes or []),
    }

def picnic_of_message(message_id):
    message = PMessage.query.filter_by(id=message_id).first()
    if message is None:
        return None, None
    return message, Picnic.query.filter_by(id=message.picnic).first()

@app.route("/api/comment/list", methods=["POST"])
def list_comments():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    message_id = request.json.get("message")
    before_id = request.json.get("before_id")
    limit = min(int(request.json.get("limit") or COMMENT_PAGE), 50)

    if message_id is None:
        return jsonify("Bad Request"), 400

    message, picnic = picnic_of_message(message_id)
    if message is None or picnic is None:
        return jsonify("Not Found"), 404
    elif picnic.comments is None:
        return jsonify("Comments are disabled"), 403

    query = Comment.query.filter_by(message=message_id)
    if before_id is not None:
        query = query.filter(Comment.id < before_id)

    comments = query.order_by(Comment.id.desc()).limit(limit + 1).all()
    has_more = len(comments) > limit
    comments = comments[:limit]

    viewer = session["user"]["id"]
    return jsonify({
        "comments": [comment_summary(c, viewer) for c in comments],
        "has_more": has_more,
    }), 200

@app.route("/api/comment/get", methods=["POST"])
def get_comment():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    comment = Comment.query.filter_by(id=id).first()
    if comment is None:
        return jsonify("Not Found"), 404

    return jsonify(comment_summary(comment, session["user"]["id"])), 200

@app.route("/api/comment/create", methods=["POST"])
def create_comment():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    message_id = request.json.get("message")
    content = request.json.get("content")
    answer_to = request.json.get("answer_to")

    if message_id is None or content is None or not str(content).strip():
        return jsonify("Bad Request"), 400

    message, picnic = picnic_of_message(message_id)
    if message is None or picnic is None:
        return jsonify("Message has not found"), 404
    elif picnic.comments is None:
        return jsonify("Comments are disabled"), 403
    elif session["user"]["id"] in (picnic.bans or []):
        return jsonify("You are banned"), 403
    elif session["user"]["id"] not in (picnic.members or []):
        return jsonify("You need to be member to send comments"), 403

    if answer_to is not None:
        parent = Comment.query.filter_by(id=answer_to).first()
        if parent is None or parent.message != message_id:
            return jsonify("Not Found"), 404

    comment = Comment(
        content=str(content),
        answer_to=answer_to,
        likes=[],
        created_at=int(time.time()),
        author=session["user"]["id"],
        picnic=picnic.id,
        message=message_id,
    )
    db.session.add(comment)
    db.session.commit()

    for member_id in (picnic.members or []):
        socketio.emit("new_comment", comment_summary(comment, member_id), to=member_id)

    return jsonify(comment_summary(comment, session["user"]["id"])), 200

@app.route("/api/comment/edit", methods=["POST"])
def edit_comment():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    content = request.json.get("content")
    if id is None or content is None or not str(content).strip():
        return jsonify("Bad Request"), 400

    comment = Comment.query.filter_by(id=id).first()
    if comment is None:
        return jsonify("Not Found"), 404
    elif comment.author != session["user"]["id"]:
        return jsonify("Forbidden"), 403

    comment.content = str(content)
    comment.edited = True
    db.session.commit()

    picnic = Picnic.query.filter_by(id=comment.picnic).first()
    for member_id in (picnic.members or []) if picnic else []:
        socketio.emit("update_comment", comment_summary(comment, member_id), to=member_id)

    return jsonify(comment_summary(comment, session["user"]["id"])), 200

@app.route("/api/comment/delete", methods=["POST"])
def delete_comment():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    comment = Comment.query.filter_by(id=id).first()
    if comment is None:
        return jsonify("Not Found"), 404

    picnic = Picnic.query.filter_by(id=comment.picnic).first()
    # The author can delete their own; a picnic admin can delete anyone's.
    is_admin = picnic is not None and session["user"]["id"] in (picnic.admins or [])
    if session["user"]["id"] != comment.author and not is_admin:
        return jsonify("Forbidden"), 403

    comment_id = comment.id
    message_id = comment.message

    db.session.delete(comment)
    db.session.commit()

    for member_id in (picnic.members or []) if picnic else []:
        socketio.emit("delete_comment", {"id": comment_id, "message": message_id}, to=member_id)

    return jsonify("Success"), 200

@app.route("/api/comment/like", methods=["POST"])
def like_comment():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    type = request.json.get("type")
    id = request.json.get("id")
    if type is None or id is None:
        return jsonify("Bad Request"), 400

    comment = Comment.query.filter_by(id=id).first()
    if comment is None:
        return jsonify("Not Found"), 404

    uid = session["user"]["id"]
    likes = list(comment.likes or [])

    if type == 1:
        if uid not in likes:
            likes.append(uid)
    else:
        if uid in likes:
            likes.remove(uid)

    comment.likes = likes
    db.session.commit()

    return jsonify({"likes": len(likes), "liked_by_me": uid in likes}), 200

from flask import Blueprint, request, session, jsonify
from db import *
from ext import *
import json
import time

app = Blueprint("admin", "admin")
cooldown = {}

@app.route("/api/user/check_admin")
def check_admin():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    return jsonify(user.isadmin), 200

@app.route("/api/user/warns")
def check_warns():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    return jsonify(load_data(user).get("warns") or []), 200

@app.route("/api/admin/issue", methods=["POST"])
def issue():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user_to_warn = request.json.get("user_to_warn")
    message = request.json.get("message")
    rule = request.json.get("rule")
    report_id = request.json.get("report_id")
    type = request.json.get("type")

    if user_to_warn is None or message is None or rule is None or report_id is None or type is None:
        return jsonify("Bad Request"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if not user.isadmin:
        return jsonify("Forbitten"), 403

    if type == 2:
        report = Report.query.filter_by(id=report_id).first()
        db.session.delete(report)
        db.session.commit()
    else:
        user_to_warn = User.query.filter_by(id=user_to_warn).first()
        message = BMessage.query.filter_by(id=message).first()

        if user_to_warn is None:
            return jsonify("This user doesn't exit"), 400
        elif message is None:
            return jsonify("This message doesn't exit"), 400

        # .get: "warns" is only seeded on socket connect, so a user who has
        # never had one raises KeyError here — which is everyone, once.
        data = load_data(user_to_warn)
        warns = data.get("warns") or []
        warns.append({
            "message": message.content,
            "rule": rule,
            "created_at": int(time.time())
        })
        data["warns"] = warns
        user_to_warn.data = json.dumps(data)

        report = Report.query.filter_by(id=report_id).first()
        if report is None:
            return jsonify("This report doesn't exist"), 404

        send_message(report.author, f"Привет\nВаша жалоба на сообщение от {user_to_warn.display_name} успешно обработана и выполнена\nСпасибо, что помогаете нам быть безопаснее")

        db.session.delete(report)
        db.session.delete(message)

        db.session.commit()

        socketio.emit("issued_warn", {"rule": rule}, to=user_to_warn.id)
        send_message(user_to_warn.id, f"Привет, {user_to_warn.display_name}!\nУ нас грустные новости(\nВам выдали предупреждение за {rule}. Это {len(data["warns"])} из 5. На 5 предупреждении потеряете доступ к аккаунту. Связанное сообщение с этим предупреждением удалено. Вы можете посмотреть ваши предупреждения в Настройки>Общение>Вы и правила\nПредупреждение подлежит к обжалованию. Вы можете добиться удаления предупреждения, если в течение 6 месяцев вы ничего не нарушали\nС уважением,\nМодерация Clody")

    return jsonify("Success"), 200

@app.route("/api/message/report", methods=["POST"])
def send_report():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    if cooldown.get(session["user"]["id"]) is not None:
        if cooldown.get(session["user"]["id"]) > time.time():
            return jsonify("Cooldown"), 403

    message = request.json.get("message")
    if message is None:
        return jsonify("Bad Request"), 400

    message = BMessage.query.filter_by(id=message).first()
    if message is None:
        return jsonify("Not Found"), 404

    user = User.query.filter_by(id=session["user"]["id"]).first()
    if message.branch not in json.loads(user.data)["branches"]:
        return jsonify("You aren't in this branch"), 403

    report = Report(message=message.id, author=session['user']['id'])
    db.session.add(report)
    db.session.commit()

    cooldown[session["user"]["id"]] = time.time()+3600
    return jsonify("Success"), 200

@app.route("/api/admin/check_reports")
def get_reports():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    user = User.query.filter_by(id=session["user"]["id"]).first()

    if not user.isadmin:
        return jsonify("Forbitten"), 403

    data = []

    reports = Report.query.all()

    for report in reports:
        data.append({
            "id": report.id,
            "author": report.author,
            "message": report.message,
            "data": json.loads(report.data)
        })

    return jsonify(data), 200
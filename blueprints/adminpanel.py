import db
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

@app.route("/api/admin/issue_picnic", methods=["POST"])
def issue_picnic():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    moderator = User.query.filter_by(id=session["user"]["id"]).first()
    if moderator is None or not moderator.isadmin:
        return jsonify("Forbitten"), 403

    id = request.json.get("id")
    rule = request.json.get("rule")
    type = request.json.get("type")

    if id is None or type is None:
        return jsonify("Bad Request"), 400

    report = PicnicReport.query.filter_by(id=id).first()
    if report is None:
        return jsonify("Not Found"), 404

    if type == 1:
        picnic = Picnic.query.filter_by(id=report.picnic_id).first()
        if picnic is None:
            db.session.delete(report)
            db.session.commit()
            return jsonify("Success"), 200

        picnic_id = picnic.id
        picnic_name = picnic.name
        members = list(picnic.members or [])
        users_to_warn = list(picnic.admins or [])
        for user_to_warn in users_to_warn:
            user_to_warn = User.query.filter_by(id=user_to_warn).first()
            if user_to_warn is None:
                continue
            data = load_data(user_to_warn)
            warns = data.get("warns") or []
            warns.append({
                "message": picnic.name,
                "rule": rule,
                "created_at": int(time.time())
            })

            data["warns"] = warns
            user_to_warn.data = json.dumps(data)

            socketio.emit("issued_warn", {"rule": rule}, to=user_to_warn.id)
            send_message(user_to_warn.id,f"Привет, {user_to_warn.display_name}!\nУ нас грустные новости(\nВы были админом на пикнике **{picnic.name}**. Этот пикник был удалён, а вы получили предупреждение по причине **{rule}**\nПикник не подлежит к восстановлению. Это ваше {len(data["warns"])} из 5 предупреждение. На 5 предупреждении вы потеряете доступ к аккаунту. Вы можете отозвать это предупреждение, если вы были добавлены в админы не по своему желанию\nС уважением,\nМодерация Clody")

        for member in members:
            if member in users_to_warn:
                continue

            send_message(member, f"Привет\nПикник **{picnic_name}**, на котором вы находились, был удалён в связи с нарушениями правил. Мы понимаем, что вы не участвовали в его ведении, поэтому мы не даём вам предупреждение")

        for member_id in members:
            member = User.query.filter_by(id=member_id).first()
            if member is None:
                continue
            member_data = load_data(member)
            member_data["picnics"] = [p for p in (member_data.get("picnics") or []) if p != picnic_id]
            member.data = json.dumps(member_data)

        Comment.query.filter_by(picnic=picnic_id).delete()
        PMessage.query.filter_by(picnic=picnic_id).delete()
        PicnicReport.query.filter_by(picnic_id=picnic_id).delete()
        db.session.delete(picnic)
        db.session.commit()

        for member_id in members:
            socketio.emit("deleted_picnic", {"id": picnic_id}, to=member_id)
    else:
        db.session.delete(report)
        db.session.commit()

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

@app.route("/api/picnic/report", methods=["POST"])
def send_picnic_report():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    if cooldown.get(session["user"]["id"]) is not None:
        if cooldown.get(session["user"]["id"]) > time.time():
            return jsonify("Cooldown"), 403

    id = request.json.get("id")
    if id is None:
        return jsonify("Bad Request"), 400

    picnic = Picnic.query.filter_by(id=id).first()
    if picnic is None:
        return jsonify("Not Found"), 404

    if PicnicReport.query.filter_by(picnic_id=id, author=session["user"]["id"]).first():
        return jsonify("Вы уже жаловались на этот пикник"), 403

    report = PicnicReport(picnic_id=id, author=session["user"]["id"], created_at=int(time.time()))
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

    data = {"branches": [], "picnics": []}

    reports = Report.query.all()
    preports = PicnicReport.query.all()

    for report in reports:
        data["branches"].append({
            "id": report.id,
            "author": report.author,
            "message": report.message,
            "data": json.loads(report.data)
        })

    for report in preports:
        picnic = Picnic.query.filter_by(id=report.picnic_id).first()
        data["picnics"].append({
            "id": report.id,
            "picnic": report.picnic_id,
            "author": report.author,
            "created_at": report.created_at,
            "name": picnic.name if picnic else None,
            "avatar": picnic.avatar if picnic else None,
            "members_count": len(picnic.members or []) if picnic else 0,
            "exists": picnic is not None,
        })

    return jsonify(data), 200
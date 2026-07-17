from flask_sqlalchemy import SQLAlchemy
import json

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(), unique=True, nullable=False)
    password = db.Column(db.String(), nullable=False)
    data = db.Column(db.String(), nullable=False, default="{}")
    display_name = db.Column(db.String(), nullable=False)
    avatar = db.Column(db.String(), nullable=True)
    isadmin = db.Column(db.Boolean(), nullable=False, default=False)

class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(), nullable=True)
    members = db.Column(db.PickleType(), nullable=False, default=list)
    messages = db.Column(db.PickleType(), nullable=False, default=list)
    data = db.Column(db.String(), nullable=False, default="{}")
    ispm = db.Column(db.Boolean(), nullable=False)
    owner = db.Column(db.Integer(), nullable=False)

class BMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    branch = db.Column(db.Integer(), nullable=False)
    cdn = db.Column(db.PickleType(), nullable=False, default=list)
    content = db.Column(db.PickleType(), nullable=False, default=list)
    read = db.Column(db.PickleType(), nullable=False, default=list)
    data = db.Column(db.String(), nullable=False, default="{}")
    created_at = db.Column(db.Integer(), nullable=False)
    edited = db.Column(db.Boolean(), nullable=False, default=False)
    author = db.Column(db.Integer(), nullable=False)

class Picnic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(), nullable=False)
    avatar = db.Column(db.String(), nullable=True)
    members = db.Column(db.PickleType(), nullable=False, default=list)
    bans = db.Column(db.PickleType(), nullable=False, default=list)
    messages = db.Column(db.PickleType(), nullable=False, default=list)
    comments = db.Column(db.PickleType(), nullable=True)
    admins = db.Column(db.PickleType(), nullable=False, default=list)
    data = db.Column(db.String(), nullable=False, default="{}")
    link = db.Column(db.String(), nullable=True)
    owner = db.Column(db.Integer(), nullable=False)

class PMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    picnic = db.Column(db.Integer(), nullable=False)
    cdn = db.Column(db.PickleType(), nullable=False, default=list)
    content = db.Column(db.PickleType(), nullable=False, default=list)
    read = db.Column(db.PickleType(), nullable=False, default=list)
    data = db.Column(db.String(), nullable=False, default="{}")
    created_at = db.Column(db.Integer(), nullable=False)
    edited = db.Column(db.Boolean(), nullable=False, default=False)
    author = db.Column(db.Integer(), nullable=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    picnic = db.Column(db.Integer(), nullable=False)
    message = db.Column(db.Integer(), nullable=False)
    content = db.Column(db.String(), nullable=False)
    likes = db.Column(db.PickleType(), nullable=False, default=list)
    answer_to = db.Column(db.Integer(), nullable=True)
    created_at = db.Column(db.Integer(), nullable=False)
    edited = db.Column(db.Boolean(), nullable=False, default=False)
    author = db.Column(db.Integer(), nullable=False)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.Integer, nullable=False)
    data = db.Column(db.String(), nullable=False, default="{}")
    author = db.Column(db.Integer(), nullable=False)


def reset_online_status():
    changed = False
    for user in User.query.all():
        try:
            data = json.loads(user.data) if user.data else {}
        except ValueError:
            data = {}

        if data.get("online"):
            data["online"] = False
            user.data = json.dumps(data)
            changed = True

    if changed:
        db.session.commit()

def init_app(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        reset_online_status()


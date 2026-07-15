from flask import Blueprint, send_from_directory, abort
import os

app = Blueprint("static", "static", static_folder="static")

# /favicon.ico is served from app.py (root favicon.ico) — one route per rule.

@app.route("/app/", defaults={"path": ""})
@app.route("/app/<path:path>")
def spa(path):
    full = os.path.join(app.static_folder, path)
    if path and os.path.isfile(full):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, "index.html")
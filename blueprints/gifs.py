import os
import requests
from flask import Blueprint, request, session, jsonify
from ext import check_session

app = Blueprint("gifs", "gifs")

GIPHY_SEARCH = "https://api.giphy.com/v1/gifs/search"
GIPHY_TRENDING = "https://api.giphy.com/v1/gifs/trending"

@app.route("/api/gifs/search", methods=["POST"])
def search_gifs():
    if not check_session(session):
        return jsonify("Not Authorized"), 400

    key = os.getenv("GIPHY_API_KEY")
    if not key:
        return jsonify("GIF search is not configured"), 503

    query = (request.json.get("q") or "").strip()
    params = {"api_key": key, "limit": 24, "rating": "pg-13", "bundle": "messaging_non_clips"}
    if query:
        params["q"] = query

    try:
        resp = requests.get(GIPHY_SEARCH if query else GIPHY_TRENDING, params=params, timeout=8)
        data = resp.json()
    except Exception:
        return jsonify("GIF service is unavailable"), 502

    results = []
    for gif in data.get("data", []):
        images = gif.get("images", {})
        preview = images.get("fixed_width_small") or images.get("preview_gif") or {}
        full = images.get("downsized") or images.get("original") or {}
        if preview.get("url") and full.get("url"):
            results.append({"id": gif.get("id"), "preview": preview["url"], "url": full["url"]})

    return jsonify(results), 200

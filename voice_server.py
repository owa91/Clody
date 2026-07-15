import eventlet
eventlet.monkey_patch()

import os

from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv

from voice_token import verify_token
from ratelimit import RateLimiter

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

peers = {}

# This process is a separate one — the main app's HTTP limits do not reach it,
# and the relay is where the real volume lands. Budget in BYTES, not messages:
# one 4 MB frame hurts as much as a thousand small ones, and eventlet relays
# them all on a single event loop, so one greedy peer stalls every call.
MAX_FRAME_BYTES = 512 * 1024          # a 1080p keyframe is well under this
SCREEN_BUDGET = RateLimiter(per_minute=4_000_000 * 60, burst=8_000_000)  # ~4 MB/s
VOICE_BUDGET = RateLimiter(per_minute=200_000 * 60, burst=400_000)       # ~200 KB/s (48k mono PCM ≈ 96 KB/s)
# Unauthenticated and cross-origin by design (the caller pings it to pick a
# server), so it is the one thing anyone on the internet can hit for free.
PING_BUDGET = RateLimiter(per_minute=120, burst=30)


def _frame_size(data):
    payload = data.get("data") if isinstance(data, dict) else None
    return len(payload) if isinstance(payload, (bytes, bytearray, memoryview)) else 0

@app.route("/ping")
def ping():
    # Health probe the caller pings cross-origin to pick the fastest server.
    # It must carry a CORS header so the browser can actually READ the response
    # (and thus tell a live 200 from a downed 5xx). The proxy only adds CORS on
    # /socket.io, not here, so this is the sole source — no duplicate header. A
    # plain no-credentials GET, so "*" is enough.
    if not PING_BUDGET.allow(request.remote_addr or "?"):
        return jsonify("Too many requests"), 429

    resp = jsonify("Success")
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp, 200

@socketio.on("join")
def on_join(data):
    call_id = data.get("call_id")
    user_id = data.get("user_id")
    token = data.get("token")
    if call_id is None or user_id is None or not verify_token(token, user_id, call_id):
        emit("error", {"cause": "unauthorized"})
        return
    peers[request.sid] = (user_id, call_id)
    join_room(call_id)


@socketio.on("leave")
def on_leave(_data=None):
    info = peers.pop(request.sid, None)
    if info is not None:
        leave_room(info[1])


@socketio.on("disconnect")
def on_disconnect():
    info = peers.pop(request.sid, None)
    if info is not None:
        leave_room(info[1])


@socketio.on("voice_frame")
def on_voice_frame(data):
    info = peers.get(request.sid)
    if info is None:
        return

    size = _frame_size(data)
    # Drop silently, not with an error: at ~23 frames/sec per speaker an error
    # reply per frame would be its own flood.
    if size > MAX_FRAME_BYTES or not VOICE_BUDGET.allow(request.sid, cost=size or 1):
        return

    user_id, call_id = info
    emit(
        "voice_frame",
        {"author": user_id, "sr": data.get("sr"), "data": data.get("data")},
        to=call_id,
        skip_sid=request.sid,
    )


@socketio.on("screen_frame")
def on_screen_frame(data):
    info = peers.get(request.sid)
    if info is None:
        return

    size = _frame_size(data)
    if size > MAX_FRAME_BYTES or not SCREEN_BUDGET.allow(request.sid, cost=size or 1):
        return

    user_id, call_id = info
    emit(
        "screen_frame",
        {
            "author": user_id,
            "key": data.get("key"),
            "ts": data.get("ts"),
            "data": data.get("data"),
            "config": data.get("config"),
        },
        to=call_id,
        skip_sid=request.sid,
    )


if __name__ == "__main__":
    print("voice server listening on :20002")
    socketio.run(app, host="0.0.0.0", port=20002, allow_unsafe_werkzeug=True, debug=True)

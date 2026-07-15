import hashlib
import hmac
import os
import time

from dotenv import load_dotenv

load_dotenv()

_SECRET = (os.getenv("SECRET_KEY") or "").encode()
TTL_SECONDS = 300


def _sign(message):
    return hmac.new(_SECRET, message.encode(), hashlib.sha256).hexdigest()


def make_token(user_id, call_id):
    expiry = int(time.time()) + TTL_SECONDS
    message = f"{user_id}:{call_id}:{expiry}"
    return f"{message}:{_sign(message)}"


def verify_token(token, user_id, call_id):
    if not token:
        return False
    try:
        uid, cid, expiry, sig = token.rsplit(":", 3)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, _sign(f"{uid}:{cid}:{expiry}")):
        return False
    if str(user_id) != uid or str(call_id) != cid:
        return False
    try:
        if int(expiry) < int(time.time()):
            return False
    except ValueError:
        return False
    return True

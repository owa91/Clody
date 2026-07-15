import functools
import time
from collections import OrderedDict

from flask import request, session
from flask_socketio import emit


class RateLimiter:

    def __init__(self, per_minute, burst=None, max_keys=20_000):
        self.rate = per_minute / 60.0
        self.burst = float(burst if burst is not None else max(1, per_minute))
        self.max_keys = max_keys
        self._buckets = OrderedDict()

    def allow(self, key, cost=1.0):
        now = time.monotonic()
        bucket = self._buckets.get(key)

        if bucket is None:
            if len(self._buckets) >= self.max_keys:
                self._buckets.popitem(last=False)
            bucket = [self.burst, now]
            self._buckets[key] = bucket
        else:
            self._buckets.move_to_end(key)
            elapsed = now - bucket[1]
            if elapsed > 0:
                bucket[0] = min(self.burst, bucket[0] + elapsed * self.rate)
                bucket[1] = now

        if bucket[0] >= cost:
            bucket[0] -= cost
            return True
        return False

    def retry_after(self, key, cost=1.0):
        bucket = self._buckets.get(key)
        if bucket is None or bucket[0] >= cost:
            return 0
        return max(0, (cost - bucket[0]) / self.rate)


def client_key():
    user = session.get("user")
    if user and user.get("id") is not None:
        return f"u:{user['id']}"
    return f"ip:{request.remote_addr}"


def limit_event(per_minute, burst=None, cost=1.0):
    limiter = RateLimiter(per_minute, burst)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = session.get("user")
            key = f"u:{user['id']}" if user and user.get("id") is not None else f"sid:{request.sid}"
            if not limiter.allow(key, cost):
                emit("error", {"cause": "Too many requests"})
                return None
            return fn(*args, **kwargs)

        return wrapper

    return decorator


class HttpLimits:
    def __init__(self, default_per_minute=200, default_burst=60):
        self._default = RateLimiter(default_per_minute, default_burst)
        self._routes = {}
        self._exempt = set()

    def route(self, prefix, per_minute, burst=None):
        self._routes[prefix] = RateLimiter(per_minute, burst)
        return self

    def exempt(self, prefix):
        self._exempt.add(prefix)
        return self

    def _limiter_for(self, path):
        best = None
        for prefix, limiter in self._routes.items():
            if path.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
                best = (prefix, limiter)
        return best[1] if best else self._default

    def init_app(self, app):
        @app.before_request
        def _enforce():
            path = request.path
            for prefix in self._exempt:
                if path.startswith(prefix):
                    return None

            limiter = self._limiter_for(path)
            key = client_key()
            if limiter.allow(key):
                return None

            retry = int(limiter.retry_after(key)) + 1
            return (
                {"error": "Too many requests"},
                429,
                {"Retry-After": str(retry)},
            )

        return app

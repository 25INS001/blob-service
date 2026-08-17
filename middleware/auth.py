"""Bearer-token authentication, verified against auth-service.

blob-service does not validate JWTs itself; it asks auth-service, which owns
the signing key and the revocation state. That is the right call -- a local
check would need the secret distributed and could not see a revoked session --
but it puts a network round trip on every authenticated request, so how that
round trip is made matters a great deal.

Measured inside the cluster against /api/token/verify:

    fresh connection per call    p50  74.7ms
    reused session               p50   0.8ms

Ninety-three times, and none of it is the endpoint: verification itself is
sub-millisecond. The rest was TCP setup, paid on every request because this
module called requests.get() directly, which builds a new connection each time.

It compounded badly here. flask-socketio runs under eventlet, and eventlet is
NOT monkey-patched in this app, so a blocking socket call stalls the whole
event loop rather than yielding. Every concurrent request therefore waited
behind that 75ms, and a load sweep at 8 concurrent clients measured p50 1628ms
on routes that answer in 118ms unauthenticated.

So: one pooled session, and a short-lived cache of successful verifications.
"""

import hashlib
import logging
import os
import threading
import time
from functools import wraps

import requests
from flask import g, jsonify, request
from requests.adapters import HTTPAdapter

from config import Config

logger = logging.getLogger("seaweed-flask")

# One session for the process, with a pool big enough that concurrent requests
# do not fall back to building fresh connections -- which would reintroduce
# exactly the cost this exists to remove. Retries are left at zero on purpose:
# auth-service being unreachable should surface immediately as 503, not be
# hidden behind a retry that multiplies the latency of an already-failing call.
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=4, pool_maxsize=32, max_retries=0)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)

VERIFY_TIMEOUT = float(os.getenv("AUTH_VERIFY_TIMEOUT", "5"))

# Cache successful verifications only, briefly.
#
# The trade is explicit: a token revoked at auth-service stays accepted here for
# up to this long. Thirty seconds keeps that window smaller than most session
# lifetimes while still collapsing a burst of requests from one client into a
# single verification. Set AUTH_VERIFY_CACHE_TTL=0 to disable it entirely, which
# is the right choice if revocation ever needs to be immediate.
CACHE_TTL = float(os.getenv("AUTH_VERIFY_CACHE_TTL", "30"))
CACHE_MAX = int(os.getenv("AUTH_VERIFY_CACHE_MAX", "2048"))

# Failures are never cached. A 401 is cheap to recompute and caching it would
# mean a client that fixes its credential stays locked out; worse, it would let
# an attacker's probe pin a negative result.
_cache = {}
_cache_lock = threading.Lock()


def _cache_key(auth_header):
    # The header is a credential; hash it so it never reaches a log, a
    # traceback or a heap dump in a readable form.
    return hashlib.sha256(auth_header.encode("utf-8")).hexdigest()


def _cache_get(key):
    if CACHE_TTL <= 0:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        user_id, expires = hit
        if expires <= now:
            _cache.pop(key, None)
            return None
        return user_id


def _cache_put(key, user_id):
    if CACHE_TTL <= 0:
        return
    now = time.monotonic()
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            # Drop what has already expired before resorting to anything
            # cleverer; under normal traffic this keeps the map small without
            # tracking access order.
            for k in [k for k, (_, exp) in _cache.items() if exp <= now]:
                _cache.pop(k, None)
            if len(_cache) >= CACHE_MAX:
                _cache.clear()
        _cache[key] = (user_id, now + CACHE_TTL)


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Missing Authorization header"}), 401

        key = _cache_key(auth_header)
        cached = _cache_get(key)
        if cached is not None:
            g.user_id = cached
            return f(*args, **kwargs)

        try:
            resp = _session.get(
                f"{Config.AUTH_SERVICE_URL}/api/token/verify",
                headers={"Authorization": auth_header},
                timeout=VERIFY_TIMEOUT,
            )

            if resp.status_code != 200:
                logger.warning(f"Auth failed: {resp.status_code} {resp.text}")
                return jsonify({"error": "Unauthorized"}), 401

            data = resp.json()
            # TokenController returns: {"isValid": true, "user_id": 123}
            user_id = data.get("user_id")
            if not user_id:
                return jsonify({"error": "Invalid token payload"}), 401

            user_id = str(user_id)  # string for S3 prefixes
            _cache_put(key, user_id)
            g.user_id = user_id

        except requests.exceptions.RequestException as e:
            logger.error(f"Auth Service unreachable: {e}")
            return jsonify({"error": "Authentication unavailable"}), 503

        return f(*args, **kwargs)

    return decorated

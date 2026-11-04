"""Remembered-login tokens: credentials are never signing keys."""
import base64
import hashlib
import hmac
import json
import secrets
import time

# Private to the running server, not derived from any publicly readable value.
# Without a configured persistent secret, a restart deliberately logs users out.
_PROCESS_KEY = secrets.token_bytes(32)


def signing_key(configured=None):
    if configured is None or configured == '':
        return _PROCESS_KEY
    value = str(configured).encode('utf-8')
    if len(value) < 32:
        raise ValueError('AUTH_COOKIE_SECRET must contain at least 32 bytes')
    return value


def signature(username, expires_at, credential, key):
    message = json.dumps(
        [2, str(username), int(expires_at), hashlib.sha256(str(credential).encode('utf-8')).hexdigest()],
        separators=(',', ':'), ensure_ascii=False,
    ).encode('utf-8')
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def create_token(username, credential, key, lifetime, now=None):
    expires = int(time.time() if now is None else now) + lifetime
    payload = {'v': 2, 'u': username, 'exp': expires,
               'sig': signature(username, expires, credential, key)}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).decode('ascii').rstrip('=')


def read_token(token, lifetime, now=None):
    if not isinstance(token, str) or len(token) > 4096:
        return None
    try:
        data = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True))
        current = int(time.time() if now is None else now)
        if not isinstance(data, dict) or data.get('v') != 2:
            return None
        if not isinstance(data.get('u'), str) or not 0 < len(data['u']) <= 256:
            return None
        expires = data.get('exp')
        if type(expires) is not int or not current < expires <= current + lifetime + 60:
            return None
        if not isinstance(data.get('sig'), str) or len(data['sig']) != 64:
            return None
        return data
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None

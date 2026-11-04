"""Shared password hashing for every account-creation entry point."""
import base64
import hashlib
import secrets


def hash_password(password):
    salt = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode('ascii').rstrip('=')
    digest = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), salt.encode('ascii'), 210000, dklen=32)
    return 'pbkdf2_sha256$210000$' + salt + '$' + base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')


def preserve_or_hash_password(value):
    value = str(value)
    if value.startswith('pbkdf2_sha256$'):
        return value
    return hash_password(value)

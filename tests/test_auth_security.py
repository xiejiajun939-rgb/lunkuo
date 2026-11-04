import base64
import hashlib
import hmac
import json
import unittest
from core.auth_tokens import create_token, read_token, signature, signing_key
from core.passwords import hash_password


class AuthSecurityTests(unittest.TestCase):
    def test_round_trip_and_credential_revocation(self):
        key = b'a' * 32
        token = create_token('tester', 'credential-hash', key, 604800, now=1000)
        payload = read_token(token, 604800, now=1001)
        self.assertEqual(payload['u'], 'tester')
        self.assertEqual(payload['sig'], signature('tester', payload['exp'], 'credential-hash', key))
        self.assertNotEqual(payload['sig'], signature('tester', payload['exp'], 'changed-hash', key))
        self.assertNotEqual(payload['sig'], signature('tester', payload['exp'], 'credential-hash', b'b' * 32))

    def test_legacy_hash_derived_forgery_is_rejected(self):
        expiry = 2000
        known_hash = 'exposed-hash'
        key = hashlib.sha256(f'lunkuo-auth-v1|tester|{known_hash}'.encode()).digest()
        old_sig = hmac.new(key, f'tester|{expiry}'.encode(), hashlib.sha256).hexdigest()
        token = base64.urlsafe_b64encode(json.dumps({'u': 'tester', 'exp': expiry, 'sig': old_sig}).encode()).decode()
        self.assertIsNone(read_token(token, 604800, now=1000))
        self.assertNotEqual(old_sig, signature('tester', expiry, known_hash, signing_key()))

    def test_malformed_and_expired_tokens(self):
        for token in ('not-json', 'A' * 5000, None, 'W10='):
            self.assertIsNone(read_token(token, 604800, now=1000))
        expired = create_token('tester', 'hash', b'x' * 32, 100, now=100)
        self.assertIsNone(read_token(expired, 100, now=201))
        long_lived = create_token('tester', 'hash', b'x' * 32, 10000, now=1000)
        self.assertIsNone(read_token(long_lived, 100, now=1001))

    def test_password_creation_hashes_with_unique_salt(self):
        first = hash_password('test-only-not-an-account')
        second = hash_password('test-only-not-an-account')
        self.assertTrue(first.startswith('pbkdf2_sha256$210000$'))
        self.assertNotEqual(first, second)
        _, rounds, salt, encoded = first.split('$')
        digest = hashlib.pbkdf2_hmac('sha256', b'test-only-not-an-account', salt.encode(), int(rounds), dklen=32)
        self.assertEqual(base64.urlsafe_b64encode(digest).decode().rstrip('='), encoded)

    def test_server_key_is_private_and_stable_in_process(self):
        self.assertEqual(signing_key(), signing_key())
        with self.assertRaises(ValueError):
            signing_key('too-short')


if __name__ == '__main__':
    unittest.main()

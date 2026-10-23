import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from mailbridge.config import Config, BridgeError, example_config, write_config
except ImportError:
    Config = None


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Config, 'configuration module must exist')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'config.json'

    def config(self, **changes):
        data = example_config()
        data.update(changes)
        write_config(self.path, data)
        return Config.load(self.path)

    def test_defaults_are_read_only_tls(self):
        c = self.config()
        self.assertFalse(c.allow_send)
        self.assertEqual(c.imap['security'], 'tls')
        self.assertEqual(c.folders, ['INBOX'])

    def test_secrets_only_from_declared_source(self):
        c = self.config()
        with patch.dict(os.environ, {'MAILBRIDGE_PASSWORD': 'local-test-value'}):
            self.assertEqual(c.secret(), 'local-test-value')
        self.assertNotIn('local-test-value', self.path.read_text())

    def test_plaintext_password_field_rejected(self):
        with self.assertRaises(BridgeError) as e:
            self.config(password='never-echo-this')
        self.assertNotIn('never-echo-this', str(e.exception))

    def test_invalid_tls_mode_rejected(self):
        with self.assertRaises(BridgeError):
            self.config(imap={'host': 'imap.example.com', 'port': 143, 'security': 'none'})

    def test_boolean_string_rejected(self):
        with self.assertRaises(BridgeError):
            self.config(allow_send='false')

    def test_email_header_injection_rejected(self):
        with self.assertRaises(BridgeError):
            self.config(email='a@example.com\r\nBcc:b@example.com')

    def test_existing_config_never_overwritten(self):
        self.config()
        before = self.path.read_bytes()
        with self.assertRaises(BridgeError):
            write_config(self.path, {'allow_send': True})
        self.assertEqual(before, self.path.read_bytes())

    def test_size_limits_and_account_id_validate(self):
        for changes in [{'max_message_bytes': -1}, {'account_id': '../escape'}, {'timeout': True}]:
            with self.subTest(changes=changes):
                self.path.unlink(missing_ok=True)
                with self.assertRaises(BridgeError):
                    self.config(**changes)

    def test_missing_secret_safe_error(self):
        c = self.config(secret_env='MAILBRIDGE_TEST_MISSING')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(BridgeError) as e:
                c.secret()
        self.assertEqual(e.exception.code, 'SECRET_MISSING')

    def test_unknown_fields_rejected(self):
        with self.assertRaises(BridgeError):
            self.config(allow_sned=True)

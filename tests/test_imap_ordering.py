import unittest
from types import SimpleNamespace
from mailbridge.transport import MailTransport
from mailbridge.config import BridgeError


class FetchOrderingTests(unittest.TestCase):
    def literal(self, response):
        client=SimpleNamespace(uid=lambda *a: ('OK',response))
        return MailTransport._literal(None,client,'7','(BODY.PEEK[])',100)

    def test_uid_after_literal_is_valid(self):
        self.assertEqual(self.literal([(b'1 (BODY[] {4}',b'test'),b' UID 7)']),b'test')

    def test_uid_from_another_response_cannot_authorize_literal(self):
        with self.assertRaises(BridgeError):
            self.literal([(b'1 (BODY[] {4}',b'test'),b')',b'2 (UID 7 FLAGS ())'])

    def test_mismatched_uid_after_literal_rejected(self):
        with self.assertRaises(BridgeError):
            self.literal([(b'1 (BODY[] {4}',b'test'),b' UID 8)'])

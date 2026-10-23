import concurrent.futures
import tempfile
import threading
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from mailbridge.config import Config, BridgeError, example_config
try:
    from mailbridge.outbox import Outbox
except ImportError:
    Outbox = None


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.result = {'state': 'accepted', 'refused': []}
        self.lock = threading.Lock()
    def submit(self, raw, recipients):
        with self.lock:
            self.calls.append((raw, recipients))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result
    def fetch(self, id):
        return {'message_id': '<parent@example.com>', 'references': '<older@example.com>'}


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Outbox, 'durable outbox must exist')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Config(Path(self.tmp.name) / 'config.json', example_config() | {'allow_send': True})
        self.transport = FakeTransport()
        self.box = Outbox(self.config, self.transport)
    def prepare(self, **kw):
        return self.box.prepare(**({'to': ['recipient@example.com'], 'subject': 'Hello 世界', 'text': 'Exact body\n'} | kw))
    def test_prepare_has_no_network_side_effect(self):
        p = self.prepare()
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(p['state'], 'prepared')
        self.assertEqual(p['preview']['text'], 'Exact body\n')
    def test_read_only_config_blocks_send(self):
        p = self.prepare()
        self.config.allow_send = False
        with self.assertRaises(BridgeError): self.box.send(p['draft_id'], p['confirmation'])
        self.assertFalse(self.transport.calls)
    def test_wrong_confirmation_blocks_send(self):
        p = self.prepare()
        with self.assertRaises(BridgeError): self.box.send(p['draft_id'], 'wrong')
        self.assertFalse(self.transport.calls)
    def test_same_draft_and_equivalent_prepare_never_resubmit(self):
        p = self.prepare()
        self.assertEqual(self.box.send(p['draft_id'], p['confirmation'])['state'], 'accepted')
        p2 = self.prepare()
        self.assertEqual(p2['draft_id'], p['draft_id'])
        self.box.send(p2['draft_id'], p2['confirmation'])
        self.assertEqual(len(self.transport.calls), 1)
    def test_bcc_envelope_only_and_unicode(self):
        p = self.prepare(bcc=['blind@example.com'])
        self.box.send(p['draft_id'], p['confirmation'])
        raw, recipients = self.transport.calls[0]
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertIsNone(parsed['Bcc'])
        self.assertEqual(str(parsed['Subject']), 'Hello 世界')
        self.assertIn('blind@example.com', recipients)
    def test_uncertain_survives_restart_without_retry(self):
        p = self.prepare()
        self.transport.result = TimeoutError('password-not-for-output')
        result = self.box.send(p['draft_id'], p['confirmation'])
        self.assertEqual(result['state'], 'uncertain')
        self.assertNotIn('password-not-for-output', str(result))
        reopened = Outbox(self.config, self.transport)
        self.assertEqual(reopened.send(p['draft_id'], p['confirmation'])['state'], 'uncertain')
        self.assertEqual(len(self.transport.calls), 1)
    def test_concurrent_submissions_only_call_transport_once(self):
        p = self.prepare()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: Outbox(self.config, self.transport).send(p['draft_id'], p['confirmation']), range(2)))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertTrue(all(r['state'] in ('sending', 'accepted') for r in results))
    def test_account_change_cannot_send_old_draft(self):
        p = self.prepare()
        self.config.email = 'different@example.com'
        with self.assertRaises(BridgeError): self.box.send(p['draft_id'], p['confirmation'])
        self.assertFalse(self.transport.calls)
    def test_header_injection_rejected(self):
        for kw in [{'subject': 'hello\r\nBcc:other@example.com'}, {'to': ['x@example.com\n']}, {'cc': 'x@example.com'}]:
            with self.subTest(kw=kw), self.assertRaises(BridgeError): self.prepare(**kw)
    def test_roles_and_body_whitespace_preserved(self):
        p1 = self.prepare(cc=['cc@example.com'])
        p2 = self.prepare(bcc=['cc@example.com'])
        p3 = self.prepare(text='Exact body')
        self.assertEqual(len({p1['confirmation'], p2['confirmation'], p3['confirmation']}), 3)
    def test_reply_headers_preserved(self):
        p = self.prepare(reply_to_id='parent-id')
        self.box.send(p['draft_id'], p['confirmation'])
        msg = BytesParser(policy=policy.default).parsebytes(self.transport.calls[0][0])
        self.assertEqual(str(msg['In-Reply-To']), '<parent@example.com>')
        self.assertEqual(str(msg['References']), '<older@example.com> <parent@example.com>')
    def test_partial_state_never_retries(self):
        p = self.prepare()
        self.transport.result = {'state':'partial','refused':['recipient@example.com']}
        self.box.send(p['draft_id'], p['confirmation'])
        self.assertEqual(self.box.send(p['draft_id'],p['confirmation'])['state'],'partial')
        self.assertEqual(len(self.transport.calls),1)

    def test_known_pre_submission_failure_can_be_explicitly_retried(self):
        p = self.prepare()
        self.transport.result = BridgeError('SECRET_MISSING')
        failed = self.box.send(p['draft_id'], p['confirmation'])
        self.assertEqual(failed['state'], 'not_submitted')
        self.transport.result = {'state':'accepted','refused':[]}
        self.assertEqual(self.box.send(p['draft_id'], p['confirmation'])['state'], 'accepted')
        self.assertEqual(len(self.transport.calls), 2)

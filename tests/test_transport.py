"""Offline protocol fakes: no provider connections or real credentials."""
import importlib.util
import os
import smtplib
import ssl
import unittest
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock, patch


def sample_message():
    msg = EmailMessage()
    msg['From'] = 'sender@example.com'
    msg['To'] = 'reader@example.com'
    msg['Subject'] = '季度报告 quarterly report'
    msg['Message-ID'] = '<sample@example.com>'
    msg['References'] = '<parent@example.com>'
    msg.set_content('Hello, 世界.\n')
    msg.add_attachment('a,b\n1,2\n'.encode(), maintype='text', subtype='csv', filename='report.csv')
    msg.add_attachment(b'<script>bad()</script>', maintype='text', subtype='html', filename='page.html')
    return msg.as_bytes()


class FakeIMAP:
    def __init__(self, raw=None):
        self.raw = raw or sample_message()
        self.validity = b'42'
        self.ids = [b'7']
        self.calls = []
        self.size = len(self.raw)
        self.body_override = None
        self.login_error = None

    def login(self, username, password):
        self.calls.append(('login', username, password))
        if self.login_error:
            raise self.login_error
        return 'OK', []

    def authenticate(self, mechanism, callback):
        self.calls.append(('authenticate', mechanism, callback(b'')))
        return 'OK', []

    def starttls(self, ssl_context):
        self.calls.append(('starttls', ssl_context))
        return 'OK', []

    def select(self, folder, readonly=False):
        self.calls.append(('select', folder, readonly))
        return 'OK', [str(len(self.ids)).encode()]

    def response(self, code):
        return code, [self.validity]

    def uid(self, operation, *args):
        self.calls.append(('uid', operation, *args))
        if operation == 'SEARCH':
            return 'OK', [b' '.join(self.ids)]
        uid, request = args
        if request == '(RFC822.SIZE)':
            return 'OK', [b'1 (UID ' + uid.encode() + b' RFC822.SIZE ' + str(self.size).encode() + b')']
        raw = self.raw if self.body_override is None else self.body_override
        if 'HEADER' in request:
            raw = self.raw.split(b'\n\n', 1)[0] + b'\n\n'
        return 'OK', [(b'1 (UID ' + uid.encode() + b' BODY[] {' + str(len(raw)).encode() + b'}', raw), b')']

    def logout(self):
        self.calls.append(('logout',))
        return 'BYE', []


class FakeSMTP:
    def __init__(self):
        self.calls = []
        self.refused = {}
        self.send_error = None
        self.quit_error = None

    def ehlo(self):
        self.calls.append(('ehlo',))
        return 250, b'hello'

    def starttls(self, context):
        self.calls.append(('starttls', context))
        return 220, b'ready'

    def login(self, username, password):
        self.calls.append(('login', username, password))

    def auth(self, mechanism, callback, initial_response_ok=True):
        self.calls.append(('auth', mechanism, callback()))
        return 235, b'ok'

    def sendmail(self, sender, recipients, raw):
        self.calls.append(('sendmail', sender, recipients, raw))
        if self.send_error:
            raise self.send_error
        return self.refused

    def quit(self):
        self.calls.append(('quit',))
        if self.quit_error:
            raise self.quit_error

    def close(self):
        self.calls.append(('close',))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mailbridge.transport'), 'Transport implementation is missing')
        from mailbridge import transport
        self.module = transport
        self.literal_guard_class = transport._BoundedIMAP4_SSL
        self.config = SimpleNamespace(
            account_id='test-account', email='reader@example.com', username='reader@example.com',
            imap={'host': 'imap.example.com', 'port': 993, 'security': 'tls'},
            smtp={'host': 'smtp.example.com', 'port': 465, 'security': 'tls'},
            auth='password', secret=Mock(return_value='TEST_SECRET'), folders=['INBOX'],
            timeout=15, max_message_bytes=100000, max_attachment_bytes=1000, allow_send=True,
        )
        self.imap = FakeIMAP()
        self.smtp = FakeSMTP()
        self.transport = transport.MailTransport(self.config)
        self.imap_constructor = self.enterContext(patch.object(transport, '_BoundedIMAP4_SSL', return_value=self.imap))
        self.enterContext(patch.object(transport, '_BoundedIMAP4', return_value=self.imap))
        self.smtp_constructor = self.enterContext(patch.object(transport.smtplib, 'SMTP_SSL', return_value=self.smtp))
        self.enterContext(patch.object(transport.smtplib, 'SMTP', return_value=self.smtp))
        # This only enables deterministic in-memory fakes; no live sockets exist.
        self.enterContext(patch.dict(os.environ, {'CODEX_SANDBOX_NETWORK_DISABLED': '0', 'MAILBRIDGE_SANDBOX': '0'}))

    def message_id(self):
        return self.transport.search()['messages'][0]['id']

    def assert_error(self, code, callback):
        with self.assertRaises(self.module.BridgeError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn('TEST_SECRET', str(caught.exception))

    def test_offline_status_does_not_load_secret_or_connect(self):
        status = self.transport.status()
        self.assertFalse(status['imap_verified'])
        self.config.secret.assert_not_called()
        self.imap_constructor.assert_not_called()

    def test_status_authenticates_with_verified_tls(self):
        status = self.transport.status(True, True)
        self.assertTrue(status['imap_verified'])
        self.assertTrue(status['smtp_verified'])
        context = self.imap_constructor.call_args.kwargs['ssl_context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(any(call[0] == 'sendmail' for call in self.smtp.calls))

    def test_guard_blocks_network_before_secret_lookup(self):
        with patch.dict(os.environ, {'CODEX_SANDBOX_NETWORK_DISABLED': '1'}):
            self.assert_error('NETWORK_DISABLED', lambda: self.transport.status(True))
        self.config.secret.assert_not_called()
        self.imap_constructor.assert_not_called()

    def test_unicode_search_filters_bounded_headers_and_preserves_unread(self):
        result = self.transport.search(query='季度')
        self.assertEqual(len(result['messages']), 1)
        self.assertIn('季度', result['messages'][0]['subject'])
        self.assertEqual(result['coverage']['scope'], 'recent_headers')
        self.assertTrue(result['untrusted'])
        self.assertIn(('select', '"INBOX"', True), self.imap.calls)
        self.assertTrue(all('PEEK' in call[3] for call in self.imap.calls if call[:2] == ('uid', 'FETCH') and 'BODY' in call[3]))

    def test_search_discloses_recent_hundred_header_coverage(self):
        self.imap.ids = [str(i).encode() for i in range(1, 151)]
        result = self.transport.search(query='never matches')
        self.assertEqual(result['coverage']['scanned'], 100)
        self.assertEqual(result['coverage']['available'], 150)
        self.assertFalse(result['coverage']['complete'])

    def test_search_rejects_invalid_folder_date_and_limit_before_connect(self):
        for args in ({'folder': 'Archive'}, {'after': '2026-99-01'}, {'limit': 0}, {'limit': True}, {'query': '\r\n'}):
            with self.subTest(args=args):
                self.assert_error('INVALID_ARGUMENT', lambda: self.transport.search(**args))
        self.imap_constructor.assert_not_called()

    def test_fetch_returns_decoded_text_and_validated_metadata(self):
        result = self.transport.fetch(self.message_id())
        self.assertIn('世界', result['text'])
        self.assertEqual(result['message_id'], '<sample@example.com>')
        self.assertEqual(result['references'], '<parent@example.com>')
        self.assertTrue(result['untrusted'])

    def test_uidvalidity_change_rejects_stale_id_before_fetch(self):
        identifier = self.message_id()
        self.imap.validity = b'43'
        self.imap.calls.clear()
        self.assert_error('STALE_MESSAGE_ID', lambda: self.transport.fetch(identifier))
        self.assertFalse(any(call[:2] == ('uid', 'FETCH') for call in self.imap.calls))

    def test_account_configuration_change_rejects_old_id(self):
        identifier = self.message_id()
        self.config.email = 'different@example.com'
        other = self.module.MailTransport(self.config)
        self.assert_error('INVALID_MESSAGE_ID', lambda: other.fetch(identifier))

    def test_size_is_checked_before_body_fetch(self):
        identifier = self.message_id()
        self.imap.size = self.config.max_message_bytes + 1
        self.imap.calls.clear()
        self.assert_error('MESSAGE_TOO_LARGE', lambda: self.transport.fetch(identifier))
        self.assertFalse(any(call[:2] == ('uid', 'FETCH') and 'BODY' in call[3] for call in self.imap.calls))

    def test_server_size_lie_or_truncated_body_is_rejected(self):
        identifier = self.message_id()
        self.imap.body_override = b'partial'
        self.assert_error('IMAP_PROTOCOL', lambda: self.transport.fetch(identifier))

    def test_body_request_has_explicit_byte_limit(self):
        self.transport.fetch(self.message_id())
        requests = [call[3] for call in self.imap.calls if call[:2] == ('uid', 'FETCH')]
        self.assertIn('(BODY.PEEK[]<0.100001>)', requests)

    def test_attachment_read_returns_text_and_rejects_html(self):
        result = self.transport.list_attachments(self.message_id())
        csv, html = result['attachments']
        self.assertEqual(csv['filename'], 'report.csv')
        self.assertTrue(csv['readable'])
        self.assertFalse(html['readable'])
        read = self.transport.read_attachment(csv['id'])
        self.assertEqual(read['text'], 'a,b\n1,2\n')
        self.assertTrue(read['untrusted'])
        self.assert_error('UNSUPPORTED_ATTACHMENT', lambda: self.transport.read_attachment(html['id']))

    def test_attachment_limit_is_enforced(self):
        identifier = self.transport.list_attachments(self.message_id())['attachments'][0]['id']
        self.config.max_attachment_bytes = 2
        self.assert_error('ATTACHMENT_TOO_LARGE', lambda: self.transport.read_attachment(identifier))

    def test_attachment_id_detects_message_content_change(self):
        identifier = self.transport.list_attachments(self.message_id())['attachments'][0]['id']
        self.imap.raw = self.imap.raw.replace(b'quarterly', b'monthly  ')
        self.imap.size = len(self.imap.raw)
        self.assert_error('STALE_ATTACHMENT_ID', lambda: self.transport.read_attachment(identifier))

    def test_attached_email_does_not_leak_into_parent_body(self):
        outer = EmailMessage()
        outer.set_content('Parent body')
        nested = EmailMessage()
        nested.set_content('Nested attachment secret')
        outer.add_attachment(nested, filename='forward.eml')
        self.imap.raw = outer.as_bytes()
        self.imap.size = len(self.imap.raw)
        result = self.transport.fetch(self.message_id())
        self.assertIn('Parent body', result['text'])
        self.assertNotIn('Nested attachment secret', result['text'])

    def test_attached_email_is_listed_as_unsupported(self):
        outer = EmailMessage()
        outer.set_content('Parent body')
        nested = EmailMessage()
        nested.set_content('Nested attachment secret')
        outer.add_attachment(nested, filename='forward.eml')
        self.imap.raw = outer.as_bytes()
        self.imap.size = len(self.imap.raw)
        result = self.transport.list_attachments(self.message_id())
        self.assertEqual(len(result['attachments']), 1)
        self.assertEqual(result['attachments'][0]['filename'], 'forward.eml')
        self.assertFalse(result['attachments'][0]['readable'])
        self.assert_error('UNSUPPORTED_ATTACHMENT', lambda: self.transport.read_attachment(result['attachments'][0]['id']))

    def test_malformed_ids_never_connect(self):
        for bad in ('', '../INBOX', 'mb1.!!', 'x' * 10000):
            self.assert_error('INVALID_MESSAGE_ID', lambda: self.transport.fetch(bad))
        self.imap_constructor.assert_not_called()

    def test_readonly_rejects_submit_before_secret(self):
        self.config.allow_send = False
        self.assert_error('SEND_DISABLED', lambda: self.transport.submit(b'Subject: x\r\n\r\nHello', ['to@example.com']))
        self.config.secret.assert_not_called()

    def test_smtp_uses_configured_envelope_and_retains_acceptance_after_quit_error(self):
        self.smtp.quit_error = OSError('TEST_SECRET provider debug')
        raw = b'From: reader@example.com\r\nTo: to@example.com\r\n\r\nHello'
        result = self.transport.submit(raw, ['to@example.com', 'hidden@example.com'])
        self.assertEqual(result, {'state': 'accepted', 'refused': []})
        self.assertIn(('sendmail', 'reader@example.com', ['to@example.com', 'hidden@example.com'], raw), self.smtp.calls)

    def test_smtp_partial_and_all_refused_are_deterministic(self):
        self.smtp.refused = {'no@example.com': (550, b'TEST_SECRET rejected')}
        self.assertEqual(self.transport.submit(b'Subject: x\r\n\r\nHello', ['yes@example.com', 'no@example.com']), {'state': 'partial', 'refused': ['no@example.com']})
        self.smtp.send_error = smtplib.SMTPRecipientsRefused(self.smtp.refused)
        self.assertEqual(self.transport.submit(b'Subject: x\r\n\r\nHello', ['no@example.com']), {'state': 'refused', 'refused': ['no@example.com']})

    def test_smtp_ambiguous_disconnect_returns_safe_uncertain_error(self):
        self.smtp.send_error = smtplib.SMTPServerDisconnected('TEST_SECRET provider debug')
        self.assert_error('SMTP_UNCERTAIN', lambda: self.transport.submit(b'Subject: x\r\n\r\nHello', ['to@example.com']))

    def test_submit_rejects_bcc_header_and_recipient_injection(self):
        self.assert_error('INVALID_ARGUMENT', lambda: self.transport.submit(b'Bcc: hidden@example.com\r\n\r\nHello', ['hidden@example.com']))
        self.assert_error('INVALID_ARGUMENT', lambda: self.transport.submit(b'Subject: x\r\n\r\nHello', ['to@example.com\r\nRCPT TO:bad@example.com']))
        self.smtp_constructor.assert_not_called()

    def test_starttls_precedes_password_authentication(self):
        self.config.imap['security'] = 'starttls'
        self.config.smtp['security'] = 'starttls'
        self.transport.status(True, True)
        self.assertLess([c[0] for c in self.imap.calls].index('starttls'), [c[0] for c in self.imap.calls].index('login'))
        self.assertLess([c[0] for c in self.smtp.calls].index('starttls'), [c[0] for c in self.smtp.calls].index('login'))

    def test_oauth2_uses_sasl_for_both_protocols(self):
        self.config.auth = 'oauth2'
        self.transport.status(True, True)
        self.assertTrue(any(c[0] == 'authenticate' and c[1] == 'XOAUTH2' for c in self.imap.calls))
        self.assertTrue(any(c[0] == 'auth' and c[1] == 'XOAUTH2' for c in self.smtp.calls))

    def test_provider_errors_do_not_escape_with_raw_text(self):
        self.imap.login_error = OSError('TEST_SECRET provider debug')
        self.assert_error('IMAP_CONNECTION', lambda: self.transport.status(True))

    def test_literal_guard_rejects_oversize_before_read(self):
        guard = self.literal_guard_class.__new__(self.literal_guard_class)
        guard.max_literal_bytes = 100
        self.assert_error('MESSAGE_TOO_LARGE', lambda: guard.read(101))


if __name__ == '__main__':
    unittest.main()

"""Immutable previews and a conservative, durable SMTP submission ledger."""
import hashlib
import hmac
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from .config import BridgeError, secure_directory, valid_address


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def addresses(values, required=False):
    if values is None: values = []
    if not isinstance(values, list) or len(values) > 100 or (required and not values):
        raise BridgeError('RECIPIENTS_INVALID')
    result = []
    for value in values:
        address = valid_address(value)
        if address not in result: result.append(address)
    return result


def message_ids(value):
    if not isinstance(value, str) or len(value) > 8192 or '\r' in value or '\n' in value:
        raise BridgeError('REPLY_HEADERS_INVALID')
    parts = value.split()
    if any(not re.fullmatch(r'<[\x21-\x3b\x3d\x3f-\x7e]+@[\x21-\x3b\x3d\x3f-\x7e]+>', p) for p in parts):
        raise BridgeError('REPLY_HEADERS_INVALID')
    return parts


class Outbox:
    def __init__(self, config, transport):
        self.config, self.transport = config, transport
        secure_directory(config.data_dir)
        self.path = config.data_dir / 'outbox.sqlite3'
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY, account TEXT NOT NULL, fingerprint TEXT NOT NULL UNIQUE,
                confirmation TEXT NOT NULL, payload TEXT NOT NULL, mime BLOB NOT NULL,
                message_id TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        if os.name != 'nt': self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def prepare(self, to, subject, text, cc=None, bcc=None, reply_to_id=None):
        to, cc, bcc = addresses(to, True), addresses(cc), addresses(bcc)
        if len(to) + len(cc) + len(bcc) > 100: raise BridgeError('TOO_MANY_RECIPIENTS')
        if not isinstance(subject, str) or len(subject) > 500 or any(ord(c) < 32 for c in subject):
            raise BridgeError('SUBJECT_INVALID')
        if not isinstance(text, str) or len(text.encode('utf-8')) > 1048576 or '\0' in text:
            raise BridgeError('BODY_INVALID')
        parent, refs = None, []
        if reply_to_id is not None:
            if not isinstance(reply_to_id, str) or not 1 <= len(reply_to_id) <= 2048:
                raise BridgeError('MESSAGE_ID_INVALID')
            result = self.transport.fetch(reply_to_id)
            parents = message_ids(result.get('message_id', ''))
            if len(parents) != 1: raise BridgeError('REPLY_MESSAGE_ID_MISSING')
            parent = parents[0]
            refs = message_ids(result.get('references', ''))[-19:]
            if parent not in refs: refs.append(parent)
        payload = {'account': self.config.identity(), 'from': self.config.email,
                   'to': to, 'cc': cc, 'bcc': bcc, 'subject': subject, 'text': text,
                   'reply_to_id': reply_to_id, 'in_reply_to': parent, 'references': refs}
        semantic = payload | {'to': sorted(to), 'cc': sorted(cc), 'bcc': sorted(bcc)}
        fingerprint = hashlib.sha256(canonical(semantic).encode('utf-8')).hexdigest()
        message = EmailMessage(policy=policy.SMTP)
        message['From'] = self.config.email
        message['To'] = ', '.join(to)
        if cc: message['Cc'] = ', '.join(cc)
        message['Subject'] = subject
        message['Date'] = format_datetime(datetime.now(timezone.utc))
        message['Message-ID'] = make_msgid(domain=self.config.email.rsplit('@', 1)[1])
        if parent:
            message['In-Reply-To'] = parent
            message['References'] = ' '.join(refs)
        message.set_content(text)
        raw = message.as_bytes()
        if len(raw) > self.config.max_message_bytes: raise BridgeError('MESSAGE_TOO_LARGE')
        confirmation = hashlib.sha256(canonical(payload).encode('utf-8') + b'\0' + raw).hexdigest()
        draft_id, now = uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT id FROM drafts WHERE fingerprint=?', (fingerprint,)).fetchone()
            if previous:
                draft_id = previous['id']
            else:
                db.execute('INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (draft_id, self.config.identity(), fingerprint, confirmation, canonical(payload),
                            raw, str(message['Message-ID']), 'prepared', '{}', now, now))
        return self.preview(draft_id)

    def row(self, db, draft_id):
        if not isinstance(draft_id, str) or not re.fullmatch(r'[a-f0-9]{32}', draft_id):
            raise BridgeError('DRAFT_ID_INVALID')
        row = db.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
        if row is None: raise BridgeError('DRAFT_NOT_FOUND')
        if row['account'] != self.config.identity(): raise BridgeError('DRAFT_ACCOUNT_MISMATCH')
        return row

    def preview(self, draft_id):
        with self.connection() as db:
            row = self.row(db, draft_id)
        payload = json.loads(row['payload'])
        payload.pop('account')
        return {'draft_id': draft_id, 'state': row['state'], 'confirmation': row['confirmation'],
                'preview': payload, 'message_id': row['message_id'],
                'notice': 'Local preview only. Send only with user authorization for these exact recipients and contents.'}

    def status(self, draft_id):
        with self.connection() as db:
            row = self.row(db, draft_id)
        return self.receipt(row)

    @staticmethod
    def receipt(row):
        return {'draft_id': row['id'], 'state': row['state'], 'message_id': row['message_id'],
                'created_at': row['created_at'], 'updated_at': row['updated_at'],
                'submission': json.loads(row['receipt']), 'delivery_confirmed': False,
                'automatic_retry_allowed': False,
                'notice': 'SMTP acceptance is not delivery proof. Sending may be active or interrupted. Never retry ambiguous submissions.'}

    def send(self, draft_id, confirmation):
        if not self.config.allow_send: raise BridgeError('SEND_DISABLED')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self.row(db, draft_id)
            if not isinstance(confirmation, str) or not hmac.compare_digest(confirmation, row['confirmation']):
                raise BridgeError('CONFIRMATION_MISMATCH')
            if row['state'] not in ('prepared','not_submitted'): return self.receipt(row)
            db.execute("UPDATE drafts SET state='sending',receipt='{}',updated_at=? WHERE id=? AND state IN ('prepared','not_submitted')",
                       (datetime.now(timezone.utc).isoformat(), draft_id))
        # Durable reservation is committed before opening any network connection.
        payload = json.loads(row['payload'])
        recipients = list(dict.fromkeys(payload['to'] + payload['cc'] + payload['bcc']))
        try:
            result = self.transport.submit(bytes(row['mime']), recipients)
            if not isinstance(result, dict) or result.get('state') not in ('accepted', 'partial', 'refused'):
                raise BridgeError('SMTP_RESULT_INVALID')
            refused = result.get('refused', [])
            if not isinstance(refused, list) or any(x not in recipients for x in refused):
                raise BridgeError('SMTP_RESULT_INVALID')
            state = result['state']
            receipt = {'refused': refused}
        except BridgeError as e:
            # These enumerated transport codes occur before sendmail starts.
            # Every error after submission starts is SMTP_UNCERTAIN instead.
            preflight = {'SECRET_MISSING','SECRET_INVALID','SECRET_STORE_ERROR',
                         'SECURE_KEYRING_UNAVAILABLE','SMTP_CONNECTION','NETWORK_DISABLED',
                         'TLS_REQUIRED','AUTH_UNSUPPORTED','SEND_DISABLED'}
            state = 'not_submitted' if e.code in preflight else 'uncertain'
            receipt = {'error': e.code if state == 'not_submitted' else 'SMTP_OUTCOME_UNCERTAIN'}
        except Exception:
            state, receipt = 'uncertain', {'error': 'SMTP_OUTCOME_UNCERTAIN'}
        with self.connection() as db:
            db.execute("UPDATE drafts SET state=?,receipt=?,updated_at=? WHERE id=? AND state='sending'",
                       (state, canonical(receipt), datetime.now(timezone.utc).isoformat(), draft_id))
        return self.status(draft_id)

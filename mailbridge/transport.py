"""Verified-TLS IMAP/SMTP transport; email content is always untrusted.

Search deliberately scans at most 100 recent headers, with Unicode substring
matching performed locally. It is not a body/full-mailbox search. IMAP literals
are bounded *before* imaplib reads/allocates them; metadata lines are capped at
64 KiB. Very large server SEARCH responses fail safely rather than paginating.
The stdlib MIME parser still uses memory proportional to a bounded raw message;
decoded attachments are never executed, rendered, or written to disk.
"""
import base64
import hashlib
import imaplib
import json
import os
import re
import smtplib
import ssl
from contextlib import contextmanager
from datetime import date
from email import policy
from email.parser import BytesParser
from pathlib import PurePosixPath

from .config import BridgeError, valid_address


_HEADER_LIMIT = 65536
_SCAN_LIMIT = 100
_PART_LIMIT = 1000
_TEXT_TYPES = {'text/plain', 'text/csv', 'text/tab-separated-values', 'text/markdown', 'application/json', 'text/json'}
_TEXT_EXTENSIONS = {'.txt', '.csv', '.tsv', '.json', '.md', '.log'}


class _LiteralBounds:
    def __init__(self, *args, max_literal_bytes=10485760, **kwargs):
        self.max_literal_bytes = max_literal_bytes
        self.remaining_literal_bytes = max_literal_bytes
        super().__init__(*args, **kwargs)

    def read(self, size):
        if size < 0 or size > self.max_literal_bytes or size > getattr(self, 'remaining_literal_bytes', self.max_literal_bytes):
            raise BridgeError('MESSAGE_TOO_LARGE', 'The server response exceeds the configured limit.')
        self.remaining_literal_bytes = getattr(self, 'remaining_literal_bytes', self.max_literal_bytes) - size
        return super().read(size)

    def readline(self):
        line = self.file.readline(_HEADER_LIMIT + 1)
        if len(line) > _HEADER_LIMIT:
            raise BridgeError('IMAP_RESPONSE_TOO_LARGE', 'The IMAP metadata response is too large.')
        return line


class _BoundedIMAP4_SSL(_LiteralBounds, imaplib.IMAP4_SSL):
    pass


class _BoundedIMAP4(_LiteralBounds, imaplib.IMAP4):
    pass


def _guard_network():
    if any(os.environ.get(key) == '1' for key in ('CODEX_SANDBOX_NETWORK_DISABLED', 'MAILBRIDGE_SANDBOX')):
        raise BridgeError('NETWORK_DISABLED', 'Network access is disabled in this environment.')


def _ok(result):
    if not isinstance(result, tuple) or len(result) != 2 or result[0] != 'OK':
        raise BridgeError('IMAP_PROTOCOL', 'The IMAP request did not succeed.')
    return result[1]


def _mailbox_name(folder):
    # IMAP modified UTF-7, supported without an optional codec dependency.
    chunks, pending = [], []

    def flush():
        if pending:
            data = ''.join(pending).encode('utf-16-be')
            chunks.append('&' + base64.b64encode(data).decode().rstrip('=').replace('/', ',') + '-')
            pending.clear()

    for char in folder:
        if ' ' <= char <= '~':
            flush()
            chunks.append('&-' if char == '&' else char)
        else:
            pending.append(char)
    flush()
    return '"' + ''.join(chunks).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _pack(prefix, payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).decode().rstrip('=')
    return prefix + encoded


def _unpack(value, prefix, code):
    try:
        if not isinstance(value, str) or len(value) > 4096 or not value.startswith(prefix):
            raise ValueError
        encoded = value[len(prefix):]
        if not re.fullmatch(r'[A-Za-z0-9_-]+', encoded):
            raise ValueError
        return json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise BridgeError(code, 'The identifier is invalid for this account.') from None


def _header(message, name):
    return str(message.get(name, ''))[:8192]


def _parse(raw):
    try:
        return BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:
        raise BridgeError('INVALID_MESSAGE', 'The message could not be parsed.') from None


def _parts(message):
    for index, part in enumerate(message.walk()):
        if index >= _PART_LIMIT:
            raise BridgeError('MESSAGE_TOO_COMPLEX', 'The message contains too many MIME parts.')
        yield index, part


def _decode_text(part, payload):
    try:
        return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
    except (LookupError, UnicodeError):
        return payload.decode('utf-8', errors='replace')


class MailTransport:
    def __init__(self, config):
        self.config = config
        identity = [config.account_id, config.email, config.username, config.imap]
        self._namespace = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    @contextmanager
    def _imap(self):
        _guard_network()
        client = None
        try:
            secret = self.config.secret()
            endpoint = self.config.imap
            context = ssl.create_default_context()
            kwargs = dict(host=endpoint['host'], port=endpoint['port'], timeout=self.config.timeout,
                          max_literal_bytes=max(self.config.max_message_bytes + 1, _HEADER_LIMIT + 1))
            if endpoint['security'] == 'tls':
                client = _BoundedIMAP4_SSL(ssl_context=context, **kwargs)
            elif endpoint['security'] == 'starttls':
                client = _BoundedIMAP4(**kwargs)
                _ok(client.starttls(ssl_context=context))
            else:
                raise BridgeError('TLS_REQUIRED', 'Verified TLS is required.')
            if self.config.auth == 'oauth2':
                auth = f'user={self.config.username}\x01auth=Bearer {secret}\x01\x01'.encode()
                _ok(client.authenticate('XOAUTH2', lambda challenge: auth if not challenge else b''))
            elif self.config.auth == 'password':
                _ok(client.login(self.config.username, secret))
            else:
                raise BridgeError('AUTH_UNSUPPORTED', 'The authentication method is unsupported.')
            yield client
        except BridgeError:
            raise
        except Exception:
            raise BridgeError('IMAP_CONNECTION', 'The IMAP connection or authentication failed.') from None
        finally:
            if client is not None:
                try:
                    client.logout()
                except Exception:
                    try:
                        client.shutdown()
                    except Exception:
                        pass

    def _open_smtp(self):
        _guard_network()
        client = None
        try:
            secret = self.config.secret()
            endpoint = self.config.smtp
            context = ssl.create_default_context()
            kwargs = dict(host=endpoint['host'], port=endpoint['port'], timeout=self.config.timeout)
            if endpoint['security'] == 'tls':
                client = smtplib.SMTP_SSL(context=context, **kwargs)
                client.ehlo()
            elif endpoint['security'] == 'starttls':
                client = smtplib.SMTP(**kwargs)
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            else:
                raise BridgeError('TLS_REQUIRED', 'Verified TLS is required.')
            if self.config.auth == 'oauth2':
                auth = f'user={self.config.username}\x01auth=Bearer {secret}\x01\x01'
                client.auth('XOAUTH2', lambda challenge=None: auth if challenge is None else '')
            elif self.config.auth == 'password':
                client.login(self.config.username, secret)
            else:
                raise BridgeError('AUTH_UNSUPPORTED', 'The authentication method is unsupported.')
            return client
        except BridgeError:
            if client is not None:
                self._close_smtp(client)
            raise
        except Exception:
            if client is not None:
                self._close_smtp(client)
            raise BridgeError('SMTP_CONNECTION', 'The SMTP connection or authentication failed.') from None

    @staticmethod
    def _close_smtp(client):
        try:
            client.quit()
        except Exception:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    def status(self, verify_connection=False, verify_smtp=False):
        if type(verify_connection) is not bool or type(verify_smtp) is not bool:
            raise BridgeError('INVALID_ARGUMENT', 'Verification options must be booleans.')
        result = dict(account_id=self.config.account_id, read_only=not self.config.allow_send,
                      send_enabled=self.config.allow_send, imap_verified=False, smtp_verified=False)
        if verify_connection:
            with self._imap():
                result['imap_verified'] = True
        if verify_smtp:
            self._close_smtp(self._open_smtp())
            result['smtp_verified'] = True
        return result

    def _select(self, client, folder, expected=None):
        if folder not in self.config.folders:
            raise BridgeError('INVALID_ARGUMENT', 'The folder is not configured.')
        _ok(client.select(_mailbox_name(folder), readonly=True))
        response = client.response('UIDVALIDITY')
        values = response[1] if isinstance(response, tuple) and len(response) == 2 else []
        validity = values[0].decode('ascii') if values and isinstance(values[0], bytes) else ''
        if not re.fullmatch(r'[1-9][0-9]{0,19}', validity):
            raise BridgeError('IMAP_PROTOCOL', 'The server did not provide valid UIDVALIDITY.')
        if expected is not None and validity != expected:
            raise BridgeError('STALE_MESSAGE_ID', 'The mailbox changed. Search for the message again.')
        return validity

    def _message_id(self, folder, validity, uid):
        return _pack('mb1.', [self._namespace, folder, validity, uid])

    def _read_id(self, identifier):
        values = _unpack(identifier, 'mb1.', 'INVALID_MESSAGE_ID')
        if not isinstance(values, list) or len(values) != 4 or values[0] != self._namespace:
            raise BridgeError('INVALID_MESSAGE_ID', 'The identifier is invalid for this account.')
        _, folder, validity, uid = values
        if not isinstance(folder, str) or folder not in self.config.folders or any(
                not isinstance(v, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', v) for v in (validity, uid)):
            raise BridgeError('INVALID_MESSAGE_ID', 'The identifier is invalid for this account.')
        return folder, validity, uid

    def _size(self, client, uid):
        data = _ok(client.uid('FETCH', uid, '(RFC822.SIZE)'))
        for line in data or []:
            if not isinstance(line, bytes):
                continue
            match = re.search(rb'\bRFC822\.SIZE ([0-9]{1,20})\b', line)
            uid_match = re.search(rb'\bUID ([0-9]+)\b', line)
            if match and uid_match and uid_match[1].decode() == uid:
                return int(match[1])
        raise BridgeError('IMAP_PROTOCOL', 'The message size or UID is missing.')

    def _literal(self, client, uid, request, limit):
        client.max_literal_bytes = limit
        client.remaining_literal_bytes = limit
        data = _ok(client.uid('FETCH', uid, request))
        groups, metadata_parts, raw_parts = [], [], []
        for entry in data or []:
            is_literal = isinstance(entry, tuple) and len(entry) == 2
            metadata, raw = entry if is_literal else (entry, None)
            if not isinstance(metadata, bytes) or (is_literal and not isinstance(raw, bytes)):
                raise BridgeError('IMAP_PROTOCOL', 'The fetched response is invalid.')
            if re.match(rb'^\d+\s+\(', metadata) and metadata_parts:
                groups.append((b' '.join(metadata_parts), raw_parts))
                metadata_parts, raw_parts = [], []
            metadata_parts.append(metadata)
            if is_literal: raw_parts.append(raw)
            if metadata.rstrip().endswith(b')'):
                groups.append((b' '.join(metadata_parts), raw_parts))
                metadata_parts, raw_parts = [], []
        if metadata_parts: groups.append((b' '.join(metadata_parts), raw_parts))
        literals = []
        for metadata, raw_parts in groups:
            if not raw_parts: continue
            found = re.findall(rb'\bUID ([0-9]+)\b', metadata)
            if found != [uid.encode('ascii')]:
                raise BridgeError('IMAP_PROTOCOL', 'The fetched message UID is invalid.')
            literals.extend(raw_parts)
        if len(literals) != 1:
            raise BridgeError('IMAP_PROTOCOL', 'The server returned an unexpected message response.')
        if len(literals[0]) > limit:
            raise BridgeError('MESSAGE_TOO_LARGE', 'The server response exceeds the configured limit.')
        return literals[0]

    @staticmethod
    def _summary(identifier, message, size):
        return dict(id=identifier, subject=_header(message, 'Subject'), **{'from': _header(message, 'From')},
                    to=_header(message, 'To'), cc=_header(message, 'Cc'), date=_header(message, 'Date'),
                    message_id=_header(message, 'Message-ID'), references=_header(message, 'References'),
                    reply_to=_header(message, 'Reply-To'), size=size)

    def search(self, query='', folder='INBOX', after=None, before=None, limit=20):
        if not isinstance(query, str) or len(query) > 512 or any(ord(c) < 32 for c in query):
            raise BridgeError('INVALID_ARGUMENT', 'The search query is invalid.')
        if not isinstance(folder, str) or folder not in self.config.folders or type(limit) is not int or not 1 <= limit <= 100:
            raise BridgeError('INVALID_ARGUMENT', 'The folder or result limit is invalid.')
        criteria = ['ALL']
        dates = []
        for name, value in (('SINCE', after), ('BEFORE', before)):
            if value is None:
                continue
            try:
                if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                    raise ValueError
                parsed = date.fromisoformat(value)
            except (ValueError, TypeError):
                raise BridgeError('INVALID_ARGUMENT', 'Search dates must be valid YYYY-MM-DD values.') from None
            dates.append(parsed)
            month = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[parsed.month - 1]
            criteria.extend([name, f'{parsed.day:02d}-{month}-{parsed.year:04d}'])
        if after and before and dates[0] >= dates[1]:
            raise BridgeError('INVALID_ARGUMENT', 'The after date must precede the before date.')
        messages, matches = [], 0
        with self._imap() as client:
            validity = self._select(client, folder)
            data = _ok(client.uid('SEARCH', None, *criteria))
            if len(data or []) != 1 or not isinstance(data[0], bytes) or len(data[0]) > _HEADER_LIMIT:
                raise BridgeError('IMAP_RESPONSE_TOO_LARGE', 'The IMAP search response is too large or invalid.')
            uids = data[0].split()
            if any(not re.fullmatch(rb'[1-9][0-9]{0,19}', uid) for uid in uids):
                raise BridgeError('IMAP_PROTOCOL', 'The server returned invalid message UIDs.')
            uids = sorted(set(uids), key=int)
            recent = list(reversed(uids[-_SCAN_LIMIT:]))
            for raw_uid in recent:
                uid = raw_uid.decode()
                size = self._size(client, uid)
                header_limit = min(_HEADER_LIMIT, self.config.max_message_bytes)
                raw = self._literal(client, uid, f'(BODY.PEEK[HEADER]<0.{header_limit + 1}>)', header_limit + 1)
                if len(raw) > header_limit:
                    raise BridgeError('HEADER_TOO_LARGE', 'A message header exceeds the configured limit.')
                message = _parse(raw)
                summary = self._summary(self._message_id(folder, validity, uid), message, size)
                searchable = '\n'.join(summary[key] for key in ('subject', 'from', 'to', 'cc', 'date', 'message_id'))
                if query.casefold() in searchable.casefold():
                    matches += 1
                    if len(messages) < limit:
                        messages.append(summary)
        return dict(messages=messages, coverage=dict(scope='recent_headers', scanned=len(recent), available=len(uids),
                    complete=len(uids) <= _SCAN_LIMIT, result_limit=limit, matches_in_scan=matches,
                    results_truncated=matches > limit), untrusted=True)

    def _load(self, identifier):
        folder, validity, uid = self._read_id(identifier)
        with self._imap() as client:
            self._select(client, folder, validity)
            size = self._size(client, uid)
            if size > self.config.max_message_bytes:
                raise BridgeError('MESSAGE_TOO_LARGE', 'The message exceeds the configured size limit.')
            raw = self._literal(client, uid, f'(BODY.PEEK[]<0.{self.config.max_message_bytes + 1}>)', self.config.max_message_bytes + 1)
            if len(raw) > self.config.max_message_bytes:
                raise BridgeError('MESSAGE_TOO_LARGE', 'The message exceeds the configured size limit.')
            if len(raw) != size:
                raise BridgeError('IMAP_PROTOCOL', 'The message was truncated or its size changed.')
        return raw, _parse(raw)

    def fetch(self, id):
        raw, message = self._load(id)
        # Validate the whole MIME tree, then skip attachment subtrees when
        # collecting the parent's body (message/rfc822 is itself multipart).
        for _ in _parts(message):
            pass
        texts, has_html = [], False
        pending = [message]
        while pending:
            part = pending.pop()
            if part.get_filename() or part.get_content_disposition() == 'attachment':
                continue
            if part.is_multipart():
                pending.extend(reversed(part.get_payload()))
                continue
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                texts.append(_decode_text(part, part.get_payload(decode=True) or b''))
            elif content_type == 'text/html':
                has_html = True
        return self._summary(id, message, len(raw)) | dict(text='\n'.join(texts), has_html=has_html, untrusted=True)

    def _attachment(self, part):
        filename = (part.get_filename() or 'attachment')[:512]
        content_type = part.get_content_type()
        suffix = PurePosixPath(filename.replace('\\', '/')).suffix.lower()
        readable = not part.is_multipart() and content_type in _TEXT_TYPES and suffix in _TEXT_EXTENSIONS
        payload = part.get_payload(decode=True)
        # Nested email/container sizes have no single decoded byte stream.
        size = len(payload) if payload is not None else None
        return dict(filename=filename, content_type=content_type, size=size, readable=readable), payload or b''

    def list_attachments(self, id):
        raw, message = self._load(id)
        digest = hashlib.sha256(raw).hexdigest()
        attachments = []
        for index, part in _parts(message):
            if not (part.get_filename() or part.get_content_disposition() == 'attachment'):
                continue
            info, _ = self._attachment(part)
            info['id'] = _pack('mba1.', [id, index, digest])
            attachments.append(info)
        return dict(attachments=attachments, untrusted=True)

    def read_attachment(self, attachment_id):
        values = _unpack(attachment_id, 'mba1.', 'INVALID_ATTACHMENT_ID')
        if not isinstance(values, list) or len(values) != 3:
            raise BridgeError('INVALID_ATTACHMENT_ID', 'The attachment identifier is invalid.')
        identifier, selected, digest = values
        if type(selected) is not int or not 0 <= selected < _PART_LIMIT or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise BridgeError('INVALID_ATTACHMENT_ID', 'The attachment identifier is invalid.')
        raw, message = self._load(identifier)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise BridgeError('STALE_ATTACHMENT_ID', 'The message changed. List its attachments again.')
        for index, part in _parts(message):
            if index != selected:
                continue
            if not (part.get_filename() or part.get_content_disposition() == 'attachment'):
                break
            info, payload = self._attachment(part)
            if not info['readable']:
                raise BridgeError('UNSUPPORTED_ATTACHMENT', 'Only approved text, CSV, and JSON attachments can be read.')
            if len(payload) > self.config.max_attachment_bytes:
                raise BridgeError('ATTACHMENT_TOO_LARGE', 'The attachment exceeds the configured size limit.')
            return info | dict(id=attachment_id, text=_decode_text(part, payload), untrusted=True)
        raise BridgeError('INVALID_ATTACHMENT_ID', 'The attachment does not exist.')

    def submit(self, message_bytes, recipients):
        if not self.config.allow_send:
            raise BridgeError('SEND_DISABLED', 'Sending is disabled in the configuration.')
        if not isinstance(message_bytes, bytes) or not message_bytes or len(message_bytes) > self.config.max_message_bytes:
            raise BridgeError('INVALID_ARGUMENT', 'The outgoing message is empty or exceeds the configured limit.')
        if not isinstance(recipients, (list, tuple)) or not 1 <= len(recipients) <= 100:
            raise BridgeError('INVALID_ARGUMENT', 'A bounded list of recipients is required.')
        try:
            recipients = list(dict.fromkeys(valid_address(address) for address in recipients))
        except BridgeError:
            raise BridgeError('INVALID_ARGUMENT', 'An envelope recipient is invalid.') from None
        message = _parse(message_bytes)
        if message.get_all('Bcc') or message.get_all('Resent-Bcc'):
            raise BridgeError('INVALID_ARGUMENT', 'Bcc recipients must appear only in the SMTP envelope.')
        client = self._open_smtp()
        try:
            try:
                failures = client.sendmail(self.config.email, recipients, message_bytes)
            except smtplib.SMTPRecipientsRefused:
                return dict(state='refused', refused=recipients)
            except Exception:
                raise BridgeError('SMTP_UNCERTAIN', 'Submission began but its outcome could not be confirmed. Do not automatically retry.') from None
            refused = [address for address in recipients if address in failures]
            state = 'accepted' if not refused else 'refused' if len(refused) == len(recipients) else 'partial'
            return dict(state=state, refused=refused)
        finally:
            # SMTP acceptance is final even if QUIT/close subsequently fails.
            self._close_smtp(client)

"""Non-secret configuration and explicit secret providers."""
import json
import os
import re
import sys
from pathlib import Path


class BridgeError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def default_config_path():
    if sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    elif sys.platform == 'darwin':
        root = Path.home() / 'Library/Application Support'
    else:
        root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return root / 'mailbridge-mcp' / 'config.json'


def example_config():
    return {
        'schema_version': 1, 'account_id': 'personal',
        'email': 'you@example.com', 'username': 'you@example.com',
        'imap': {'host': 'imap.example.com', 'port': 993, 'security': 'tls'},
        'smtp': {'host': 'smtp.example.com', 'port': 465, 'security': 'tls'},
        'auth': 'password', 'secret_provider': 'environment',
        'secret_env': 'MAILBRIDGE_PASSWORD', 'allow_send': False,
        'folders': ['INBOX'], 'timeout': 20,
        'max_message_bytes': 10485760, 'max_attachment_bytes': 1048576,
    }


def valid_address(value):
    # Deliberately require bare, ASCII addr-spec. Display names are separate.
    if not isinstance(value, str) or len(value) > 254:
        raise BridgeError('INVALID_ADDRESS')
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise BridgeError('INVALID_ADDRESS')
    local, domain = value.rsplit('@', 1)
    if len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in value or '.' not in domain:
        raise BridgeError('INVALID_ADDRESS')
    return local + '@' + domain.lower()


def secure_directory(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        path.chmod(0o700)
    return path


def write_config(path, data):
    path = Path(path)
    secure_directory(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BridgeError('CONFIG_EXISTS') from None
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def native_keyring():
    try:
        import keyring
        backend = keyring.get_keyring()
        module = type(backend).__module__
        allowed = ('keyring.backends.Windows', 'keyring.backends.macOS',
                   'keyring.backends.SecretService', 'keyring.backends.kwallet')
        if not module.startswith(allowed):
            raise BridgeError('SECURE_KEYRING_UNAVAILABLE')
        return keyring
    except BridgeError:
        raise
    except Exception:
        raise BridgeError('SECURE_KEYRING_UNAVAILABLE') from None


class Config:
    @classmethod
    def load(cls, path):
        path = Path(path).expanduser().resolve()
        try:
            if path.stat().st_size > 65536:
                raise BridgeError('CONFIG_TOO_LARGE')
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except FileNotFoundError:
            raise BridgeError('CONFIG_MISSING') from None
        except (OSError, ValueError, RecursionError):
            raise BridgeError('CONFIG_INVALID') from None
        return cls(path, data)

    def __init__(self, path, data):
        defaults = example_config()
        if not isinstance(data, dict) or set(data) - set(defaults) - {'data_dir'}:
            raise BridgeError('CONFIG_UNKNOWN_FIELD')
        value = defaults | data
        if value['schema_version'] != 1 or isinstance(value['schema_version'], bool):
            raise BridgeError('CONFIG_VERSION_UNSUPPORTED')
        self.path = Path(path).resolve()
        for name, val in value.items():
            setattr(self, name, val)
        if not isinstance(self.account_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.account_id):
            raise BridgeError('ACCOUNT_ID_INVALID')
        self.email = valid_address(self.email)
        if not isinstance(self.username, str) or not self.username or len(self.username) > 320 or any(ord(c) < 32 for c in self.username):
            raise BridgeError('USERNAME_INVALID')
        for endpoint in (self.imap, self.smtp):
            if not isinstance(endpoint, dict) or set(endpoint) != {'host', 'port', 'security'}:
                raise BridgeError('ENDPOINT_INVALID')
            host = endpoint['host']
            if not isinstance(host, str) or len(host) > 253 or not re.fullmatch(r'[A-Za-z0-9.-]+', host):
                raise BridgeError('HOST_INVALID')
            if type(endpoint['port']) is not int or not 1 <= endpoint['port'] <= 65535:
                raise BridgeError('PORT_INVALID')
            if endpoint['security'] not in ('tls', 'starttls'):
                raise BridgeError('TLS_REQUIRED')
        if self.auth not in ('password', 'oauth2'):
            raise BridgeError('AUTH_UNSUPPORTED')
        if self.secret_provider not in ('environment', 'keyring'):
            raise BridgeError('SECRET_PROVIDER_UNSUPPORTED')
        if not isinstance(self.secret_env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.secret_env):
            raise BridgeError('SECRET_ENV_INVALID')
        if type(self.allow_send) is not bool:
            raise BridgeError('ALLOW_SEND_INVALID')
        if not isinstance(self.folders, list) or not 1 <= len(self.folders) <= 20 or any(
            not isinstance(f, str) or not f or len(f) > 200 or any(ord(c) < 32 for c in f)
            for f in self.folders):
            raise BridgeError('FOLDERS_INVALID')
        for name, low, high in [('timeout', 1, 120), ('max_message_bytes', 1024, 26214400),
                                ('max_attachment_bytes', 1, 5242880)]:
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise BridgeError('LIMIT_INVALID')
        if self.max_attachment_bytes > self.max_message_bytes:
            raise BridgeError('LIMIT_INVALID')
        raw_dir = value.get('data_dir')
        if raw_dir is not None and (not isinstance(raw_dir, str) or not Path(raw_dir).is_absolute()):
            raise BridgeError('DATA_DIR_MUST_BE_ABSOLUTE')
        self.data_dir = Path(raw_dir) if raw_dir else self.path.parent / 'data' / self.account_id

    def secret(self):
        if self.secret_provider == 'environment':
            value = os.environ.get(self.secret_env)
        else:
            try:
                value = native_keyring().get_password('mailbridge-mcp', self.account_id)
            except BridgeError:
                raise
            except Exception:
                raise BridgeError('SECRET_STORE_ERROR') from None
        if not value:
            raise BridgeError('SECRET_MISSING')
        if len(value) > 16384 or any(c in value for c in ('\r', '\n', '\0')):
            raise BridgeError('SECRET_INVALID')
        return value

    def identity(self):
        import hashlib
        value = [self.account_id, self.email, self.username, self.imap, self.smtp]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

"""Render per-user services and supervise a trusted external tunnel executable.

Rendering is pure: no services, keys, tunnels or directories are created. Normal
stdio MCP servers are launched by their client and do not need this supervisor.
Child output is discarded, including authentication errors. Set documented
provider exit codes explicitly; otherwise failures share a finite retry budget.
Credentials require human rotation when revoked or expired.
"""
import json
import ntpath
import os
from pathlib import Path
import plistlib
import re
import shlex
import signal
import subprocess
import threading
import xml.etree.ElementTree as ET

from .config import BridgeError, native_keyring


_TASK_NAME = 'MailBridge MCP Tunnel'
_LABEL = 'org.mailbridge.mcp.tunnel'
_SHELLS = {'cmd', 'powershell', 'pwsh', 'sh', 'bash', 'dash', 'zsh', 'fish',
           'ksh', 'csh', 'tcsh', 'wscript', 'cscript', 'mshta'}
_NOTES = [
    'Render only: save content to output_path when provided, otherwise use filename in repo_path; then review and run the installation commands yourself.',
    'This user service supervises a trusted, separately installed official tunnel executable. Client-managed stdio MCP needs no background service.',
    'Use the official client in foreground mode. Daemonizing clients and children that deliberately detach from a process group are not supported.',
    'No uptime guarantee while asleep, offline or signed out. A locked or unavailable OS keyring fails closed; login services may not inherit terminal environment variables.',
    'Child stdout and stderr are discarded. Inspect official client diagnostics manually in a trusted terminal when troubleshooting.',
    'Nonzero exits retry after 30, 60, 120, 240, then 300 seconds, subject to restart_limit (default 5; 0 disables retries; maximum 20). A successful exit stops.',
    'authentication_exit_codes may contain only exit codes documented by your official tunnel client. No authentication-error text is parsed. Expired credentials need human rotation and an explicit service restart.',
    'The OS service does not restart the supervisor after it exits; this prevents repeated expired-credential restart loops.',
]


def _text(value):
    return isinstance(value, str) and bool(value) and not any(ord(c) < 32 for c in value)


def validate_supervisor_config(path: str) -> dict:
    """Validate a non-secret JSON command configuration without starting it.

    argv is an argument list with an absolute executable, never a shell command.
    env_secrets maps environment variable names to OS keyring account names in
    service ``mailbridge-mcp``. Existing nonempty environment values take priority.
    Only the host's native path syntax is accepted for executable and cwd.
    """
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise BridgeError('SUPERVISOR_CONFIG_TOO_LARGE')
        data = json.loads(raw.decode('utf-8-sig'))
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise BridgeError('SUPERVISOR_CONFIG_INVALID') from None
    allowed = {'argv', 'env_secrets', 'cwd', 'restart_limit', 'authentication_exit_codes'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise BridgeError('SUPERVISOR_CONFIG_INVALID')
    argv = data.get('argv')
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 256
            or any(not _text(arg) for arg in argv)
            or sum(len(arg) for arg in argv) > 32768
            or not Path(argv[0]).is_absolute()):
        raise BridgeError('SUPERVISOR_ARGV_INVALID')
    executable = Path(argv[0])
    if executable.stem.lower() in _SHELLS or executable.suffix.lower() in ('.bat', '.cmd', '.ps1'):
        raise BridgeError('SUPERVISOR_SHELL_FORBIDDEN')
    cwd = data.get('cwd')
    if cwd is not None and (not _text(cwd) or not Path(cwd).is_absolute()):
        raise BridgeError('SUPERVISOR_CWD_INVALID')
    secrets = data.get('env_secrets', {})
    if not isinstance(secrets, dict) or len(secrets) > 32:
        raise BridgeError('SUPERVISOR_SECRETS_INVALID')
    for variable, account in secrets.items():
        if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', variable)
                or not _text(account) or len(account) > 200):
            raise BridgeError('SUPERVISOR_SECRETS_INVALID')
    restarts = data.get('restart_limit', 5)
    if type(restarts) is not int or not 0 <= restarts <= 20:
        raise BridgeError('SUPERVISOR_RESTART_LIMIT_INVALID')
    auth_codes = data.get('authentication_exit_codes', [])
    if (not isinstance(auth_codes, list) or len(auth_codes) > 32
            or any(type(code) is not int or not 1 <= code <= 255 for code in auth_codes)):
        raise BridgeError('SUPERVISOR_AUTH_CODES_INVALID')
    return {'argv': argv, 'env_secrets': secrets, 'cwd': cwd,
            'restart_limit': restarts, 'authentication_exit_codes': auth_codes}


def _child_environment(config):
    environment = os.environ.copy()
    for variable, account in config['env_secrets'].items():
        value = environment.get(variable)
        if not value:
            try:
                value = native_keyring().get_password('mailbridge-mcp', account)
            except Exception:
                raise BridgeError('SUPERVISOR_SECRET_UNAVAILABLE') from None
        if (not isinstance(value, str) or not value or len(value) > 16384
                or any(c in value for c in ('\x00', '\r', '\n'))):
            raise BridgeError('SUPERVISOR_SECRET_UNAVAILABLE')
        environment[variable] = value
    return environment


class _WindowsJob:
    """Kill descendants on job close, including an exited leader's descendants."""
    def __init__(self, child):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [('ProcessTime', ctypes.c_longlong), ('JobTime', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ('ReadOperations', 'WriteOperations', 'OtherOperations',
                         'ReadBytes', 'WriteBytes', 'OtherBytes')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('Job creation failed')
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                or not self.kernel.AssignProcessToJobObject(self.handle, int(child._handle))):
            self.close()
            raise OSError('Job assignment failed')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _attach_job(child):
    return _WindowsJob(child) if os.name == 'nt' else None


def _cleanup_child(child, job):
    if os.name == 'nt':
        if job is not None:
            job.close()
        elif child.poll() is None:
            child.terminate()
    else:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)
    finally:
        if os.name != 'nt':
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def supervise(path: str) -> int:
    """Run a trusted external executable; return 0 on clean exit/stop, else 2.

    Child output and exception details are never forwarded. Invalid config,
    unavailable credentials, sandbox guards, known authentication exit codes,
    and exhausted retries all stop. Invoke from the main thread for signals.
    """
    if any(os.environ.get(flag) == '1' for flag in
           ('CODEX_SANDBOX_NETWORK_DISABLED', 'MAILBRIDGE_SANDBOX')):
        return 2
    previous = {}
    stop = threading.Event()
    try:
        config = validate_supervisor_config(path)
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        if hasattr(signal, 'SIGBREAK'):
            previous[signal.SIGBREAK] = signal.signal(signal.SIGBREAK, lambda *_: stop.set())
        for attempt in range(config['restart_limit'] + 1):
            if stop.is_set():
                return 0
            options = {'shell': False, 'stdin': subprocess.DEVNULL,
                       'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
                       'cwd': config['cwd'], 'env': _child_environment(config), 'close_fds': True}
            if os.name == 'nt':
                options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                options['start_new_session'] = True
            child = subprocess.Popen(config['argv'], **options)
            job = None
            try:
                job = _attach_job(child)
                while not stop.is_set():
                    try:
                        exit_code = child.wait(timeout=0.25)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                else:
                    return 0
            finally:
                _cleanup_child(child, job)
            if exit_code == 0:
                return 0
            if exit_code in config['authentication_exit_codes'] or attempt == config['restart_limit']:
                return 2
            if stop.wait(min(30 * 2 ** attempt, 300)):
                return 0
        return 2
    except (BridgeError, OSError, ValueError, subprocess.SubprocessError):
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _absolute_path(value, windows):
    valid = ntpath.isabs(value) and bool(ntpath.splitdrive(value)[0]) if windows and _text(value) else False
    if not windows:
        valid = _text(value) and value.startswith('/')
    if not valid:
        raise BridgeError('SERVICE_ABSOLUTE_PATH_REQUIRED')
    return value


def _ps_quote(value):
    return "'" + value.replace("'", "''") + "'"


def _unit_quote(value, executable=False):
    value = value.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
    if executable:
        value = value.replace('$', '$$')
    return '"' + value + '"'


def render_service(platform: str, python_exe: str, config_path: str,
                   supervisor_config_path: str, repo_path: str,
                   output_path: str | None = None) -> dict:
    """Return service text plus explicit user-level commands; execute nothing."""
    aliases = {'win32': 'windows', 'windows': 'windows', 'darwin': 'macos',
               'macos': 'macos', 'linux': 'linux'}
    if platform not in aliases:
        raise BridgeError('SERVICE_PLATFORM_UNSUPPORTED')
    platform = aliases[platform]
    windows = platform == 'windows'
    python_exe, config_path, supervisor_config_path, repo_path = [
        _absolute_path(value, windows) for value in
        (python_exe, config_path, supervisor_config_path, repo_path)]
    if output_path is not None:
        output_path = _absolute_path(output_path, windows)
    notes = list(_NOTES)
    if windows and ntpath.basename(python_exe).lower() == 'python.exe':
        pythonw = ntpath.join(ntpath.dirname(python_exe), 'pythonw.exe')
        if os.path.isfile(pythonw):
            python_exe = pythonw
        else:
            notes.append('pythonw.exe was not found beside python.exe; python.exe is used. Install pythonw or explicitly select it to suppress a console window at logon.')
    argv = [python_exe, '-m', 'mailbridge', '--config', config_path,
            'supervise', '--supervisor-config', supervisor_config_path]
    if windows:
        filename = 'mailbridge-mcp-task.xml'
        ns = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
        ET.register_namespace('', ns)
        def add(parent, tag, text=None, **attributes):
            node = ET.SubElement(parent, '{' + ns + '}' + tag, attributes)
            node.text = text
            return node
        root = ET.Element('{' + ns + '}Task', {'version': '1.4'})
        trigger = add(add(root, 'Triggers'), 'LogonTrigger')
        add(trigger, 'Enabled', 'true')
        add(trigger, 'UserId', '__CURRENT_USER_SID__')
        principal = add(add(root, 'Principals'), 'Principal', id='CurrentUser')
        add(principal, 'UserId', '__CURRENT_USER_SID__')
        add(principal, 'LogonType', 'InteractiveToken')
        add(principal, 'RunLevel', 'LeastPrivilege')
        settings = add(root, 'Settings')
        for name, value in [('MultipleInstancesPolicy', 'IgnoreNew'), ('DisallowStartIfOnBatteries', 'false'),
                            ('StopIfGoingOnBatteries', 'false'), ('StartWhenAvailable', 'true'),
                            ('Enabled', 'true'), ('Hidden', 'true'), ('ExecutionTimeLimit', 'PT0S')]:
            add(settings, name, value)
        action = add(add(root, 'Actions', Context='CurrentUser'), 'Exec')
        add(action, 'Command', python_exe)
        add(action, 'Arguments', subprocess.list2cmdline(argv[1:]))
        add(action, 'WorkingDirectory', repo_path)
        content = ET.tostring(root, encoding='unicode', xml_declaration=True)
        source = _ps_quote(output_path if output_path is not None else ntpath.join(repo_path, filename))
        install = [f'$taskXml = Get-Content -LiteralPath {source} -Raw -Encoding UTF8',
                   "$taskXml = $taskXml.Replace('__CURRENT_USER_SID__', [Security.Principal.WindowsIdentity]::GetCurrent().User.Value)",
                   f'Register-ScheduledTask -TaskName {_ps_quote(_TASK_NAME)} -Xml $taskXml',
                   f'Start-ScheduledTask -TaskName {_ps_quote(_TASK_NAME)}']
        uninstall = [f'Stop-ScheduledTask -TaskName {_ps_quote(_TASK_NAME)}',
                     f'Unregister-ScheduledTask -TaskName {_ps_quote(_TASK_NAME)} -Confirm:$false']
        notes.append('Run Windows commands in ordinary PowerShell as the intended user. The install commands resolve the current user SID. No administrator rights or stored login password are requested.')
    elif platform == 'macos':
        filename = _LABEL + '.plist'
        content = plistlib.dumps({'Label': _LABEL, 'ProgramArguments': argv,
                                  'WorkingDirectory': repo_path, 'RunAtLoad': True,
                                  'KeepAlive': False, 'ProcessType': 'Background',
                                  'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null',
                                  'ExitTimeOut': 10}, sort_keys=False).decode('utf-8')
        source = shlex.quote(output_path if output_path is not None else repo_path.rstrip('/') + '/' + filename)
        target = '"$HOME/Library/LaunchAgents/' + filename + '"'
        install = ['mkdir -p "$HOME/Library/LaunchAgents"', f'install -m 600 {source} {target}',
                   f'launchctl bootstrap "gui/$(id -u)" {target}']
        uninstall = [f'launchctl bootout "gui/$(id -u)/{_LABEL}"', f'rm -f {target}']
        notes.append('macOS LaunchAgents run in the signed-in user GUI session. Use launchctl kickstart after fixing stopped credentials.')
    else:
        filename = 'mailbridge-mcp-tunnel.service'
        content = ('[Unit]\nDescription=MailBridge MCP tunnel supervisor\n\n'
                   '[Service]\nType=simple\nExecStart=' + ' '.join(_unit_quote(arg, True) for arg in argv)
                   + '\nWorkingDirectory=' + _unit_quote(repo_path)
                   + '\nRestart=no\nKillMode=control-group\nTimeoutStopSec=10\n'
                   'StandardOutput=null\nStandardError=null\n\n[Install]\nWantedBy=default.target\n')
        source = shlex.quote(output_path if output_path is not None else repo_path.rstrip('/') + '/' + filename)
        target = '"$HOME/.config/systemd/user/' + filename + '"'
        install = ['mkdir -p "$HOME/.config/systemd/user"', f'install -m 600 {source} {target}',
                   'systemctl --user daemon-reload', f'systemctl --user enable --now {filename}']
        uninstall = [f'systemctl --user disable --now {filename}', f'rm -f {target}',
                     'systemctl --user daemon-reload']
        notes.append('Linux requires a user systemd session. Logout persistence/lingering is not enabled by these commands.')
    return {'filename': filename, 'content': content, 'install_commands': install,
            'uninstall_commands': uninstall, 'notes': notes}

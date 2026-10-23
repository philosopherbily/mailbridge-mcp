"""Offline service-render and process-supervision contract tests."""
import io
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

from mailbridge import background
from mailbridge.config import BridgeError


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'supervisor.json'
        self.config = {'argv': [sys.executable, '-c', 'pass']}
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.config), encoding='utf-8')

    def test_validation_preserves_argument_boundaries(self):
        self.config['argv'] += ['argument with spaces', 'Unicode 中文', '$literal;value']
        self.write()
        result = background.validate_supervisor_config(str(self.path))
        self.assertEqual(result['argv'], self.config['argv'])
        self.assertEqual(result['restart_limit'], 5)
        self.assertEqual(result['env_secrets'], {})
        self.assertEqual(result['authentication_exit_codes'], [])

    def test_validation_rejects_shell_strings_and_relative_executables(self):
        for value in ('tunnel start', ['tunnel', 'start'], [], [sys.executable, None]):
            with self.subTest(value=value):
                self.config = {'argv': value}
                self.write()
                with self.assertRaises(BridgeError):
                    background.validate_supervisor_config(str(self.path))

    def test_validation_rejects_command_shells_and_script_wrappers(self):
        for name in ('cmd.exe', 'powershell.exe', 'pwsh', 'bash', 'sh', 'tunnel.cmd', 'tunnel.bat'):
            with self.subTest(name=name):
                self.config = {'argv': [str(Path(self.temp.name) / name), '-c', 'anything']}
                self.write()
                with self.assertRaises(BridgeError):
                    background.validate_supervisor_config(str(self.path))

    def test_validation_rejects_unknown_fields_and_invalid_limits(self):
        invalid = [{'shell': True}, {'restart_limit': True}, {'restart_limit': -1},
                   {'restart_limit': 21}, {'cwd': 'relative'}, {'env_secrets': {'BAD=NAME': 'account'}},
                   {'env_secrets': {'TOKEN': ''}}, {'authentication_exit_codes': [0]},
                   {'authentication_exit_codes': [True]}, {'argv': [sys.executable, '\x00']}]
        for extra in invalid:
            with self.subTest(extra=extra):
                self.config = {'argv': [sys.executable]} | extra
                self.write()
                with self.assertRaises(BridgeError):
                    background.validate_supervisor_config(str(self.path))

    def test_invalid_json_does_not_echo_content(self):
        self.path.write_text('{"secret": "DO_NOT_ECHO"', encoding='utf-8')
        with self.assertRaises(BridgeError) as caught:
            background.validate_supervisor_config(str(self.path))
        self.assertNotIn('DO_NOT_ECHO', str(caught.exception))

    def test_oversized_config_rejected(self):
        self.path.write_text(' ' * 65537, encoding='utf-8')
        with self.assertRaises(BridgeError):
            background.validate_supervisor_config(str(self.path))

    def test_sandbox_guards_prevent_child_creation(self):
        for flag in ('MAILBRIDGE_SANDBOX', 'CODEX_SANDBOX_NETWORK_DISABLED'):
            with self.subTest(flag=flag), patch.dict(os.environ, {flag: '1'}, clear=True), \
                    patch.object(background.subprocess, 'Popen') as popen:
                self.assertEqual(background.supervise(str(self.path)), 2)
                popen.assert_not_called()

    def test_clean_child_exit_and_output_are_discarded(self):
        self.config['argv'] = [sys.executable, '-c',
                               'import sys; print("PRIVATE_OUTPUT"); sys.stderr.write("PRIVATE_ERROR")']
        self.write()
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'MAILBRIDGE_SANDBOX': '0', 'CODEX_SANDBOX_NETWORK_DISABLED': '0'}), \
                patch('sys.stdout', output), patch('sys.stderr', errors):
            result = background.supervise(str(self.path))
        self.assertEqual(result, 0)
        self.assertNotIn('PRIVATE', output.getvalue() + errors.getvalue())

    def test_environment_secret_precedes_keyring_and_is_not_mutated(self):
        self.config['env_secrets'] = {'MAILBRIDGE_TEST_TOKEN': 'tunnel-test'}
        self.config['argv'] = [sys.executable, '-c',
                              'import os,sys; sys.exit(0 if os.environ.get("MAILBRIDGE_TEST_TOKEN") == "example-value" else 9)']
        self.write()
        with patch.dict(os.environ, {'MAILBRIDGE_SANDBOX': '0', 'CODEX_SANDBOX_NETWORK_DISABLED': '0',
                                     'MAILBRIDGE_TEST_TOKEN': 'example-value'}), \
                patch.object(background, 'native_keyring') as keyring:
            self.assertEqual(background.supervise(str(self.path)), 0)
            keyring.assert_not_called()
            self.assertEqual(os.environ['MAILBRIDGE_TEST_TOKEN'], 'example-value')

    def test_descendant_is_cleaned_after_parent_exit(self):
        marker = Path(self.temp.name) / 'unexpected-descendant-output'
        descendant = ('import pathlib,time; time.sleep(0.8); '
                      f'pathlib.Path({str(marker)!r}).write_text("still-running")')
        parent = ('import subprocess,sys,time; '
                  f'subprocess.Popen([sys.executable,"-c",{descendant!r}]); '
                  'time.sleep(0.2)')
        self.config['argv'] = [sys.executable, '-c', parent]
        self.write()
        with patch.dict(os.environ, {'MAILBRIDGE_SANDBOX': '0', 'CODEX_SANDBOX_NETWORK_DISABLED': '0'}):
            self.assertEqual(background.supervise(str(self.path)), 0)
        time.sleep(1)
        self.assertFalse(marker.exists(), 'A descendant survived supervisor cleanup')

    def test_missing_credential_is_fatal_without_child_creation(self):
        self.config['env_secrets'] = {'MAILBRIDGE_TEST_TOKEN': 'tunnel-test'}
        self.write()
        keyring = Mock()
        keyring.get_password.return_value = None
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(background, 'native_keyring', return_value=keyring), \
                patch.object(background.subprocess, 'Popen') as popen:
            self.assertEqual(background.supervise(str(self.path)), 2)
            popen.assert_not_called()
            keyring.get_password.assert_called_once_with('mailbridge-mcp', 'tunnel-test')

    def test_keyring_error_is_fatal_without_exposing_backend_error(self):
        self.config['env_secrets'] = {'MAILBRIDGE_TEST_TOKEN': 'tunnel-test'}
        self.write()
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(background, 'native_keyring', side_effect=RuntimeError('PRIVATE_BACKEND')), \
                patch('sys.stderr', output), patch.object(background.subprocess, 'Popen') as popen:
            self.assertEqual(background.supervise(str(self.path)), 2)
            popen.assert_not_called()
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_restarts_use_bounded_backoff_and_no_shell(self):
        child = Mock(pid=12345)
        child.wait.return_value = 1
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.return_value = False
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(background.threading, 'Event', return_value=stop), \
                patch.object(background.subprocess, 'Popen', return_value=child) as popen, \
                patch.object(background, '_attach_job', return_value=None), \
                patch.object(background, '_cleanup_child'):
            self.assertEqual(background.supervise(str(self.path)), 2)
        self.assertEqual(popen.call_count, 6)
        self.assertEqual([call.args[0] for call in stop.wait.call_args_list], [30, 60, 120, 240, 300])
        for call in popen.call_args_list:
            self.assertFalse(call.kwargs['shell'])
            self.assertEqual(call.kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(call.kwargs['stderr'], subprocess.DEVNULL)

    def test_declared_auth_exit_stops_without_retry(self):
        self.config['authentication_exit_codes'] = [77]
        self.write()
        child = Mock(pid=12345)
        child.wait.return_value = 77
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(background.subprocess, 'Popen', return_value=child) as popen, \
                patch.object(background, '_attach_job', return_value=None), \
                patch.object(background, '_cleanup_child'), \
                patch.object(background.threading, 'Event') as event:
            event.return_value.is_set.return_value = False
            self.assertEqual(background.supervise(str(self.path)), 2)
            self.assertEqual(popen.call_count, 1)
            event.return_value.wait.assert_not_called()

    def test_stop_signal_cleans_child_and_restores_handlers(self):
        initial = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        child = Mock(pid=12345)
        def wait(timeout):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            raise subprocess.TimeoutExpired('test-child', timeout)
        child.wait.side_effect = wait
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(background.subprocess, 'Popen', return_value=child), \
                patch.object(background, '_attach_job', return_value=None), \
                patch.object(background, '_cleanup_child') as cleanup:
            self.assertEqual(background.supervise(str(self.path)), 0)
        cleanup.assert_called_once_with(child, None)
        for sig, handler in initial.items():
            self.assertEqual(signal.getsignal(sig), handler)


class ServiceRenderTests(unittest.TestCase):
    def render(self, platform):
        if platform == 'windows':
            paths = (r'C:\Example App\venv\python.exe', r'C:\Example App\config.json',
                     r'C:\Example App\supervisor.json', r'C:\Example App\repo')
        else:
            paths = ('/opt/Example App/venv/bin/python', '/opt/Example App/config.json',
                     '/opt/Example App/supervisor.json', '/opt/Example App/repo')
        return background.render_service(platform, *paths)

    def test_windows_task_has_interactive_least_privilege_single_instance(self):
        result = self.render('windows')
        root = ET.fromstring(result['content'])
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertEqual(root.find('.//t:LogonType', ns).text, 'InteractiveToken')
        self.assertEqual(root.find('.//t:RunLevel', ns).text, 'LeastPrivilege')
        self.assertEqual(root.find('.//t:MultipleInstancesPolicy', ns).text, 'IgnoreNew')
        self.assertEqual(root.find('.//t:ExecutionTimeLimit', ns).text, 'PT0S')
        self.assertIsNone(root.find('.//t:RestartOnFailure', ns))
        self.assertIn('--supervisor-config', root.find('.//t:Arguments', ns).text)
        self.assertIn('GetCurrent', '\n'.join(result['install_commands']))

    def test_windows_prefers_existing_pythonw(self):
        with patch.object(background.os.path, 'isfile', return_value=True):
            result = self.render('windows')
        root = ET.fromstring(result['content'])
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertTrue(root.find('.//t:Command', ns).text.endswith('pythonw.exe'))

    def test_launchd_has_exact_argv_without_restart(self):
        result = self.render('macos')
        value = plistlib.loads(result['content'].encode())
        self.assertEqual(value['ProgramArguments'][0], '/opt/Example App/venv/bin/python')
        self.assertIn('/opt/Example App/supervisor.json', value['ProgramArguments'])
        self.assertTrue(value['RunAtLoad'])
        self.assertFalse(value['KeepAlive'])
        self.assertEqual(value['StandardErrorPath'], '/dev/null')

    def test_systemd_is_user_scoped_and_does_not_restart_auth_failures(self):
        result = self.render('linux')
        self.assertIn('Restart=no', result['content'])
        self.assertIn('KillMode=control-group', result['content'])
        self.assertIn('"/opt/Example App/venv/bin/python"', result['content'])
        self.assertIn('StandardError=null', result['content'])
        self.assertIn('systemctl --user', '\n'.join(result['install_commands']))
        self.assertNotIn('sudo', '\n'.join(result['install_commands']))

    def test_systemd_escapes_specifiers_and_environment_expansion(self):
        result = background.render_service('linux', '/opt/100%/$python', '/opt/config.json',
                                           '/opt/supervisor.json', '/opt/repo')
        self.assertIn('/opt/100%%/$$python', result['content'])

    def test_render_requires_explicit_paths_and_known_platform(self):
        for platform, python in [('unknown', '/usr/bin/python'), ('linux', 'python'), ('windows', 'python.exe')]:
            with self.subTest(platform=platform), self.assertRaises(BridgeError):
                background.render_service(platform, python, '/config', '/supervisor', '/repo')

    def test_render_does_not_install_or_create_files(self):
        with patch.object(background.subprocess, 'Popen') as popen, \
                patch.object(background.subprocess, 'run') as run:
            for platform in ('windows', 'linux', 'macos'):
                result = self.render(platform)
                self.assertEqual(set(result), {'filename', 'content', 'install_commands', 'uninstall_commands', 'notes'})
                self.assertTrue(result['notes'])
        popen.assert_not_called()
        run.assert_not_called()

    def test_explicit_output_path_is_install_source_not_working_directory(self):
        windows = background.render_service(
            'windows', r'C:\Example App\python.exe', r'C:\Example App\config.json',
            r'C:\Example App\supervisor.json', r'C:\Example App\repo',
            output_path=r'C:\Export Folder\custom task.xml')
        self.assertIn(r"'C:\Export Folder\custom task.xml'", windows['install_commands'][0])
        root = ET.fromstring(windows['content'])
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertEqual(root.find('.//t:WorkingDirectory', ns).text, r'C:\Example App\repo')
        for platform in ('linux', 'macos'):
            with self.subTest(platform=platform):
                result = background.render_service(
                    platform, '/opt/Example App/python', '/opt/config.json',
                    '/opt/supervisor.json', '/opt/Example App/repo',
                    output_path='/tmp/Export Folder/custom service')
                self.assertIn("'/tmp/Export Folder/custom service'", result['install_commands'][1])
                if platform == 'macos':
                    self.assertEqual(plistlib.loads(result['content'].encode())['WorkingDirectory'], '/opt/Example App/repo')
                else:
                    self.assertIn('WorkingDirectory="/opt/Example App/repo"', result['content'])

    def test_explicit_output_path_must_be_absolute(self):
        with self.assertRaises(BridgeError):
            background.render_service('linux', '/python', '/config', '/supervisor', '/repo',
                                      output_path='relative.service')


if __name__ == '__main__':
    unittest.main()

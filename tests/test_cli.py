import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest.mock import patch
try:
    from mailbridge.cli import main
except ImportError:
    main = None


class CliTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(main, 'CLI must exist')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'private settings'/'config.json'
    def run_cli(self,*args):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream): code=main(['--config',str(self.path),*args])
        return code,stream.getvalue()
    def test_init_and_no_overwrite(self):
        code,output=self.run_cli('init');self.assertEqual(code,0)
        self.assertTrue(self.path.exists());before=self.path.read_bytes()
        self.assertEqual(self.run_cli('init')[0],2)
        self.assertEqual(before,self.path.read_bytes())
    def test_missing_config_returns_machine_error(self):
        code,output=self.run_cli('doctor')
        self.assertEqual(code,2);self.assertEqual(json.loads(output)['error'],'CONFIG_MISSING')
    def test_client_configs_no_secrets_and_absolute_paths(self):
        self.run_cli('init')
        for client in ['generic','claude','cursor','workbuddy']:
            with self.subTest(client=client):
                code,output=self.run_cli('client-config','--client',client)
                config=json.loads(output)['mcpServers']['mailbridge']
                self.assertEqual(code,0)
                self.assertTrue(Path(config['command']).is_absolute())
                config_path=Path(config['args'][config['args'].index('--config')+1])
                self.assertTrue(config_path.is_absolute())
                self.assertTrue(config_path.samefile(self.path))
                self.assertNotIn('env',config)
                if client=='workbuddy':self.assertEqual(config['type'],'stdio')
    def test_codex_toml_escapes_windows_paths(self):
        import tomllib
        self.run_cli('init')
        code,output=self.run_cli('client-config','--client','codex')
        self.assertEqual(code,0)
        self.assertEqual(tomllib.loads(output)['mcp_servers']['mailbridge']['args'][-1],'serve')
    def test_generated_command_keeps_the_selected_virtual_environment(self):
        self.run_cli('init')
        environment=Path(self.tmp.name)/'agent environment'
        venv.EnvBuilder(with_pip=False,symlinks=os.name!='nt').create(environment)
        executable=environment/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        result=subprocess.run([str(executable),'-m','mailbridge','--config',str(self.path),
                               'client-config','--client','generic'],capture_output=True,text=True,check=True,timeout=30)
        command=json.loads(result.stdout)['mcpServers']['mailbridge']['command']
        selected=subprocess.run([command,'-c','import sys; print(sys.prefix)'],
                                capture_output=True,text=True,check=True,timeout=15)
        self.assertTrue(Path(selected.stdout.strip()).samefile(environment),
                        'Generated command must retain the venv and its installed dependencies')

        supervisor=Path(self.tmp.name)/'supervisor.json'
        supervisor.write_text(json.dumps({'argv':[str(executable),'-c','pass']}),encoding='utf-8')
        platform='windows' if os.name=='nt' else 'macos'
        result=subprocess.run([str(executable),'-m','mailbridge','--config',str(self.path),
                               'service','render','--platform',platform,'--supervisor-config',str(supervisor)],
                              capture_output=True,text=True,check=True,timeout=30)
        service=json.loads(result.stdout)
        if platform=='windows':
            import xml.etree.ElementTree as ET
            command=ET.fromstring(service['content']).find('.//{http://schemas.microsoft.com/windows/2004/02/mit/task}Command').text
        else:
            import plistlib
            command=plistlib.loads(service['content'].encode())['ProgramArguments'][0]
        self.assertTrue(Path(command).parent.samefile(executable.parent),
                        'Background launch must use the same virtual environment')
    def test_offline_doctor_never_connects(self):
        self.run_cli('init')
        with patch('mailbridge.transport.MailTransport.status', side_effect=AssertionError('must not connect')):
            code,output=self.run_cli('doctor')
        self.assertEqual(code,2)
        self.assertNotIn('Traceback',output)
    def test_stdio_subprocess_handshake(self):
        self.run_cli('init')
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
                  {'jsonrpc':'2.0','method':'notifications/initialized'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'}]
        proc=subprocess.run([sys.executable,'-m','mailbridge','--config',str(self.path),'serve'],
                            input=('\n'.join(json.dumps(x) for x in messages)+'\n').encode(),capture_output=True,timeout=15)
        self.assertEqual(proc.returncode,0,proc.stderr.decode(errors='replace'))
        output=[json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(output),2);self.assertEqual(len(output[1]['result']['tools']),8)

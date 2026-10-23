import io
import json
import tempfile
import unittest
from pathlib import Path
from mailbridge.config import Config, example_config
try:
    from mailbridge.server import MCPServer, run_stdio, TOOLS, MAX_REQUEST
except ImportError:
    MCPServer = None


class FakeTransport:
    def __init__(self): self.calls = []
    def status(self, **kw): self.calls.append(kw); return {'ok':True}
    def search(self, **kw): return {'messages': [], 'coverage': {'complete': False}}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MCPServer, 'MCP server must exist')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.config = Config(Path(self.tmp.name)/'config.json', example_config())
        self.transport = FakeTransport()
        self.server = MCPServer(self.config, self.transport)
    def request(self, method, params=None, id=1):
        return self.server.handle({'jsonrpc':'2.0','id':id,'method':method,'params':params or {}})
    def initialize(self):
        self.request('initialize', {'protocolVersion':'2025-11-25','clientInfo':{'name':'test','version':'1'},'capabilities':{}})
        self.server.handle({'jsonrpc':'2.0','method':'notifications/initialized'})
    def test_handshake_and_eight_tools_no_network(self):
        self.initialize()
        result = self.request('tools/list')['result']
        self.assertEqual(len(result['tools']),8)
        self.assertEqual(self.transport.calls,[])
    def test_preinit_call_rejected(self):
        self.assertIn('error', self.request('tools/list'))
    def test_strict_argument_type_and_unknown_field(self):
        self.initialize()
        for arguments in [{'verify_smtp':'false'}, {'mystery':True}]:
            result=self.request('tools/call',{'name':'mail_status','arguments':arguments})
            self.assertIn('error',result)
        self.assertEqual(self.transport.calls,[])
    def test_send_without_authorization_never_calls_network(self):
        self.initialize()
        result=self.request('tools/call',{'name':'send_email','arguments':{'draft_id':'a'*32,'confirmation':'b'*64,'operation_authorized':False}})
        self.assertTrue(result['result']['isError'])
        self.assertEqual(self.transport.calls,[])
    def test_write_annotations(self):
        tools={t['name']:t for t in TOOLS}
        self.assertFalse(tools['send_email']['annotations']['readOnlyHint'])
        self.assertFalse(tools['prepare_email']['annotations']['openWorldHint'])
        self.assertTrue(tools['fetch']['annotations']['readOnlyHint'])
    def test_jsonrpc_invalid_ids_and_nonobjects(self):
        for value in [[], {'jsonrpc':'2.0','id':True,'method':'ping'}, {'jsonrpc':'1.0','id':1,'method':'ping'}]:
            self.assertIn('error',self.server.handle(value))
    def test_stream_invalid_json_recovers_and_notifications_no_reply(self):
        source=io.BytesIO(b'not-json\n'+json.dumps({'jsonrpc':'2.0','id':2,'method':'ping'}).encode()+b'\n'+b'{"jsonrpc":"2.0","method":"notifications/cancelled"}\n')
        sink=io.BytesIO(); run_stdio(self.server,source,sink)
        responses=[json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual(len(responses),2)
        self.assertEqual(responses[1]['result'],{})
    def test_oversized_line_is_bounded_and_closes(self):
        source=io.BytesIO(b'x'*(MAX_REQUEST+1)+b'\n');sink=io.BytesIO()
        run_stdio(self.server,source,sink)
        self.assertEqual(len(sink.getvalue().splitlines()),1)
        self.assertIn('error',json.loads(sink.getvalue()))

    def test_unpaired_unicode_id_cannot_crash_stream(self):
        source=io.BytesIO(b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}\n')
        sink=io.BytesIO()
        run_stdio(self.server,source,sink)
        self.assertTrue(json.loads(sink.getvalue()))

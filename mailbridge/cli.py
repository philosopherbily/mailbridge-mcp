"""Human and agent friendly commands. No command installs or sends implicitly."""
import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from . import __version__
from .config import BridgeError, Config, default_config_path, example_config, native_keyring, write_config


def emit(value):
    if sys.stdout is not None:
        print(json.dumps(value,ensure_ascii=False,indent=2))


def parser():
    p=argparse.ArgumentParser(description='Local email bridge for MCP clients. Secrets never belong in chat or arguments.')
    p.add_argument('--version',action='version',version=__version__)
    p.add_argument('--config',default=str(default_config_path()))
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init',help='Create a non-secret template without overwriting an existing file')
    d=sub.add_parser('doctor',help='Structured readiness checks; network only when requested')
    d.add_argument('--connect',action='store_true');d.add_argument('--smtp',action='store_true')
    sub.add_parser('serve',help='Run the stdio MCP server; stdout contains only JSON-RPC')
    c=sub.add_parser('client-config',help='Print client config to merge; never edits the client settings')
    c.add_argument('--client',choices=['generic','claude','cursor','codex','workbuddy'],default='generic')
    s=sub.add_parser('secret',help='Store a secret in the native OS credential store')
    ss=s.add_subparsers(dest='secret_command',required=True)
    setter=ss.add_parser('set');setter.add_argument('--account',help='Override keyring account, e.g. openai-tunnel-runtime')
    service=sub.add_parser('service',help='Generate background-service configuration without installing')
    svc=service.add_subparsers(dest='service_command',required=True).add_parser('render')
    svc.add_argument('--platform',choices=['windows','macos','linux'],required=True)
    svc.add_argument('--supervisor-config',required=True)
    svc.add_argument('--output',help='Write generated service content here; refuse overwrite')
    supervise=sub.add_parser('supervise',help='Run an explicitly configured tunnel command')
    supervise.add_argument('--supervisor-config',required=True)
    return p


def client_config(config, client):
    command=str(Path(sys.executable).resolve())
    args=['-m','mailbridge','--config',str(config.path),'serve']
    if client=='codex':
        # JSON basic-string escaping is valid TOML for these paths/arguments.
        print('[mcp_servers.mailbridge]\ncommand = '+json.dumps(command)+'\nargs = '+json.dumps(args))
    else:
        server={'command':command,'args':args}
        if client=='workbuddy':server['type']='stdio'
        emit({'mcpServers':{'mailbridge':server}})


def doctor(config, connect=False, smtp=False):
    checks={'config_valid':True,'secret_available':False,'network_checked':False}
    errors=[]
    if config.email.endswith('@example.com') or any(e['host'].endswith('.example.com') for e in (config.imap,config.smtp)):
        errors.append('CONFIG_TEMPLATE')
    try:
        config.secret();checks['secret_available']=True
    except BridgeError as e: errors.append(e.code)
    if (connect or smtp) and not errors:
        from .transport import MailTransport
        try:
            checks['connection']=MailTransport(config).status(verify_connection=True,verify_smtp=smtp)
            checks['network_checked']=True
        except BridgeError as e: errors.append(e.code)
    emit({'ok':not errors,'version':__version__,'config_path':str(config.path),'checks':checks,
          'errors':errors,'send_enabled':config.allow_send,'message_sent':False})
    return 2 if errors else 0


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        path=Path(args.config).expanduser().resolve()
        if args.command=='init':
            write_config(path,example_config())
            emit({'ok':True,'config_path':str(path),'next':'Edit non-secret mailbox settings, then configure secret and run doctor.'})
            return 0
        if args.command=='supervise':
            from .background import supervise
            return supervise(args.supervisor_config)
        if args.command=='secret' and args.account:
            account=args.account
        else:
            config=Config.load(path)
            account=config.account_id
        if args.command=='secret':
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',account):raise BridgeError('ACCOUNT_ID_INVALID')
            backend=native_keyring()
            secret=getpass.getpass('Secret (hidden, stored only in the OS credential store): ')
            if not secret or len(secret)>16384 or any(x in secret for x in ('\r','\n','\0')):raise BridgeError('SECRET_INVALID')
            try:backend.set_password('mailbridge-mcp',account,secret)
            except Exception:raise BridgeError('SECRET_STORE_ERROR') from None
            emit({'ok':True,'account_id':account,'secret_stored':True})
        elif args.command=='doctor':return doctor(config,args.connect,args.smtp)
        elif args.command=='client-config':client_config(config,args.client)
        elif args.command=='serve':
            from .server import MCPServer,run_stdio
            run_stdio(MCPServer(config))
        elif args.command=='service':
            from .background import render_service,validate_supervisor_config
            supervisor_path=str(Path(args.supervisor_config).expanduser().resolve())
            validate_supervisor_config(supervisor_path)
            output_path=str(Path(args.output).expanduser().resolve()) if args.output else None
            result=render_service(args.platform,str(Path(sys.executable).resolve()),str(path),supervisor_path,str(Path(__file__).resolve().parent.parent),output_path=output_path)
            if args.output:
                output=Path(args.output).expanduser().resolve()
                output.parent.mkdir(parents=True,exist_ok=True)
                try:
                    with output.open('x',encoding='utf-8',newline='\n') as f:f.write(result['content'])
                except FileExistsError:raise BridgeError('OUTPUT_EXISTS') from None
                result['written_to']=str(output)
            emit(result)
        return 0
    except BridgeError as e:
        emit({'ok':False,'error':e.code});return 2
    except (OSError,ValueError,EOFError):
        emit({'ok':False,'error':'LOCAL_OPERATION_FAILED'});return 2
    except KeyboardInterrupt:
        return 130


if __name__=='__main__':raise SystemExit(main())

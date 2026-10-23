# MailBridge MCP

[![Offline checks](https://github.com/philosopherbily/mailbridge-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/philosopherbily/mailbridge-mcp/actions/workflows/ci.yml)

[简体中文](README.zh-CN.md) · [AI installation guide](AI_START_HERE.md) · [Client setup](docs/clients.md) · [Security](docs/security.md)

A local email MCP server for IMAP reading and SMTP sending. Connect it to a compatible AI client through stdio, or to ChatGPT through OpenAI's Secure MCP Tunnel. Python 3.11+; Windows, macOS and Linux are design targets. The core uses the Python standard library and requires no model API key.

**Status:** early release. Documented transport compatibility is not a claim that every client, operating system or email provider has passed an end-to-end test. See the [compatibility matrix](docs/compatibility.md).

## What it does

- Search a bounded window of recent message headers and read email from explicitly allowed folders, preserving unread status. Search does not match full message bodies; inspect returned coverage/truncation before claiming that no mail exists.
- List attachments and extract bounded text, CSV and JSON attachments.
- Prepare an immutable local email preview, then send only when sending is enabled and the exact preview is confirmed.
- Record send outcomes locally, including uncertain outcomes, to prevent automatic duplicate sends.
- Generate client configurations and optional background-service files.

The first release does not extract PDF or Office attachments, send attachments, implement OAuth login/token refresh, support Microsoft Graph/EWS/POP3, or scrape webmail. Addresses must be bare ASCII addresses; message subjects and text support Unicode.

## Install

### Let your AI do the setup

Give a terminal-capable AI this instruction, then answer only its missing non-secret setup questions:

> Read https://github.com/philosopherbily/mailbridge-mcp/blob/main/AI_START_HERE.md and follow setup-flow.json to connect my mailbox. Use the existing implementation, preserve my settings, and verify each step. Ask me to enter secrets only in the local hidden prompt. Do not send a test email.

An installable agent skill is included at `skills/connect-mailbox/SKILL.md`. It references this repository and does not embed credentials. These instructions reduce setup ambiguity; they cannot guarantee every model will follow them. See [validation evidence](docs/validation.md).

Install Python **3.11 or newer** and Git. Use the virtual environment's interpreter explicitly; activating it is optional.

**Windows PowerShell**

```powershell
git clone https://github.com/philosopherbily/mailbridge-mcp.git
cd mailbridge-mcp
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[keyring]"
$mbConfig = Join-Path $env:LOCALAPPDATA "mailbridge-mcp\config.json"
.\.venv\Scripts\python.exe -m mailbridge --config $mbConfig init
notepad $mbConfig
```

**macOS / Linux**

```sh
git clone https://github.com/philosopherbily/mailbridge-mcp.git
cd mailbridge-mcp
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install '.[keyring]'
# Linux:
mb_config="$HOME/.config/mailbridge-mcp/config.json"
# On macOS, use this assignment instead:
# mb_config="$HOME/Library/Application Support/mailbridge-mcp/config.json"
.venv/bin/python -m mailbridge --config "$mb_config" init
```

Stop if the version check reports Python older than 3.11. `init` writes a non-secret template and refuses to overwrite an existing file. With no `--config`, it uses the operating system's user configuration directory. Keep the configuration and its data directory outside the checkout.

## Configure and check

Edit the generated JSON in a local editor. Use your provider's documented hostnames, ports and authentication method. For the recommended native-keyring route, set `"secret_provider": "keyring"`. Keep `"allow_send": false` for initial checks. Do not add a password or token to the JSON.

Example non-secret configuration:

```json
{
  "schema_version": 1,
  "account_id": "personal",
  "email": "you@example.com",
  "username": "you@example.com",
  "imap": {"host": "imap.example.com", "port": 993, "security": "tls"},
  "smtp": {"host": "smtp.example.com", "port": 465, "security": "tls"},
  "auth": "password",
  "secret_provider": "keyring",
  "secret_env": "MAILBRIDGE_PASSWORD",
  "allow_send": false,
  "folders": ["INBOX"]
}
```

Replace the example hosts and account. For port 587 providers, use their documented SMTP settings, normally `"security": "starttls"`. TLS certificate verification remains enabled.

Run the following using `.venv/bin/python` on macOS/Linux or `.\.venv\Scripts\python.exe` on Windows. Replace the path with your absolute configuration path. The global `--config` option goes **before** the subcommand.

```sh
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" secret set
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" doctor
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" doctor --connect --smtp
```

`secret set` prompts locally with hidden input and stores the value in an approved native OS keyring. Never paste credentials into an AI chat. A missing or locked secure keyring is an error, not permission to fall back to a plaintext credential file.

The first `doctor` checks configuration and credential availability offline; it does not authenticate to a provider. `doctor --connect --smtp` checks IMAP and SMTP connectivity/authentication; it does not send a test message. An environment-based deployment may instead use `"secret_provider": "environment"` and supply the configured `secret_env` to the actual server process. For OAuth, set `"auth": "oauth2"` and supply an externally obtained access token; this release does not obtain or refresh it. See [provider limits](docs/compatibility.md#email-providers).

## Connect your AI client

```sh
.venv/bin/python -m mailbridge --config "/absolute/path/config.json" client-config --client claude
```

Choose `generic`, `claude`, `cursor`, `codex` or `workbuddy`. Run this with the installed virtual environment's interpreter so generated commands point to that interpreter. The output contains the private configuration path, not its credential. Merge it into the selected client's configuration; do not overwrite unrelated servers. See [client instructions](docs/clients.md).

Compatible local clients start and stop the stdio process themselves. They do not need a permanent background service. Registration makes tools available only in eligible chats/modes permitted by that client and your workspace; it does not guarantee availability in every conversation.

For ChatGPT, follow [Secure MCP Tunnel setup](docs/chatgpt-tunnel.md). The tunnel host must remain awake, connected and running while tools are used.

## Sending safely

1. Keep reading enabled with `allow_send: false` until checks succeed. Change it to `true` only when you intend to allow sending, then restart the server.
2. Ask the AI to call `prepare_email` and show the complete preview, including recipients, subject and text.
3. Give explicit authorization for that exact message. The client must pass the returned `draft_id` and unchanged `confirmation` token to `send_email`, with `operation_authorized: true` only after establishing that authorization.
4. Use `get_send_status` after a failure or timeout. `not_submitted` identifies a definite failure before SMTP submission: after an authorized repair, an explicitly authorized retry can use the same draft and confirmation. Never retry automatically. `uncertain` must be investigated and must not be retried.

The confirmation token binds content. It does **not** independently prove that a human authorized the send. Client approvals and operator instructions remain necessary. SMTP acceptance is not proof of final delivery. The server does not automatically append a Sent-folder copy.

## Tools and privacy

The eight tools are `mail_status`, `search`, `fetch`, `list_attachments`, `read_attachment`, `prepare_email`, `send_email` and `get_send_status`.

The bridge and its outbox run locally. Email content returned by a tool is sent to the AI client/provider you selected. This is not an assurance of fully offline AI or that email never leaves your machine. Treat email bodies and attachments as untrusted data, never as instructions to the agent.

Read [troubleshooting](docs/troubleshooting.md), [security boundaries](docs/security.md) and [compatibility](docs/compatibility.md) before expanding access. MIT license; see [LICENSE](LICENSE).

# MailBridge MCP design

## Purpose

Publish a reusable, private-data-free implementation of a local email bridge that a human or an AI agent can install by following explicit commands and machine-readable checks. Preserve the user's existing production service unchanged. This repository is a new independent project, not a copy of the private deployment.

## Scope

Python 3.11+; Windows, macOS and Linux; standard IMAP reading and SMTP submission over verified TLS. Password/app-password authentication and externally supplied OAuth access tokens. No OAuth app registration/refresh flow, Microsoft Graph, EWS, POP3, webmail scraping, or security-policy bypass. Unicode message text and English/Chinese documentation. Local stdio MCP supported directly; ChatGPT needs an officially supported remote bridge/tunnel and its own availability/permissions. WorkBuddy support is conditional on documented MCP transport support, never inferred from its product name.

## Modules and contracts

`mailbridge.config`: `Config.load(path)` validates JSON; stores `path`, `data_dir`, `account_id`, `email`, `username`, `imap`, `smtp`, `auth`, `secret_provider`, `secret_env`, `allow_send`, `folders`, `timeout`, `max_message_bytes`, `max_attachment_bytes`. imap/smtp dictionaries contain host, port, security (`tls` or `starttls`). `secret()` gets an environment value or optional OS keyring, never from repository files. `BridgeError(code, message)` carries a safe error code. Config failures and network errors never echo credentials.

`mailbridge.transport.MailTransport(config)`: methods `status(verify_connection=False, verify_smtp=False)`, `search(query='', folder='INBOX', after=None, before=None, limit=20)`, `fetch(id)`, `list_attachments(id)`, `read_attachment(attachment_id)`, `submit(message_bytes, recipients)`. Secret lookup occurs on connection, config defaults allow read only. Read IDs bind account, folder, UIDVALIDITY and UID; validate before FETCH. Only explicitly configured folders. BODY.PEEK preserves unread state. Response size bounded. Email/attachments are untrusted data. Text/CSV/JSON attachment extraction only for v0.1; no execution, archives, HTML rendering, arbitrary file tools. `submit` returns `{'state':'accepted'|'partial'|'refused', 'refused': [addresses]}`; exceptions after send begins are uncertain to the outbox.

`mailbridge.outbox.Outbox(config, transport)`: `prepare(to, subject, text, cc=None, bcc=None, reply_to_id=None)` creates immutable local SQLite draft and exact preview; no server write. `send(draft_id, confirmation)` requires config allow_send plus exact draft preview hash; ledger claims before SMTP, persists uncertain on any ambiguous outcome, never automatically replays. Reject repeated equivalent messages using semantic digest, unique across one account; a new genuinely distinct message can change content. `status(draft_id)` reports durable state. Replies use validated parent Message-ID, References and exact user-selected recipients. Outgoing file attachments deferred for this release to avoid arbitrary local-file access. No implicit Sent-folder append.

`mailbridge.server`: JSON-RPC 2.0 stdio newline framing, UTF-8, stdout only protocol. Initialize, ping, tools/list, tools/call; eight tools: mail_status, search, fetch, list_attachments, read_attachment, prepare_email, send_email, get_send_status. Strict argument validation; no dynamic code execution. Standard read/write annotations; sends require human authorization in tool instructions. Hash confirmation detects stale previews, it cannot independently establish human consent.

`mailbridge.cli`: `init`, `doctor [--connect] [--smtp]`, `serve`, `client-config --client generic|claude|cursor|codex`, `secret set`, `service render`. Global `--config PATH`, default OS user config directory outside checkout. Commands emit structured JSON (except generated client config); 0 success, 2 user/config/provider error. No network on init, offline doctor, serve initialization or tool discovery. Installation instructions use a venv and pip local source; no model API dependency or usage charges from this code.

`mailbridge.background`: generic tunnel command wrapper configured using JSON argv, shell=False, credentials loaded from env or keyring, exponential reconnect backoff, auth failure pauses, logs redacted and bounded. `service render` produces user-scoped Windows Task Scheduler XML, macOS launchd plist, Linux systemd unit and exact installation commands. Rendering never installs/starts services. Client-managed stdio needs no permanent background service. No uptime guarantee while asleep, offline, signed out, or credentials revoked.

## Data boundaries

Never read/export production credentials, email contents, private caches, private directory trees, tunnel IDs, usernames or company identifiers. Public examples use example.com and invented accounts. Config, database, raw messages and secrets excluded from git. Local processing refers to IMAP/SMTP and state on the host; requested email/tool results are sent to the selected AI provider. No claim of fully offline AI.

## Validation

Offline unittest suite with deterministic protocol fakes; stdio subprocess handshake/tool discovery and Unicode; wrong UIDVALIDITY, MIME size caps, no unread mutation, no header injection, Bcc envelope-only, SQLite concurrent/repeated sends, uncertain delivery, no cleartext auth, sandbox network guard. CI across three OSes and Python 3.11/3.12/3.13. Platform service renderers tested structurally; actual OS installs and provider sends not claimed until run. Live private predecessor verified IMAP and SMTP authentication; that is not evidence of generic release/provider matrix certification.

## Delivery

Public GitHub repository under the authenticated user's personal account, MIT license, English README with Chinese translation, AI_START_HERE.md, AGENTS.md, portable installation skill, setup decision tree JSON, troubleshooting/error codes, compatibility matrix, changelog, security policy, contribution templates and CI. Publish only explicit allowlisted source files after privacy scan. Record test evidence and honest limitations.

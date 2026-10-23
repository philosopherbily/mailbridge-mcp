# Security boundaries

MailBridge is a local email integration with explicit access limits. It does not make the AI client, email provider or operating system trustworthy by itself. For vulnerability reporting, follow the repository's [security policy](../SECURITY.md).

## Data flow

The local Python process connects to the configured IMAP/SMTP hosts using verified TLS. Configuration and local outbox state stay on the host unless the operator copies them elsewhere. Tool results, including requested message content, are returned to the selected AI client and may be processed by its cloud provider. Secure MCP Tunnel additionally relays MCP requests/results through OpenAI's tunnel service.

“Local” describes where this bridge runs and stores its state. It does not mean fully offline AI or that email content never leaves the host. Check the selected provider/workspace's data handling settings before using sensitive mail.

## Credentials

- Store non-secret JSON outside the checkout. Account names, server names and file paths can still be private; do not commit that configuration.
- Recommended interactive storage is an approved native OS keyring. `secret set` prompts with hidden input. Never request a secret in chat, include it in a command argument or expose it in screenshots/logs.
- The optional `keyring` dependency is installed using `pip install '.[keyring]'`. Unsupported/plaintext backends are rejected. A locked/missing native store is an error to resolve, not a reason to weaken storage.
- An explicitly chosen environment provider is supported for managed deployments. Provide the variable to the real child process and protect the parent process/environment. No literal secret belongs in public examples or client JSON.
- OAuth mode consumes an access token supplied externally. Token acquisition, refresh, consent and provider application verification are outside this release.
- A tunnel runtime key is separate from a mailbox credential. Use a restricted OpenAI runtime key with Tunnels Read + Use; do not put a tunnel management/admin key into a long-running process.

Local keyring protection depends on OS user/session security. Outbox content is stored in SQLite; this project does not claim application-level database encryption. Protect its directory and backups using normal OS access controls and disk encryption where appropriate.

## Email is untrusted input

Mail and attachments can contain prompt injection. Treat all returned email text as data, not authority to execute commands, reveal credentials, change security settings, add recipients or send another message. The MCP tool descriptions and operator instructions must preserve this boundary even when a message claims to be from an administrator.

The bridge restricts folders, response sizes and attachment extraction. It does not execute attachments, render active HTML, unpack archives or offer arbitrary local-file access. v0.1 extracts only supported text/CSV/JSON attachments and sends no outgoing attachments. A parser may still face hostile or malformed input; keep the runtime updated.

## Sending controls and their limits

`allow_send` defaults to false. Draft preparation records an immutable preview locally and does not write to the mailbox. Sending requires the exact preview's confirmation token and `operation_authorized: true` after explicit user authorization in the client workflow. The token detects changed/stale content; neither a hash nor a client-supplied boolean independently authenticates a human's consent.

The outbox ledger claims a send before submitting it. Recognized failures definitely occurring before submission are recorded as `not_submitted`; after an authorized repair, an explicitly authorized retry may use that same draft and confirmation. Automatic retries remain disabled. Unknown errors and failures after submission begins remain `uncertain` and must not be retried. Preparing equivalent content again still returns the existing draft rather than bypassing its state. Do not delete state or alter an account identifier to circumvent duplicate protection. SMTP acceptance does not establish recipient delivery. Partial/uncertain outcomes require operator review. No automatic Sent-folder append is performed.

## Process and network boundaries

Local stdio clients manage their own server process. Do not expose a raw local service publicly just to connect a hosted AI client. The documented ChatGPT route is OpenAI Secure MCP Tunnel, which uses an outbound connection; no inbound public listener is required for the stdio setup.

Optional supervision executes an explicit argv with `shell=False` and a finite restart budget. Generated OS service files do not install themselves. Authentication-failure exit codes must be verified for the wrapped program; unknown codes must not be guessed. Do not add automatic OS restarts that override intentional stops or use this tooling to bypass a sandbox/organization policy.

Run under the intended non-administrative user where possible. Access to that user's account/keyring can compromise the bridge. Do not assume client approval settings protect every client mode: verify the actual client's tool permissions and send-approval behavior.

## Public contributions and reports

Use invented `example.com` accounts and synthetic messages. Never submit real mail, attachments, configuration, token values, tunnel IDs, outbox databases, private paths or unredacted debug captures. Before publication, review tracked files and generated artifacts; `.gitignore` alone cannot remove an already tracked secret.

Official references: [OpenAI tunnel permissions](https://github.com/openai/tunnel-client/blob/master/docs/permissions.md), [OpenAI tunnel architecture](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), [Microsoft SMTP AUTH controls](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission).

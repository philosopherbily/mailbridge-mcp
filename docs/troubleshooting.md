# Troubleshooting

Work through the failing layer. Do not send credentials, raw mail, outbox databases, private configuration or full private paths to a public issue. Report the exact safe error code, OS, Python/client versions and a redacted reproduction.

## 1. Installation and configuration

Use the same virtual-environment interpreter for installation, checks and generated client configuration. Python must be 3.11+. `No module named mailbridge` usually means the wrong interpreter or an installation that did not complete.

```sh
/absolute/path/python -m mailbridge --config "/absolute/private/config.json" doctor
```

| Error / symptom | Next action |
|---|---|
| `CONFIG_EXISTS` | `init` deliberately refuses overwrite. Inspect the existing private configuration, or choose a new path. |
| `CONFIG_MISSING` | Check the absolute path and the OS user running the process. Run `init` only for a genuinely new configuration. |
| `CONFIG_INVALID` / `CONFIG_UNKNOWN_FIELD` | Use valid JSON and documented fields; remove unsupported password/token fields. |
| `CONFIG_TEMPLATE` | Replace all example account/host values with the actual provider settings in the private configuration. |
| `ENDPOINT_INVALID` / `HOST_INVALID` / `PORT_INVALID` | Use a hostname without a URL scheme, an integer port and the required endpoint keys. |
| `TLS_REQUIRED` | Choose `tls` or `starttls` as documented by the provider. Plaintext authentication is unsupported. |
| `INVALID_ADDRESS` | Use a bare ASCII mailbox address, without display names, newlines or internationalized local parts. |
| `DATA_DIR_MUST_BE_ABSOLUTE` | Use an absolute private directory outside the checkout, or omit `data_dir` for the default next to the configuration. |
| `LIMIT_INVALID` | Use supported numeric bounds and keep the attachment limit no larger than the message limit. |
| CLI rejects `--config` | Put the global option before the subcommand: `mailbridge --config PATH doctor`. |

The offline check tests credential availability, but does not establish that the credential is accepted or that a server is reachable.

## 2. Credential access

| Error / symptom | Next action |
|---|---|
| `SECRET_MISSING` | For `keyring`, run `secret set` as the service user. For `environment`, provide the configured variable to the actual server process. |
| `SECURE_KEYRING_UNAVAILABLE` | Install `.[keyring]` in the same venv and make an approved native backend available/unlocked. Headless Linux may not have a user secret-store session. |
| `SECRET_STORE_ERROR` | Check the logged-in user and native store permissions/lock state. Retry locally after fixing the store. |
| `SECRET_INVALID` | Re-enter the credential without line breaks or surrounding copied formatting. Do not print it to diagnose the problem. |
| Terminal works; desktop or scheduled launch fails | Those processes may use a different user, environment, interpreter or keyring session. Inspect the generated launch paths and user context. |
| OAuth stops working later | Obtain a fresh access token externally and replace the stored value or restart with the replacement environment. MailBridge does not refresh tokens. |

Do not ask an AI to read an existing secret or paste one into chat. `secret set` uses local hidden input. Do not install a plaintext keyring backend to get past a secure-backend error.

## 3. Mailbox authentication

```sh
/absolute/path/python -m mailbridge --config "/absolute/private/config.json" doctor --connect --smtp
```

This performs connection/authentication checks, not a test send. Confirm host/port/TLS mode, provider protocol enablement, app-password availability or OAuth scope, and tenant/mailbox policy. Read [provider limitations](compatibility.md#email-providers). For a certificate error, fix hostname, trust configuration or the server certificate; do not disable verification. Network restrictions and corporate proxies may need an administrator.

Only configured folders are accessible. Provider folder names vary. A stale message identifier after mailbox UIDVALIDITY changes must be replaced by a fresh search; do not edit its encoded value or fall back to an unrelated message.

Search matches decoded headers within a bounded recent-message window, not full bodies. Read returned coverage and truncation indicators. A no-match result is not proof that the entire mailbox lacks the message. A `NETWORK_DISABLED` result means the execution environment disallows network access; use an authorized environment rather than altering sandbox flags to bypass the restriction.

## 4. Client or tunnel connection

If tools are missing, inspect client MCP status, merge rather than replace its configuration, verify absolute executable/configuration paths, restart and enable the server where needed. A quiet `serve` process is waiting for protocol input; do not print diagnostics to its stdout. Some hosted chats cannot use local client registrations.

For ChatGPT, check the selected workspace/tunnel association, restricted runtime-key permissions, official tunnel-client readiness and the running host. Use the [tunnel checklist](chatgpt-tunnel.md). A locally healthy bridge is not proof that ChatGPT can discover it.

## 5. Sending and uncertain outcomes

- `allow_send` defaults to false. Enable it deliberately and restart the server before an authorized send.
- A preview confirmation mismatch means the exact preview is no longer the one being confirmed. Prepare and show the intended message again; obtain authorization for it.
- `USER_AUTHORIZATION_REQUIRED` means `send_email` has not been given `operation_authorized: true`. Set it only after establishing the user's explicit authorization for the exact recipients and content; do not use it merely to clear the error.
- Check `get_send_status` before retrying anything. An uncertain SMTP result may mean the server accepted the message before the connection failed.
- Investigate uncertain/partial outcomes against the provider's records. Never delete the outbox ledger, change `account_id`, or modify content simply to bypass duplicate protection.
- SMTP acceptance is not final delivery, and this project does not append Sent-folder copies automatically.

| State | Meaning | Permitted next step |
|---|---|---|
| `prepared` | Local immutable preview; no submission attempted. | Send only with explicit authorization for that preview. |
| `not_submitted` | A recognized failure occurred before SMTP submission began, such as `SECRET_MISSING`, `SMTP_CONNECTION` or `NETWORK_DISABLED`. | Diagnose the reported error. After a user-authorized repair, an explicitly authorized retry may use the same `draft_id` and unchanged `confirmation`; never retry automatically. |
| `sending` | A durable send reservation exists; submission may be active or interrupted. | Check status and provider records; do not retry. |
| `accepted` | SMTP accepted the submission, without proving final delivery. | Report the result; do not resend. |
| `partial` | Some recipients were refused. | Review the receipt/provider records; do not retry the original draft. |
| `refused` | All recipients were refused. | Review the receipt and cause; this draft is not retried by the send tool. |
| `uncertain` | An unknown error or a failure after submission began prevents a definitive outcome. | Investigate; do not retry. |

Only the server's explicit pre-submission error classification produces `not_submitted`. Do not infer it from a timeout, a generic error or the absence of a Sent-folder copy. Preparing the same content again still resolves to the existing draft; the new state does not disable duplicate protection. Repairing a network-policy error means using an authorized environment, not bypassing sandbox settings.

No outgoing attachments are supported. Incoming PDF/Office/archive attachments are outside this release; listing an attachment does not imply that its format can be extracted.

## 6. Background process recovery

Service rendering does not install or start a service. Inspect the emitted file and installation commands, then check the OS service status after installation. The supervisor has a **finite** retry budget, stops after a clean exit and pauses on explicitly configured authentication-failure exit codes. It is not an unlimited uptime guarantee.

When retries are exhausted, correct the cause and restart manually. Configure authentication exit codes only if verified for the exact wrapped command; otherwise leave the list empty. A user-scoped service can still be unavailable while signed out, asleep, offline or unable to unlock the native keyring. Do not add an OS-level restart loop that defeats the supervisor's stop conditions.

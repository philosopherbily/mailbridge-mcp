# Connect ChatGPT through Secure MCP Tunnel

This guide uses the official [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) and [tunnel-client](https://github.com/openai/tunnel-client). Documentation checked on 2026-10-22. UI labels, access and CLI versions can change; check the installed client's help before proceeding.

MailBridge remains a local stdio server. ChatGPT calls an OpenAI-hosted tunnel endpoint; the tunnel client relays requests to the local process over stdio. No inbound public listener is needed. The host needs outbound HTTPS to OpenAI and network access to the mail provider. Returned mail content still reaches the selected AI provider.

## 1. Complete local checks

Use the [README](../README.md) to install MailBridge, create private configuration outside the checkout, store the mailbox credential and run:

```sh
/absolute/path/python -m mailbridge --config "/absolute/private/config.json" doctor
/absolute/path/python -m mailbridge --config "/absolute/private/config.json" doctor --connect --smtp
```

Keep `allow_send` false for discovery and authentication checks. The tunnel must use the same absolute Python/configuration paths and the same OS user/keyring context.

## 2. Provision the official tunnel

You need three separate things:

1. Permission in the intended ChatGPT workspace to add/use a custom MCP connection.
2. A tunnel associated with the intended ChatGPT workspace and Platform organization. Creating/editing it requires **Tunnels Read + Manage**; using/selecting it requires **Read + Use**.
3. A **Restricted runtime API key with Tunnels Read + Use** whose principal has access to that tunnel. This is not a mailbox credential or a model API key used by MailBridge. Never use an admin key for the long-running daemon.

Use the [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels) and [runtime API-key settings](https://platform.openai.com/settings/organization/api-keys). Record the tunnel ID privately. A tunnel attached to one organization is not automatically available in every ChatGPT workspace. See the official [permissions guide](https://github.com/openai/tunnel-client/blob/master/docs/permissions.md).

## 3. Install and configure tunnel-client

On macOS, the official supported installation is:

```sh
brew install openai/tools/tunnel-client
```

For Windows/Linux, choose the matching official release/download linked from [the repository](https://github.com/openai/tunnel-client). Releases cover Windows, macOS and Linux on amd64/arm64. Do not bypass macOS Gatekeeper for an unnotarized manually downloaded archive; use the supported Homebrew route.

```sh
tunnel-client --version
tunnel-client help quickstart
```

Create a named stdio profile, replacing all placeholders. On macOS/Linux, the outer quotes make `--mcp-command` one argument; the inner quotes preserve spaces in the executable and configuration paths:

```sh
tunnel-client init --sample sample_mcp_stdio_local --profile mailbridge --tunnel-id <TUNNEL_ID> --mcp-command '"/absolute/path/python" -m mailbridge --config "/absolute/private/config.json" serve'
```

On Windows PowerShell, use this separate example. Replace both paths and the tunnel ID. Keep **forward slashes** inside the command and the inner **single quotes**; the tunnel client's command parser may treat backslashes as escapes. These example paths contain no apostrophes. If your paths contain apostrophes, stop and consult the exact installed client's parser documentation rather than deleting characters from a real path.

```powershell
$mbCommand = "'C:/absolute/path/.venv/Scripts/python.exe' -m mailbridge --config 'C:/private/config.json' serve"
tunnel-client init --sample sample_mcp_stdio_local --profile mailbridge --tunnel-id 'YOUR_TUNNEL_ID' --mcp-command $mbCommand
```

Verify the saved executable/arguments and quote handling with the installed tunnel client's help/diagnostics, particularly in older PowerShell versions. Do not add a credential to the command or save a literal key in its profile; the runtime credential reference should be `env:CONTROL_PLANE_API_KEY`.

The official diagnostic command is `tunnel-client doctor --profile mailbridge --explain`. It needs the same restricted runtime key supplied locally in its own process environment. A supervisor does not export secrets back to its parent shell, and it discards child output; run diagnostics directly in a trusted local terminal when needed. Never paste the key into chat or include it in a command argument.

## 4. Store the runtime key and run locally

With `.[keyring]` installed, store the tunnel key separately from the mailbox credential:

```sh
/absolute/path/python -m mailbridge secret set --account openai-tunnel-runtime
```

This prompts locally with hidden input. It stores the value under the native keyring service `mailbridge-mcp` and the selected account name; it does not require loading a mailbox configuration. Do not paste the key into ChatGPT.

Create a **private** supervisor JSON file outside the checkout, for example next to the mailbox configuration. Use a new filename rather than overwriting an existing deployment. Replace `/absolute/path/tunnel-client` with the installed executable's absolute path (`tunnel-client.exe` on Windows):

```json
{
  "argv": ["/absolute/path/tunnel-client", "run", "--profile", "mailbridge"],
  "env_secrets": {
    "CONTROL_PLANE_API_KEY": "openai-tunnel-runtime"
  },
  "restart_limit": 5,
  "authentication_exit_codes": []
}
```

`env_secrets` maps a child environment-variable name to a native-keyring account name, not to a secret value. An existing nonempty environment value takes precedence over keyring lookup; remove stale values from the launching environment when rotating a key. `cwd` is optional and must be absolute if used. The executable must be absolute. Paths in Windows JSON need escaped backslashes; forward-slash absolute Windows paths may be easier to enter where supported.

Start it in the foreground before installing anything at login:

```sh
/absolute/path/python -m mailbridge supervise --supervisor-config "/absolute/private/tunnel-supervisor.json"
```

The supervisor passes the runtime key to the child, uses `shell=False`, discards child stdout/stderr and retries failures within a finite budget. Inspect the official client's health/readiness interface or run its diagnostics directly; a quiet supervisor is not proof of health. `restart_limit` accepts 0–20; 0 means no retries. Clean exit stops supervision. `authentication_exit_codes` must contain only exit codes verified for the exact wrapped command/version; leaving it empty is safer than guessing. When a configured authentication code occurs, supervision stops rather than repeatedly trying the same credential. No OS restart loop should override these decisions.

## 5. Complete ChatGPT registration

While the tunnel is running:

1. Open the intended workspace's Plugins/Apps/custom MCP settings, using the current UI.
2. Create or finish a custom MCP connection, choose **Connection: Tunnel** and select/paste the same tunnel ID.
3. Complete any required connection authentication and enable/install the connection.
4. Confirm tool discovery and make a safe `mail_status` call in an eligible chat. A narrow read-only search is a separate functional mailbox check if authorized.

Declare setup complete only after a real ChatGPT tool call succeeds. Local configuration, a running process or a successful mailbox check alone is insufficient. A connection's account/workspace scope does not guarantee that every chat, model or mode can use it.

If the tunnel is missing, check workspace association and the operator's Read + Use permissions. If it is visible but tools fail, check the runtime's health/readiness, actual executable paths, mailbox keyring access and outbound network. See [official onboarding](https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md).

## 6. Optional start at login

Only after foreground validation, render the appropriate **user-scoped** service file. Rendering writes a file and returns installation commands; it does not install or start a service. Inspect the file/commands before applying them.

**Windows PowerShell**

```powershell
& "C:\absolute\path\python.exe" -m mailbridge --config "C:\private\config.json" service render --platform windows --supervisor-config "C:\private\tunnel-supervisor.json" --output "C:\private\mailbridge-tunnel.xml"
```

**macOS**

```sh
/absolute/path/python -m mailbridge --config "/absolute/private/config.json" service render --platform macos --supervisor-config "/absolute/private/tunnel-supervisor.json" --output "/absolute/private/mailbridge-tunnel.plist"
```

**Linux**

```sh
/absolute/path/python -m mailbridge --config "/absolute/private/config.json" service render --platform linux --supervisor-config "/absolute/private/tunnel-supervisor.json" --output "/absolute/private/mailbridge-tunnel.service"
```

`--output` writes UTF-8 without a BOM and refuses overwrite. Use the returned installation commands for the rendered file; do not invent a task/service name. Check the OS status and make another ChatGPT tool call after installing. Successful rendering does not establish that Task Scheduler, launchd or systemd has accepted or started the service.

This is finite automatic recovery, not a guarantee of 24/7 operation. User-scoped launch may require a logged-in session and an unlocked native keyring. Sleep, logout, lost network, expired/revoked credentials or an exhausted retry budget can make tools unavailable. Correct the cause and restart intentionally. Always-on use needs a suitable continuously available host and an approved credential/session design.

Local Codex/Claude/Cursor stdio setups do not need this tunnel or background service. See [client setup](clients.md).

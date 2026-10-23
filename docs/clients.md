# Connect a local MCP client

Complete the [README checks](../README.md#configure-and-check) first. Every example assumes an installed virtual environment and a private configuration file **outside the checkout**. Substitute real absolute paths. `--config` is a global option and must precede `serve`, `doctor` or `client-config`.

## Generate instead of hand-editing paths

```sh
/absolute/path/to/.venv/bin/python -m mailbridge --config "/absolute/private/config.json" client-config --client claude
```

On Windows, invoke the absolute `.venv\Scripts\python.exe` path with PowerShell's `&` operator if it is quoted. Options: `generic`, `claude`, `cursor`, `codex`, `workbuddy`.

The generator uses its current Python interpreter and outputs the equivalent of:

```json
{
  "mcpServers": {
    "mailbridge": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "mailbridge", "--config", "/absolute/private/config.json", "serve"]
    }
  }
}
```

Use the actual generated name/output, particularly for Codex TOML and WorkBuddy's explicit type. JSON Windows paths need escaped backslashes; the generator handles this. No activation script, `cd`, shell wrapper or secret value belongs in this launch command. Merge the server entry into existing configuration, preserving unrelated servers.

## Client-specific steps

| Client | Where to put the generated configuration | Verify |
|---|---|---|
| Claude Desktop | Settings → Developer → Edit Config. macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows: `%APPDATA%\Claude\claude_desktop_config.json`. Use Edit Config to locate Linux's file. | Fully restart; enable tools; ask for `mail_status`. |
| Cursor | Global `~/.cursor/mcp.json` or project `.cursor/mcp.json`. | Inspect server status and invoke `mail_status` in an eligible agent chat. |
| Codex CLI / IDE | User `~/.codex/config.toml` or project `.codex/config.toml`; use `--client codex`. | `codex mcp list`, then `/mcp` in the client. |
| WorkBuddy | Connector `mcp.json` using `--client workbuddy`; follow the installed version's connector import/settings flow. | Check connection status; actual package import needs version-specific validation. |
| Generic | The client's documented `mcpServers` JSON configuration. | Verify initialization, tool discovery and one read-only call. |

Alternative CLI registration (substitute absolute paths):

```sh
codex mcp add mailbridge -- /absolute/path/python -m mailbridge --config /absolute/private/config.json serve
claude mcp add --scope user --transport stdio mailbridge -- /absolute/path/python -m mailbridge --config /absolute/private/config.json serve
codebuddy mcp add --scope user mailbridge -- /absolute/path/python -m mailbridge --config /absolute/private/config.json serve
```

These are separate commands for separate clients; run only the one selected. Quote path arguments containing spaces. Claude Code can verify with `claude mcp get mailbridge`; CodeBuddy uses `codebuddy mcp get mailbridge`.

WorkBuddy and CodeBuddy must not be conflated. WorkBuddy's connector format calls remote HTTP `streamableHttp`; CodeBuddy CLI uses `http`. Both document stdio, but this release's generator targets WorkBuddy's connector shape, not every possible UI import mechanism.

## Credentials and availability

- Native keyring is the recommended interactive-desktop route. The client and bridge must run as the user who stored the credential and be able to unlock that native store.
- If using an environment credential, supply it to the **process that launches the bridge**. Starting a desktop app from an icon may not inherit a terminal variable. Do not place literal secrets into a committed client configuration.
- Environment interpolation is client-specific: for example, Cursor documents `${env:NAME}`. A generic JSON entry does not promise interpolation support in every client.
- A user/global server registration is available only to client modes/workspaces that allow MCP. It does not automatically configure hosted ChatGPT, other users or cloud agents.

Normal local stdio is client-managed: do not install a second always-running copy for the same client. ChatGPT's cloud access instead needs [the tunnel process](chatgpt-tunnel.md) to remain running. `serve` waits for JSON-RPC on stdin and reserves stdout for protocol messages; a quiet terminal is normal and is not a connection test.

Start with `mail_status` and a narrow search. Tool discovery and server initialization do not fetch mail or authenticate. A successful client connection is not evidence of successful mailbox authentication; use `doctor --connect --smtp` separately.

Official English references: [Codex MCP](https://developers.openai.com/codex/mcp), [Claude Desktop local servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers), [Claude Code MCP](https://code.claude.com/docs/en/mcp), [Cursor MCP](https://cursor.com/docs/mcp), [WorkBuddy connectors](https://open.workbuddy.cn/en/docs/connector), [CodeBuddy MCP](https://www.codebuddy.ai/docs/cli/mcp).

# Compatibility and provider limits

Documentation reviewed: **2026-10-22**. Links below are official English-language sources. These are documented capabilities and design targets, not provider certifications or evidence of live end-to-end testing. Automated test results and actual client/provider trials must be reported separately.

## AI clients

| Client | MailBridge route | Registration | Qualification |
|---|---|---|---|
| Codex CLI / IDE | Local stdio | CLI or `config.toml` | Supported transport in official documentation. Hosted ChatGPT does not read local Codex configuration. |
| Claude Desktop | Local stdio | Developer → Edit Config | Restart after changing configuration. |
| Claude Code | Local stdio | `claude mcp add` | Select user or project scope deliberately. |
| Cursor | Local stdio | Global or project `mcp.json` | Client/workspace policies may restrict tools. |
| WorkBuddy | Local stdio connector | WorkBuddy connector `mcp.json` | Official developer documentation confirms stdio; package import and end-to-end operation still require version-specific testing. |
| CodeBuddy CLI | Local stdio | `codebuddy mcp add` | A separate product/configuration route from WorkBuddy. |
| ChatGPT | OpenAI Secure MCP Tunnel → stdio | Custom MCP connection with Tunnel | Needs workspace access, tunnel permissions and a running tunnel host. |
| Other MCP clients | Local stdio | Client-specific | Confirm newline-framed JSON-RPC MCP tool support and test discovery; not a blanket compatibility promise. |

Sources: [Codex](https://developers.openai.com/codex/mcp), [Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers), [Claude Code](https://code.claude.com/docs/en/mcp), [Cursor](https://cursor.com/docs/mcp), [WorkBuddy](https://open.workbuddy.cn/en/docs/connector), [CodeBuddy](https://www.codebuddy.ai/docs/cli/mcp), [OpenAI Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

Global registration makes a server eligible for supported chats/modes. It does not grant access to every conversation, workspace or hosted agent. Some clients expose tools only after a restart, an explicit enablement or an approval. MailBridge itself implements stdio; remote HTTP availability in a client's documentation does not mean this release serves an HTTP endpoint.

This release implements the MCP initialize/tool-call lifecycle with its advertised 2024/2025 protocol versions. It does not claim every newer protocol extension or client capability. Verify actual version negotiation and discovery with the client release being deployed.

## Operating systems

| Component | Documented / intended platforms | Validation limit |
|---|---|---|
| MailBridge core | Python 3.11+ on Windows, macOS, Linux | Design targets; inspect CI results for the exact tested revision. |
| MailBridge native keyring | Windows Credential Manager, macOS Keychain, supported Linux Secret Service/KWallet backends | Requires an available, unlocked native store in the process's user session. |
| Optional background launch | Windows Task Scheduler, macOS launchd, Linux user systemd | Generated files do not prove successful installation or startup. |
| OpenAI tunnel-client | Windows/macOS/Linux, amd64/arm64 releases | Install the official binary for the host. macOS supported path is Homebrew. |
| Claude Desktop | macOS, Windows, Linux beta | Linux has distribution/version restrictions; use current download documentation. |
| Claude Code / Cursor | Windows, macOS, Linux | Client-specific versions and policies still apply. |
| WorkBuddy | English docs list Windows and Mac installation | Linux application support was not verified for this project. |

Sources: [tunnel-client](https://github.com/openai/tunnel-client), [Claude Desktop installation](https://support.claude.com/en/articles/10065433-install-claude-desktop), [Claude Code setup](https://code.claude.com/docs/en/setup), [Cursor downloads](https://cursor.com/download), [WorkBuddy documentation](https://www.codebuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide).

## Email providers

| Provider / authentication | What this release supports | What the operator must supply |
|---|---|---|
| Standard IMAP + SMTP | Password or provider app password, verified TLS or STARTTLS | Enabled protocols, documented hosts/ports, authorized credentials and allowed folders. |
| Gmail app password | Password authentication when the account permits app passwords | Two-Step Verification and an available app-password option; organization and account policies can prevent it. |
| Gmail OAuth | Externally supplied access token via SASL XOAUTH2 | OAuth application, consent, appropriate scope, verification if applicable, token acquisition and refresh outside MailBridge. |
| Microsoft 365 / Outlook.com OAuth | Externally supplied access token via SASL XOAUTH2 | Entra application/consent, correct resource scopes, externally managed tokens and permitted mailbox protocols. |
| Exchange without enabled IMAP/SMTP, Graph-only, EWS-only or webmail-only | Not supported | Use an appropriate provider integration; do not bypass policy. |

OAuth is **access-token consumption only**. Set `auth` to `oauth2`; set `secret_env` to a name such as `MAILBRIDGE_ACCESS_TOKEN` when using the environment provider. A changed parent-shell environment does not update an already running server: restart it with the replacement token. Native-keyring storage is also available, but MailBridge does not refresh tokens there either.

Gmail IMAP/SMTP uses the broad `https://mail.google.com/` scope. Public applications may require verification, and Google recommends Gmail API scopes when full mail access is unnecessary. Restricted scopes have additional requirements, including security assessment when restricted data is stored on servers or transmitted. An external OAuth application in Testing normally receives refresh tokens that expire after seven days. This project's local/open-source status is not an automatic exemption. See [Gmail XOAUTH2](https://developers.google.com/workspace/gmail/imap/xoauth2-protocol), [Gmail scope requirements](https://developers.google.com/workspace/gmail/api/auth/scopes), [token expiration](https://developers.google.com/identity/protocols/oauth2), [desktop OAuth/PKCE](https://developers.google.com/identity/protocols/oauth2/native-app) and [app passwords](https://support.google.com/accounts/answer/185833?hl=en).

Microsoft's delegated IMAP scope is `https://outlook.office.com/IMAP.AccessAsUser.All`; SMTP uses `https://outlook.office.com/SMTP.Send`. Token-management software may request `offline_access` for refresh tokens. SMTP AUTH can be disabled by tenant/mailbox policy and by Security Defaults. Successful OAuth consent alone does not enable the protocol. MailBridge does not change those settings. See [Microsoft OAuth for IMAP/SMTP](https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth) and [SMTP AUTH controls](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/authenticated-client-smtp-submission).

For generic secure ports, IMAP implicit TLS commonly uses 993; SMTP implicit TLS uses 465, while submission on 587 normally uses STARTTLS. Follow the provider's documentation and never disable certificate verification to make a test pass. See [RFC 8314](https://www.rfc-editor.org/rfc/rfc8314.html).

## Features intentionally outside v0.1

No OAuth login/refresh workflow, PDF/Office extraction, archive unpacking, outgoing attachments, arbitrary local-file access, HTML execution, Graph/EWS/POP3, automatic Sent-folder append or final-delivery guarantee. Unicode message text is supported; SMTPUTF8/internationalized mailbox addresses are not claimed.

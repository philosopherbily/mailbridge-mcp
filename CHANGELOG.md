# Changelog

## 0.1.0

- Generic IMAP/SMTP over TLS, Unicode mail text, read-only default.
- Eight MCP stdio tools and explicit prepare/authorize/send/receipt workflow.
- Account-bound IDs, UIDVALIDITY checks, BODY.PEEK, bounded MIME and text attachments.
- Durable duplicate protection; ambiguous submissions never automatically replay.
- Environment or native OS keyring secrets; no model API dependency.
- Client config generation for Codex, Claude, Cursor, WorkBuddy and generic stdio.
- ChatGPT official tunnel guide and render-only Windows/macOS/Linux user services.
- English/Chinese guides, AI entrypoint, setup state machine and portable installation skill.

Initial scope excludes OAuth login/refresh, POP3, EWS, Microsoft Graph, webmail automation, outgoing attachments and PDF/Office extraction. MCP uses the 2025-era initialization lifecycle, negotiating up to 2025-11-25; it does not implement the 2026 stateless lifecycle.

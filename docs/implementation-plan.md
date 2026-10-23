# MailBridge MCP implementation plan

Goal: publish a practical cross-platform email bridge and deterministic agent onboarding kit.
Spec: design.md. Execution: autonomous implementation authorized by the user's request to create and share the project.

## Tasks

- [x] Configuration, secret lookup and CLI scaffolding: reject plaintext secrets/unsafe config; test missing config, wrong types, TLS modes, no secret disclosure.
- [x] IMAP/SMTP adapter: test UIDVALIDITY, PEEK, MIME limits, safe authentication and SMTP results with protocol fakes.
- [x] Outbox and MCP: test no send before confirmation, immutable previews, concurrent dedupe, partial/uncertain outcomes, newline JSON-RPC handshake and strict schemas.
- [x] Background integration: render per-user OS services, use absolute paths and argument lists, no silent installation; test escaping and supervision; document tunnel limitations.
- [x] AI-facing bilingual documentation, installation skill, setup decision tree and compatibility matrix using official sources.
- [x] Run full offline tests, secret/private-data scan and independent review; fix material findings. See validation.md.
- [x] Publish allowlisted files to the public GitHub repository and verify that its Git tree matches local source. Cross-platform check outcomes are recorded in [GitHub Actions](https://github.com/philosopherbily/mailbridge-mcp/actions/workflows/ci.yml).

## Review focus

1. A dropped SMTP connection after DATA must never be automatically retried.
2. Non-ASCII names, Windows paths and spaces must survive generated commands.
3. A reset mailbox UIDVALIDITY must invalidate old IDs before message reading.
4. A weak agent must stop on missing credentials/policies instead of inventing settings or changing protections.
5. Public history and CI logs must contain no production data.

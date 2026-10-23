# Agent guide

For installation or connecting a user's mailbox, read AI_START_HERE.md first and follow setup-flow.json. Do not infer credentials, account settings or permission to send from installation requests.

For repository development:

- Python 3.11+, standard library core; optional native keyring extra only.
- Run `python -m unittest discover -v` and `python scripts/check_publication.py` before committing.
- Never connect a real mailbox in tests. Use protocol fakes, temporary directories and example.com accounts.
- Never commit config.json, .env, databases, .eml, logs, tokens, account identifiers or personal paths.
- stdout is a protocol channel in serve mode; logs and diagnostics never go there.
- Preserve verified TLS, BODY.PEEK and UIDVALIDITY checks, immutable drafts, account binding and durable submission states.
- A partial/uncertain SMTP operation cannot be automatically replayed. No implicit test emails.
- Do not add arbitrary local file tools or execute email content/attachments.
- Keep English/Chinese documentation and CLI examples synchronized; use JSON booleans and absolute client command paths.
- Add a regression test for behavioral changes. CI runs Windows/macOS/Linux; rendering a service file alone is not an installation test.
- See docs/design.md and docs/implementation-plan.md for scope. MCP supports negotiated 2025-era stdio; no claim of 2026 stateless protocol support.

Use existing authorized tools and OS permissions. A sandbox/network denial is a boundary to report, not a reason to create an alternate execution route.

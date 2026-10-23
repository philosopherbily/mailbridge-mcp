# Security policy

This is an early open-source release. Read [the threat model and data flow](docs/security.md) before connecting confidential mail.

Do not put credentials, raw mail, mailbox databases, private hostnames, or screenshots of secrets in issues or pull requests. Report ordinary bugs using synthetic example.com messages and safe error codes.

For a vulnerability, use GitHub private vulnerability reporting if enabled for this repository. If that option is unavailable, open a minimal issue requesting a private reporting channel without exploit details or personal data. Do not assume an unpublished email address is a security contact.

Supported security maintenance: latest source on main. No guaranteed response SLA. Old snapshots should be upgraded only after reviewing changes and verifying backups.

Never disable certificate validation, tenant security policies or agent sandboxes to make a connection work. Native OS credential stores are optional dependencies; plaintext fallback stores are rejected.

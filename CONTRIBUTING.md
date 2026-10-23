# Contributing

Start with [AGENTS.md](AGENTS.md) and [design](docs/design.md). Open an issue for scope changes before adding a provider-specific authentication subsystem.

```sh
python -m unittest discover -v
python scripts/check_publication.py
```

Tests are offline. Do not connect a personal or employer mailbox in CI. Use temporary directories and synthetic example.com fixtures; tests must never send real mail. Add focused regression tests for fixes. Preserve the native OS keyring boundary, TLS verification, immutable drafts and durable submission ledger.

English and Chinese documentation should describe the same behavior. New translations belong in `docs/i18n/` and should link to the English source/revision. Keep JSON keys, CLI flags and error codes unchanged. Label each platform/provider claim as documented, rendered, CI-tested or tested end to end.

For client integrations, link official documentation and demonstrate the generated config parses. Do not overwrite users' existing MCP settings. Do not add a global daemon for clients that manage their own stdio process.

Pull requests should explain the user-visible problem, change and tests. Keep dependencies minimal. Never include an author's private environment snapshot or secrets in a report.

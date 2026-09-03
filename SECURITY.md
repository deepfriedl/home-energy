# Security and Privacy

This project accesses utility-account information. Treat all account numbers,
premise and meter identifiers, authentication credentials, session tokens, and
energy-usage responses as sensitive.

## Before publishing

- Keep `FPL_USERNAME` and `FPL_PASSWORD` only in an untracked `.env` file or a
  secrets manager. Never put real values in source, tests, issues, or commits.
- Do not commit API responses, logs, MCP transcripts, local databases, or
  screenshots containing account or energy data.
- Use clearly synthetic values in fixtures, examples, and documentation.
- Review `git status --ignored` and `git log --all -p` before publishing.
- If a credential or identifier was committed, rotate the credential and
  rewrite the affected Git history before pushing a public repository.

## Reporting a problem

Please report potential exposure privately to the repository maintainer rather
than opening a public issue with sensitive details.

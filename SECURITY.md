# Security

ROMULUS is intended for local development. Treat it as a single-user system unless you harden it.

## API keys
- Store API keys locally.
- The Phase 0 implementation stores API keys in a local SQLite database in plaintext (PROVISIONAL). Avoid using real trading keys.
- Prefer environment variables for sensitive keys until secure storage is implemented.

## Threat model (local dev)
- Assume the local machine is the trust boundary.
- Do not expose the FastAPI service publicly without authentication hardening and TLS.
- Treat any imported data as untrusted input and keep file permissions restricted.

## Roadmap
- Add at-rest encryption for API keys.
- Add role-based access control and audit logging for admin operations.

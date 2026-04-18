# Security notes

Monarch Insights handles credentials and personal-finance data. This note captures how
secrets are stored, what assumptions the library makes, and the risks to be aware of
before pointing it at real accounts.

## Secrets at rest

| Secret | Location | Protection |
| --- | --- | --- |
| Monarch API token + device UUID | `~/.config/monarch-insights/session.enc` | Fernet (AES-128-CBC + HMAC-SHA256) encrypted with a key derived from hostname, MAC address, and platform info. File mode `0600`. |
| Google OAuth refresh token | `~/.config/monarch-insights/google_token.json` | Plain JSON at `0600`; `google-auth` reads/writes. Consider encrypting with a passphrase-derived key if the host is physically exposed. |
| Google OAuth client secrets | `~/.config/monarch-insights/google_client.json` | Plain JSON at `0600`. Treat as a password. |
| Schwab refresh token | Not yet persisted — bootstrap command is a scaffold. When finished, will mirror the Monarch Fernet pattern. |
| Robinhood session pickle | `~/.tokens/` (managed by `robin_stocks`) | Library-managed; user-home readable. |

The machine-bound Fernet key is NOT a hardware key — it's enough entropy that copying
the encrypted blob to a different machine yields `InvalidToken`, but it is not proof
against a co-located attacker who has shell access to the same user. Do not assume
these files survive an unencrypted disk image.

## Network

* Monarch GraphQL is `https://api.monarch.com/graphql` (post Jan-2026 endpoint move).
* We attach `Authorization: Token <token>`, `device-uuid`, `Origin`, and a
  `User-Agent: MonarchInsights/0.1 (+home-assistant)` string. Monarch's terms of
  service apply — this is an unofficial library; rate-limit yourself.
* The library retries on 429 with exponential backoff respecting `Retry-After`.

## Logging

* Structured logs go to `~/.local/share/monarch-insights/logs/monarch-insights.log`
  (daily rotation, 365-day retention by default).
* **Tokens, passwords, and MFA codes never land in logs.** The `client/auth.py`
  login flow only logs `extra={"user_email": ...}` and success/failure outcomes.
  Verify this remains true before adding new log statements.

## Home Assistant integration

* The HA config flow collects credentials once; they are handed to `MonarchAuth.login`,
  which encrypts them at rest. The HA config entry stores only the user email, never
  the password or token.
* The HA long-lived access token (for `notify.*` service calls from our dispatcher) is
  stored where the user configured it — not inside this project.

## Data that leaves the machine

* Monarch GraphQL (outbound to `api.monarch.com`).
* Optional Google APIs (Gmail, Drive, Calendar, Sheets) when the integration is wired.
* Optional market-data providers (`yfinance`, Finnhub, FRED, EDGAR) — each makes its
  own outbound calls; some (yfinance, FRED, EDGAR) are unauthenticated.
* Optional HA notify call: sends alert title + message to whatever `notify.*` service
  you configure. Review the body content before enabling mobile-app notifications.

Nothing in this library ships data to the maintainers. There's no telemetry.

## Reporting a vulnerability

Until this project has a security contact, open a private issue on the repo or email
the owner directly. Do not disclose publicly before a fix is available.

# Connecting Monarch (tomorrow's checklist)

Step-by-step setup once you're ready to connect real credentials. Follow the order —
each step validates something the next one depends on.

## Prereqs

* Python 3.11 or 3.12 available locally.
* The repo cloned somewhere comfortable.
* Your Monarch email + password, plus access to your MFA method (authenticator app or
  email for OTP).

## 1. Install the library in a venv

```bash
cd <repo>
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .                # core deps
.venv/bin/pip install -e ".[market_data]" # yfinance + robin_stocks + curl_cffi
.venv/bin/pip install -e ".[dev]"         # pytest etc.
```

## 2. Verify the baseline still passes

```bash
.venv/bin/python -m pytest tests/ -q
```

Expect ~85 passing. If anything fails, stop and triage before touching credentials.

## 3. Authenticate to Monarch

```bash
.venv/bin/python -m monarch_insights.cli.main auth login
```

Prompts for email + password, handles MFA interactively, stores the encrypted session
at `~/.config/monarch-insights/session.enc` (file mode `600`).

## 4. First sync — small window

```bash
.venv/bin/python -m monarch_insights.cli.main sync full --months 3
```

Only pulls 3 months first. If the GraphQL schema has drifted (very likely on first
contact since queries were introspected externally), you'll see `MonarchSchemaDrift`
exceptions naming the exact query + field. Triage those before pulling 18 months.

## 5. Sanity-check each insight against your own data

```bash
.venv/bin/python -m monarch_insights.cli.main insight networth
.venv/bin/python -m monarch_insights.cli.main insight cashflow --months 3
.venv/bin/python -m monarch_insights.cli.main insight spending --days 30
.venv/bin/python -m monarch_insights.cli.main insight investments
```

Cross-check totals against the Monarch web UI. If something's off, the client's
`_flatten_transaction`/`_flatten_account_payload` or the model aliases may need
adjustment — file a follow-up, don't paper over it.

## 6. Seed targets so alerts can fire

```bash
.venv/bin/python -m monarch_insights.cli.main providers list           # show the connector plan
.venv/bin/python -m monarch_insights.cli.main watchlist add VTI --kind alert_move --move-threshold 3
# Plus in Python if you prefer (set allocation targets):
.venv/bin/python -c "
from monarch_insights.supplements.store import SupplementStore
s = SupplementStore()
s.set_allocation_target('us_stock', 60, 5)
s.set_allocation_target('intl_stock', 25, 5)
s.set_allocation_target('bond', 15, 5)
"
```

## 7. First gap scan

```bash
.venv/bin/python -m monarch_insights.cli.main gaps scan
.venv/bin/python -m monarch_insights.cli.main gaps list
```

Your first pass at "what to provide manually" — cost basis for positions older than
Monarch's sync window, any 1099s you should have on file, uncategorized-refund inflows,
etc.

## 8. Bootstrap Google (optional, but powerful)

```bash
.venv/bin/python -m monarch_insights.cli.main bootstrap google \
  --client-secrets ~/Downloads/google_client.json
```

Opens a browser to approve Gmail read-only + Drive (file-scope) + Calendar + Sheets.
Token lands at `~/.config/monarch-insights/google_token.json`. Copy that file (plus
`google_client.json`) to the Pi if you're running the daemon there:

```bash
scp ~/.config/monarch-insights/google_*.json \
  homeassistant@192.168.1.109:~/.config/monarch-insights/
```

## 9. Wire Robinhood + Schwab

```bash
.venv/bin/python -m monarch_insights.cli.main bootstrap robinhood
.venv/bin/python -m monarch_insights.cli.main bootstrap schwab \
  --client-id <app-key> --client-secret <secret>
```

Schwab requires a developer-portal approval first (separate from your Monarch account).
The bootstrap prints the consent URL.

## 10. Start the daemon (optional for now, scheduled via SystemD later)

```bash
.venv/bin/python -m monarch_insights.cli.main daemon run \
  --sync-interval-minutes 60 --digest-hour 7
```

Or install the SystemD unit we ship (Linux/Pi only):

```bash
cp scripts/monarch-insights.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now monarch-insights
journalctl --user -u monarch-insights -f
```

## 11. Install the HA integration

```bash
scp -r custom_components/monarch_insights \
  homeassistant@192.168.1.109:/config/custom_components/
```

Restart HA, then Settings → Devices & Services → Add Integration → Monarch Insights.
The config flow asks for email/password/MFA, then creates the sensors.

The sample dashboard and automations in
`custom_components/monarch_insights/lovelace_dashboard.yaml` and
`automations_examples.yaml` are ready to paste in.

## Rollback / cleanup

```bash
.venv/bin/python -m monarch_insights.cli.main auth logout
rm -rf ~/.config/monarch-insights ~/.local/share/monarch-insights
```

## Common issues

* **`MonarchSchemaDrift: [GetAccounts] Cannot query field 'X' on type 'Y'`** — Monarch
  changed its schema. Remove or rename the field in `client/queries.py` and re-run.
  Open an issue so the nightly agent can pick up the fix.
* **`MonarchAuthError: 403`** — MFA expired or the device UUID is new. Re-run
  `auth login`.
* **`MonarchRateLimited`** — Shouldn't surface to you thanks to retry+backoff, but if
  it keeps hitting, space out syncs.
* **`InvalidToken` decrypting the session** — You copied the encrypted file from a
  different machine. Log back in on this machine; Fernet is intentionally
  host-bound.

# Agent guide

Context for any automated agent (local or remote) working on this repo. The night-build
trigger points here; keep it current when conventions change.

## Bounds

* **Never commit to `main`.** Always branch + PR.
* **Never force-push.** No history rewrites.
* **Never commit secrets.** The `.gitignore` excludes `session.enc`, `google_token.json`,
  `google_client.json`, `*.db`, and `*_session*`. Re-check before every commit.
* **Never merge your own PR.** Leave PRs open for a human review.
* **Never add a new runtime dependency** unless it's unavoidable. If you do, update
  `pyproject.toml`'s `dependencies` (for required) or an extras group (for optional).

## Required quality bar

1. **Tests green before and after.** Run
   `.venv/bin/python -m pytest tests/ -q` before making changes (baseline must be green)
   and again after. No `skip`/`xfail` without a comment explaining why.
2. **Every new code path gets a test.** Parametrize edge cases (empty, None,
   decimal precision, timezone boundaries) where they apply.
3. **Industry-grade docstrings.** Module + class + public method. Use Args/Returns/Raises
   blocks when meaningful.
4. **Comments explain WHY, not what.** Non-obvious branches get a one-line `# why`.
5. **Structured logging.** Use `monarch_insights.observability.get_logger`, not
   `logging.getLogger` directly. For audit-worthy events, also write to `EventLog`.

## Module conventions

| Area | Convention |
| --- | --- |
| Money | `decimal.Decimal`. Avoid float in tax/cost-basis code paths. |
| Dates | `datetime.date` / `datetime.datetime`. Treat all stored timestamps as UTC. |
| SQL | SQLite via `sqlite3` stdlib. Every store uses WAL journal mode. |
| HTTP | `aiohttp` with `tenacity` retries. No synchronous `requests` in library code. |
| Models | Pydantic v2 with `populate_by_name=True` and `extra="ignore"` — schema drift is survivable. |
| CLI | `typer` + `rich` for tables. Add new sub-apps in `monarch_insights/cli/`. |
| Tests | `pytest-asyncio` with `auto` mode. Fixtures under `tests/fixtures/`. |

## Where to add new work

* **New Monarch GraphQL call?** Add to `client/queries.py`, map payload in `client/api.py`.
  Write a test that uses the `graphql_server` fixture in `tests/test_client_integration.py`.
* **New insight?** Create a module under `monarch_insights/insights/`, export from
  `insights/__init__.py`, add tests that exercise it against fixtures.
* **New alert rule?** Add to `monarch_insights/alerts/rules.py` and include it in
  `default_rules()`.
* **New gap rule?** Add to `monarch_insights/gaps/extra_rules.py` and call from the
  detector (or create a test-only harness).
* **New data provider?** Follow the Protocol in `providers/market_data/base.py` or
  `providers/accounts/base.py` and wire it into the appropriate router/directory.

## How to open a PR

```bash
git checkout -b nightly/YYYY-MM-DD-short-slug
# ...edits...
.venv/bin/python -m pytest tests/ -q          # must be green
git add -A
git commit -m "Concise summary

Longer rationale if needed.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
gh pr create --title "…" --body "…"
```

Include the pytest output summary in the PR body.

## Out-of-scope work

These are explicit non-goals — don't surprise the owner with them:

* Automated trading (buy/sell orders via brokerage APIs). The signal engine is
  idea-generation only.
* Sharing any data outside the local machine without explicit owner opt-in.
* Feature flags or backwards-compatibility shims for APIs that don't exist yet.
* "Cleanup" sweeps that mix unrelated changes into one PR.

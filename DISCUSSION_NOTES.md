# Discussion notes for tomorrow

These are research findings + design decisions worth talking over before we wire up live credentials.

---

## 1. Highest-leverage insights (from community research)

The features people most often complain Monarch *doesn't* do well, ranked by how often they come up across r/MonarchMoney, r/financialindependence, r/Bogleheads, r/personalfinance threads:

1. **30/60-day checking-balance forecast** — "do I have enough on payday minus 3 days?" The single most-asked-for cashflow feature, and the easiest to ship. We already have `forecast/cashflow.py` + `rule_low_balance_forecast`. Just needs a primary checking account ID and a recurring-stream snapshot.
2. **Monte Carlo retirement / FIRE projection** — Origin and ProjectionLab demand validates this. We have it (`forecast/retirement.py`) — pure Python with optional numpy fast-path. Ready for `monarch-insights forecast retirement --age X --balance Y`.
3. **Asset-allocation drift + expense-ratio drag** — Monarch's investment tracking is the #1 complaint domain; it doesn't compute IRR/TWR, doesn't track drift, doesn't surface ER drag. We do all three (`insights/investments.py` + `rule_allocation_drift`). Drift requires you to set targets — `gaps/detector.py` will nag you if you haven't.
4. **Subscription intelligence** — duplicate detection, price creep, gray charges, idle subs. Ready in `insights/recurring.py` + `rule_subscription_intel`.
5. **Daily budget-pace notifier** — Mint-style "time-progress vs dollars-spent." Ready in `insights/spending.py:budget_pace` + `rule_budget_pace`.

We ship #1 and #5 first because they're cheap pings users feel every day; #2/#3 are weekly digests; #4 is monthly.

## 2. Stock-data integration plan

| Provider | Free? | Use it for |
| --- | --- | --- |
| `yfinance` | Yes (scrape, fragile) | Default for quotes, historicals, options chains, dividends, splits |
| `robin_stocks` (underscore!) | Yes (your RH account) | Your RH positions + average cost, fundamentals, ratings, news |
| Finnhub free | 60 req/min | Analyst price targets + consensus (best free source) |
| FRED | ~unlimited | Macro: CPI, fed funds, 10Y yield, mortgage rate, VIX |
| SEC EDGAR | Free, polite UA | Authoritative 10-K/Q/8-K for any holding |
| Polygon free | 5 req/min, 15-min delay | Skip — too restrictive |
| Alpha Vantage free | 25/day | Skip |
| OpenBB Platform | Free open-source facade | Optional: unifies the above behind one API |

**Robinhood Gold caveat**: Morningstar/Nasdaq Level II are app-only. The JSON endpoints expose the standard set. We use RH Gold for *your positions + average cost* (fills the cost-basis gap that Monarch can't), not for Morningstar reports.

The router (`providers/market_data/router.py`) tries them in order with a 60-second TTL cache and skips any that raise `NotImplementedError`. So you can pass `[YFinanceProvider(), FinnhubProvider(key)]` and it'll fall back automatically.

## 3. Account-by-account integration plan

| Institution | How we get data |
| --- | --- |
| **Schwab** | Direct via official Trader API (developer.schwab.com OAuth dance once). Best source for trades + cost basis. |
| **Robinhood** | `robin_stocks` for positions/orders/avg cost. Plus Gold gives you in-app Morningstar (manually). |
| **Chase / Amex / Citi / Barclays** | No public APIs. We parse Gmail alerts via per-vendor regex rules in `providers/accounts/email_provider.py`. |
| **Marcus** | Monarch's Plaid sync usually works. Email backup for HYS rate changes. |
| **Bilt** | Email parsing for rent-payment + points emails. Useful for rewards optimization. |
| **Toyota Financial Services** | Email statements + amortization. No API; payment-due alerts are reliable. |

Run `monarch-insights providers list` for the directory.

## 4. Google integrations

- **Gmail readonly** for receipts, paystubs, brokerage trade confirmations, 1099 alerts.
- **Drive `drive.file` scope** for tax-doc vault organized by `Year/Institution/`. Drive auto-OCRs PDFs at upload — effectively free OCR via `fullText contains` searches.
- **Calendar** for Apr/Jun/Sep/Jan estimated-tax dates, RMD birthday alarm, RSU vest schedule.
- **Sheets** for shareable tax-prep packets and budget snapshots.

Auth model: OAuth Installed App flow run once on Mac, `token.json` SCP'd to Pi at `~/.config/monarch-insights/google_token.json`. Refresh tokens long-lived; `google-auth` rotates access tokens automatically.

## 5. Alerting + signal architecture

`alerts/engine.py` reduces all the insight outputs to a stream of `Alert` objects. Default rules in `alerts/rules.py`. Dispatchers route alerts to:

- `LogDispatcher` — stdout
- `StoreDispatcher` — SQLite (so HA can read history)
- `HassNotifyDispatcher` — POSTs to your HA `/api/services/notify/...` (mobile_app, persistent_notification, slack, whatever).

Severity tiers: info → persistent only; warn → persistent + mobile; critical → persistent + mobile + a configurable critical channel (Slack DM, second iPhone, etc).

Buy/sell signals (`signals/`) combine technical + fundamental + portfolio context into a single `ScoredSignal` with an `Action`. **This is idea generation, not investment advice** — the scorer is intentionally conservative and exposes its rationale list so you can sanity-check.

## 6. Things to decide together tomorrow

- **Filing status + state** for tax module (federal brackets are 2025; state is per-state and not yet wired).
- **Target asset allocation** — what % US-stock / intl / bonds / real estate / cash do you want? Drift alerts only fire after these are set.
- **Low-balance floor** for checking — what dollar amount triggers a "you're projected to dip below X" alert?
- **Watchlist tickers** — beyond what you hold, what do you want price-movement alerts on?
- **Notification routing** — which HA `notify.*` service should warn-tier alerts go to? Mobile app, Pushover, Slack?
- **Schwab developer registration** — needs your physical attention; we can't do it from here.
- **Robinhood credentials handling** — we can prompt at first run and store via the Monarch-style encrypted session, or env vars, your call.
- **Manual data — what to load first?** Cost basis for any held position older than your Monarch sync window. RSU grant schedule if applicable. Any K-1 / side-business income.

## 7. Known unknowns / risks

- **GraphQL schema drift.** Queries are derived from the community-introspected schema (`monarch-graphql.ajzbc.com`) and the hammem/keithah Python clients. Monarch already moved their endpoint in Jan 2026, so expect occasional `MonarchSchemaDrift` exceptions on first contact. The client classifies these and continues; we'll triage on first run.
- **`yfinance` fragility.** Yahoo is hostile; we may need `curl_cffi` to bypass Cloudflare. Not installed by default; the provider will surface a clear error if so.
- **Robinhood account-flagging risk.** Heavy polling can flag your RH account. Default cadence is conservative (positions once a day, prices on demand).
- **Gmail parsing brittleness.** Vendor email templates change a few times a year. The regex rules table is small and per-vendor; easy to update without touching the IMAP code.
- **Cost-basis math.** FIFO/LIFO/HIFO is implemented; Specific-ID requires you to pass lot IDs. Wash-sale detection is a *flag*, not the IRS adjustment — we don't try to compute the basis adjustment automatically.

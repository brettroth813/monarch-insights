"""User-facing directory of which provider handles which institution.

Centralised so the CLI can render "configure provider for X" prompts and the gap detector
can know whether a "Schwab balance is stale" warning is actionable (we have a direct
provider) vs. informational (we can only nag you to refresh Monarch).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProviderEntry:
    institution: str
    aliases: list[str]
    provider_name: str
    auth_kind: str
    notes: str = ""
    setup_hint: str = ""


def build_default_directory() -> list[ProviderEntry]:
    return [
        ProviderEntry(
            institution="Charles Schwab",
            aliases=["Schwab", "Schwab Bank", "Schwab Brokerage", "Schwab One"],
            provider_name="schwab",
            auth_kind="oauth",
            notes="Has official trader API; richest source for positions and trades.",
            setup_hint=(
                "Register at developer.schwab.com → create app → run "
                "`monarch-insights schwab bootstrap` to do the OAuth dance."
            ),
        ),
        ProviderEntry(
            institution="Robinhood",
            aliases=["Robinhood Brokerage", "Robinhood Gold"],
            provider_name="robinhood",
            auth_kind="user_pass_mfa",
            notes="Use robin_stocks (underscore). Gold gives in-app Morningstar; not exposed via JSON.",
            setup_hint="Set RH_USERNAME, RH_PASSWORD env vars; first run prompts for MFA.",
        ),
        ProviderEntry(
            institution="Chase",
            aliases=["JPMorgan Chase", "Chase Sapphire", "Chase Freedom"],
            provider_name="email-derived",
            auth_kind="email",
            notes="No public API. Categorize Chase alerts in Gmail; we'll pick them up.",
            setup_hint="Create Gmail filter: from:chase.com → label Finance/Chase",
        ),
        ProviderEntry(
            institution="American Express",
            aliases=["Amex"],
            provider_name="email-derived",
            auth_kind="email",
            notes="Amex emails are clean; transaction alerts work well.",
            setup_hint="Filter from:americanexpress.com → label Finance/Amex",
        ),
        ProviderEntry(
            institution="Citi",
            aliases=["Citibank"],
            provider_name="email-derived",
            auth_kind="email",
            setup_hint="Filter from:citi.com OR from:accountonline.com → label Finance/Citi",
        ),
        ProviderEntry(
            institution="Barclays",
            aliases=["Barclaycard"],
            provider_name="email-derived",
            auth_kind="email",
        ),
        ProviderEntry(
            institution="Bilt",
            aliases=["Bilt Rewards", "Bilt Mastercard"],
            provider_name="email-derived",
            auth_kind="email",
            notes="Bilt sends rent-payment + points emails. Useful for rewards optimisation.",
        ),
        ProviderEntry(
            institution="Marcus by Goldman Sachs",
            aliases=["Marcus"],
            provider_name="email-derived",
            auth_kind="email",
            notes="Monarch usually syncs via Plaid; emails are backup for HYS rate changes.",
        ),
        ProviderEntry(
            institution="Toyota Financial Services",
            aliases=["TFS", "Toyota Finance"],
            provider_name="email-derived",
            auth_kind="email",
            notes="Auto loan. Pull payment due + amortization schedule from monthly statements.",
            setup_hint="Filter from:toyotafinancial.com → label Finance/Toyota",
        ),
    ]
